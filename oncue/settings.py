"""Non-secret application preferences, stored independently of provider credentials."""
import json
from zoneinfo import ZoneInfo

DEFAULTS = {
    'theme': 'system', 'provider': 'opencode', 'model': 'opencode/big-pickle', 'fallback_provider': '',
    'fallback_model': '', 'allow_fallback': False, 'timezone': 'America/Chicago',
    'retry_enabled': True, 'retry_minutes': 30, 'max_retries': 3,
    'notifications': True, 'codex_login': 'existing', 'max_workers': 4, 'keep_awake': False,
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
    for key in ('allow_fallback', 'retry_enabled', 'notifications', 'keep_awake'):
        if type(data[key]) is not bool:
            raise ValueError(f'{key} must be true or false')
    for key, low, high in (('retry_minutes', 1, 1440), ('max_retries', 0, 10), ('max_workers', 1, 8)):
        if type(data[key]) is not int or not low <= data[key] <= high:
            raise ValueError(f'{key} must be between {low} and {high}')
    store.connection.execute('INSERT OR REPLACE INTO app_settings(id,value) VALUES (1,?)', (json.dumps(data),))
    store.connection.commit()
    return data
