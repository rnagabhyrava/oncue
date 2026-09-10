"""Shared due recording and a bounded local worker dispatcher for the app."""
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread

from .runner import scheduler_lock
from .schedules import due_key
from .store import Store


def enqueue_due(store, now=None):
    now = now or datetime.now(timezone.utc)
    with scheduler_lock(store.path.parent) as acquired:
        if not acquired:
            return []
        store.recover_interrupted_runs()
        import json
        for job in store.jobs():
            cfg=json.loads(job['task_config'])
            deferred=store.connection.execute("SELECT 1 FROM runs WHERE job_id=? AND status='queued' AND retry_at IS NOT NULL",(job['id'],)).fetchone()
            if job['enabled'] and not job['completed_at'] and cfg.get('mode') not in ('draft','chat') and not deferred:
                key = due_key(job['schedule'], job['timezone'], now)
                if key:
                    store.queue_run(job['id'], key)
        store.connection.execute('INSERT OR REPLACE INTO scheduler_state(id,last_tick) VALUES (1,?)', (now.isoformat(),))
        store.connection.commit()
        return [r['id'] for r in store.queued_runs()]


class LocalScheduler:
    def __init__(self, database):
        self.database = Path(database).resolve()
        self.stop_event = Event()
        self.thread = Thread(target=self._loop, daemon=True)
        self.workers = {}
        self.inhibitor = None

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=12)
        if self.inhibitor and self.inhibitor.poll() is None:
            self.inhibitor.terminate()
            self.inhibitor.wait(timeout=5)
        # Reap child processes without interrupting already-started work.
        def reap():
            for process in list(self.workers.values()):
                process.wait()
        Thread(target=reap, daemon=True).start()

    def _loop(self):
        while not self.stop_event.is_set():
            store = None
            try:
                self.workers = {k: p for k, p in self.workers.items() if p.poll() is None}
                store = Store(self.database)
                from .settings import get_settings
                import shutil
                awake=get_settings(store)['keep_awake']
                if awake and self.inhibitor is None and shutil.which('systemd-inhibit'):
                    self.inhibitor=subprocess.Popen(['systemd-inhibit','--what=sleep','--who=OnCue','--why=Scheduled tasks','--mode=block','sleep','infinity'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                if not awake and self.inhibitor:
                    if self.inhibitor.poll() is None:
                        self.inhibitor.terminate();self.inhibitor.wait(timeout=5)
                    self.inhibitor=None
                ids = enqueue_due(store)
                for run_id in ids:
                    from .settings import get_settings
                    if len(self.workers) >= get_settings(store)['max_workers']:
                        break
                    if run_id not in self.workers:
                        self.workers[run_id] = subprocess.Popen(
                            __import__('oncue.service',fromlist=['command_prefix']).command_prefix() + ['--data-dir', str(self.database.parent), 'run-queued', str(run_id)],
                            cwd=Path(__file__).resolve().parent.parent,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True,
                        )
            except Exception:
                logging.exception('Local scheduler tick failed')
            finally:
                if store:
                    store.close()
            self.stop_event.wait(2)
