"""Small stdio MCP bridge for local coding agents; calls the same task service."""
import json
import sys
from .tasks import save_task, queue_manual, read_output
from .attachments import list_attachments, read as read_attachment, remove as remove_attachment, upload
from .conversations import cancel_run, history, queue_message, retry_run
from .settings import get_settings

SCHEMA={'type':'object','properties':{
    'instructions':{'type':'string'},'title':{'type':'string'},'model':{'type':'string'},
    'provider':{'type':'string','enum':['codex','opencode']},
    'frequency':{'type':'string','enum':['once','daily','weekdays','weekly','custom']},
    'time':{'type':'string'},'date':{'type':'string'},'weekday':{'type':'integer'},
    'cron':{'type':'string'},'timezone':{'type':'string'},'enabled':{'type':'boolean'},
    'mode':{'type':'string','enum':['task','monitor']},'condition':{'type':'string'},
    'remember':{'type':'boolean'},'retry_safe':{'type':'boolean'},
    'max_checks':{'type':'integer'},'task_project_id':{'type':['integer','null']}},'additionalProperties':False}


def obj(properties, required=()):
    return {'type':'object','properties':properties,'required':list(required),'additionalProperties':False}


TOOLS=[
    {'name':'create_task','description':'Create a scheduled AI task or monitor. Use explicit user timing and stop condition. Model defaults to app settings.', 'inputSchema':{**SCHEMA,'required':['instructions','frequency']}},
    {'name':'update_task','description':'Update specified task fields, preserving omitted settings.','inputSchema':obj({'slug':{'type':'string'},'changes':SCHEMA},['slug','changes'])},
    {'name':'list_tasks','description':'List tasks, next runs and states.','inputSchema':obj({})},
    {'name':'task_action','description':'Run now, pause, resume, or archive a task. Archiving preserves history.','inputSchema':obj({'slug':{'type':'string'},'action':{'enum':['run','pause','resume','archive']}},['slug','action'])},
    {'name':'delete_task','description':'Permanently delete a task, conversation, run history, outputs, and task files. Requires explicit confirmation.','inputSchema':obj({'slug':{'type':'string'},'confirm_permanent':{'type':'boolean'}},['slug','confirm_permanent']),'annotations':{'destructiveHint':True}},
    {'name':'send_message','description':'Send a follow-up message in a task conversation. The reply is queued asynchronously and may update the schedule when requested.','inputSchema':obj({'slug':{'type':'string'},'text':{'type':'string'}},['slug','text'])},
    {'name':'read_history','description':'Read task conversation, responses and failures. Pass before for earlier pages.','inputSchema':obj({'slug':{'type':'string'},'before':{'type':'integer'}},['slug'])},
    {'name':'read_response','description':'Read one run response or execution log.','inputSchema':obj({'run_id':{'type':'integer'},'log':{'type':'boolean'}},['run_id'])},
    {'name':'retry_run','description':'Retry a failed run now or later. Verify repeat execution is appropriate.','inputSchema':obj({'run_id':{'type':'integer'},'minutes':{'type':'integer'}},['run_id'])},
    {'name':'cancel_run','description':'Cancel queued or running work while retaining the attempt in task history.','inputSchema':obj({'run_id':{'type':'integer'}},['run_id'])},
    {'name':'scheduler_settings','description':'Read configured provider/model and non-secret defaults.','inputSchema':obj({})},
    {'name':'list_projects','description':'List organizational projects and their task counts.','inputSchema':obj({})},
    {'name':'create_project','description':'Create an organizational project with optional shared instructions and visual identity.','inputSchema':obj({'name':{'type':'string'},'instructions':{'type':'string'},'icon':{'type':'string'},'color':{'type':'string'}},['name'])},
    {'name':'update_project','description':'Update specified organizational project fields, preserving omitted values.','inputSchema':obj({'project_id':{'type':'integer'},'name':{'type':'string'},'instructions':{'type':'string'},'icon':{'type':'string'},'color':{'type':'string'}},['project_id'])},
    {'name':'delete_project','description':'Permanently delete an organizational project and its shared references. Tasks are retained and become unassigned. Requires explicit confirmation.','inputSchema':obj({'project_id':{'type':'integer'},'confirm_permanent':{'type':'boolean'}},['project_id','confirm_permanent']),'annotations':{'destructiveHint':True}},
    {'name':'list_attachments','description':'List current reference files for a task or project. Owner is a task slug or project ID.','inputSchema':obj({'owner_type':{'type':'string','enum':['task','project']},'owner':{'anyOf':[{'type':'string'},{'type':'integer'}]}},['owner_type','owner'])},
    {'name':'upload_attachment','description':'Upload or replace a UTF-8 .txt or .md reference file. Content is base64 encoded and limited to 64 KiB.','inputSchema':obj({'owner_type':{'type':'string','enum':['task','project']},'owner':{'anyOf':[{'type':'string'},{'type':'integer'}]},'name':{'type':'string'},'content':{'type':'string'}},['owner_type','owner','name','content'])},
    {'name':'read_attachment','description':'Read one reference attachment as UTF-8 text.','inputSchema':obj({'attachment_id':{'type':'integer'}},['attachment_id'])},
    {'name':'delete_attachment','description':'Remove one reference attachment from future task runs. Existing run snapshots are unchanged.','inputSchema':obj({'attachment_id':{'type':'integer'}},['attachment_id'])},
]


def validate_arguments(value, schema, path='arguments'):
    """Enforce the advertised tool boundary, including nested change objects."""
    if 'anyOf' in schema:
        for choice in schema['anyOf']:
            try:validate_arguments(value,choice,path);return
            except ValueError:pass
        raise ValueError(f'{path} has an invalid type')
    kind = schema.get('type')
    if isinstance(kind,list):
        if value is None and 'null' in kind:return
        choices=[item for item in kind if item!='null']
        if not any(_matches_type(value,item) for item in choices):raise ValueError(f'{path} has an invalid type')
        kind=next(item for item in choices if _matches_type(value,item))
    if kind == 'object':
        if not isinstance(value, dict): raise ValueError(f'{path} must be an object')
        properties = schema.get('properties', {})
        if set(value) - properties.keys(): raise ValueError(f'{path} contains unsupported fields')
        if set(schema.get('required', [])) - value.keys(): raise ValueError(f'{path} is missing required fields')
        for key, item in value.items(): validate_arguments(item, properties[key], path + '.' + key)
    elif kind == 'string' and not isinstance(value, str):
        raise ValueError(f'{path} must be a string')
    elif kind == 'integer' and type(value) is not int:
        raise ValueError(f'{path} must be an integer')
    elif kind == 'boolean' and type(value) is not bool:
        raise ValueError(f'{path} must be a boolean')
    if 'enum' in schema and value not in schema['enum']: raise ValueError(f'{path} has an unsupported value')


def _matches_type(value, kind):
    return ((kind=='string' and isinstance(value,str)) or (kind=='integer' and type(value) is int)
            or (kind=='boolean' and type(value) is bool) or (kind=='object' and isinstance(value,dict)))


def call(store,name,args):
    tool = next((tool for tool in TOOLS if tool['name'] == name), None)
    if not tool: raise ValueError('Unknown tool')
    validate_arguments(args, tool['inputSchema'])
    if name in ('update_task','send_message') or name == 'task_action' and args['action'] == 'run':
        job = store.job(args['slug'])
        if job and job['runner'] == 'command':
            raise ValueError('Shell tasks must be edited or run through the local UI or CLI')
    if name == 'retry_run':
        job = store.run_job(args['run_id'])
        if job and job['runner'] == 'command':
            raise ValueError('Shell tasks must be retried through the local UI or CLI')
    from .dashboard import task_list
    from .service import start
    if name=='create_task':result={'slug':save_task(store,args)}
    elif name=='update_task':result={'slug':save_task(store,args['changes'],args['slug'])}
    elif name=='list_tasks':return task_list(store)['jobs']
    elif name=='send_message':result=queue_message(store,args['slug'],args['text'])
    elif name=='read_history':return history(store,args['slug'],args.get('before'))
    elif name=='read_response':return read_output(store,args['run_id'],args.get('log',False))
    elif name=='scheduler_settings':return get_settings(store)
    elif name=='retry_run':result={'run_id':retry_run(store,args['run_id'],args.get('minutes',0))}
    elif name=='cancel_run':result={'ok':cancel_run(store,args['run_id'])}
    elif name=='list_projects':return [dict(row) for row in store.task_projects()]
    elif name=='create_project':result={'project_id':store.create_task_project(args['name'],args.get('instructions',''),args.get('icon',''),args.get('color',''))}
    elif name=='update_project':
        store.update_task_project(args['project_id'],args.get('name'),args.get('instructions'),args.get('icon'),args.get('color'));result={'ok':True}
    elif name=='delete_project':
        if not args['confirm_permanent']:raise ValueError('Permanent project deletion requires confirm_permanent=true')
        store.delete_task_project(args['project_id']);result={'ok':True}
    elif name=='list_attachments':return list_attachments(store,args['owner_type'],args['owner'])
    elif name=='upload_attachment':result={'attachment_id':upload(store,args['owner_type'],args['owner'],args['name'],args['content'])}
    elif name=='read_attachment':
        attachment_name,content=read_attachment(store,args['attachment_id']);return {'name':attachment_name,'text':content.decode('utf-8')}
    elif name=='delete_attachment':remove_attachment(store,args['attachment_id']);result={'ok':True}
    elif name=='delete_task':
        if not args['confirm_permanent']:raise ValueError('Permanent task deletion requires confirm_permanent=true')
        if not store.delete_job(args['slug']):raise ValueError('Task not found')
        result={'ok':True}
    elif name=='task_action':
        action=args['action'];slug=args['slug']
        if action=='run':result={'run_id':queue_manual(store,slug)}
        elif action in ('pause','resume','archive'):
            ok=store.archive_job(slug) if action=='archive' else store.set_job_enabled(slug,action=='resume')
            if not ok:raise ValueError('Task not found')
            result={'ok':True}
        else:raise ValueError('Unknown action')
    else:raise ValueError('Unknown tool')
    start(store.path.parent)
    return result


def handle(store,request):
    id=request.get('id');method=request.get('method');params=request.get('params',{})
    if id is None:return None
    response={'jsonrpc':'2.0','id':id}
    if not isinstance(params,dict) or not isinstance(method,str):
        return {**response,'error':{'code':-32600,'message':'Expected a method and object params'}}
    if method=='initialize':
        version=params.get('protocolVersion')
        if version not in ('2024-11-05','2025-03-26','2025-06-18'):version='2025-06-18'
        result={'protocolVersion':version,'capabilities':{'tools':{}},'serverInfo':{'name':'oncue','version':'0.3.0'}}
    elif method=='ping':result={}
    elif method=='tools/list':result={'tools':TOOLS}
    elif method=='tools/call':
        try:
            args=params.get('arguments',{})
            if not isinstance(args,dict):raise ValueError('Tool arguments must be an object')
            value=call(store,params['name'],args)
            result={'content':[{'type':'text','text':json.dumps(value)}],'isError':False}
        except Exception as error:result={'content':[{'type':'text','text':str(error)}],'isError':True}
    else:return {**response,'error':{'code':-32601,'message':'Method not found'}}
    return {**response,'result':result}


def serve(store):
    while True:
        line = sys.stdin.readline(1048577)
        if not line: break
        try:
            if len(line)>1048576:
                print(json.dumps({'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Request too large'}}),flush=True)
                return
            request=json.loads(line)
            if not isinstance(request,dict):raise ValueError('Expected an object')
            result=handle(store,request)
        except (ValueError,TypeError):result={'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Invalid JSON-RPC request'}}
        if result:
            print(json.dumps(result),flush=True)
