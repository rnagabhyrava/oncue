"""Non-secret application preferences, stored independently of provider credentials."""
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULTS = {
    'theme': 'system', 'provider': 'opencode', 'model': 'opencode/big-pickle', 'fallback_provider': '',
    'fallback_model': '', 'allow_fallback': False, 'timezone': 'America/Chicago',
    'retry_enabled': True, 'retry_minutes': 30, 'max_retries': 3,
    'notifications': True, 'desktop_notifications': False, 'webhooks': [], 'codex_login': 'existing', 'max_workers': 4, 'keep_awake': False,
}


def get_settings(store):
    row = store.connection.execute('SELECT value FROM app_settings WHERE id=1').fetchone()
    return {**DEFAULTS, **(json.loads(row[0]) if row else {})}


def update_settings(store, patch):
    if not isinstance(patch, dict) or set(patch) - DEFAULTS.keys():
        raise ValueError('Unknown settings')
    data = {**get_settings(store), **patch}
    if data['theme'] not in ('system', 'light', 'dark'):
        raise ValueError('Choose System, Light or Dark')
    if data['provider'] not in ('codex', 'opencode') or data['fallback_provider'] not in ('', 'codex', 'opencode'):
        raise ValueError('Unknown provider')
    if data['codex_login'] not in ('existing', 'managed'):
        raise ValueError('Unknown sign-in mode')
    ZoneInfo(data['timezone'])
    for key in ('model', 'fallback_model'):
        if not isinstance(data[key], str) or len(data[key]) > 200:
            raise ValueError('Invalid model identifier')
    for key in ('allow_fallback', 'retry_enabled', 'notifications', 'desktop_notifications', 'keep_awake'):
        if type(data[key]) is not bool:
            raise ValueError(f'{key} must be true or false')
    if 'webhooks' in patch:
        if not isinstance(data['webhooks'],list) or len(data['webhooks'])>20: raise ValueError('Invalid webhook list')
        secret_items=[]
        for item in data['webhooks']:
            if not isinstance(item,dict) or not isinstance(item.get('name'),str) or not isinstance(item.get('url'),str): raise ValueError('Invalid webhook destination')
            secret_items.append({'name':item['name'],'url':item['url'],'token':item.get('token','')})
        secret_path=Path(store.path.parent)/'notification-secrets.json'
        secret_path.write_text(json.dumps({'webhooks':secret_items}));os.chmod(secret_path,0o600)
        data['webhooks']=[{k:item[k] for k in ('name','enabled','allow_local') if k in item} for item in data['webhooks']]
    for key, low, high in (('retry_minutes', 1, 1440), ('max_retries', 0, 10), ('max_workers', 1, 8)):
        if type(data[key]) is not int or not low <= data[key] <= high:
            raise ValueError(f'{key} must be between {low} and {high}')
    store.connection.execute('INSERT OR REPLACE INTO app_settings(id,value) VALUES (1,?)', (json.dumps(data),))
    store.connection.commit()
    return data
