"""Execution with project-scoped locks and persisted output."""

from __future__ import annotations

import os
import signal
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager

import fcntl

from .store import Store, process_start_ticks


@contextmanager
def _project_lock(data_dir: Path, project_slug: str):
    lock_dir = data_dir / "locks" / "projects"
    lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (lock_dir / f"{project_slug}.lock").open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            try:
                yield True
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


@contextmanager
def scheduler_lock(data_dir: Path):
    """Ensure only one scheduler tick can claim due work at a time."""
    lock_dir = data_dir / "locks" / "scheduler"
    lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (lock_dir / "tick.lock").open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            try:
                yield True
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    """End the shell/Codex process and its children after a timeout."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    except ProcessLookupError:
        pass
    # The group leader can exit while a child ignores SIGTERM. Kill the group
    # even when wait() above succeeds so no descendant is left behind.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def _secure_output_path(path: Path) -> None:
    """Create run logs as owner-readable files regardless of the caller umask."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.close(descriptor)
    os.chmod(path, 0o600)


def run_job(store: Store, job, data_dir: Path, scheduled_for: datetime, manual: bool = False) -> str:
    base_key = scheduled_for.astimezone(timezone.utc).isoformat()
    scheduled_key = f"manual:{base_key}" if manual else scheduled_for.astimezone(timezone.utc).replace(second=0, microsecond=0).isoformat()
    with _project_lock(data_dir, job["project_slug"]) as acquired:
        if not acquired:
            return "skipped-project-busy"
        run_id = store.start_run(job["id"], scheduled_key, os.getpid(), process_start_ticks(os.getpid()))
        if run_id is None:
            return "already-recorded"
        return _execute_started_run(store, job, run_id, data_dir, scheduled_for)


def run_queued_job(store: Store, run_id: int, data_dir: Path) -> str:
    """Claim and execute a durable queued occurrence in a worker process."""
    job = store.claim_queued_run(run_id, os.getpid(), process_start_ticks(os.getpid()))
    if job is None:
        return "already-claimed"
    scheduled_for = datetime.now(timezone.utc) if job["run_scheduled_for"].startswith("retry:") else datetime.fromisoformat(job["run_scheduled_for"].removeprefix("manual:"))
    with _project_lock(data_dir, job["project_slug"]) as acquired:
        if not acquired:
            store.release_run(run_id, "project is busy; waiting for the next scheduler dispatch")
            return "queued-project-busy"
        return _execute_started_run(store, job, run_id, data_dir, scheduled_for)


def _execute_started_run(store: Store, job, run_id: int, data_dir: Path, scheduled_for: datetime) -> str:
    """Execute an occurrence/attempt with durable output and provider-independent history."""
    import json
    import time
    from . import providers
    from .settings import get_settings
    from .conversations import prompt_for, accept_response, classify_error, retry_run, message

    settings = get_settings(store)
    run = store.connection.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone()
    current_job = dict(job)
    if run['config_snapshot']:
        job = json.loads(run['config_snapshot'])
    else:
        from .attachments import snapshot_run
        job = snapshot_run(store, current_job, run_id)
    output_dir = data_dir / 'runs' / job['slug']
    output_path = output_dir / f'{run_id}.log'
    response_path = output_dir / f'{run_id}.response.txt'
    process = None
    status, exit_code, detail = 'failed', None, None
    provider = job.get('provider','codex')
    cfg = json.loads(job.get('task_config','{}'))
    try:
        output_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
        os.chmod(output_dir,0o700)
        _secure_output_path(output_path)
        _secure_output_path(response_path)
        store.connection.execute('UPDATE runs SET output_path=?,response_path=?,provider=?,model=? WHERE id=?',
            (str(output_path.resolve()),str(response_path.resolve()) if job['runner']!='command' else None,provider,job['model'],run_id))
        store.connection.commit()
        if job['runner']=='command':
            command, use_shell = job['command'], True
            environment={'PATH':os.environ.get('PATH',''),'ONCUE_PROJECT':job['project_slug']}
            from .migration import legacy_execution_environment
            environment.update(legacy_execution_environment({'PROJECT':job['project_slug']}))
        else:
            prompt=prompt_for(store,job,run)
            command=providers.command(provider,job['model'],prompt,response_path.resolve(),
                sandbox='read-only' if run['kind']=='plan' else job['sandbox'],
                effort=job['reasoning_effort'],auto=bool(job['auto_approve']) and run['kind']!='plan',planning=run['kind']=='plan',live_search=cfg.get('mode')=='monitor',data_dir=data_dir)
            use_shell=False
            environment=providers.environment(data_dir,settings,provider)
            if run['kind']=='plan' and provider=='opencode':
                environment['OPENCODE_PERMISSION']='"deny"'
        if job['connection_slug']:
            environment['ONCUE_CONNECTION']=job['connection_slug']
            environment['ONCUE_CONNECTION_KIND']=job['connection_kind']
            from .migration import legacy_execution_environment
            environment.update(legacy_execution_environment({'CONNECTION':job['connection_slug'],'CONNECTION_KIND':job['connection_kind']}))
        with output_path.open('wb') as output:
            process=subprocess.Popen(command,shell=use_shell,cwd=job['project_path'],env=environment,
                stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
            deadline=time.monotonic()+job['timeout_seconds']
            while process.poll() is None:
                cancelled=store.connection.execute('SELECT cancel_requested FROM runs WHERE id=?',(run_id,)).fetchone()[0]
                if cancelled:
                    _terminate_process_group(process);status='skipped';detail='Cancelled by user';break
                if time.monotonic()>=deadline:
                    _terminate_process_group(process);status='timed_out';detail='Timed out by OnCue.'
                    output.write(b'\nTimed out by OnCue.\n');break
                try:process.wait(timeout=.2)
                except subprocess.TimeoutExpired:pass
            else:
                exit_code=process.returncode
                status='succeeded' if exit_code==0 else 'failed'
        if provider=='opencode' and job['runner']!='command':
            providers.extract_opencode(output_path,response_path)
        if status=='succeeded' and job['runner']!='command':
            text=response_path.read_text(errors='replace')
            if not text.strip():raise ValueError('Provider returned no response; check its execution log')
            text=accept_response(store,job,run,text)
            response_path.write_text(text)
        if status=='failed' and not detail:
            with output_path.open('rb') as source:
                source.seek(max(0,output_path.stat().st_size-16384))
                detail=source.read().decode(errors='replace')
    except Exception as error:
        if process and process.poll() is None:_terminate_process_group(process)
        detail=str(error);status='failed'
        if output_path.exists():
            with output_path.open('a') as output:output.write(f'\nRunner error: {error}\n')
    error_kind, friendly, retryable = classify_error(detail or '') if status in ('failed','timed_out') else (None,detail,False)
    store.finish_run(run_id,status,exit_code,str(output_path.resolve()),friendly)
    store.connection.execute('UPDATE runs SET error_kind=? WHERE id=?',(error_kind,run_id));store.connection.commit()
    message(store,job['id'],'assistant','',run_id)
    from .notifications import queue_run_event, process
    queue_run_event(store,job,run_id)
    process(store)
    if retryable and settings['retry_enabled'] and (cfg.get('retry_safe',False) or run['kind']=='plan' or cfg.get('mode')=='monitor'):
        rid=retry_run(store,run_id,automatic=True)
        if rid and settings['allow_fallback'] and settings['fallback_provider'] and settings['fallback_model']:
            replacement={**job,'provider':settings['fallback_provider'],'model':settings['fallback_model']}
            store.connection.execute('UPDATE runs SET config_snapshot=? WHERE id=?',(json.dumps(replacement),rid));store.connection.commit()
    if cfg.get('mode')=='monitor' and cfg.get('max_checks') and run['kind']=='task':
        count=store.connection.execute("SELECT COUNT(*) FROM runs WHERE job_id=? AND kind='task' AND retry_of IS NULL",(job['id'],)).fetchone()[0]
        if count>=cfg['max_checks']:
            store.set_job_enabled(job['slug'],False)
            message(store,job['id'],'system','Maximum monitoring checks reached. Review results before resuming.')
    return status
