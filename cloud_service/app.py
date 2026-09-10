"""FastAPI service for Auth0 accounts and local OnCue computers."""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    issuer: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("issuer", "subject"),)


class Computer(Base):
    __tablename__ = "computers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    installation_id: Mapped[str] = mapped_column(String(36))
    name: Mapped[str] = mapped_column(String(120))
    credential_hash: Mapped[str] = mapped_column(String(64))
    last_sequence: Mapped[int] = mapped_column(Integer, default=0)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    account: Mapped[Account] = relationship()
    __table_args__ = (UniqueConstraint("account_id", "installation_id"),)


class Snapshot(Base):
    __tablename__ = "snapshots"
    computer_id: Mapped[str] = mapped_column(ForeignKey("computers.id", ondelete="CASCADE"), primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RemoteCommand(Base):
    __tablename__ = "remote_commands"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    computer_id: Mapped[str] = mapped_column(ForeignKey("computers.id", ondelete="CASCADE"), index=True)
    task_slug: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    expected_revision: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    result: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: now() + timedelta(hours=24))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Enrollment(BaseModel):
    installation_id: str = Field(min_length=36, max_length=36)
    name: str = Field(min_length=1, max_length=120)


class SyncBody(BaseModel):
    computer_id: str
    sequence: int = Field(ge=0)
    snapshot: dict[str, Any] | None = None


class CommandBody(BaseModel):
    computer_id: str
    task_slug: str | None = None
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    expected_revision: int | None = None


class Acknowledgement(BaseModel):
    status: str
    result: dict[str, Any] = Field(default_factory=dict)


class Auth0Verifier:
    def __init__(self, domain: str, audience: str):
        self.issuer = "https://" + domain.strip("/") + "/"
        self.audience = audience
        self.jwks = jwt.PyJWKClient(self.issuer + ".well-known/jwks.json")

    def __call__(self, token: str) -> dict:
        key = self.jwks.get_signing_key_from_jwt(token)
        return jwt.decode(token, key.key, algorithms=["RS256"], audience=self.audience, issuer=self.issuer)


def create_app(database_url: str | None = None, token_verifier: Callable[[str], dict] | None = None) -> FastAPI:
    database_url = database_url or os.environ.get("DATABASE_URL", "sqlite:///./oncue-cloud.sqlite3")
    if database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgres://")
    engine = create_engine(database_url, connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {})
    sessions = sessionmaker(engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    domain, audience = os.environ.get("AUTH0_DOMAIN", ""), os.environ.get("AUTH0_AUDIENCE", "")
    verifier = token_verifier or (Auth0Verifier(domain, audience) if domain and audience else None)
    app = FastAPI(title="OnCue Cloud API", version="1.0")
    origin = os.environ.get("ONCUE_WEB_ORIGIN", "")
    if origin:
        app.add_middleware(CORSMiddleware, allow_origins=[origin], allow_methods=["GET", "POST", "PATCH", "DELETE"],
                           allow_headers=["Authorization", "Content-Type"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        if int(request.headers.get("content-length", "0") or 0) > 16 * 1024 * 1024:
            return JSONResponse({"detail": "Request is too large"}, status_code=413)
        response = await call_next(request)
        auth_origin = "https://" + domain.strip("/") if domain else ""
        frame_source = auth_origin or "'none'"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self' {auth_origin}; "
            f"frame-src {frame_source}; img-src 'self' data: https:; object-src 'none'; "
            "frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    def db():
        with sessions() as session:
            yield session

    def account(authorization: str | None = Header(default=None), session: Session = Depends(db)) -> Account:
        if not authorization or not authorization.startswith("Bearer ") or verifier is None:
            raise HTTPException(401, "Sign in required")
        try:
            claims = verifier(authorization[7:])
            issuer, subject = str(claims["iss"]), str(claims["sub"])
            if not subject.startswith("google-oauth2|"):
                raise ValueError("Google identity required")
        except Exception:
            raise HTTPException(401, "Invalid or expired access token") from None
        value = session.scalar(select(Account).where(Account.issuer == issuer, Account.subject == subject))
        if value is None:
            value = Account(issuer=issuer, subject=subject, email=claims.get("email"))
            session.add(value); session.commit()
        elif claims.get("email") and value.email != claims["email"]:
            value.email = claims["email"]; session.commit()
        return value

    def agent(authorization: str | None = Header(default=None), session: Session = Depends(db)) -> Computer:
        if not authorization or not authorization.startswith("Bearer ocd_"):
            raise HTTPException(401, "Computer credential required")
        try:
            _, computer_id, secret = authorization[7:].split("_", 2)
        except ValueError:
            raise HTTPException(401, "Invalid computer credential") from None
        value = session.get(Computer, computer_id)
        digest = hashlib.sha256(secret.encode()).hexdigest()
        if value is None or value.revoked_at or not secrets.compare_digest(value.credential_hash, digest):
            raise HTTPException(401, "Computer credential is revoked or invalid")
        return value

    def owned(session: Session, owner: Account, computer_id: str) -> Computer:
        value = session.get(Computer, computer_id)
        if value is None or value.account_id != owner.id:
            raise HTTPException(404, "Computer not found")
        return value

    @app.get("/health")
    def health(): return {"ok": True}

    @app.get("/v1/config")
    def config():
        return {"auth0_domain": domain, "auth0_client_id": os.environ.get("AUTH0_CLIENT_ID", ""),
                "auth0_audience": audience, "connection": "google-oauth2"}

    @app.get("/api/account/status")
    def browser_config():
        return {"mode": "cloud", "configured": bool(domain and audience and os.environ.get("AUTH0_CLIENT_ID")),
                "auth0_domain": domain, "auth0_client_id": os.environ.get("AUTH0_CLIENT_ID", ""),
                "auth0_audience": audience}

    @app.get("/v1/account")
    def me(owner: Account = Depends(account)):
        return {"issuer": owner.issuer, "subject": owner.subject, "email": owner.email}

    @app.get("/v1/computers")
    def computers(owner: Account = Depends(account), session: Session = Depends(db)):
        values = session.scalars(select(Computer).where(Computer.account_id == owner.id)).all()
        return {"computers": [{"id": c.id, "name": c.name, "last_seen_at": c.last_seen_at,
                                "revoked": bool(c.revoked_at)} for c in values]}

    @app.post("/v1/computers/enroll", status_code=201)
    def enroll(body: Enrollment, owner: Account = Depends(account), session: Session = Depends(db)):
        previous = session.scalar(select(Computer).where(Computer.account_id == owner.id,
                                                          Computer.installation_id == body.installation_id))
        if previous and not previous.revoked_at:
            raise HTTPException(409, "This installation is already linked")
        secret = secrets.token_urlsafe(36)
        value = previous or Computer(account_id=owner.id, installation_id=body.installation_id,
                                     name=body.name, credential_hash="")
        value.name, value.credential_hash, value.revoked_at = body.name, hashlib.sha256(secret.encode()).hexdigest(), None
        session.add(value); session.commit()
        return {"computer_id": value.id, "credential": f"ocd_{value.id}_{secret}"}

    @app.delete("/v1/computers/{computer_id}")
    def revoke(computer_id: str, owner: Account = Depends(account), session: Session = Depends(db)):
        value = owned(session, owner, computer_id); value.revoked_at = now(); session.commit(); return {"ok": True}

    @app.post("/v1/agent/sync")
    def sync(body: SyncBody, computer: Computer = Depends(agent), session: Session = Depends(db)):
        if body.computer_id != computer.id:
            raise HTTPException(403, "Credential does not belong to this computer")
        if body.sequence < computer.last_sequence:
            raise HTTPException(409, "Sync sequence moved backwards")
        if body.snapshot is not None:
            if body.sequence == computer.last_sequence:
                current = session.get(Snapshot, computer.id)
                if current and current.payload != body.snapshot:
                    raise HTTPException(409, "Sequence was already used")
            else:
                value = session.get(Snapshot, computer.id) or Snapshot(computer_id=computer.id, sequence=body.sequence, payload={})
                value.sequence, value.payload, value.received_at = body.sequence, body.snapshot, now()
                session.add(value); computer.last_sequence = body.sequence
        computer.last_seen_at = now()
        commands = session.scalars(select(RemoteCommand).where(RemoteCommand.computer_id == computer.id,
            RemoteCommand.status == "pending", RemoteCommand.expires_at > now()).order_by(RemoteCommand.created_at).limit(50)).all()
        session.commit()
        return {"acknowledged_sequence": computer.last_sequence, "server_time": now().isoformat(),
                "commands": [{"id": c.id, "task_slug": c.task_slug, "action": c.action, "payload": c.payload,
                              "expected_revision": c.expected_revision} for c in commands]}

    @app.post("/v1/agent/commands/{command_id}/ack")
    def acknowledge(command_id: str, body: Acknowledgement, computer: Computer = Depends(agent), session: Session = Depends(db)):
        command = session.get(RemoteCommand, command_id)
        if command is None or command.computer_id != computer.id:
            raise HTTPException(404, "Command not found")
        if body.status not in ("applied", "rejected"):
            raise HTTPException(400, "Invalid acknowledgement")
        if command.status == "pending":
            command.status, command.result, command.acknowledged_at = body.status, body.result, now(); session.commit()
        return {"ok": True}

    @app.post("/v1/commands", status_code=202)
    def create_command(body: CommandBody, owner: Account = Depends(account), session: Session = Depends(db)):
        owned(session, owner, body.computer_id)
        allowed = {"create", "update", "message", "run", "retry", "pause", "resume", "archive"}
        if body.action not in allowed:
            raise HTTPException(400, "Remote action is not allowed")
        payload = safe_task_payload(body.payload, body.computer_id, body.action == "create") \
            if body.action in ("create", "update") else body.payload
        value = RemoteCommand(account_id=owner.id, computer_id=body.computer_id, task_slug=body.task_slug,
                              action=body.action, payload=payload, expected_revision=body.expected_revision)
        session.add(value); session.commit()
        return {"id": value.id, "status": value.status, "expires_at": value.expires_at}

    @app.delete("/v1/commands/{command_id}")
    def cancel(command_id: str, owner: Account = Depends(account), session: Session = Depends(db)):
        value = session.get(RemoteCommand, command_id)
        if value is None or value.account_id != owner.id:
            raise HTTPException(404, "Command not found")
        if value.status != "pending":
            raise HTTPException(409, "Command has already been processed")
        value.status = "cancelled"; session.commit(); return {"ok": True}

    @app.get("/v1/commands/{command_id}")
    def command_status(command_id: str, owner: Account = Depends(account), session: Session = Depends(db)):
        value = session.get(RemoteCommand, command_id)
        if value is None or value.account_id != owner.id:
            raise HTTPException(404, "Command not found")
        if value.status == "pending" and aware(value.expires_at) <= now():
            value.status = "expired"; session.commit()
        return {"id": value.id, "status": value.status, "result": value.result,
                "expires_at": value.expires_at, "acknowledged_at": value.acknowledged_at}

    @app.get("/v1/history")
    def history(owner: Account = Depends(account), session: Session = Depends(db)):
        rows = session.execute(select(Computer, Snapshot).join(Snapshot, Snapshot.computer_id == Computer.id, isouter=True)
                               .where(Computer.account_id == owner.id)).all()
        return {"computers": [{"id": c.id, "name": c.name, "last_seen_at": c.last_seen_at,
                                "snapshot": s.payload if s else None} for c, s in rows]}

    def account_rows(session: Session, owner: Account):
        return session.execute(select(Computer, Snapshot).join(Snapshot, Snapshot.computer_id == Computer.id, isouter=True)
                               .where(Computer.account_id == owner.id, Computer.revoked_at.is_(None))).all()

    def split_slug(value: str):
        try: return value.split("~", 1)
        except (AttributeError, ValueError): raise HTTPException(400, "Invalid task identifier") from None

    def pending_count(session: Session, owner: Account):
        return len(session.scalars(select(RemoteCommand).where(RemoteCommand.account_id == owner.id,
            RemoteCommand.status == "pending", RemoteCommand.expires_at > now())).all())

    def submit(session: Session, owner: Account, computer_id: str, action: str, task_slug=None, payload=None):
        computer = owned(session, owner, computer_id)
        if computer.revoked_at: raise HTTPException(409, "Computer is revoked")
        revision = None
        snapshot = session.get(Snapshot, computer_id)
        if task_slug and snapshot:
            match = next((j for j in snapshot.payload.get("jobs", []) if j.get("slug") == task_slug), None)
            revision = match.get("revision", 0) if match else None
        command = RemoteCommand(account_id=owner.id, computer_id=computer_id, task_slug=task_slug,
                                action=action, payload=payload or {}, expected_revision=revision)
        session.add(command); session.commit()
        return {"command_id": command.id, "status": "pending", "expires_at": command.expires_at}

    def safe_task_payload(payload: dict, computer_id: str, creating: bool = False) -> dict:
        value = dict(payload)
        # Filesystem/shell/approval boundaries are only configurable on the computer.
        for key in ("runner", "sandbox", "auto_approve", "connection", "project"):
            value.pop(key, None)
        project_id = value.get("task_project_id")
        if isinstance(project_id, str) and "~" in project_id:
            project_computer, local_id = project_id.split("~", 1)
            if project_computer != computer_id: raise HTTPException(400, "Project belongs to another computer")
            value["task_project_id"] = int(local_id)
        if creating:
            value.update({"runner": "codex", "sandbox": "read-only", "auto_approve": False})
        return value

    def new_slug(title: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "task"
        return f"{base}-{uuid.uuid4().hex[:8]}"

    @app.get("/api/tasks")
    def dashboard_tasks(owner: Account = Depends(account), session: Session = Depends(db)):
        jobs, runs, projects, computers_result = [], [], [], []
        dashboard_defaults = {"provider": "codex", "model": "", "timezone": "UTC"}
        for computer, snapshot in account_rows(session, owner):
            payload = snapshot.payload if snapshot else {}
            if snapshot and not computers_result:
                dashboard_defaults.update({key: value for key, value in payload.get("defaults", {}).items() if value})
            computers_result.append({"id": computer.id, "name": computer.name, "last_seen_at": computer.last_seen_at,
                                     "online": bool(computer.last_seen_at and (now() - aware(computer.last_seen_at)).total_seconds() < 30),
                                     "defaults": payload.get("defaults", {})})
            for job in payload.get("jobs", []):
                item = dict(job); item["local_slug"] = item.get("slug"); item["slug"] = computer.id + "~" + item["local_slug"]
                if item.get("task_project_id") is not None:
                    item["task_project_id"] = computer.id + "~" + str(item["task_project_id"])
                item["computer_id"], item["computer_name"] = computer.id, computer.name; jobs.append(item)
            for run in payload.get("runs", []):
                item = dict(run); item["id"] = computer.id + "~" + str(item["id"]); item["job"] = item.get("task_slug")
                item.pop("response", None); runs.append(item)
            for project in payload.get("projects", []):
                item = dict(project); item["id"] = computer.id + "~" + str(item["id"]); projects.append(item)
        return {"generated_at": now().isoformat(), "jobs": jobs, "runs": runs, "projects": projects, "remote": True,
                "computers": computers_result, "pending_commands": pending_count(session, owner),
                "scheduler_active": any(c["online"] for c in computers_result),
                "settings": {"theme": "system", "notifications": False, "desktop_notifications": False,
                             **dashboard_defaults, "retry_minutes": 30}}

    @app.get("/api/settings")
    def dashboard_settings(owner: Account = Depends(account)):
        return {"settings": {"theme": "system", "notifications": False, "desktop_notifications": False,
                             "provider": "codex", "model": "", "retry_enabled": True, "retry_minutes": 30,
                             "max_retries": 3, "max_workers": 1, "timezone": "UTC", "keep_awake": False,
                             "fallback_provider": "", "fallback_model": "", "allow_fallback": False,
                             "webhooks": [], "codex_login": "existing"},
                "providers": [], "login": {}, "runtimes": {}, "remote": True}

    @app.get("/api/projects")
    def dashboard_projects(owner: Account = Depends(account), session: Session = Depends(db)):
        return {"projects": dashboard_tasks(owner, session)["projects"]}

    @app.post("/api/preview")
    async def dashboard_preview(request: Request, owner: Account = Depends(account)):
        from oncue.schedules import from_form, next_run
        body = await request.json(); schedule = from_form(body)
        return {"next_run": next_run(schedule, body.get("timezone", "UTC"))}

    @app.get("/api/tasks/{cloud_slug}")
    def dashboard_task(cloud_slug: str, owner: Account = Depends(account), session: Session = Depends(db)):
        computer_id, slug = split_slug(cloud_slug); owned(session, owner, computer_id)
        snapshot = session.get(Snapshot, computer_id)
        if not snapshot: raise HTTPException(404, "Task not found")
        job = next((j for j in snapshot.payload.get("jobs", []) if j.get("slug") == slug), None)
        if not job: raise HTTPException(404, "Task not found")
        return {"instructions": job.get("instructions", ""), "history": [], "attachments": []}

    @app.get("/api/conversation/{cloud_slug}")
    def dashboard_conversation(cloud_slug: str, owner: Account = Depends(account), session: Session = Depends(db)):
        computer_id, slug = split_slug(cloud_slug); owned(session, owner, computer_id)
        snapshot = session.get(Snapshot, computer_id)
        if not snapshot: raise HTTPException(404, "Task history is not available")
        run_map = {str(r["id"]): r for r in snapshot.payload.get("runs", []) if r.get("task_slug") == slug}
        messages = []
        for message in snapshot.payload.get("messages", []):
            if message.get("task_slug") != slug: continue
            item = dict(message); run = run_map.get(str(item.get("run_id")))
            if run and not item.get("content"):
                item["content"] = run.get("response") or run.get("error") or "No response was produced."
            if run:
                item["run"] = {key: run.get(key) for key in ("status", "scheduled_for", "retry_at", "error",
                    "error_kind", "provider", "model", "attempt", "kind", "notify")}
                item["run"]["id"] = computer_id + "~" + str(run["id"])
            messages.append(item)
        active = [{**r, "id": computer_id + "~" + str(r["id"])} for r in run_map.values() if r.get("status") in ("queued", "running")]
        return {"messages": messages[-30:], "before": None, "active_runs": active}

    @app.post("/api/message", status_code=202)
    async def dashboard_message(request: Request, owner: Account = Depends(account), session: Session = Depends(db)):
        body = await request.json(); cloud_slug = body.get("slug")
        if cloud_slug: computer_id, slug = split_slug(cloud_slug)
        else:
            computer_id, slug = body.get("options", {}).get("computer_id"), None
            if not computer_id:
                computer = session.scalar(select(Computer).where(Computer.account_id == owner.id, Computer.revoked_at.is_(None)))
                if not computer: raise HTTPException(409, "Link a computer before creating tasks")
                computer_id = computer.id
            slug = new_slug(body.get("text", ""))
        result = submit(session, owner, computer_id, "message", slug, {"text": body.get("text", ""), "options": body.get("options")})
        result["slug"] = cloud_slug or computer_id + "~" + slug
        return result

    @app.post("/api/tasks", status_code=202)
    async def dashboard_create(request: Request, owner: Account = Depends(account), session: Session = Depends(db)):
        body = await request.json(); computer_id = body.pop("computer_id", None)
        if not computer_id: raise HTTPException(400, "Choose a computer")
        slug = new_slug(body.get("title") or body.get("instructions", ""))
        payload = safe_task_payload(body, computer_id, True); payload["_slug"] = slug
        result = submit(session, owner, computer_id, "create", task_slug=slug, payload=payload)
        result["slug"] = computer_id + "~" + slug
        return result

    @app.patch("/api/tasks/{cloud_slug}", status_code=202)
    async def dashboard_update(cloud_slug: str, request: Request, owner: Account = Depends(account), session: Session = Depends(db)):
        computer_id, slug = split_slug(cloud_slug)
        result = submit(session, owner, computer_id, "update", slug, safe_task_payload(await request.json(), computer_id))
        result["slug"] = cloud_slug
        return result

    @app.post("/api/tasks/{cloud_slug}/{action}", status_code=202)
    def dashboard_action(cloud_slug: str, action: str, owner: Account = Depends(account), session: Session = Depends(db)):
        if action not in ("run", "pause", "resume", "archive"): raise HTTPException(400, "Remote action is not allowed")
        computer_id, slug = split_slug(cloud_slug); return submit(session, owner, computer_id, action, slug)

    @app.post("/api/runs/{cloud_run}/retry", status_code=202)
    async def dashboard_retry(cloud_run: str, request: Request, owner: Account = Depends(account), session: Session = Depends(db)):
        computer_id, run_id = split_slug(cloud_run); body = await request.json()
        return submit(session, owner, computer_id, "retry", payload={"run_id": int(run_id), "minutes": body.get("minutes", 0)})

    static = Path(os.environ.get("ONCUE_STATIC_DIR", "oncue/static")).resolve()
    if static.is_dir():
        @app.get("/")
        def index(): return FileResponse(static / "index.html")
        @app.get("/{asset:path}")
        def asset(asset: str):
            target = (static / asset).resolve()
            if target.is_file() and target.is_relative_to(static): return FileResponse(target)
            return FileResponse(static / "index.html")
    return app
