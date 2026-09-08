"""A dependency-free, read-only local dashboard for scheduler state."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .cron import matches
from .store import Store


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Codex Local Scheduler</title>
  <style>
    :root{color-scheme:light dark}body{font:14px system-ui,sans-serif;margin:2rem auto;padding:0 1rem;max-width:1100px;color:#222;background:#fff}h1{margin-bottom:.2rem}h2{margin-top:2rem}header,.section-head{display:flex;justify-content:space-between;align-items:center;gap:1rem}.muted{color:#666}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:.7rem;margin:1.4rem 0}.card{border:1px solid #ddd;border-radius:8px;padding:.75rem}.card strong{display:block;font-size:1.5rem}.toolbar{display:flex;gap:.5rem;align-items:center;margin:.75rem 0}input,select,button{font:inherit;padding:.45rem;border:1px solid #aaa;border-radius:5px}button{cursor:pointer;background:#f5f5f5}button.primary{background:#1769aa;color:#fff;border-color:#1769aa}.danger{color:#a11}table{border-collapse:collapse;width:100%;display:block;overflow-x:auto}th,td{padding:.55rem;text-align:left;border-bottom:1px solid #ddd;white-space:nowrap}.status{font-weight:600}.status.failed,.status.timed_out{color:#a11}.status.succeeded{color:#176b35}.status.running,.status.queued{color:#9a6500}dialog{border:1px solid #aaa;border-radius:8px;max-width:38rem;width:calc(100% - 2rem)}form{display:grid;gap:.7rem}label{display:grid;gap:.2rem}form .actions{display:flex;justify-content:flex-end;gap:.5rem}#empty{color:#666}@media(max-width:700px){.summary{grid-template-columns:repeat(2,1fr)}body{margin-top:1rem}}
    @media(prefers-color-scheme:dark){body{color:#eee;background:#171717}.muted{color:#aaa}.card,dialog{border-color:#555;background:#222}input,select,button{color:#eee;background:#333;border-color:#666}th,td{border-color:#444}}
  </style>
</head>
<body><main>
  <header><div><h1>Codex Local Scheduler</h1><div class="muted">Local dashboard · changes affect scheduled work</div></div><div class="muted" id="updated">Loading…</div></header>
  <div class="summary" id="summary"></div>
  <section><div class="section-head"><h2>Jobs</h2><button class="primary" onclick="openJob()">Add job</button></div><div class="toolbar"><input id="job-filter" placeholder="Filter jobs…" oninput="renderJobs()"></div><div id="jobs"></div></section>
  <section><div class="section-head"><h2>Recent runs</h2><select id="run-filter" onchange="renderRuns()"><option value="">All statuses</option><option>queued</option><option>running</option><option>succeeded</option><option>failed</option><option>timed_out</option><option>skipped</option></select></div><div id="runs"></div></section><dialog id="job-dialog"></dialog>
</main><script>
const csrf = '__CSRF_TOKEN__'; let snapshot = {jobs:[],runs:[]}; let options = {projects:[],connections:[]};
const escape = value => { const node=document.createElement('span'); node.textContent=value ?? ''; return node.innerHTML; };
const table = (heads, rows) => rows.length ? `<table><thead><tr>${heads.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>` : '<div id="empty">Nothing to show yet.</div>';
function render(data) {
  snapshot=data; document.querySelector('#updated').textContent = `Updated ${new Date(data.generated_at).toLocaleString()} · refreshes every 15 seconds`;
  document.querySelector('#summary').innerHTML = Object.entries(data.counts).map(([label,count]) => `<div class="card"><span class="muted">${escape(label)}</span><strong>${count}</strong></div>`).join(''); renderJobs(); renderRuns();
}
function renderJobs() { const q=document.querySelector('#job-filter').value.toLowerCase(); const rows=snapshot.jobs.filter(j=>`${j.slug} ${j.project}`.toLowerCase().includes(q)).map(job => `<tr><td>${escape(job.slug)}</td><td>${escape(job.project)}</td><td>${escape(job.schedule)} <span class="muted">${escape(job.timezone)}</span></td><td>${escape(job.runner)}${job.model ? ` <span class="muted">${escape(job.model)}</span>` : ''}</td><td class="status ${escape(job.state)}">${escape(job.state)}</td><td>${escape(job.last_status || 'never')} <span class="muted">${escape(job.last_finished_at || '')}</span></td><td><button onclick="openJob('${encodeURIComponent(job.slug)}')">Edit</button> <button class="danger" onclick="archiveJob('${encodeURIComponent(job.slug)}')">Remove</button></td></tr>`); document.querySelector('#jobs').innerHTML=table(['Job','Project','Schedule','Runner','State','Last run',''],rows); }
function renderRuns() { const filter=document.querySelector('#run-filter').value; const rows=snapshot.runs.filter(r=>!filter||r.status===filter).map(run => `<tr><td>${escape(run.job)}</td><td>${escape(run.scheduled_for)}</td><td>${escape(run.started_at)}</td><td>${escape(run.finished_at || '—')}</td><td class="status ${escape(run.status)}">${escape(run.status)}</td><td>${escape(run.exit_code ?? '—')}</td></tr>`); document.querySelector('#runs').innerHTML=table(['Job','Scheduled for','Started','Finished','Status','Exit'],rows); }
async function refresh() { try { const [data,meta]=await Promise.all([fetch('/api/overview',{cache:'no-store'}),fetch('/api/options',{cache:'no-store'})]); options=await meta.json(); render(await data.json()); } catch (error) { document.querySelector('#updated').textContent = `Could not load dashboard: ${error}`; } }
function field(label,name,value='',type='text'){return `<label>${label}<input name="${name}" type="${type}" value="${escape(value)}"></label>`}
function openJob(encoded=''){ const job=encoded?snapshot.jobs.find(j=>j.slug===decodeURIComponent(encoded)):null; const d=document.querySelector('#job-dialog'); d.innerHTML=`<form id="job-form"><h3>${job?'Edit':'Add'} job</h3>${job?'':field('Job slug','slug')}${job?'':`<label>Project<select name="project" required>${options.projects.map(p=>`<option>${escape(p)}</option>`).join('')}</select></label>`}${field('Schedule (five-field cron)','schedule',job?.schedule||'* * * * *')}${field('Timezone','timezone',job?.timezone||'America/Chicago')}${field('Timeout seconds','timeout',job?.timeout||1800,'number')}<label>Runner<select name="runner"><option ${job?.runner==='command'?'selected':''}>command</option><option ${job?.runner==='codex'?'selected':''}>codex</option></select></label>${field('Model (Codex only)','model',job?.model||'')} ${field('Reasoning effort (optional)','effort',job?.reasoning_effort||'')}<label>Sandbox<select name="sandbox"><option>read-only</option><option ${job?.sandbox==='workspace-write'?'selected':''}>workspace-write</option></select></label><label>Connection<select name="connection"><option value="">None</option>${options.connections.map(c=>`<option>${escape(c)}</option>`).join('')}</select></label>${field('Command / prompt (leave blank when editing to keep existing)','command','')}<label><input name="auto_approve" type="checkbox" ${job?.auto_approve?'checked':''}> Automatic approval</label><label><input name="enabled" type="checkbox" ${!job||job.state==='enabled'?'checked':''}> Enabled</label><div class="actions"><button type="button" onclick="this.closest('dialog').close()">Cancel</button><button class="primary">Save</button></div></form>`; const form=d.querySelector('form'); if(job) { form.querySelector('[name=connection]').value=job.connection||''; form.dataset.slug=job.slug; } form.onsubmit=async e=>{e.preventDefault();const body=Object.fromEntries(new FormData(form));body.enabled=form.enabled.checked;body.auto_approve=form.auto_approve.checked;body.timeout=Number(body.timeout); if(!body.command)delete body.command; await write(job?`/api/jobs/${encodeURIComponent(job.slug)}`:'/api/jobs',job?'PATCH':'POST',body);d.close();refresh()}; d.showModal(); }
async function archiveJob(slug){if(confirm(`Archive ${decodeURIComponent(slug)}? Its run history will remain.`)){await write(`/api/jobs/${slug}/archive`,'POST',{});refresh()}}
async function write(url,method,body){const response=await fetch(url,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)});if(!response.ok){const detail=await response.text();alert(detail||`Request failed (${response.status})`);throw new Error(detail)}}
refresh(); setInterval(refresh, 15000);
</script></body></html>"""


def overview(store: Store) -> dict[str, Any]:
    """Return only operational metadata; never commands, prompts, logs, or errors."""
    jobs = []
    for row in store.dashboard_jobs():
        state = "archived" if row["archived"] else ("enabled" if row["enabled"] else "paused")
        jobs.append({
            "slug": row["slug"], "project": row["project_slug"], "schedule": row["schedule"],
            "timezone": row["timezone"], "runner": row["runner"], "model": row["model"],
            "reasoning_effort": row["reasoning_effort"], "sandbox": row["sandbox"], "auto_approve": bool(row["auto_approve"]),
            "connection": row["connection_slug"], "timeout": row["timeout_seconds"],
            "state": state, "last_status": row["last_status"], "last_finished_at": row["last_finished_at"],
        })
    runs = [dict(row) for row in store.recent_runs(30)]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "Enabled jobs": sum(job["state"] == "enabled" for job in jobs),
            "Paused jobs": sum(job["state"] == "paused" for job in jobs),
            "Queued runs": sum(run["status"] == "queued" for run in runs),
            "Failed runs": sum(run["status"] in ("failed", "timed_out") for run in runs),
        },
        "jobs": jobs,
        "runs": runs,
    }


def _handler(database_path: Path):
    csrf_token = secrets.token_urlsafe(32)

    class DashboardHandler(BaseHTTPRequestHandler):
        def _json(self, status: int, payload: object) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _write_allowed(self) -> bool:
            host = urlsplit("//" + self.headers.get("Host", "")).hostname
            origin = self.headers.get("Origin")
            origin_host = urlsplit(origin).hostname if origin else None
            return host in ("127.0.0.1", "localhost", "::1") and (not origin or origin_host == host) and self.headers.get("X-CSRF-Token") == csrf_token

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 65536:
                raise ValueError("request body is too large")
            value = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(value, dict):
                raise ValueError("request body must be an object")
            return value

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            if self.path == "/":
                body = HTML.replace("__CSRF_TOKEN__", csrf_token).encode()
                content_type = "text/html; charset=utf-8"
            elif self.path == "/api/overview":
                request_store = Store(database_path)
                try:
                    request_store.initialize()
                    body = json.dumps(overview(request_store)).encode()
                finally:
                    request_store.close()
                content_type = "application/json; charset=utf-8"
            elif self.path == "/api/options":
                request_store = Store(database_path)
                try:
                    request_store.initialize()
                    self._json(200, {"projects": [row["slug"] for row in request_store.connection.execute("SELECT slug FROM projects ORDER BY slug")], "connections": [row["slug"] for row in request_store.connection.execute("SELECT slug FROM connections ORDER BY slug")]})
                finally:
                    request_store.close()
                return
            else:
                self.send_error(404, "Not found")
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            self._mutate("POST")

        def do_PATCH(self) -> None:  # noqa: N802
            self._mutate("PATCH")

        def _mutate(self, method: str) -> None:
            if not self._write_allowed():
                self._json(403, {"error": "write not permitted"})
                return
            request_store: Store | None = None
            try:
                payload = self._read_json()
                request_store = Store(database_path)
                request_store.initialize()
                path = self.path.rstrip("/").split("/")
                if self.path == "/api/jobs" and method == "POST":
                    ZoneInfo(str(payload["timezone"]))
                    matches(str(payload["schedule"]), datetime.now())
                    request_store.add_job(str(payload["slug"]), str(payload["project"]), str(payload["schedule"]), str(payload["command"]), payload.get("connection") or None, int(payload.get("timeout", 1800)), str(payload.get("runner", "command")), payload.get("model") or None, payload.get("effort") or None, str(payload["timezone"]), str(payload.get("sandbox", "read-only")), bool(payload.get("auto_approve", False)))
                elif len(path) == 4 and path[1:3] == ["api", "jobs"] and path[3] and path[3] != "archive" and method == "PATCH":
                    slug = path[3]
                    ZoneInfo(str(payload["timezone"]))
                    matches(str(payload["schedule"]), datetime.now())
                    request_store.update_job(slug, str(payload["schedule"]), int(payload.get("timeout", 1800)), str(payload.get("runner", "command")), payload.get("model") or None, payload.get("effort") or None, str(payload["timezone"]), str(payload.get("sandbox", "read-only")), bool(payload.get("auto_approve", False)), payload.get("connection") or None, bool(payload.get("enabled", True)), payload.get("command"))
                elif len(path) == 5 and path[1:4] == ["api", "jobs", path[3]] and path[4] == "archive" and method == "POST":
                    if not request_store.archive_job(path[3]):
                        raise ValueError(f"unknown job: {path[3]}")
                else:
                    raise ValueError("unknown dashboard route")
                self._json(200, {"ok": True})
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
                self._json(400, {"error": str(error)})
            except Exception as error:
                self._json(500, {"error": str(error)})
            finally:
                if request_store is not None:
                    request_store.close()

        def log_message(self, format: str, *args: object) -> None:
            return

    return DashboardHandler


def serve(store: Store, host: str, port: int) -> None:
    """Serve the dashboard only to a local loopback interface."""
    if host not in ("127.0.0.1", "::1"):
        raise ValueError("dashboard host must be a loopback address (127.0.0.1 or ::1)")
    if not 1 <= port <= 65535:
        raise ValueError("dashboard port must be between 1 and 65535")
    # Browser previews can open an idle connection before sending a request.
    # A threaded server keeps that client from blocking every other request.
    server = ThreadingHTTPServer((host, port), _handler(store.path))
    server.daemon_threads = True
    print(f"Dashboard available at http://{host}:{port}/ (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()
