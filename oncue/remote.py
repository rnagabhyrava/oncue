"""Account linking and outbound cloud synchronization.

The local database remains authoritative.  This module deliberately uses only the
Python standard library so remote access does not add runtime dependencies to the
scheduler bundle.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import secrets
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path


ACCOUNT_FILE = "remote-account.json"
OUTBOX_FILE = "remote-sync-outbox.json"


def cloud_config() -> dict:
    return {
        "cloud_url": os.environ.get("ONCUE_CLOUD_URL", "").rstrip("/"),
        "auth0_domain": os.environ.get("ONCUE_AUTH0_DOMAIN", ""),
        "auth0_client_id": os.environ.get("ONCUE_AUTH0_CLIENT_ID", ""),
        "auth0_audience": os.environ.get("ONCUE_AUTH0_AUDIENCE", ""),
    }


def _account_path(data_dir: Path) -> Path:
    return Path(data_dir) / ACCOUNT_FILE


def account_state(data_dir: Path) -> dict:
    cfg = cloud_config()
    result = {"mode": "local", "configured": all(cfg.values()), **cfg, "linked": False, "claimed": False}
    try:
        saved = json.loads(_account_path(data_dir).read_text())
        result.update({
            "linked": bool(saved.get("account_subject")),
            "claimed": bool(saved.get("computer_id") and saved.get("credential")),
            "computer_id": saved.get("computer_id"),
            "computer_name": saved.get("computer_name"),
            "email": saved.get("email"),
            "last_sync_at": saved.get("last_sync_at"),
            "sync_error": saved.get("sync_error"),
        })
    except (OSError, ValueError, TypeError):
        pass
    return result


def _request(data_dir: Path, path: str, *, payload=None, bearer=None, method=None) -> dict:
    cfg = cloud_config()
    if not cfg["cloud_url"]:
        raise ValueError("Remote access is not configured")
    from urllib.parse import urlsplit
    parsed = urlsplit(cfg["cloud_url"])
    if parsed.scheme != "https" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Remote access requires an HTTPS service URL")
    body = None if payload is None else json.dumps(payload).encode()
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    request = urllib.request.Request(cfg["cloud_url"] + path, data=body, headers=headers,
                                     method=method or ("POST" if body is not None else "GET"))
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read()).get("detail")
        except (ValueError, AttributeError):
            detail = None
        raise ValueError(detail or f"Remote service returned {error.code}") from None
    except urllib.error.URLError as error:
        raise ValueError(f"Remote service is unavailable: {error.reason}") from None


def verify_session(data_dir: Path, access_token: str) -> dict:
    """Verify a browser token through the cloud API and bind it to this install."""
    profile = _request(data_dir, "/v1/account", bearer=access_token)
    path = _account_path(data_dir)
    saved = {}
    try:
        saved = json.loads(path.read_text())
    except (OSError, ValueError):
        pass
    existing = saved.get("account_subject")
    identity = profile["issuer"] + "\n" + profile["subject"]
    if existing and not secrets.compare_digest(existing, identity):
        raise ValueError("This installation belongs to a different OnCue account")
    saved.update({"account_subject": identity, "email": profile.get("email")})
    _save_account(path, saved)
    return {"email": profile.get("email"), "claimed": bool(saved.get("credential"))}


def claim_installation(data_dir: Path, access_token: str, name: str | None = None) -> dict:
    path = _account_path(data_dir)
    saved = json.loads(path.read_text()) if path.exists() else {}
    if not saved.get("account_subject"):
        verify_session(data_dir, access_token)
        saved = json.loads(path.read_text())
    if saved.get("credential"):
        return account_state(data_dir)
    installation_id = saved.get("installation_id") or str(uuid.uuid4())
    computer_name = (name or platform.node() or "OnCue computer").strip()[:120]
    enrolled = _request(data_dir, "/v1/computers/enroll", bearer=access_token,
                        payload={"installation_id": installation_id, "name": computer_name})
    saved.update({"installation_id": installation_id, "computer_id": enrolled["computer_id"],
                  "computer_name": computer_name, "credential": enrolled["credential"]})
    _save_account(path, saved)
    return account_state(data_dir)


def _save_account(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(value, output)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def _snapshot(store) -> dict:
    """Return the cloud-safe projection; paths, logs, attachments and secrets stay local."""
    from .dashboard import task_list
    tasks = task_list(store)
    settings = tasks.pop("settings", {})
    tasks["defaults"] = {key: settings.get(key) for key in ("provider", "model", "timezone")}
    tasks.pop("generated_at", None)
    tasks["projects"] = [dict(row) for row in store.task_projects()]
    tasks["messages"] = [dict(row) for row in store.connection.execute(
        "SELECT messages.id,jobs.slug AS task_slug,messages.role,messages.content,messages.run_id,messages.created_at "
        "FROM messages JOIN jobs ON jobs.id=messages.job_id ORDER BY messages.id")]
    runs = []
    for row in store.connection.execute(
            "SELECT runs.*,jobs.slug AS task_slug FROM runs JOIN jobs ON jobs.id=runs.job_id ORDER BY runs.id"):
        item = dict(row)
        response_path = item.pop("response_path", None)
        item.pop("output_path", None)
        item.pop("config_snapshot", None)
        item.pop("process_id", None)
        item.pop("process_start_ticks", None)
        # User-visible response only; execution diagnostics remain on the computer.
        item["response"] = ""
        if response_path:
            try:
                response = Path(response_path).resolve()
                if response.is_relative_to((store.path.parent / "runs").resolve()):
                    item["response"] = response.read_text(errors="replace")
            except OSError:
                pass
        runs.append(item)
    tasks["runs"] = runs
    return tasks


def _apply_command(store, command: dict) -> dict:
    from .conversations import queue_message, retry_run
    from .tasks import queue_manual, save_task
    action, payload = command["action"], dict(command.get("payload") or {})
    slug = command.get("task_slug")
    if action == "create":
        data = dict(payload)
        new_slug = data.pop("_slug", None)
        for key in ("runner", "sandbox", "auto_approve", "connection", "project"):
            data.pop(key, None)
        data.update({"runner": "codex", "sandbox": "read-only", "auto_approve": False})
        return {"slug": save_task(store, data, commit=False, new_slug=new_slug)}
    if action == "update":
        for key in ("runner", "sandbox", "auto_approve", "connection", "project"):
            payload.pop(key, None)
        return {"slug": save_task(store, payload, slug, commit=False)}
    if action == "message":
        existing_slug = slug if slug and store.job(slug, include_archived=True) else None
        options = payload.get("options") or {}
        options = {key: options[key] for key in ("provider", "model", "timezone") if key in options}
        return queue_message(store, existing_slug, payload.get("text", ""), options,
                             commit=False, scheduled_for="remote:" + command["id"], new_slug=slug)
    if action == "run":
        return {"run_id": queue_manual(store, slug, scheduled_for="remote:" + command["id"], commit=False)}
    if action == "retry":
        return {"run_id": retry_run(store, int(payload["run_id"]), payload.get("minutes", 0), commit=False)}
    if action in ("pause", "resume"):
        if not store.set_job_enabled(slug, action == "resume", commit=False):
            raise ValueError("Task not found")
        return {"ok": True}
    if action == "archive":
        if not store.archive_job(slug, commit=False):
            raise ValueError("Task not found")
        return {"ok": True}
    raise ValueError("Remote action is not allowed")


def sync_once(database_path: Path) -> bool:
    from .store import Store
    data_dir = Path(database_path).parent
    path = _account_path(data_dir)
    try:
        saved = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    if not saved.get("computer_id") or not saved.get("credential"):
        return False
    store = Store(database_path)
    try:
        snapshot = _snapshot(store)
        digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        sequence = int(saved.get("sequence", 0))
        outbox_path = data_dir / OUTBOX_FILE
        try:
            outbox = json.loads(outbox_path.read_text())
        except (OSError, ValueError):
            outbox = None
        if outbox is None and digest != saved.get("snapshot_hash"):
            outbox = {"sequence": sequence + 1, "digest": digest, "snapshot": snapshot}
            _save_account(outbox_path, outbox)
        send_sequence = outbox["sequence"] if outbox else sequence
        result = _request(data_dir, "/v1/agent/sync", bearer=saved["credential"], payload={
            "computer_id": saved["computer_id"], "sequence": send_sequence,
            "snapshot": outbox["snapshot"] if outbox else None,
        })
        for command in result.get("commands", []):
            # The local receipt table makes command replay safe across process crashes.
            existing = store.connection.execute("SELECT status,result FROM remote_commands WHERE id=?", (command["id"],)).fetchone()
            if existing:
                outcome = {"status": existing["status"], "result": json.loads(existing["result"] or "{}")}
            else:
                try:
                    with store.connection:
                        current = store.connection.execute("SELECT remote_revision FROM jobs WHERE slug=?", (command.get("task_slug"),)).fetchone()
                        expected = command.get("expected_revision")
                        if expected is not None and (not current or current[0] != expected):
                            raise ValueError("Task changed since this command was created")
                        value = _apply_command(store, command)
                        store.connection.execute("INSERT INTO remote_commands(id,status,result) VALUES (?,?,?)",
                                                 (command["id"], "applied", json.dumps(value)))
                    outcome = {"status": "applied", "result": value}
                except Exception as error:
                    store.connection.rollback()
                    message = str(error)[:500]
                    store.connection.execute("INSERT OR IGNORE INTO remote_commands(id,status,result) VALUES (?,?,?)",
                                             (command["id"], "rejected", json.dumps({"error": message})))
                    store.connection.commit()
                    outcome = {"status": "rejected", "result": {"error": message}}
            _request(data_dir, f"/v1/agent/commands/{command['id']}/ack", bearer=saved["credential"], payload=outcome)
        if outbox and result.get("acknowledged_sequence", send_sequence) >= send_sequence:
            sequence, digest = send_sequence, outbox["digest"]
            outbox_path.unlink(missing_ok=True)
        saved.update({"sequence": sequence, "snapshot_hash": digest, "last_sync_at": result.get("server_time"), "sync_error": None})
        _save_account(path, saved)
        return True
    except Exception as error:
        saved["sync_error"] = str(error)[:500]
        _save_account(path, saved)
        return False
    finally:
        store.close()


class SyncAgent:
    def __init__(self, database_path: Path, interval: float = 5.0):
        self.database_path, self.interval = Path(database_path), interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="oncue-cloud-sync", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=10)

    def _run(self):
        while not self._stop.is_set():
            sync_once(self.database_path)
            self._stop.wait(self.interval)
