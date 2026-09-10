#!/usr/bin/env python3
"""Exercise a built bundle in a temporary home; no provider calls or real account changes.
Run from the checkout: PYTHONPATH=. python3 scripts/smoke_install.py
"""
import json, os, socket, subprocess, tempfile, time, urllib.request
from pathlib import Path
from oncue.store import Store
from oncue.tasks import save_task, read_output
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='oncue-install-smoke-') as tmp:
    home=Path(tmp); prefix=home/'.local'; data=prefix/'share/oncue/data'
    env={k:v for k,v in os.environ.items() if k not in ('ONCUE_DATA','CODEX_LOCAL_SCHEDULER_DATA','CODEX_HOME')}
    env['HOME']=str(home)
    command=prefix/'bin/oncue'
    def call(args, **kw):
        result=subprocess.run([str(x) for x in args],env=env,capture_output=True,text=True,timeout=120,**kw)
        if result.returncode: raise RuntimeError(result.stdout+result.stderr)
        return result.stdout
    install=['sh',root/'install.sh','--archive',root/'dist/oncue-linux-x86_64.tar.gz','--prefix',prefix,'--no-start']
    print(call(install),flush=True)
    assert command.exists()
    assert (prefix/'share/applications/oncue.desktop').exists()
    with socket.socket() as s:
        s.bind(('127.0.0.1',0)); port=s.getsockname()[1]
    log=(home/'dashboard.log').open('w')
    process=subprocess.Popen([str(command),'dashboard','--port',str(port)],env=env,stdout=log,stderr=log)
    try:
        for _ in range(100):
            if (data/'service.json').exists():break
            if process.poll() is not None: raise RuntimeError('dashboard exited')
            time.sleep(.1)
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/') as response:
            assert response.status==200
            assert b'<html' in response.read()
        store=Store(data/'scheduler.sqlite3')
        slug=save_task(store,{'instructions':'printf installer-due-run','runner':'command','frequency':'custom','cron':'* * * * *','timezone':'UTC'})
        for _ in range(100):
            history=store.history(slug)
            if history and history[0]['status']=='succeeded':break
            time.sleep(.1)
        assert history[0]['status']=='succeeded',history
        assert read_output(store,history[0]['id'])['text']=='installer-due-run'
        store.set_job_enabled(slug,False); store.close()
        print('HTTP UI and actual scheduled due-run passed',flush=True)
        print(call(install),flush=True)
        process.wait(timeout=20)
        store=Store(data/'scheduler.sqlite3')
        assert store.history(slug)[0]['status']=='succeeded';store.close()
        print(call([command,'uninstall']),flush=True)
        assert not command.exists() and (data/'scheduler.sqlite3').exists()
        print(call(install),flush=True)
        print(call([command,'uninstall','--purge-data']),flush=True)
        assert not data.exists()
        print('Upgrade, history retention, reinstall, and purge passed',flush=True)
    finally:
        if process.poll() is None:
            process.send_signal(2); process.wait(timeout=20)
        log.close()
