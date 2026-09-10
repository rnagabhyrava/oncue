"""Local task UI and same-origin API. Private content requires a session token."""
import json
import base64
import hashlib
import secrets
import socket
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from typing import Any

from .scheduler import LocalScheduler
from .settings import get_settings, update_settings
from .conversations import cancel_run, history, queue_message, retry_run
from .providers import catalog
from .auth import start_login, login_state
from . import runtime
from .schedules import from_form, next_run, once_at, to_form
from .store import Store
from .tasks import queue_manual, read_output, save_task

STATIC = Path(__file__).parent / 'static'

def overview(store: Store) -> dict[str, Any]:
    """Return only operational metadata; never commands, prompts, logs, or errors."""
    jobs = []
    for row in store.dashboard_jobs():
        state = "archived" if row["archived"] else ("enabled" if row["enabled"] else "paused")
        jobs.append({
            "slug": row["slug"], "title": row["title"] or row["slug"], "project": row["task_project_name"], "task_project_id": row["task_project_id"], "workspace_project": row["project_slug"], "schedule": row["schedule"],
            "timezone": row["timezone"], "runner": row["runner"], "model": row["model"],
            "reasoning_effort": row["reasoning_effort"], "sandbox": row["sandbox"], "auto_approve": bool(row["auto_approve"]),
            "connection": row["connection_slug"], "timeout": row["timeout_seconds"],
            "revision": row["remote_revision"],
            "state": state, "last_status": row["last_status"], "last_finished_at": row["last_finished_at"],
        })
    runs = [dict(row) for row in store.recent_runs(30)]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "Enabled jobs": sum(job["state"] == "enabled" for job in jobs),
            "Paused jobs": sum(job["state"] == "paused" for job in jobs),
            "Queued runs": store.connection.execute("SELECT COUNT(*) FROM runs WHERE status = 'queued'").fetchone()[0],
            "Failed runs": store.connection.execute("SELECT COUNT(*) FROM runs WHERE status IN ('failed', 'timed_out')").fetchone()[0],
        },
        "jobs": jobs,
        "runs": runs,
    }


def task_list(store):
    result = overview(store)
    for job in result['jobs']:
        full=store.job(job['slug'],include_archived=True)
        job['provider']=full['provider']
        job['instructions']=full['command']
        job['config']=json.loads(full['task_config'])
        scheduled = once_at(job['schedule'])
        occurrence = store.connection.execute(
            'SELECT status FROM runs WHERE job_id=(SELECT id FROM jobs WHERE slug=?) AND scheduled_for=?',
            (job['slug'], scheduled.isoformat() if scheduled else ''),
        ).fetchone() if scheduled else None
        if scheduled and occurrence and occurrence['status'] not in ('queued', 'running') and job['state'] != 'archived':
            job['state'] = 'failed' if occurrence['status'] in ('failed','timed_out') else 'completed'
        if full['completed_at'] and job['state']!='archived':job['state']='completed'
        if job['config'].get('mode') in ('draft','chat') and job['state']!='archived':job['state']='draft'
        job['next_run'] = next_run(job['schedule'], job['timezone']) if job['state'] == 'enabled' and not occurrence else None
        job['timing'] = to_form(job['schedule'], job['timezone'])
    heartbeat = store.connection.execute('SELECT last_tick FROM scheduler_state WHERE id=1').fetchone()
    result['scheduler_active'] = bool(heartbeat and (datetime.now(timezone.utc) - datetime.fromisoformat(heartbeat['last_tick'])).total_seconds() < 90)
    result['settings']=get_settings(store)
    result['projects']=[dict(row) for row in store.task_projects()]
    from .remote import account_state
    remote = account_state(store.path.parent)
    result['account'] = {key: remote.get(key) for key in ('configured', 'claimed', 'last_sync_at', 'sync_error')}
    return result


def _handler(database_path: Path):
    csrf_token = secrets.token_urlsafe(32)
    browser_sessions = {}
    from .remote import cloud_config
    account_config = cloud_config()
    remote_sources = []
    for candidate in ("https://" + account_config["auth0_domain"].strip("/"), account_config["cloud_url"]):
        parsed = urlsplit(candidate)
        if parsed.scheme in ("http", "https") and parsed.hostname:
            remote_sources.append(f"{parsed.scheme}://{parsed.netloc}")

    def remember_token(token):
        try:
            payload = token.split('.')[1]
            payload += '=' * (-len(payload) % 4)
            expires = int(json.loads(base64.urlsafe_b64decode(payload))["exp"])
        except (ValueError, KeyError, IndexError, TypeError):
            expires = int(datetime.now(timezone.utc).timestamp()) + 300
        browser_sessions[hashlib.sha256(token.encode()).digest()] = expires

    def signed_in(headers):
        from .remote import cloud_config
        if not all(cloud_config().values()):
            return True
        authorization = headers.get('Authorization', '')
        if not authorization.startswith('Bearer '):
            return False
        token = authorization[7:]
        expires = browser_sessions.get(hashlib.sha256(token.encode()).digest(), 0)
        return expires > datetime.now(timezone.utc).timestamp()

    def installation_claimed():
        from .remote import account_state
        state = account_state(database_path.parent)
        return not state["configured"] or state["claimed"]

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def _headers(self, status, content_type, body):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'no-referrer')
            sources = " ".join(dict.fromkeys(remote_sources))
            frame_source = remote_sources[0] if remote_sources else "'none'"
            self.send_header('Content-Security-Policy',
                f"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self' {sources}; "
                f"frame-src {frame_source}; img-src 'self' data: https:; "
                "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, payload):
            self._headers(status, 'application/json; charset=utf-8', json.dumps(payload).encode())

        def _host_allowed(self):
            try:
                host = urlsplit('//' + self.headers.get('Host', ''))
                return host.hostname in ('127.0.0.1', 'localhost', '::1') and (host.port or 80) == self.server.server_port
            except ValueError:
                return False

        def _write_allowed(self):
            if not self._host_allowed():
                return False
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + self.headers.get('Host', ''):
                return False
            return secrets.compare_digest(self.headers.get('X-CSRF-Token', ''), csrf_token)

        def do_GET(self):
            if not self._host_allowed():
                self._json(403, {'error': 'Loopback host required'})
                return
            if self.path in ('/', '/app.js', '/app.css', '/favicon.svg'):
                name = {'/': 'index.html', '/app.js': 'app.js', '/app.css': 'app.css', '/favicon.svg':'favicon.svg'}[self.path]
                body = (STATIC / name).read_bytes().replace(b'__CSRF_TOKEN__', csrf_token.encode())
                mime = {'/': 'text/html', '/app.js': 'text/javascript', '/app.css': 'text/css', '/favicon.svg':'image/svg+xml'}[self.path]
                self._headers(200, mime + '; charset=utf-8', body)
                return
            if self.path == '/api/account/status':
                from .remote import account_state
                self._json(200, account_state(database_path.parent))
                return
            if not self._write_allowed():
                self._json(403, {'error': 'Session token required'})
                return
            if not signed_in(self.headers):
                self._json(401, {'error': 'Sign in with Google to use OnCue'})
                return
            if not installation_claimed():
                self._json(428, {'error': 'Claim this installation before accessing its tasks'})
                return
            store = Store(database_path)
            try:
                if self.path == '/api/overview':
                    self._json(200, overview(store))
                elif self.path == '/api/tasks':
                    self._json(200, task_list(store))
                elif self.path == '/api/projects':
                    self._json(200, {'projects':[dict(row) for row in store.task_projects()]})
                elif self.path.startswith('/api/projects/'):
                    project_id=int(self.path.split('/')[-1]); row=store.connection.execute('SELECT * FROM task_projects WHERE id=?',(project_id,)).fetchone()
                    if not row: raise ValueError('Project not found')
                    from .attachments import list_attachments
                    tasks=[{'slug':r['slug'],'title':r['title'] or r['slug']} for r in store.connection.execute('SELECT slug,title FROM jobs WHERE task_project_id=? AND archived=0 ORDER BY title',(project_id,))]
                    self._json(200, {'project':dict(row),'attachments':list_attachments(store,'project',project_id),'tasks':tasks})
                elif self.path.startswith('/api/attachments/'):
                    aid=int(self.path.split('/')[-1]); name,content=__import__('oncue.attachments',fromlist=['read']).read(store,aid)
                    self._headers(200, 'text/plain; charset=utf-8', content)
                elif self.path.startswith('/api/export/'):
                    from .exports import archive
                    import shutil
                    with archive(store,self.path.split('/')[-1]) as source:
                        self.send_response(200)
                        self.send_header('Content-Type','application/zip')
                        self.send_header('Cache-Control','no-store')
                        self.end_headers()
                        shutil.copyfileobj(source,self.wfile)
                elif self.path.startswith('/api/conversation/'):
                    url=urlsplit(self.path);slug=url.path.split('/')[-1]
                    self._json(200,history(store,slug,parse_qs(url.query).get('before',[None])[0]))
                elif self.path == '/api/settings':
                    self._json(200,{'settings':get_settings(store),'providers':catalog(store.path.parent,get_settings(store)), 'login':login_state(store.path.parent),'runtimes':runtime.state()})
                elif self.path.startswith('/api/tasks/'):
                    slug = self.path.split('/')[-1]
                    job = store.job(slug, include_archived=True)
                    if not job:
                        raise ValueError('Task not found')
                    from .attachments import list_attachments
                    self._json(200, {'instructions': job['command'], 'history': [dict(r) for r in store.history(slug, 100)], 'attachments':list_attachments(store,'task',slug)})
                elif self.path.startswith('/api/runs/'):
                    parts = self.path.split('/')
                    self._json(200, read_output(store, int(parts[3]), log=len(parts) == 5 and parts[4] == 'log'))
                else:
                    self._json(404, {'error': 'Not found'})
            except (ValueError, KeyError) as error:
                self._json(400, {'error': str(error)})
            finally:
                store.close()

        def _read_json(self):
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 131072:
                raise ValueError('Request must be at most 128 KiB')
            value = json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(value, dict):
                raise ValueError('Expected a JSON object')
            return value

        def do_POST(self):
            self._mutate()

        def do_PATCH(self):
            self._mutate()

        def do_DELETE(self):
            self._mutate()

        def _mutate(self):
            if not self._write_allowed():
                self._json(403, {'error': 'Session token and same origin required'})
                return
            if self.path == '/api/account/session':
                authorization = self.headers.get('Authorization', '')
                if not authorization.startswith('Bearer '):
                    self._json(401, {'error': 'Sign in required'}); return
                try:
                    from .remote import verify_session
                    result = verify_session(database_path.parent, authorization[7:])
                    remember_token(authorization[7:])
                    self._json(200, result)
                except ValueError as error:
                    self._json(401, {'error': str(error)})
                return
            if not signed_in(self.headers):
                self._json(401, {'error': 'Sign in with Google to use OnCue'})
                return
            if self.path != '/api/account/claim' and not installation_claimed():
                self._json(428, {'error': 'Claim this installation before accessing its tasks'})
                return
            store = None
            try:
                data = self._read_json()
                if self.path == '/api/account/claim':
                    from .remote import claim_installation
                    self._json(201, claim_installation(database_path.parent, self.headers['Authorization'][7:], data.get('name')))
                    return
                store = Store(database_path)
                parts = self.path.split('/')
                if self.path == '/api/settings':
                    self._json(200,update_settings(store,data));return
                if self.path == '/api/projects' and self.command == 'POST':
                    self._json(201,{'id':store.create_task_project(data.get('name',''),data.get('instructions',''),data.get('icon',''),data.get('color',''))});return
                if len(parts)==4 and parts[1:3]==['api','projects']:
                    project_id=int(parts[3])
                    if self.command=='PATCH': store.update_task_project(project_id,data.get('name'),data.get('instructions'),data.get('icon'),data.get('color'));self._json(200,{'ok':True});return
                    if self.command=='DELETE': store.delete_task_project(project_id);self._json(200,{'ok':True});return
                if self.path == '/api/attachments' and self.command == 'POST':
                    from .attachments import upload
                    self._json(201,{'id':upload(store,data.get('owner_type'),data.get('owner'),data.get('name'),data.get('content'))});return
                if len(parts)==4 and parts[1:3]==['api','attachments'] and self.command=='DELETE':
                    from .attachments import remove
                    remove(store,int(parts[3]));self._json(200,{'ok':True});return
                if self.path == '/api/notifications/process':
                    from .notifications import process
                    process(store);self._json(200,{'ok':True});return
                if self.path == '/api/startup':
                    from .service import install_startup
                    self._json(200,{'launcher':install_startup(store.path.parent)});return
                if self.path == '/api/providers/refresh':
                    self._json(200,catalog(store.path.parent,get_settings(store),True));return
                if self.path == '/api/providers/login':
                    self._json(200,start_login(store.path.parent,get_settings(store)));return
                if self.path == '/api/providers/install':
                    self._json(202,runtime.install(store.path.parent,data.get('provider')));return
                if self.path == '/api/message':
                    self._json(202,queue_message(store,data.get('slug'),data.get('text'),data.get('options')));return
                if len(parts)==5 and parts[1:3]==['api','runs'] and parts[4]=='retry':
                    self._json(202,{'run_id':retry_run(store,int(parts[3]),data.get('minutes',0))});return
                if len(parts)==5 and parts[1:3]==['api','runs'] and parts[4]=='cancel':
                    cancel_run(store,int(parts[3]))
                    self._json(200,{'ok':True});return
                if self.path == '/api/preview'  and self.command == 'POST':
                    schedule = from_form(data)
                    self._json(200, {'next_run': next_run(schedule, data.get('timezone', 'UTC'))})
                    return
                if self.path == '/api/tasks' and self.command == 'POST':
                    slug = save_task(store, data)
                    self._json(201, {'slug': slug})
                    return
                if len(parts) == 4 and parts[1:3] == ['api', 'tasks'] and self.command == 'PATCH':
                    self._json(200, {'slug': save_task(store, data, parts[3])})
                    return
                if len(parts) == 4 and parts[1:3] == ['api', 'tasks'] and self.command == 'DELETE':
                    if not store.delete_job(parts[3]): raise ValueError('Task not found')
                    self._json(200, {'ok': True})
                    return
                if len(parts) == 5 and parts[1:3] == ['api', 'tasks'] and self.command == 'POST':
                    slug, action = parts[3:]
                    if action == 'run':
                        self._json(202, {'run_id': queue_manual(store, slug)})
                        return
                    if action not in ('pause', 'resume', 'archive'):
                        raise ValueError('Unknown action')
                    ok = store.archive_job(slug) if action == 'archive' else store.set_job_enabled(slug, action == 'resume')
                    if not ok:
                        raise ValueError('Task not found')
                    self._json(200, {'ok': True})
                    return
                self._json(404, {'error': 'Not found'})
            except (ValueError, KeyError, TypeError, sqlite3.IntegrityError) as error:
                self._json(400, {'error': str(error)})
            except Exception:
                self._json(500, {'error': 'Could not complete request. Check the app terminal.'})
                import logging
                logging.exception('Task request failed')
            finally:
                if store:
                    store.close()

        def log_message(self, format, *args):
            return

    return Handler


def serve(store, host, port):
    if host not in ('127.0.0.1', '::1'):
        raise ValueError('dashboard host must be a loopback address')
    if not 1 <= port <= 65535:
        raise ValueError('dashboard port must be between 1 and 65535')
    class Server(ThreadingHTTPServer):
        address_family = socket.AF_INET6 if host == '::1' else socket.AF_INET
        daemon_threads = True
    server = Server((host, port), _handler(store.path.resolve()))
    scheduler = LocalScheduler(store.path)
    scheduler.start()
    from .remote import SyncAgent
    sync_agent = SyncAgent(store.path)
    sync_agent.start()
    import os
    from .store import process_start_ticks
    marker=store.path.parent/'service.json'
    marker.write_text(json.dumps({'pid':os.getpid(),'start_ticks':process_start_ticks(os.getpid()),'url':f'http://{"[::1]" if host=="::1" else host}:{port}/'}))
    os.chmod(marker,0o600)
    print(f'Tasks available at http://{"[::1]" if host == "::1" else host}:{port}/ — scheduling is active', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        sync_agent.stop()
        scheduler.stop()
        from .auth import close_sessions
        close_sessions()
        try:
            if json.loads(marker.read_text())['pid']==os.getpid():marker.unlink()
        except (OSError,ValueError,KeyError):pass
