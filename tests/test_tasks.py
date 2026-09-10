"""End-to-end task scheduling, saved responses and local API boundaries."""
import json
import os
import re
import subprocess
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from oncue.dashboard import _handler, task_list
from oncue.runner import run_queued_job
from oncue.scheduler import enqueue_due, LocalScheduler
from oncue.schedules import from_form, next_run
from oncue.store import Store
from oncue.tasks import save_task, queue_manual, read_output


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'data' / 'scheduler.sqlite3')
        self.store.initialize()

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def task(self, **overrides):
        return save_task(self.store, {'instructions':'printf task-response', 'runner':'command',
                         'title':'My task', 'timezone':'UTC', 'frequency':'custom', 'cron':'* * * * *', **overrides})

    def test_due_task_without_project_runs_once_and_logs_response(self):
        slug = self.task()
        job = self.store.job(slug)
        self.assertTrue(Path(job['project_path']).is_dir())
        now = datetime(2027, 1, 1, tzinfo=timezone.utc)
        ids = enqueue_due(self.store, now)
        self.assertEqual(len(ids), 1)
        self.assertEqual(run_queued_job(self.store, ids[0], self.store.path.parent), 'succeeded')
        self.assertEqual(read_output(self.store, ids[0])['text'], 'task-response')
        self.assertEqual(enqueue_due(self.store, now), [])
        self.assertEqual(len(self.store.history(slug)), 1)

    def test_once_late_start_manual_run_and_history_preserving_edit(self):
        scheduled = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(days=1)
        slug = self.task(frequency='once', date=scheduled.strftime('%Y-%m-%d'), time=scheduled.strftime('%H:%M'))
        manual = queue_manual(self.store, slug)
        self.assertEqual(run_queued_job(self.store, manual, self.store.path.parent), 'succeeded')
        ids = enqueue_due(self.store, scheduled + timedelta(days=1))
        self.assertEqual(len(ids), 1)
        self.assertEqual(run_queued_job(self.store, ids[0], self.store.path.parent), 'succeeded')
        self.assertEqual(enqueue_due(self.store, scheduled + timedelta(days=2)), [])
        self.assertEqual(task_list(self.store)['jobs'][0]['state'], 'completed')
        save_task(self.store, {'title':'Updated task', 'instructions':'printf updated'}, slug)
        self.assertEqual(len(self.store.history(slug)), 2)
        self.store.archive_job(slug)
        self.assertEqual(read_output(self.store, ids[0])['text'], 'task-response')

    def test_disabled_creation_manual_run_and_busy_release_after_pause(self):
        slug = self.task(enabled=False)
        self.assertFalse(self.store.job(slug)['enabled'])
        self.assertEqual(enqueue_due(self.store), [])
        manual = queue_manual(self.store, slug)
        self.assertEqual(run_queued_job(self.store, manual, self.store.path.parent), 'succeeded')
        self.store.set_job_enabled(slug, True)
        rid = enqueue_due(self.store)[0]
        self.store.claim_queued_run(rid, os.getpid(), None)
        self.store.set_job_enabled(slug, False)
        self.store.release_run(rid, 'busy')
        self.assertEqual(self.store.history(slug)[0]['status'], 'skipped')
        self.assertEqual(self.store.queued_runs(), [])

    def test_presets_dst_and_impossible_schedule(self):
        self.assertEqual(from_form({'frequency':'weekdays','time':'09:30'}), '30 9 * * 1-5')
        self.assertEqual(next_run('30 2 * * *', 'America/Chicago', datetime(2027,3,14,7,0,tzinfo=timezone.utc)), '2027-03-15T07:30:00+00:00')
        self.assertEqual(next_run('30 1 * * *', 'America/Chicago', datetime(2027,11,7,6,31,tzinfo=timezone.utc)), '2027-11-07T07:30:00+00:00')
        self.assertIsNone(next_run('0 9 31 2 *', 'UTC'))
        with self.assertRaises(ValueError):
            from_form({'frequency':'once','date':'2027-03-14','time':'02:30','timezone':'America/Chicago'})

    def test_codex_response_is_separate_from_log_using_fake_executable(self):
        bindir=self.root/'bin';bindir.mkdir()
        fake=bindir/'codex'
        fake.write_text('#!'+sys.executable+'\nimport sys\nfrom pathlib import Path\nassert "--skip-git-repo-check" in sys.argv\nPath(sys.argv[sys.argv.index("--output-last-message")+1]).write_text("A useful answer")\nprint("diagnostic output")\n')
        fake.chmod(0o700)
        slug=self.task(runner='codex',provider='codex',model='test-model',instructions='Say hello')
        rid=queue_manual(self.store,slug)
        with patch.dict(os.environ,{'PATH':str(bindir)+os.pathsep+os.environ['PATH']}):
            self.assertEqual(run_queued_job(self.store,rid,self.store.path.parent),'succeeded')
        self.assertEqual(read_output(self.store,rid)['text'],'A useful answer')
        self.assertIn('diagnostic output',read_output(self.store,rid,True)['text'])
        self.assertEqual(Path(self.store.history(slug)[0]['response_path']).stat().st_mode & 0o777,0o600)

    def test_output_path_and_size_boundaries(self):
        slug=self.task();rid=queue_manual(self.store,slug)
        outside=self.root/'private';outside.write_text('not a scheduler response')
        self.store.connection.execute('UPDATE runs SET output_path=? WHERE id=?',(str(outside),rid));self.store.connection.commit()
        with self.assertRaises(ValueError):read_output(self.store,rid)
        log=self.store.path.parent/'runs'/'large';log.parent.mkdir();log.write_text('a'*300000)
        self.store.connection.execute('UPDATE runs SET output_path=? WHERE id=?',(str(log),rid));self.store.connection.commit()
        self.assertTrue(read_output(self.store,rid)['truncated'])
        self.assertEqual(len(read_output(self.store,rid)['text']),262144)

    def test_local_scheduler_dispatches_without_systemd(self):
        slug=self.task()
        scheduler=LocalScheduler(self.store.path);scheduler.start()
        try:
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                history=self.store.history(slug)
                if history and history[0]['status']=='succeeded':break
                time.sleep(.05)
            else:self.fail('Embedded scheduler did not complete task')
            self.assertEqual(read_output(self.store,history[0]['id'])['text'],'task-response')
        finally:scheduler.stop()

    def test_api_create_edit_run_and_protect_private_content(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),_handler(self.store.path))
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base) as r:token=re.search('name="csrf-token" content="([^"]+)"',r.read().decode())[1]
            def request(path,method='GET',data=None,**headers):
                req=Request(base+path,data=json.dumps(data).encode() if data is not None else None,method=method,headers={'X-CSRF-Token':token,'Content-Type':'application/json',**headers})
                with urlopen(req) as r:return json.load(r)
            with self.assertRaises(HTTPError) as error:request('/api/overview',**{'X-CSRF-Token':''})
            self.assertEqual(error.exception.code,403)
            error.exception.close()
            slug=request('/api/tasks','POST',{'instructions':'printf api-response','runner':'command','enabled':False})['slug']
            self.assertFalse(self.store.job(slug)['enabled'])
            request('/api/tasks/'+slug,'PATCH',{'title':'Edited task'})
            self.assertEqual(self.store.job(slug)['command'],'printf api-response')
            with self.assertRaises(HTTPError) as error:request('/api/tasks/'+slug,**{'X-CSRF-Token':''})
            self.assertEqual(error.exception.code,403)
            error.exception.close()
            with self.assertRaises(HTTPError) as error:request('/api/tasks/'+slug,**{'Origin':'http://127.0.0.1:9999'})
            error.exception.close()
            with self.assertRaises(HTTPError) as error:request('/',**{'Host':'attacker.example'})
            error.exception.close()
            rid=request('/api/tasks/'+slug+'/run','POST',{})['run_id']
            run_queued_job(self.store,rid,self.store.path.parent)
            self.assertEqual(request('/api/runs/'+str(rid))['text'],'api-response')
            self.assertEqual(request('/api/tasks/'+slug)['instructions'],'printf api-response')
        finally:server.shutdown();server.server_close();thread.join()

    def test_cli_task_add_edit_and_list(self):
        cmd=[sys.executable,'-m','oncue','--data-dir',str(self.store.path.parent),'task']
        added=subprocess.run(cmd+['add','--instructions','Hello','--model','test-model','--paused'],capture_output=True,text=True,check=True)
        slug=added.stdout.strip()
        subprocess.run(cmd+['edit',slug,'--frequency','weekdays','--time','08:15'],capture_output=True,text=True,check=True)
        self.assertEqual(self.store.job(slug)['schedule'],'15 8 * * 1-5')
        self.assertFalse(self.store.job(slug)['enabled'])
