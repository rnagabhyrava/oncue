"""A dependency-free, read-only local dashboard for scheduler state."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .store import Store


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Codex Local Scheduler</title>
  <style>body{font:14px system-ui,sans-serif;margin:2rem;max-width:1100px}h1{margin-bottom:.2rem}h2{margin-top:2rem}table{border-collapse:collapse;width:100%}th,td{padding:.45rem;text-align:left;border-bottom:1px solid #ddd;white-space:nowrap}.muted{color:#666}.summary{margin:1rem 0}#empty{color:#666}</style>
</head>
<body><main>
  <header><div><h1>Codex Local Scheduler</h1><div class="muted">Local, read-only dashboard</div></div><div class="muted" id="updated">Loading…</div></header>
  <div class="summary" id="summary"></div>
  <h2>Jobs</h2><div id="jobs"></div>
  <h2>Recent runs</h2><div id="runs"></div>
</main><script>
const escape = value => { const node=document.createElement('span'); node.textContent=value ?? ''; return node.innerHTML; };
const table = (heads, rows) => rows.length ? `<table><thead><tr>${heads.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>` : '<div id="empty">Nothing to show yet.</div>';
function render(data) {
  document.querySelector('#updated').textContent = `Updated ${new Date(data.generated_at).toLocaleString()} · refreshes every 15 seconds`;
  document.querySelector('#summary').textContent = Object.entries(data.counts).map(([label,count]) => `${label}: ${count}`).join(' · ');
  document.querySelector('#jobs').innerHTML = table(['Job','Project','Schedule','Runner','State','Last run'], data.jobs.map(job => `<tr><td>${escape(job.slug)}</td><td>${escape(job.project)}</td><td>${escape(job.schedule)} <span class="muted">${escape(job.timezone)}</span></td><td>${escape(job.runner)}${job.model ? ` <span class="muted">${escape(job.model)}</span>` : ''}</td><td>${escape(job.state)}</td><td>${escape(job.last_status || 'never')}</td></tr>`));
  document.querySelector('#runs').innerHTML = table(['Job','Scheduled for','Started','Finished','Status','Exit'], data.runs.map(run => `<tr><td>${escape(run.job)}</td><td>${escape(run.scheduled_for)}</td><td>${escape(run.started_at)}</td><td>${escape(run.finished_at || '—')}</td><td>${escape(run.status)}</td><td>${escape(run.exit_code ?? '—')}</td></tr>`));
}
async function refresh() { try { render(await (await fetch('/api/overview', {cache:'no-store'})).json()); } catch (error) { document.querySelector('#updated').textContent = `Could not load dashboard: ${error}`; } }
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
            "state": state, "last_status": row["last_status"],
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
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            if self.path == "/":
                body = HTML.encode()
                content_type = "text/html; charset=utf-8"
            elif self.path == "/api/overview":
                request_store = Store(database_path)
                try:
                    request_store.initialize()
                    body = json.dumps(overview(request_store)).encode()
                finally:
                    request_store.close()
                content_type = "application/json; charset=utf-8"
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
