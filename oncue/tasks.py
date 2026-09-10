"""Task operations shared by the local UI, API and CLI."""
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .schedules import from_form, once_at, validate_schedule


def save_task(store, data: dict, slug: str | None = None) -> str:
    from .settings import get_settings
    settings = get_settings(store)
    existing = store.job(slug) if slug else None
    if slug and not existing:
        raise ValueError('Task not found or archived')
    title = str(data.get('title', existing['title'] or existing['slug'] if existing else '')).strip()
    instructions = data.get('instructions', existing['command'] if existing else '')
    if not isinstance(instructions, str) or not instructions.strip():
        raise ValueError('Describe what the task should do')
    if not title:
        title = instructions.strip().splitlines()[0][:70]
    if len(title) > 160:
        raise ValueError('Task name must be 160 characters or fewer')
    zone = str(data.get('timezone', existing['timezone'] if existing else settings['timezone']))
    schedule = from_form({**data, "timezone": zone}) if 'frequency' in data else str(data.get('schedule', existing['schedule'] if existing else '0 9 * * *'))
    validate_schedule(schedule, zone)
    once = once_at(schedule)
    if once and (not existing or schedule != existing['schedule']) and once <= datetime.now(timezone.utc):
        raise ValueError('Choose a future date and time')
    runner = str(data.get('runner', existing['runner'] if existing else 'codex'))
    if runner not in ('command', 'codex'):
        raise ValueError('Unknown task type')
    model = data.get('model', existing['model'] if existing else settings['model'])
    if runner == 'codex' and (not isinstance(model, str) or not model.strip()):
        raise ValueError('Choose a model')
    effort = data.get('effort', existing['reasoning_effort'] if existing else None) or None
    if effort not in (None, 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'):
        raise ValueError('Unknown reasoning effort')
    timeout = data.get('timeout', existing['timeout_seconds'] if existing else 1800)
    if type(timeout) is not int or not 1 <= timeout <= 86400:
        raise ValueError('Timeout must be between 1 and 86400 seconds')
    enabled = data.get('enabled', bool(existing['enabled']) if existing else True)
    if type(enabled) is not bool:
        raise ValueError('Enabled must be true or false')
    sandbox = data.get('sandbox', existing['sandbox'] if existing else 'read-only')
    auto = data.get('auto_approve', bool(existing['auto_approve']) if existing else False)
    if sandbox not in ('read-only', 'workspace-write') or type(auto) is not bool:
        raise ValueError('Invalid execution settings')
    if runner == 'command' and (sandbox != 'read-only' or auto):
        raise ValueError('Sandbox and automatic approval apply only to Codex')
    if auto and sandbox != 'workspace-write':
        raise ValueError('Automatic approval requires workspace-write')
    cfg = json.loads(existing['task_config']) if existing else {}
    provider = data.get('provider', existing['provider'] if existing else settings['provider'])
    if provider not in ('codex','opencode'):
        raise ValueError('Choose Codex or OpenCode')
    for key in ('mode','condition','remember','retry_safe','max_checks'):
        if key in data: cfg[key]=data[key]
    if cfg.get('mode','task') not in ('task','monitor','draft','chat'):
        raise ValueError('Unknown task mode')
    if cfg.get('mode') == 'monitor' and not str(cfg.get('condition','')).strip():
        raise ValueError('Describe when this monitor should stop')
    if cfg.get('mode') == 'monitor':
        cfg.setdefault('max_checks',365)
        if runner == 'command':raise ValueError('Monitoring requires an AI provider')
    if provider == 'opencode' and (sandbox != 'read-only' or auto):
        raise ValueError('OpenCode tasks currently support read-only access')
    for key in ('remember','retry_safe'):
        if key in cfg and type(cfg[key]) is not bool:
            raise ValueError(f'{key} must be true or false')
    if 'max_checks' in cfg and (type(cfg['max_checks']) is not int or not 1 <= cfg['max_checks'] <= 10000):
        raise ValueError('Maximum checks must be between 1 and 10000')
    if existing:
        if runner != existing['runner'] and 'instructions' not in data:
            raise ValueError('Changing task type requires new instructions')
        store.update_job(slug, schedule, timeout, runner, model, effort, zone, sandbox, auto,
                         existing['connection_slug'], enabled, instructions, commit=False)
    else:
        base = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:40] or 'task'
        slug = f'{base}-{uuid.uuid4().hex[:8]}'
        project = data.get('project')
        if not project:
            project = slug
            workspace = store.path.parent / 'workspaces' / slug
            workspace.mkdir(parents=True, mode=0o700)
            store.add_project(project, workspace)
        store.add_job(slug, project, schedule, instructions, None, timeout, runner, model,
                      effort, zone, sandbox, auto, enabled=enabled, commit=False)
    store.connection.execute('UPDATE jobs SET title = ?, provider=?, task_config=?, completed_at=NULL WHERE slug = ?', (title, provider, json.dumps(cfg), slug))
    store.connection.commit()
    return slug


def queue_manual(store, slug: str) -> int:
    job = store.job(slug)
    if not job:
        raise ValueError('Task not found or archived')
    if json.loads(job['task_config']).get('mode') in ('draft','chat'):
        raise ValueError('Finish scheduling this conversation before running the task. Use Task details or send a schedule.')
    key = 'manual:' + datetime.now(timezone.utc).isoformat()
    return store.queue_run(job['id'], key)


def read_output(store, run_id: int, log: bool = False) -> dict:
    row = store.connection.execute('SELECT * FROM runs WHERE id = ?', (run_id,)).fetchone()
    if not row:
        raise ValueError('Run not found')
    raw = row['output_path'] if log else row['response_path'] or row['output_path']
    result = dict(id=run_id, status=row['status'], text='', truncated=False, error=row['error'])
    if raw:
        path = Path(raw).resolve()
        if not path.is_relative_to((store.path.parent / 'runs').resolve()):
            raise ValueError('Output is outside scheduler storage')
        try:
            with path.open('rb') as handle:
                content = handle.read(262145)
            result.update(text=content[:262144].decode('utf-8', errors='replace'), truncated=len(content) > 262144)
        except FileNotFoundError:
            result['text'] = 'No saved output is available yet.'
    return result
