"""Supported Codex sign-in through app-server; no credentials enter the task database."""
import json
import queue
import subprocess
import threading
from urllib.parse import urlsplit
from .providers import executable, environment


class Login:
    def __init__(self,data_dir,settings):
        binary=executable('codex',data_dir)
        if not binary:raise ValueError('Install the Codex runtime first')
        self.process=subprocess.Popen([binary,'app-server'],env=environment(data_dir,{**settings,'codex_login':'managed'},'codex'),
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,start_new_session=True)
        self.responses=queue.Queue();self.state={'status':'starting'}
        self.lock=threading.Lock()
        threading.Thread(target=self._read,daemon=True).start()
        self._rpc(0,'initialize',{'clientInfo':{'name':'oncue','title':'OnCue','version':'0.3.0'}})
        self._send({'method':'initialized','params':{}})
        result=self._rpc(1,'account/login/start',{'type':'chatgpt'})
        url=result.get('authUrl','')
        parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.hostname not in ('auth.openai.com','auth0.openai.com'):
            self.close();raise ValueError('Provider did not return a supported sign-in URL')
        if self.state.get('status')!='connected':self.state={'status':'waiting','url':url}

    def _send(self,value):
        self.process.stdin.write(json.dumps(value)+'\n');self.process.stdin.flush()

    def _rpc(self,id,method,params):
        self._send({'id':id,'method':method,'params':params})
        try:
            value=self.responses.get(timeout=20)
        except queue.Empty:
            self.close();raise ValueError('Sign-in service did not respond. Try again.') from None
        if 'error' in value:
            self.close();raise ValueError('Provider could not start sign-in. Check the runtime and try again.')
        return value.get('result',{})

    def _read(self):
        for line in self.process.stdout:
            try:value=json.loads(line)
            except ValueError:continue
            if 'id' in value:self.responses.put(value)
            if value.get('method')=='account/login/completed':
                success=value.get('params',{}).get('success')
                self.state={'status':'connected' if success else 'failed'}
        if self.state.get('status') not in ('connected','failed'):self.state={'status':'failed'}

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        for handle in (self.process.stdin,self.process.stdout):
            if handle:handle.close()


_sessions={}
_lock=threading.Lock()

def start_login(data_dir,settings):
    with _lock:
        key=str(data_dir)
        previous=_sessions.pop(key,None)
        if previous:previous.close()
        login=Login(data_dir,settings);_sessions[key]=login
        return login.state


def login_state(data_dir):
    login=_sessions.get(str(data_dir))
    return login.state if login else {'status':'idle'}


def close_sessions():
    with _lock:
        for session in list(_sessions.values()):session.close()
        _sessions.clear()
