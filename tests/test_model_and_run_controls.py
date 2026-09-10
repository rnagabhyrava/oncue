"""Conversation actions, safe onboarding defaults and agent-tool boundaries."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from oncue.store import Store
from oncue.tasks import save_task, read_output
from oncue.settings import get_settings, update_settings
from oncue.conversations import queue_message
from oncue.runner import run_queued_job
from oncue.mcp_server import handle


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'scheduler.sqlite3')
        self.store.initialize()

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_first_boot_free_model_and_existing_preferences(self):
        self.assertEqual(get_settings(self.store)['provider'], 'opencode')
        self.assertEqual(get_settings(self.store)['model'], 'opencode/big-pickle')
        update_settings(self.store, {'provider': 'codex', 'model': 'my-saved-model'})
        self.store.initialize()
        self.assertEqual(get_settings(self.store)['model'], 'my-saved-model')
        self.assertEqual(get_settings(self.store)['provider'], 'codex')

    def test_conversation_model_override_is_local(self):
        q = queue_message(self.store, None, 'Plan my morning', {'provider':'codex','model':'chosen-model'})
        self.assertEqual(self.store.job(q['slug'])['model'], 'chosen-model')
        self.assertEqual(get_settings(self.store)['model'], 'opencode/big-pickle')
        save_task(self.store, {'provider':'opencode','model':'opencode/another-free'}, q['slug'])
        self.assertEqual(self.store.job(q['slug'])['model'], 'opencode/another-free')
        self.assertEqual(get_settings(self.store)['model'], 'opencode/big-pickle')

    def test_run_now_executes_saved_task_without_rescheduling(self):
        slug = save_task(self.store, {'instructions':'printf run-now-result','runner':'command',
                                     'frequency':'daily','time':'21:00','enabled':False})
        schedule = self.store.job(slug)['schedule']
        q = queue_message(self.store, slug, 'Run now!')
        run = self.store.connection.execute('SELECT * FROM runs WHERE id=?',(q['run_id'],)).fetchone()
        self.assertEqual(run['kind'], 'task')
        self.assertEqual(run_queued_job(self.store, q['run_id'], self.root), 'succeeded')
        self.assertEqual(read_output(self.store, q['run_id'])['text'], 'run-now-result')
        self.assertEqual(self.store.job(slug)['schedule'], schedule)
        self.assertFalse(self.store.job(slug)['enabled'])

    def test_run_now_requires_configured_task_and_no_negation_trigger(self):
        with self.assertRaisesRegex(ValueError, 'Schedule a task first'):
            queue_message(self.store, None, 'Run now')
        q = queue_message(self.store, None, "Don't run now")
        run = self.store.connection.execute('SELECT kind FROM runs WHERE id=?',(q['run_id'],)).fetchone()
        self.assertEqual(run['kind'], 'plan')
        with self.assertRaisesRegex(ValueError, 'Finish scheduling'):
            queue_message(self.store, q['slug'], 'Run now')

    def test_mcp_rejects_undeclared_execution_fields_before_mutation(self):
        def invoke(name,args):
            return handle(self.store, {'id':1,'method':'tools/call','params':{'name':name,'arguments':args}})['result']
        with patch('oncue.service.start') as start:
            malicious = {'instructions':'printf unsafe','frequency':'daily','runner':'command'}
            self.assertTrue(invoke('create_task', malicious)['isError'])
            self.assertEqual(len(self.store.jobs()), 0)
            slug = save_task(self.store, {'instructions':'Safe AI task','frequency':'daily'})
            self.assertTrue(invoke('update_task', {'slug':slug,'changes':{'instructions':'printf unsafe','runner':'command'}})['isError'])
            self.assertTrue(invoke('update_task', {'slug':slug,'changes':{'sandbox':'workspace-write'}})['isError'])
            self.assertTrue(invoke('retry_run', {'run_id':True})['isError'])
            self.assertEqual(self.store.job(slug)['runner'], 'codex')
            shell = save_task(self.store, {'instructions':'printf original','runner':'command','frequency':'daily'})
            self.assertTrue(invoke('update_task', {'slug':shell,'changes':{'instructions':'printf replaced'}})['isError'])
            self.assertTrue(invoke('task_action', {'slug':shell,'action':'run'})['isError'])
            self.assertEqual(self.store.job(shell)['command'], 'printf original')
            start.assert_not_called()
