import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from oncue.migration import migrate_data_dir, default_data_dir, LEGACY_NAME
from oncue.store import Store, process_start_ticks
from oncue.tasks import save_task, queue_manual, read_output
from oncue.runner import run_queued_job


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.home=Path(self.temp.name)
        self.old=self.home/'.local/share'/LEGACY_NAME
        self.new=self.home/'.local/share/oncue/data'
        self.patch=patch('pathlib.Path.home',return_value=self.home);self.patch.start()

    def tearDown(self):
        self.patch.stop();self.temp.cleanup()

    def test_moves_history_workspaces_and_queued_configuration(self):
        store=Store(self.old/'scheduler.sqlite3');store.initialize()
        slug=save_task(store,{'instructions':'printf migrated','runner':'command','enabled':False})
        first=queue_manual(store,slug)
        self.assertEqual(run_queued_job(store,first,self.old),'succeeded')
        queued=queue_manual(store,slug)
        snapshot=dict(store.job(slug))
        store.connection.execute('UPDATE runs SET config_snapshot=? WHERE id=?',(json.dumps(snapshot),queued));store.connection.commit();store.close()
        with patch('oncue.service.stop'),patch('oncue.service.service_info',return_value=None):
            self.assertEqual(migrate_data_dir(self.new),self.new)
        self.assertTrue(self.old.is_symlink())
        store=Store(self.new/'scheduler.sqlite3')
        self.assertEqual(read_output(store,first)['text'],'migrated')
        self.assertEqual(run_queued_job(store,queued,self.new),'succeeded')
        self.assertEqual(read_output(store,queued)['text'],'migrated')
        self.assertEqual(len(store.history(slug)),2);store.close()
        self.assertEqual(migrate_data_dir(self.old),self.new)
        self.old.unlink()  # Recover an interruption between move and alias creation.
        self.assertEqual(migrate_data_dir(self.new),self.new)
        self.assertTrue(self.old.is_symlink())

    def test_refuses_conflicting_stores(self):
        self.old.mkdir(parents=True);self.new.mkdir(parents=True)
        (self.old/'keep').write_text('old');(self.new/'keep').write_text('new')
        with self.assertRaisesRegex(ValueError,'Both old and new'):
            migrate_data_dir(self.new)
        self.assertEqual((self.old/'keep').read_text(),'old')
        self.assertEqual((self.new/'keep').read_text(),'new')

    def test_refuses_to_move_active_worker(self):
        store=Store(self.old/'scheduler.sqlite3');store.initialize()
        slug=save_task(store,{'instructions':'hello','enabled':False})
        store.start_run(store.job(slug)['id'],'manual:2026-01-01T00:00:00+00:00',os.getpid(),process_start_ticks(os.getpid()))
        store.close()
        with patch('oncue.service.stop'),patch('oncue.service.service_info',return_value=None):
            with self.assertRaisesRegex(ValueError,'still running'):migrate_data_dir(self.new)
        self.assertFalse(self.new.exists());self.assertTrue(self.old.is_dir())

    def test_custom_location_and_environment_precedence(self):
        custom=self.home/'custom'
        self.assertEqual(migrate_data_dir(custom),custom)
        with patch.dict(os.environ,{'ONCUE_DATA':str(custom),'CODEX_LOCAL_SCHEDULER_DATA':'/old'}):
            self.assertEqual(default_data_dir(),custom)

    def test_updates_generated_launchers_without_enabling_services(self):
        from oncue.migration import migrate_launchers
        unit=self.home/'.config/systemd/user/oncue.service';unit.parent.mkdir(parents=True)
        unit.write_text('ExecStart=/usr/bin/python -m codex_local_scheduler --data-dir '+str(self.old)+' dashboard\n')
        with patch('subprocess.run') as run:
            self.assertEqual(migrate_launchers(),[unit])
            run.assert_called_once_with(['systemctl','--user','daemon-reload'],check=True)
        self.assertIn('-m oncue',unit.read_text())
        self.assertIn(str(self.new),unit.read_text())
