"""Small stdio MCP bridge for local coding agents; calls the same task service."""
import json
import sys
from .tasks import save_task, queue_manual, read_output
from .conversations import history, retry_run
from .settings import get_settings

SCHEMA={'type':'object','properties':{
    'instructions':{'type':'string'},'title':{'type':'string'},'model':{'type':'string'},
    'provider':{'type':'string','enum':['codex','opencode']},
    'frequency':{'type':'string','enum':['once','daily','weekdays','weekly','custom']},
    'time':{'type':'string'},'date':{'type':'string'},'weekday':{'type':'integer'},
    'cron':{'type':'string'},'timezone':{'type':'string'},'enabled':{'type':'boolean'},
    'mode':{'type':'string','enum':['task','monitor']},'condition':{'type':'string'},
    'remember':{'type':'boolean'},'retry_safe':{'type':'boolean'}},'additionalProperties':False}


def obj(properties, required=()):
    return {'type':'object','properties':properties,'required':list(required),'additionalProperties':False}


TOOLS=[
    {'name':'create_task','description':'Create a scheduled AI task or monitor. Use explicit user timing and stop condition. Model defaults to app settings.', 'inputSchema':{**SCHEMA,'required':['instructions','frequency']}},
    {'name':'update_task','description':'Update specified task fields, preserving omitted settings.','inputSchema':obj({'slug':{'type':'string'},'changes':SCHEMA},['slug','changes'])},
    {'name':'list_tasks','description':'List tasks, next runs and states.','inputSchema':obj({})},
    {'name':'task_action','description':'Run now, pause, resume, or archive a task. Archiving preserves history.','inputSchema':obj({'slug':{'type':'string'},'action':{'enum':['run','pause','resume','archive']}},['slug','action'])},
    {'name':'read_history','description':'Read task conversation, responses and failures. Pass before for earlier pages.','inputSchema':obj({'slug':{'type':'string'},'before':{'type':'integer'}},['slug'])},
    {'name':'read_response','description':'Read one run response or execution log.','inputSchema':obj({'run_id':{'type':'integer'},'log':{'type':'boolean'}},['run_id'])},
    {'name':'retry_run','description':'Retry a failed run now or later. Verify repeat execution is appropriate.','inputSchema':obj({'run_id':{'type':'integer'},'minutes':{'type':'integer'}},['run_id'])},
    {'name':'scheduler_settings','description':'Read configured provider/model and non-secret defaults.','inputSchema':obj({})},
]


def validate_arguments(value, schema, path='arguments'):
    """Enforce the advertised tool boundary, including nested change objects."""
    kind = schema.get('type')
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


def call(store,name,args):
    tool = next((tool for tool in TOOLS if tool['name'] == name), None)
    if not tool: raise ValueError('Unknown tool')
    validate_arguments(args, tool['inputSchema'])
    if name == 'update_task' or name == 'task_action' and args['action'] == 'run':
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
    elif name=='read_history':return history(store,args['slug'],args.get('before'))
    elif name=='read_response':return read_output(store,args['run_id'],args.get('log',False))
    elif name=='scheduler_settings':return get_settings(store)
    elif name=='retry_run':result={'run_id':retry_run(store,args['run_id'],args.get('minutes',0))}
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
