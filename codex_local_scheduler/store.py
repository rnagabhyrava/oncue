"""SQLite persistence for projects, connections, jobs, and runs."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .validation import validate_slug


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  path TEXT UNIQUE NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS connections (
  id INTEGER PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  kind TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  project_id INTEGER NOT NULL REFERENCES projects(id),
  schedule TEXT NOT NULL,
  command TEXT NOT NULL,
  runner TEXT NOT NULL DEFAULT 'command' CHECK(runner IN ('command', 'codex')),
  model TEXT,
  reasoning_effort TEXT,
  timezone TEXT NOT NULL DEFAULT 'America/Chicago',
  sandbox TEXT NOT NULL DEFAULT 'read-only' CHECK(sandbox IN ('read-only', 'workspace-write')),
  auto_approve INTEGER NOT NULL DEFAULT 0 CHECK(auto_approve IN (0, 1)),
  connection_id INTEGER REFERENCES connections(id),
  enabled INTEGER NOT NULL DEFAULT 1,
  archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0, 1)),
  timeout_seconds INTEGER NOT NULL DEFAULT 1800,
  last_scheduled_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  job_id INTEGER NOT NULL REFERENCES jobs(id),
  scheduled_for TEXT NOT NULL,
  started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT,
  status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'succeeded', 'failed', 'timed_out', 'skipped')),
  process_id INTEGER,
  process_start_ticks INTEGER,
  exit_code INTEGER,
  output_path TEXT,
  error TEXT,
  UNIQUE(job_id, scheduled_for)
);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        self.connection = sqlite3.connect(path, timeout=10)
        os.chmod(path, 0o600)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA busy_timeout = 10000")

    def close(self) -> None:
        self.connection.close()

    def initialize(self) -> None:
        self.connection.executescript(SCHEMA)
        existing_columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(jobs)")}
        for definition in (
            "runner TEXT NOT NULL DEFAULT 'command'",
            "model TEXT",
            "reasoning_effort TEXT",
            "timezone TEXT NOT NULL DEFAULT 'America/Chicago'",
            "sandbox TEXT NOT NULL DEFAULT 'read-only'",
            "auto_approve INTEGER NOT NULL DEFAULT 0",
            "archived INTEGER NOT NULL DEFAULT 0",
        ):
            column = definition.split()[0]
            if column not in existing_columns:
                self.connection.execute(f"ALTER TABLE jobs ADD COLUMN {definition}")
        existing_run_columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(runs)")}
        if "process_id" not in existing_run_columns:
            self.connection.execute("ALTER TABLE runs ADD COLUMN process_id INTEGER")
        if "process_start_ticks" not in existing_run_columns:
            self.connection.execute("ALTER TABLE runs ADD COLUMN process_start_ticks INTEGER")
        run_schema = self.connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'runs'"
        ).fetchone()["sql"].lower()
        if "'queued'" not in run_schema:
            self._migrate_runs_for_queue()
        self.connection.commit()

    def _migrate_runs_for_queue(self) -> None:
        """Upgrade the immutable run-status constraint without losing history."""
        self.connection.executescript(
            """
            CREATE TABLE runs_new (
              id INTEGER PRIMARY KEY,
              job_id INTEGER NOT NULL REFERENCES jobs(id),
              scheduled_for TEXT NOT NULL,
              started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              finished_at TEXT,
              status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'succeeded', 'failed', 'timed_out', 'skipped')),
              process_id INTEGER,
              process_start_ticks INTEGER,
              exit_code INTEGER,
              output_path TEXT,
              error TEXT,
              UNIQUE(job_id, scheduled_for)
            );
            INSERT INTO runs_new(id, job_id, scheduled_for, started_at, finished_at, status, process_id, process_start_ticks, exit_code, output_path, error)
            SELECT id, job_id, scheduled_for, started_at, finished_at, status, process_id, process_start_ticks, exit_code, output_path, error FROM runs;
            DROP TABLE runs;
            ALTER TABLE runs_new RENAME TO runs;
            """
        )

    def add_project(self, slug: str, path: Path) -> None:
        validate_slug(slug, "project slug")
        if not path.is_dir():
            raise ValueError(f"project directory does not exist: {path}")
        self.connection.execute("INSERT INTO projects(slug, path) VALUES (?, ?)", (slug, str(path.resolve())))
        self.connection.commit()

    def add_connection(self, slug: str, kind: str) -> None:
        validate_slug(slug, "connection slug")
        self.connection.execute("INSERT INTO connections(slug, kind) VALUES (?, ?)", (slug, kind))
        self.connection.commit()

    def add_job(
        self, slug: str, project: str, schedule: str, command: str, connection: str | None,
        timeout: int, runner: str, model: str | None, reasoning_effort: str | None,
        timezone: str, sandbox: str, auto_approve: bool,
    ) -> None:
        validate_slug(slug, "job slug")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        project_id = self.connection.execute("SELECT id FROM projects WHERE slug = ?", (project,)).fetchone()
        if not project_id:
            raise ValueError(f"unknown project: {project}")
        connection_id = None
        if connection:
            row = self.connection.execute("SELECT id FROM connections WHERE slug = ?", (connection,)).fetchone()
            if not row:
                raise ValueError(f"unknown connection: {connection}")
            connection_id = row["id"]
        if runner == "codex" and not model:
            raise ValueError("Codex jobs require a model")
        if runner == "command" and sandbox != "read-only":
            raise ValueError("sandbox selection applies only to Codex jobs")
        if runner == "command" and auto_approve:
            raise ValueError("automatic approval applies only to Codex jobs")
        if auto_approve and sandbox != "workspace-write":
            raise ValueError("automatic approval requires the workspace-write sandbox")
        self.connection.execute(
            """INSERT INTO jobs(slug, project_id, schedule, command, connection_id, timeout_seconds,
                                 runner, model, reasoning_effort, timezone, sandbox, auto_approve)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (slug, project_id["id"], schedule, command, connection_id, timeout, runner, model,
             reasoning_effort, timezone, sandbox, int(auto_approve)),
        )
        self.connection.commit()

    def jobs(self, include_archived: bool = False):
        archived_filter = "" if include_archived else "WHERE jobs.archived = 0"
        return self.connection.execute(
            """SELECT jobs.*, projects.slug AS project_slug, projects.path AS project_path,
                      connections.slug AS connection_slug, connections.kind AS connection_kind
               FROM jobs JOIN projects ON projects.id = jobs.project_id
               LEFT JOIN connections ON connections.id = jobs.connection_id """ + archived_filter + " ORDER BY jobs.slug"
        ).fetchall()

    def status(self):
        return self.connection.execute(
            """SELECT jobs.slug, projects.slug AS project_slug, jobs.schedule, jobs.enabled, jobs.runner,
                      jobs.model, jobs.reasoning_effort, jobs.timezone, jobs.sandbox, jobs.auto_approve,
                      runs.status AS last_status, runs.finished_at AS last_finished_at
               FROM jobs JOIN projects ON projects.id = jobs.project_id
               LEFT JOIN runs ON runs.id = (SELECT id FROM runs WHERE job_id = jobs.id ORDER BY id DESC LIMIT 1)
               WHERE jobs.archived = 0
               ORDER BY jobs.slug"""
        ).fetchall()

    def dashboard_jobs(self):
        """Operational job data safe to present in the local read-only dashboard."""
        return self.connection.execute(
            """SELECT jobs.slug, projects.slug AS project_slug, jobs.schedule, jobs.enabled, jobs.archived,
                      jobs.runner, jobs.model, jobs.timezone, runs.status AS last_status
               FROM jobs JOIN projects ON projects.id = jobs.project_id
               LEFT JOIN runs ON runs.id = (SELECT id FROM runs WHERE job_id = jobs.id ORDER BY id DESC LIMIT 1)
               ORDER BY jobs.archived, jobs.slug"""
        ).fetchall()

    def recent_runs(self, limit: int):
        """Recent run metadata, deliberately excluding output paths and error contents."""
        return self.connection.execute(
            """SELECT jobs.slug AS job, runs.scheduled_for, runs.started_at, runs.finished_at,
                      runs.status, runs.exit_code
               FROM runs JOIN jobs ON jobs.id = runs.job_id
               ORDER BY runs.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()

    def job(self, slug: str, include_archived: bool = False):
        archived_filter = "" if include_archived else "AND jobs.archived = 0"
        return self.connection.execute(
            """SELECT jobs.*, projects.slug AS project_slug, projects.path AS project_path,
                      connections.slug AS connection_slug, connections.kind AS connection_kind
               FROM jobs JOIN projects ON projects.id = jobs.project_id
               LEFT JOIN connections ON connections.id = jobs.connection_id
               WHERE jobs.slug = ? """ + archived_filter,
            (slug,),
        ).fetchone()

    def set_job_enabled(self, slug: str, enabled: bool) -> bool:
        cursor = self.connection.execute(
            "UPDATE jobs SET enabled = ? WHERE slug = ? AND archived = 0", (int(enabled), slug)
        )
        if cursor.rowcount == 1 and not enabled:
            self._skip_queued_runs(slug, "job paused before execution")
        self.connection.commit()
        return cursor.rowcount == 1

    def archive_job(self, slug: str) -> bool:
        """Hide a job from scheduling while retaining its immutable run history."""
        cursor = self.connection.execute(
            "UPDATE jobs SET enabled = 0, archived = 1 WHERE slug = ? AND archived = 0", (slug,)
        )
        if cursor.rowcount == 1:
            self._skip_queued_runs(slug, "job archived before execution")
        self.connection.commit()
        return cursor.rowcount == 1

    def _skip_queued_runs(self, slug: str, reason: str) -> None:
        """Close unclaimed work when a job is paused or archived."""
        self.connection.execute(
            """UPDATE runs SET status = 'skipped', finished_at = CURRENT_TIMESTAMP, error = ?
               WHERE status = 'queued' AND job_id = (SELECT id FROM jobs WHERE slug = ?)""",
            (reason, slug),
        )

    def history(self, slug: str, limit: int = 20):
        return self.connection.execute(
            """SELECT runs.* FROM runs JOIN jobs ON jobs.id = runs.job_id
               WHERE jobs.slug = ? ORDER BY runs.id DESC LIMIT ?""",
            (slug, limit),
        ).fetchall()

    def recover_interrupted_runs(self) -> int:
        """Close runs left active after an interrupted scheduler process."""
        interrupted_ids = []
        for row in self.connection.execute("SELECT id, process_id, process_start_ticks FROM runs WHERE status = 'running'"):
            if not _process_is_alive(row["process_id"], row["process_start_ticks"]):
                interrupted_ids.append(row["id"])
        if interrupted_ids:
            placeholders = ", ".join("?" for _ in interrupted_ids)
            cursor = self.connection.execute(
                f"""UPDATE runs SET finished_at = CURRENT_TIMESTAMP, status = 'failed',
                       error = COALESCE(error, 'scheduler process ended before run completion')
                   WHERE id IN ({placeholders})""",
                interrupted_ids,
            )
        else:
            cursor = _EmptyCursor()
        self.connection.commit()
        return cursor.rowcount

    def start_run(
        self, job_id: int, scheduled_for: str, process_id: int | None = None, process_start_ticks: int | None = None
    ) -> int | None:
        try:
            cursor = self.connection.execute(
                """INSERT INTO runs(job_id, scheduled_for, status, process_id, process_start_ticks)
                   VALUES (?, ?, 'running', ?, ?)""",
                (job_id, scheduled_for, process_id, process_start_ticks),
            )
            self.connection.execute("UPDATE jobs SET last_scheduled_at = ? WHERE id = ?", (scheduled_for, job_id))
            self.connection.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            return None

    def queue_run(self, job_id: int, scheduled_for: str) -> int | None:
        """Persist a due occurrence before an executor claims it."""
        try:
            cursor = self.connection.execute(
                "INSERT INTO runs(job_id, scheduled_for, status) VALUES (?, ?, 'queued')", (job_id, scheduled_for)
            )
            self.connection.execute("UPDATE jobs SET last_scheduled_at = ? WHERE id = ?", (scheduled_for, job_id))
            self.connection.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            return None

    def queued_runs(self):
        return self.connection.execute(
            "SELECT id FROM runs WHERE status = 'queued' ORDER BY id"
        ).fetchall()

    def claim_queued_run(self, run_id: int, process_id: int, process_start_ticks: int | None):
        """Atomically move one queued occurrence into a worker process."""
        cursor = self.connection.execute(
            """UPDATE runs SET status = 'running', started_at = CURRENT_TIMESTAMP, process_id = ?,
                   process_start_ticks = ?, error = NULL
               WHERE id = ? AND status = 'queued'
                 AND EXISTS (
                   SELECT 1 FROM jobs
                   WHERE jobs.id = runs.job_id AND jobs.enabled = 1 AND jobs.archived = 0
                 )""",
            (process_id, process_start_ticks, run_id),
        )
        self.connection.commit()
        if cursor.rowcount != 1:
            return None
        return self.run_job(run_id)

    def release_run(self, run_id: int, reason: str) -> None:
        """Return a claimed run to the queue when its project is busy."""
        self.connection.execute(
            """UPDATE runs SET status = 'queued', process_id = NULL, process_start_ticks = NULL, error = ?
               WHERE id = ? AND status = 'running'""",
            (reason, run_id),
        )
        self.connection.commit()

    def run_job(self, run_id: int):
        return self.connection.execute(
            """SELECT jobs.*, projects.slug AS project_slug, projects.path AS project_path,
                      connections.slug AS connection_slug, connections.kind AS connection_kind,
                      runs.scheduled_for AS run_scheduled_for
               FROM runs JOIN jobs ON jobs.id = runs.job_id
               JOIN projects ON projects.id = jobs.project_id
               LEFT JOIN connections ON connections.id = jobs.connection_id
               WHERE runs.id = ?""",
            (run_id,),
        ).fetchone()

    def finish_run(self, run_id: int, status: str, exit_code: int | None, output_path: str, error: str | None = None) -> None:
        self.connection.execute(
            "UPDATE runs SET finished_at = CURRENT_TIMESTAMP, status = ?, exit_code = ?, output_path = ?, error = ? WHERE id = ?",
            (status, exit_code, output_path, error, run_id),
        )
        self.connection.commit()


class _EmptyCursor:
    rowcount = 0


def process_start_ticks(process_id: int) -> int | None:
    """Return Linux's process start marker, which protects against PID reuse."""
    try:
        return int(Path(f"/proc/{process_id}/stat").read_text().split()[21])
    except (FileNotFoundError, IndexError, ValueError):
        return None


def _process_is_alive(process_id: int | None, expected_start_ticks: int | None) -> bool:
    if not process_id or process_id <= 0:
        return False
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    actual_start_ticks = process_start_ticks(process_id)
    if actual_start_ticks is None:
        return False
    if expected_start_ticks is not None and actual_start_ticks != expected_start_ticks:
        return False
    try:
        return Path(f"/proc/{process_id}/stat").read_text().split()[2] != "Z"
    except FileNotFoundError:
        return False
