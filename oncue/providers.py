"""Codex and OpenCode runtimes. Credentials remain in provider-owned storage."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def executable(name, data_dir=None):
    if name not in ('codex', 'opencode'):
        raise ValueError('Unknown provider')
    if data_dir:
        native=Path(data_dir)/'runtimes'/'node_modules'/('opencode-linux-x64-baseline/bin/opencode' if name=='opencode' else '@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex')
        if native.is_file() and os.access(native,os.X_OK):return str(native)
        managed=Path(data_dir)/'runtimes'/'node_modules'/'.bin'/name
        if managed.is_file() and os.access(managed,os.X_OK):return str(managed)
    roots = [Path(sys.executable).resolve().parent] if getattr(sys,'frozen',False) else []
    for root in roots:
        candidate = root / 'runtimes' / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    on_path=shutil.which(name)
    if on_path:return on_path
    installed=Path.home()/'.local/share/oncue/bin/runtimes'/name
    return str(installed) if installed.is_file() and os.access(installed,os.X_OK) else None


def environment(data_dir, settings, provider):
    env = {'PATH': os.environ.get('PATH',''), 'HOME': str(Path.home()), 'TERM':'dumb', 'NO_COLOR':'1'}
    if provider == 'codex':
        if settings.get('codex_login') == 'managed':
            home = Path(data_dir)/'providers'/'codex'
            home.mkdir(parents=True, exist_ok=True, mode=0o700)
            env['CODEX_HOME'] = str(home.resolve())
        elif os.environ.get('CODEX_HOME'):
            env['CODEX_HOME'] = os.environ['CODEX_HOME']
    if provider == 'opencode':
        for key in ('XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME'):
            if os.environ.get(key): env[key] = os.environ[key]
        env['OPENCODE_PERMISSION'] = json.dumps({'*':'deny','read':'allow','glob':'allow','grep':'allow','webfetch':'allow','websearch':'allow'})
    return env


def command(provider, model, prompt, response_path, *, sandbox='read-only', effort=None, auto=False, planning=False, live_search=False, data_dir=None):
    binary = executable(provider, data_dir)
    if not binary:
        raise ValueError(f'{provider.title()} is not installed. Open Settings to install the runtime.')
    if provider == 'opencode':
        return [binary,'run','--format','json','--model',model,'--',prompt]
    args = [binary,'exec','--model',model,'--sandbox',sandbox,'--skip-git-repo-check','--color','never',
            '--config','approval_policy="never"','--output-last-message',str(response_path)]
    if planning:
        args += ['--config','web_search="disabled"','--config','mcp_servers={}']
    elif live_search:
        args += ['--config','web_search="live"']
    if effort: args += ['--config',f'model_reasoning_effort="{effort}"']
    if auto: args += ['--approve-for-me']
    return args + ['--',prompt]


def extract_opencode(log_path, response_path):
    pieces=[]
    with Path(log_path).open(errors='replace') as handle:
        for line in handle:
            try:
                event=json.loads(line)
                if event.get('type')=='text': pieces.append(event.get('part',{}).get('text',''))
            except (ValueError, AttributeError): pass
    Path(response_path).write_text('\n'.join(pieces))


def parse_models(text):
    """Read the CLI's verbose model records; expose only display/cost metadata."""
    decoder=json.JSONDecoder();items=[];offset=0
    while offset<len(text):
        start=text.find('{',offset)
        if start<0:break
        try:
            model,end=decoder.raw_decode(text,start)
        except ValueError:
            offset=start+1;continue
        offset=end
        if not isinstance(model,dict):continue
        name,provider=model.get('id'),model.get('providerID')
        if not isinstance(name,str) or not isinstance(provider,str):continue
        cost=model.get('cost',{})
        items.append({'id':provider+'/'+name,'name':str(model.get('name',name)),
                      'free':provider=='opencode' and cost.get('input')==0 and cost.get('output')==0})
    return items


_catalog_cache = {}

def catalog(data_dir, settings, refresh=False):
    key=(str(data_dir),settings.get('codex_login'))
    if not refresh and key in _catalog_cache and time.monotonic()-_catalog_cache[key][0]<60:
        return _catalog_cache[key][1]
    result=[]
    for provider in ('codex','opencode'):
        binary=executable(provider,data_dir)
        item={'id':provider,'installed':bool(binary),'models':[],'status':'Not installed'}
        if binary:
            env=environment(data_dir,settings,provider)
            try:
                if provider=='codex':
                    status=subprocess.run([binary,'login','status'],env=env,capture_output=True,text=True,timeout=8)
                    item['status']='Connected to Codex' if status.returncode==0 else 'Sign in to Codex to continue'
                    item['connected']=status.returncode==0
                    home=Path(env.get('CODEX_HOME',Path.home()/'.codex'))
                    try:
                        data=json.loads((home/'models_cache.json').read_text())
                        item['models']=[m['slug'] for m in data.get('models',[]) if isinstance(m,dict) and m.get('visibility')=='list']
                    except (OSError,ValueError,AttributeError): pass
                else:
                    models=subprocess.run([binary,'models','--verbose'],env=env,capture_output=True,text=True,timeout=15)
                    item['model_details']=parse_models(models.stdout)
                    item['models']=[m['id'] for m in item['model_details']]
                    if not item['models']:
                        item['models']=[m.strip() for m in models.stdout.splitlines() if '/' in m and not ' ' in m and len(m)<200]
                    free=sum(m['free'] for m in item['model_details'])
                    item['status']=(f'{len(item["models"])} models available · {free} free' if models.returncode==0 and item['models'] else 'Could not list models. Refresh the provider or enter a model ID.')
            except (subprocess.TimeoutExpired,OSError): item['status']='Could not check provider; try Refresh'
        result.append(item)
    _catalog_cache[key]=(time.monotonic(),result)
    return result
