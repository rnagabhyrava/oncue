"""Exercise durable planning, monitoring, retries, history and the MCP bridge."""
import base64
import json
import sys
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from oncue.store import Store
from oncue.tasks import save_task, queue_manual, read_output
from oncue.conversations import queue_message, accept_response, history, message, retry_run, prompt_for
from oncue.settings import update_settings
from oncue.runner import run_queued_job
from oncue.scheduler import enqueue_due
from oncue.exports import archive
from oncue.mcp_server import handle


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.root=Path(self.temp.name)
        self.store=Store(self.root/'scheduler.sqlite3');self.store.initialize()
        update_settings(self.store,{'provider':'codex','model':'test-model','timezone':'UTC','retry_minutes':1})

    def tearDown(self):
        self.store.close();self.temp.cleanup()

    def task(self,**kw):
        return save_task(self.store,{'instructions':'Check the event','frequency':'custom','cron':'* * * * *',**kw})

    def execute(self,rid,text,exit_code=0):
        def cmd(provider,model,prompt,path,**kw):
            self.last_prompt=prompt
            return [sys.executable,'-c',f'from pathlib import Path;Path({str(path)!r}).write_text({text!r});print({text!r});raise SystemExit({exit_code})']
        with patch('oncue.providers.command',side_effect=cmd):
            return run_queued_job(self.store,rid,self.root)

    def test_planning_clarification_schedule_due_and_prior_context(self):
        q=queue_message(self.store,None,'Remind me to stretch')
        self.assertEqual(self.execute(q['run_id'],json.dumps({'action':'clarify','reply':'When?'})),'succeeded')
        self.assertFalse(self.store.job(q['slug'])['enabled'])
        self.assertEqual(enqueue_due(self.store),[])
        second=queue_message(self.store,q['slug'],'Every minute')
        answer={'action':'schedule','reply':'Scheduled.','task':{'instructions':'Suggest a stretch','frequency':'custom','cron':'* * * * *','timezone':'UTC'}}
        self.assertEqual(self.execute(second['run_id'],json.dumps(answer)),'succeeded')
        self.assertIn('When?',self.last_prompt)
        due=enqueue_due(self.store)
        self.assertEqual(len(due),1)
        self.assertEqual(self.execute(due[0],'Try a shoulder stretch.'),'succeeded')
        self.assertEqual(enqueue_due(self.store),[])
        self.assertEqual(len(history(self.store,q['slug'])['messages']),5)
        self.assertIn('Try a shoulder stretch.',history(self.store,q['slug'])['messages'][-1]['content'])

    def test_schedule_accepts_valid_task_without_acknowledgement(self):
        q=queue_message(self.store,None,'Every Monday at 9, give me a planning exercise')
        with self.assertRaisesRegex(ValueError,'Finish scheduling'):queue_manual(self.store,q['slug'])
        answer={'action':'schedule','task':{'instructions':'Give me a planning exercise','frequency':'weekly','weekday':1,'time':'09:00','timezone':'UTC'}}
        self.assertEqual(self.execute(q['run_id'],json.dumps(answer)),'succeeded')
        self.assertTrue(self.store.job(q['slug'])['enabled'])
        self.assertIn('Your task is scheduled.',read_output(self.store,q['run_id'])['text'])

    def test_invalid_proposal_cannot_change_model_or_permissions(self):
        q=queue_message(self.store,None,'Every day at 9')
        answer={'action':'schedule','reply':'Okay','task':{'model':'other','sandbox':'workspace-write'}}
        self.assertEqual(self.execute(q['run_id'],json.dumps(answer)),'failed')
        self.assertFalse(self.store.job(q['slug'])['enabled'])
        self.assertEqual(self.store.job(q['slug'])['model'],'test-model')

    def test_usage_limit_persists_failure_and_delayed_retry_then_success(self):
        slug=self.task(retry_safe=True);rid=queue_manual(self.store,slug)
        self.assertEqual(self.execute(rid,"ERROR: You've hit your usage limit.",1),'failed')
        old=self.store.connection.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
        self.assertEqual(old['error_kind'],'usage_limit')
        child=self.store.connection.execute('SELECT * FROM runs WHERE retry_of=?',(rid,)).fetchone()
        self.assertIsNotNone(child)
        self.assertEqual(run_queued_job(self.store,child['id'],self.root),'already-claimed')
        self.store.connection.execute("UPDATE runs SET retry_at='2000-01-01T00:00:00+00:00' WHERE id=?",(child['id'],));self.store.connection.commit()
        self.assertEqual(self.execute(child['id'],'Success'),'succeeded')
        self.assertEqual(len(history(self.store,slug)['messages']),2)
        self.assertEqual(read_output(self.store,rid)['status'],'failed')
        with self.assertRaises(ValueError):retry_run(self.store,rid,0)

    def test_manual_retry_of_paused_task_and_no_auto_retry_of_actions(self):
        slug=self.task(enabled=False);rid=queue_manual(self.store,slug)
        self.execute(rid,'network unavailable',1)
        self.assertEqual(len(self.store.history(slug)),1)
        child=retry_run(self.store,rid,0)
        self.assertEqual(self.execute(child,'Done'),'succeeded')

    def test_monitor_quiet_changes_and_evidence_required_for_completion(self):
        slug=self.task(mode='monitor',condition='Event date is officially announced')
        def check(data):
            rid=queue_manual(self.store,slug)
            return rid,self.execute(rid,json.dumps(data))
        base={'summary':'No announcement','changed':False,'complete':False,'memory':'Nothing yet','evidence':[]}
        rid,status=check(base);self.assertEqual(status,'succeeded')
        self.assertEqual(self.store.recent_runs(1)[0]['notify'],0)
        rid,status=check({**base,'complete':True});self.assertEqual(status,'failed')
        self.assertTrue(self.store.job(slug)['enabled'])
        rid,status=check({**base,'complete':True,'changed':True,'evidence':[{'url':'https://example.com/event','detail':'Official date announced'}]})
        self.assertEqual(status,'succeeded');self.assertFalse(self.store.job(slug)['enabled'])
        self.assertIsNotNone(self.store.job(slug)['completed_at'])
        self.assertEqual(enqueue_due(self.store),[])

    def test_history_pagination_export_full_output_and_migration(self):
        slug=self.task();job=self.store.job(slug)
        for i in range(105):message(self.store,job['id'],'user',f'message {i}')
        newest=history(self.store,slug);older=history(self.store,slug,newest['before'],100)
        self.assertEqual(len(newest['messages'])+len(older['messages']),105)
        text='response '+('x'*300000);rid=queue_manual(self.store,slug)
        # Direct file avoids an operating-system argv length limit in fake provider.
        path=self.root/'runs'/slug/'large.txt';path.parent.mkdir(parents=True);path.write_text(text)
        self.store.connection.execute("UPDATE runs SET status='succeeded',response_path=? WHERE id=?",(str(path),rid));self.store.connection.commit()
        self.store.initialize();self.store.initialize()
        self.assertEqual(len(self.store.connection.execute('SELECT * FROM messages WHERE run_id=?',(rid,)).fetchall()),1)
        self.assertTrue(read_output(self.store,rid)['truncated'])
        with archive(self.store,slug) as output,zipfile.ZipFile(output) as zipped:
            self.assertEqual(zipped.read(f'runs/{rid}.response.txt').decode(),text)

    def test_global_defaults_do_not_modify_existing_jobs_and_mcp(self):
        slug=self.task();update_settings(self.store,{'model':'changed','theme':'dark'})
        self.assertEqual(self.store.job(slug)['model'],'test-model')
        with patch('oncue.service.start'):
            response=handle(self.store,{'id':1,'method':'tools/call','params':{'name':'create_task','arguments':{'instructions':'Say hello','frequency':'daily','time':'09:00'}}})
        self.assertFalse(response['result']['isError'])
        new=json.loads(response['result']['content'][0]['text'])['slug']
        self.assertEqual(self.store.job(new)['model'],'changed')
        self.assertEqual(len(handle(self.store,{'id':2,'method':'tools/list'})['result']['tools']),19)

    def test_mcp_covers_projects_references_followups_and_safe_deletion(self):
        def invoke(name,args):
            response=handle(self.store,{'id':1,'method':'tools/call','params':{'name':name,'arguments':args}})['result']
            return response,json.loads(response['content'][0]['text']) if not response['isError'] else None
        with patch('oncue.service.start'):
            response,project=invoke('create_project',{'name':'Research','instructions':'Prefer primary sources','icon':'🔎','color':'#4f94ed'})
            self.assertFalse(response['isError']);project_id=project['project_id']
            response,created=invoke('create_task',{'instructions':'Check the launch','frequency':'daily','time':'09:00','mode':'monitor',
                                                   'condition':'An official date is announced','max_checks':12,'task_project_id':project_id})
            self.assertFalse(response['isError']);slug=created['slug']
            self.assertEqual(json.loads(self.store.job(slug)['task_config'])['max_checks'],12)
            self.assertEqual(self.store.job(slug)['task_project_id'],project_id)
            self.assertFalse(invoke('update_task',{'slug':slug,'changes':{'task_project_id':None}})[0]['isError'])
            self.assertIsNone(self.store.job(slug)['task_project_id'])
            self.assertFalse(invoke('update_task',{'slug':slug,'changes':{'task_project_id':project_id}})[0]['isError'])

            encoded=base64.b64encode(b'# Brief\nUse the official announcement.').decode()
            response,uploaded=invoke('upload_attachment',{'owner_type':'project','owner':project_id,'name':'brief.md','content':encoded})
            self.assertFalse(response['isError']);attachment_id=uploaded['attachment_id']
            self.assertEqual(invoke('list_attachments',{'owner_type':'project','owner':project_id})[1][0]['name'],'brief.md')
            self.assertIn('official announcement',invoke('read_attachment',{'attachment_id':attachment_id})[1]['text'])
            self.assertFalse(invoke('delete_attachment',{'attachment_id':attachment_id})[0]['isError'])

            response,followup=invoke('send_message',{'slug':slug,'text':'Move this to 10 AM'})
            self.assertFalse(response['isError'])
            self.assertFalse(invoke('cancel_run',{'run_id':followup['run_id']})[0]['isError'])
            self.assertEqual(self.store.connection.execute('SELECT status FROM runs WHERE id=?',(followup['run_id'],)).fetchone()['status'],'skipped')

            self.assertTrue(invoke('delete_project',{'project_id':project_id,'confirm_permanent':False})[0]['isError'])
            self.assertFalse(invoke('delete_project',{'project_id':project_id,'confirm_permanent':True})[0]['isError'])
            self.assertIsNone(self.store.job(slug)['task_project_id'])
            self.assertTrue(invoke('delete_task',{'slug':slug,'confirm_permanent':False})[0]['isError'])
            self.assertFalse(invoke('delete_task',{'slug':slug,'confirm_permanent':True})[0]['isError'])
            self.assertIsNone(self.store.job(slug,include_archived=True))

    def test_cancel_running_provider_preserves_attempt(self):
        import threading,time
        slug=self.task();rid=queue_manual(self.store,slug)
        def cancel():
            other=Store(self.root/'scheduler.sqlite3')
            for _ in range(100):
                row=other.connection.execute('SELECT output_path FROM runs WHERE id=?',(rid,)).fetchone()
                if row['output_path']:
                    other.connection.execute('UPDATE runs SET cancel_requested=1 WHERE id=?',(rid,));other.connection.commit();break
                time.sleep(.02)
            other.close()
        thread=threading.Thread(target=cancel);thread.start()
        with patch('oncue.providers.command',return_value=[sys.executable,'-c','import time;time.sleep(30)']):
            self.assertEqual(run_queued_job(self.store,rid,self.root),'skipped')
        thread.join(timeout=3)
        self.assertEqual(history(self.store,slug)['messages'][-1]['run']['error'],'Cancelled by user')

    def test_managed_login_protocol_does_not_store_tokens(self):
        from oncue.auth import Login
        fake=self.root/'auth-server'
        fake.write_text('#!'+sys.executable+'\nimport sys,json\nfor line in sys.stdin:\n r=json.loads(line)\n if r.get("method")=="initialize":print(json.dumps({"id":r["id"],"result":{}}),flush=True)\n if r.get("method")=="account/login/start":print(json.dumps({"id":r["id"],"result":{"authUrl":"https://auth.openai.com/test-login"}}),flush=True)\n')
        fake.chmod(0o700)
        with patch('oncue.auth.executable',return_value=str(fake)):
            login=Login(self.root,{})
            try:self.assertEqual(login.state,{'status':'waiting','url':'https://auth.openai.com/test-login'})
            finally:login.close()
        self.assertFalse(self.store.connection.execute('SELECT * FROM messages').fetchall())
        self.assertTrue((self.root/'providers/codex').is_dir())

    def test_mcp_bad_params_returns_error_and_negotiates_version(self):
        result=handle(self.store,{'id':1,'method':'tools/list','params':[]})
        self.assertEqual(result['error']['code'],-32600)
        result=handle(self.store,{'id':2,'method':'initialize','params':{'protocolVersion':'unsupported'}})
        self.assertEqual(result['result']['protocolVersion'],'2025-06-18')

    def test_shell_tasks_reject_ai_conversation_and_monitor(self):
        slug=self.task(runner='command',model=None)
        with self.assertRaises(ValueError):queue_message(self.store,slug,'Change it')
        with self.assertRaises(ValueError):self.task(runner='command',model=None,mode='monitor',condition='done')

if __name__=='__main__':unittest.main()
