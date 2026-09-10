"""One-time naming migration; legacy names are confined to compatibility helpers."""
import fcntl
import os
import sqlite3
import time
from pathlib import Path

LEGACY_NAME = 'codex-local-scheduler'
LEGACY_DATA_ENV = 'CODEX_LOCAL_SCHEDULER_DATA'


def default_data_dir():
    configured = os.environ.get('ONCUE_DATA') or os.environ.get(LEGACY_DATA_ENV)
    return Path(configured).expanduser() if configured else Path.home()/'.local/share/oncue/data'


def migrate_data_dir(requested):
    """Move the old store as a unit, retaining absolute historical path aliases.

    Never merge databases or move active workers. Custom stores are unchanged.
    A directory rename preserves the database, WAL, logs, and provider-owned files.
    """
    requested = Path(requested).expanduser().absolute()
    legacy = Path.home()/'.local/share'/LEGACY_NAME
    target = Path.home()/'.local/share/oncue/data'
    if requested not in (legacy, target): return requested
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (target.parent/'.migration.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if legacy.is_symlink():
            if legacy.resolve() != target.resolve():
                raise ValueError('Legacy data path points elsewhere; select it explicitly with --data-dir using its resolved path')
            return target
        if not legacy.exists():
            if (target/'.legacy-path-alias').exists():
                legacy.symlink_to(target, target_is_directory=True)
            return target
        if target.exists():
            raise ValueError('Both old and new data directories exist. Back them up and choose a store with --data-dir; automatic merging is disabled.')
        from .service import stop, service_info
        from .store import _process_is_alive
        stop(legacy)
        for _ in range(150):
            if not service_info(legacy): break
            time.sleep(.1)
        else: raise ValueError('The previous scheduler is still stopping. Try again shortly.')
        database = legacy/'scheduler.sqlite3'
        if database.exists():
            with sqlite3.connect(database) as connection:
                columns = {r[1] for r in connection.execute('PRAGMA table_info(runs)')}
                if {'process_id','process_start_ticks'}.issubset(columns):
                    for pid,ticks in connection.execute("SELECT process_id,process_start_ticks FROM runs WHERE status='running'"):
                        if _process_is_alive(pid,ticks):
                            raise ValueError('A task is still running. Let it finish, then start OnCue again to migrate safely.')
                connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        (legacy/'.legacy-path-alias').touch(mode=0o600)
        legacy.rename(target)
        try: legacy.symlink_to(target, target_is_directory=True)
        except OSError:
            target.rename(legacy)
            raise
        return target


def worker_unit(run_id):
    units = Path.home()/'.config/systemd/user'
    prefix = LEGACY_NAME if (units/(LEGACY_NAME+'-worker@.service')).exists() and not (units/'oncue-worker@.service').exists() else 'oncue'
    return f'{prefix}-worker@{run_id}.service'


def legacy_execution_environment(values):
    """Preserve variables used by existing user-authored shell tasks."""
    return {'CODEX_LOCAL_SCHEDULER_'+key:value for key,value in values.items()}


def migrate_launchers():
    """Refresh generated launchers without enabling services or changing accounts."""
    import subprocess
    root = Path.home()
    units = root/'.config/systemd/user'
    paths = [units/'oncue.service', units/(LEGACY_NAME+'.service'),
             units/(LEGACY_NAME+'-worker@.service'), root/'.local/share/applications/oncue.desktop']
    changed = []
    for path in paths:
        if not path.is_file(): continue
        text = path.read_text()
        updated = text.replace('codex_local_scheduler', 'oncue')
        updated = updated.replace('/usr/bin/env '+LEGACY_NAME+' ', '/usr/bin/env oncue ')
        updated = updated.replace(str(root/'.local/share'/LEGACY_NAME), str(root/'.local/share/oncue/data'))
        if updated != text:
            path.write_text(updated)
            changed.append(path)
    if any(p.parent == units for p in changed):
        subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    return changed
