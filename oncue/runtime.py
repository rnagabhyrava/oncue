"""Managed optional provider runtime installation from versioned npm packages."""
import subprocess
import threading
from pathlib import Path
import shutil

PACKAGES={'codex':'@openai/codex@0.153.4','opencode':'opencode-ai@1.18.30'}
_state={}
_lock=threading.Lock()


def state():return dict(_state)


def install(data_dir,provider):
    if provider not in PACKAGES:raise ValueError('Unknown runtime')
    npm=shutil.which('npm')
    if not npm:raise ValueError('This source install needs npm to add runtimes. The portable distribution includes both runtimes.')
    with _lock:
        if any(s.get('status')=='installing' for s in _state.values()):raise ValueError('A runtime installation is already in progress')
        _state[provider]={'status':'installing'}
    target=Path(data_dir)/'runtimes'
    target.mkdir(parents=True,exist_ok=True,mode=0o700)
    def work():
        try:
            result=subprocess.run([npm,'install','--prefix',str(target),PACKAGES[provider],'--ignore-scripts','--no-audit','--no-fund'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=300)
            _state[provider]={'status':'ready' if result.returncode==0 else 'failed'}
        except (OSError,subprocess.TimeoutExpired):_state[provider]={'status':'failed'}
        from .providers import _catalog_cache
        _catalog_cache.clear()
    threading.Thread(target=work,daemon=True).start()
    return _state[provider]
