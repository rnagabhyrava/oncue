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
    if info:
        try: os.kill(info['pid'],signal.SIGINT)
        except ProcessLookupError: return
        for _ in range(150):
            if not _process_is_alive(info['pid'],info['start_ticks']): return
            time.sleep(.1)
        raise ValueError('OnCue is still stopping. Try again shortly.')


def install_startup(data_dir):
    """User-owned service and launcher, with no administrator permissions."""
    if sys.platform!='linux':raise ValueError('Login startup currently supports Linux')
    data_dir=Path(data_dir).resolve()
    def quoted(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
    args=command_prefix()+['--data-dir',str(data_dir),'dashboard']
    unit=Path.home()/'.config/systemd/user/oncue.service';unit.parent.mkdir(parents=True,exist_ok=True)
    unit.write_text('[Unit]\nDescription=OnCue background task assistant\nAfter=network.target\n\n[Service]\nType=simple\nWorkingDirectory='+quoted(Path(__file__).resolve().parent.parent)+'\nExecStart='+' '.join(map(quoted,args))+'\nRestart=on-failure\nUMask=0077\n\n[Install]\nWantedBy=default.target\n')
    launcher=install_launcher(data_dir)
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    subprocess.run(['systemctl','--user','enable','oncue.service'],check=True)
    return str(launcher)


def prepare_update(data_dir):
    """Stop dispatch and refuse removal while independent workers are active."""
    stop(data_dir)
    from .store import Store
    database = Path(data_dir)/'scheduler.sqlite3'
    if not database.exists(): return
    with_store = Store(database)
    try:
        for row in with_store.connection.execute(
                "SELECT process_id, process_start_ticks FROM runs WHERE status='running'"):
            if _process_is_alive(*row):
                raise ValueError('A task is still running. Let it finish, then retry; task data was retained.')
    finally:
        with_store.close()


def installation_prefix(prefix=None):
    if prefix is None and getattr(sys, 'frozen', False):
        prefix = Path(sys.executable).resolve().parents[3]
    return Path(prefix or Path.home()/'.local').resolve()


def install_launcher(data_dir, prefix=None):
    prefix = installation_prefix(prefix)
    launcher = prefix/'share/applications/oncue.desktop'
    launcher.parent.mkdir(parents=True, exist_ok=True)
    # Desktop Exec has a second escaping layer for quoted special characters.
    def quoted(value):
        value = str(value).replace('%', '%%')
        for char in ('\\', '"', '`', '$'):
            value = value.replace(char, '\\'+char)
        return '"'+value.replace('\\', '\\\\')+'"'
    args = command_prefix()+['--data-dir', str(Path(data_dir).resolve()), 'open']
    launcher.write_text('[Desktop Entry]\nType=Application\nName=OnCue\n'
        'Comment=Schedule AI tasks. Keep the conversation.\nExec='
        +' '.join(map(quoted, args))+'\nIcon=appointment-soon\nTerminal=false\nCategories=Utility;\n')
    return str(launcher)


def uninstall(data_dir, prefix=None, purge_data=False):
    import shutil
    prefix = installation_prefix(prefix)
    install_dir = prefix/'share/oncue/bin'
    executable = install_dir/'oncue'
    if not executable.is_file() or not (install_dir/'install.sh').is_file():
        raise ValueError('No portable installation found at this prefix. For pip installs, use pip uninstall oncue.')
    data_dir = Path(data_dir).resolve()
    default = Path.home()/'.local/share/oncue/data'
    if purge_data and (data_dir != default.absolute() or default.is_symlink()):
        raise ValueError('Automatic data removal only supports the default data directory. Back up and remove custom storage manually.')
    prepare_update(data_dir)
    unit = Path.home()/'.config/systemd/user/oncue.service'
    if unit.exists():
        subprocess.run(['systemctl','--user','disable','oncue.service'], check=True)
        unit.unlink()
        subprocess.run(['systemctl','--user','daemon-reload'], check=True)
    for name in ('oncue', 'codex-local-scheduler'):
        link = prefix/'bin'/name
        if link.is_symlink() and link.resolve() == executable.resolve():
            link.unlink()
    launcher = prefix/'share/applications/oncue.desktop'
    launcher.unlink(missing_ok=True)
    shutil.rmtree(install_dir)
    if purge_data:
        from .migration import LEGACY_NAME
        legacy = Path.home()/'.local/share'/LEGACY_NAME
        if legacy.is_symlink() and legacy.resolve() == data_dir:
            legacy.unlink()
        shutil.rmtree(data_dir)
        return 'OnCue uninstalled and default task data deleted. Shared provider logins were retained.'
    return f'OnCue uninstalled. Task history and app settings retained at {data_dir}.'
