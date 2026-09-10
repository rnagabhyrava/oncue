"""Launch OnCue as a background app; optional Linux login startup integration."""
import json
import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from .store import _process_is_alive


def command_prefix():
    return [sys.executable] if getattr(sys,'frozen',False) else [sys.executable,'-m','oncue']


def service_info(data_dir):
    try:
        value=json.loads((Path(data_dir)/'service.json').read_text())
        return value if _process_is_alive(value['pid'],value['start_ticks']) else None
    except (OSError,ValueError,KeyError):return None


def start(data_dir,port=8765,open_window=False):
    data_dir=Path(data_dir).resolve();info=service_info(data_dir)
    if not info:
        data_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
        log=data_dir/'service.log'
        fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        with os.fdopen(fd,'ab') as output:
            process=subprocess.Popen(command_prefix()+['--data-dir',str(data_dir),'dashboard','--port',str(port)],
                cwd=Path(__file__).resolve().parent.parent,stdin=subprocess.DEVNULL,stdout=output,stderr=output,start_new_session=True)
        for _ in range(100):
            info=service_info(data_dir)
            if info:break
            if process.poll() is not None:raise ValueError('OnCue could not start. Another app may be using the port; inspect service.log.')
            time.sleep(.1)
        if not info:raise ValueError('OnCue did not become ready; inspect service.log')
    url=info['url']
    if open_window:webbrowser.open(url)
    return url


def stop(data_dir):
    info=service_info(data_dir)
    if info:os.kill(info['pid'],signal.SIGINT)


def install_startup(data_dir):
    """User-owned service and launcher, with no administrator permissions."""
    if sys.platform!='linux':raise ValueError('Login startup currently supports Linux')
    data_dir=Path(data_dir).resolve()
    def quoted(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
    args=command_prefix()+['--data-dir',str(data_dir),'dashboard']
    unit=Path.home()/'.config/systemd/user/oncue.service';unit.parent.mkdir(parents=True,exist_ok=True)
    unit.write_text('[Unit]\nDescription=OnCue background task assistant\nAfter=network.target\n\n[Service]\nType=simple\nWorkingDirectory='+quoted(Path(__file__).resolve().parent.parent)+'\nExecStart='+' '.join(map(quoted,args))+'\nRestart=on-failure\nUMask=0077\n\n[Install]\nWantedBy=default.target\n')
    launcher=Path.home()/'.local/share/applications/oncue.desktop';launcher.parent.mkdir(parents=True,exist_ok=True)
    launcher.write_text('[Desktop Entry]\nType=Application\nName=OnCue\nComment=Schedule AI tasks. Keep the conversation.\nExec='+' '.join(map(quoted,command_prefix()+['--data-dir',str(data_dir),'open']))+'\nIcon=appointment-soon\nTerminal=false\nCategories=Utility;\n')
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    subprocess.run(['systemctl','--user','enable','oncue.service'],check=True)
    return str(launcher)
