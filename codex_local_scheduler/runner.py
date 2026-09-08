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


def invocation(job) -> tuple[str | list[str], bool]:
    """Return a subprocess command and whether it requires a shell."""
    if job["runner"] == "command":
        return job["command"], True
    command = ["codex", "exec", "--model", job["model"]]
    command.extend(["--sandbox", job["sandbox"]])
    if job["auto_approve"]:
        command.append("--approve-for-me")
    if job["reasoning_effort"]:
        command.extend(["--config", f'model_reasoning_effort="{job["reasoning_effort"]}"'])
    command.append(job["command"])
    return command, False


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
    scheduled_for = datetime.fromisoformat(job["run_scheduled_for"])
    with _project_lock(data_dir, job["project_slug"]) as acquired:
        if not acquired:
            store.release_run(run_id, "project is busy; waiting for the next scheduler dispatch")
            return "queued-project-busy"
        return _execute_started_run(store, job, run_id, data_dir, scheduled_for)


def _execute_started_run(store: Store, job, run_id: int, data_dir: Path, scheduled_for: datetime) -> str:
    """Execute a claimed run and write its terminal state exactly once."""
    output_dir = data_dir / "runs" / job["slug"]
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output_dir, 0o700)
    output_path = output_dir / f"{scheduled_for.strftime('%Y%m%dT%H%M%S%f')}.log"
    _secure_output_path(output_path)
    environment = {"PATH": os.environ.get("PATH", ""), "CODEX_LOCAL_SCHEDULER_PROJECT": job["project_slug"]}
    if job["connection_slug"]:
        environment["CODEX_LOCAL_SCHEDULER_CONNECTION"] = job["connection_slug"]
        environment["CODEX_LOCAL_SCHEDULER_CONNECTION_KIND"] = job["connection_kind"]
    if job["runner"] == "codex":
        # Codex authentication belongs to the local account; it is not stored in this scheduler.
        environment["HOME"] = os.environ.get("HOME", str(Path.home()))
        if os.environ.get("CODEX_HOME"):
            environment["CODEX_HOME"] = os.environ["CODEX_HOME"]
    try:
        command, use_shell = invocation(job)
        # Stream output directly to disk. A verbose Codex job should never consume
        # unbounded scheduler memory, and start_new_session lets timeout kill children.
        with output_path.open("wb") as output:
            process = subprocess.Popen(
                command, shell=use_shell, cwd=job["project_path"], env=environment,
                stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
            )
            try:
                exit_code = process.wait(timeout=job["timeout_seconds"])
            except subprocess.TimeoutExpired:
                _terminate_process_group(process)
                output.write(b"\nTimed out by codex-local-scheduler.\n")
                store.finish_run(run_id, "timed_out", None, str(output_path), "timeout")
                return "timed_out"
        status = "succeeded" if exit_code == 0 else "failed"
        store.finish_run(run_id, status, exit_code, str(output_path))
        return status
    except Exception as error:
        with output_path.open("ab") as output:
            output.write(f"Runner error: {error}\n".encode())
        store.finish_run(run_id, "failed", None, str(output_path), str(error))
        return "failed"
