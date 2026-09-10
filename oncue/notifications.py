"""Durable, at-least-once local notification delivery."""
import json, subprocess, urllib.error, urllib.request, uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
from .tasks import read_output
from .settings import get_settings

RETRIES=(1,5,30)
def _secrets_path(store): return store.path.parent/'notification-secrets.json'
def destinations(store):
    value=get_settings(store).get('webhooks',[])
    try: secrets=json.loads(_secrets_path(store).read_text()).get('webhooks',[])
    except (OSError,ValueError): secrets=[]
    by_name={item.get('name'):item for item in secrets}
    return [{**item,**by_name.get(item.get('name'),{})} for item in value if item.get('name') in by_name]
def queue_run_event(store, job, run_id):
    run=store.connection.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone()
    if not run or run['status']=='skipped' or not run['notify'] or run['kind'] in ('plan','chat'): return
    if run['status'] in ('failed','timed_out') and store.connection.execute('SELECT 1 FROM runs WHERE retry_of=?',(run_id,)).fetchone(): return
    event='completed' if run['status']=='succeeded' else 'failed'
    if job.get('task_config') and json.loads(job['task_config']).get('mode')=='monitor': event='monitor_completed' if not job['enabled'] else 'monitor_changed'
    source=Path(run['response_path'] or run['output_path']) if (run['response_path'] or run['output_path']) else None
    root=(store.path.parent/'runs').resolve()
    if source and source.resolve().is_relative_to(root): result=source.read_text(encoding='utf-8',errors='replace')
    else: result=read_output(store,run_id)['text']
    payload={'version':1,'event_id':str(uuid.uuid4()),'event':event,'timestamp':datetime.now(timezone.utc).isoformat(),'task':{'slug':job['slug'],'title':job['title'] or job['slug']},'project':job.get('task_project_name'),'run_id':run_id,'status':run['status'],'result':result,'error':run['error']}
    eid=payload['event_id'];store.connection.execute('INSERT INTO notification_events(id,run_id,event,payload) VALUES (?,?,?,?)',(eid,run_id,event,json.dumps(payload)))
    settings=get_settings(store)
    for dest in destinations(store):
        if dest.get('enabled',True): store.connection.execute("INSERT OR IGNORE INTO notification_deliveries(event_id,destination,kind) VALUES (?,?,'webhook')",(eid,dest.get('name','webhook')))
    if settings.get('desktop_notifications',False): store.connection.execute("INSERT OR IGNORE INTO notification_deliveries(event_id,destination,kind) VALUES (?,?,'desktop')",(eid,'desktop'))
    store.connection.commit()
def process(store):
    rows=store.connection.execute("SELECT * FROM notification_deliveries WHERE status='queued' AND (retry_at IS NULL OR retry_at<=?)",(datetime.now(timezone.utc).isoformat(),)).fetchall()
    for row in rows:
        event=store.connection.execute('SELECT payload FROM notification_events WHERE id=?',(row['event_id'],)).fetchone(); payload=json.loads(event['payload'])
        try:
            if row['kind']=='desktop':
                subprocess.run(['notify-send','--expire-time=3600000','OnCue: '+payload['event'],payload['task']['title']+'\n'+payload['result'][:240]],timeout=10,check=True)
            else:
                dest=next((d for d in destinations(store) if d.get('name')==row['destination']),None)
                if not dest: raise ValueError('Webhook destination was removed')
                url=dest.get('url','');
                if not url.startswith('https://') and not (dest.get('allow_local') and url.startswith('http://')): raise ValueError('Webhook URL must use HTTPS')
                headers={'Content-Type':'application/json','Idempotency-Key':payload['event_id']}
                if dest.get('token'): headers['Authorization']='Bearer '+dest['token']
                req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers=headers,method='POST')
                with urllib.request.urlopen(req,timeout=10) as response:
                    if not 200<=response.status<300: raise urllib.error.HTTPError(url,response.status,'HTTP error',response.headers,None)
            store.connection.execute("UPDATE notification_deliveries SET status='delivered',delivered_at=CURRENT_TIMESTAMP WHERE id=?",(row['id'],))
        except Exception as error:
            attempt=row['attempt']+1
            if attempt<=len(RETRIES):
                due=(datetime.now(timezone.utc)+timedelta(minutes=RETRIES[attempt-1])).isoformat();store.connection.execute("UPDATE notification_deliveries SET attempt=?,retry_at=?,error=? WHERE id=?",(attempt,due,str(error)[:1000],row['id']))
            else: store.connection.execute("UPDATE notification_deliveries SET status='failed',attempt=?,error=? WHERE id=?",(attempt,str(error)[:1000],row['id']))
    store.connection.commit()
