"""SQLite persistence for projects, connections, jobs, and runs."""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
from pathlib import Path

from .validation import validate_slug
from .schedules import validate_schedule


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
        self.path = path
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
        self.connection.execute("CREATE TABLE IF NOT EXISTS scheduler_state (id INTEGER PRIMARY KEY CHECK(id=1), last_tick TEXT NOT NULL)")
        existing_columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(jobs)")}
        for definition in (
            "title TEXT",
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
        columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(runs)")}
        if "response_path" not in columns:
            self.connection.execute("ALTER TABLE runs ADD COLUMN response_path TEXT")
        self.connection.execute("CREATE TABLE IF NOT EXISTS app_settings (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id), role TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '', run_id INTEGER UNIQUE REFERENCES runs(id),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        self.connection.execute("CREATE INDEX IF NOT EXISTS messages_job ON messages(job_id,id)")
        for table, additions in {
            'jobs': ["provider TEXT NOT NULL DEFAULT 'codex'", "task_config TEXT NOT NULL DEFAULT '{}'", "completed_at TEXT"],
            'runs': ["kind TEXT NOT NULL DEFAULT 'task'", "input TEXT", "retry_of INTEGER", "retry_at TEXT",
                     "attempt INTEGER NOT NULL DEFAULT 0", "error_kind TEXT", "provider TEXT", "model TEXT",
                     "config_snapshot TEXT", "cancel_requested INTEGER NOT NULL DEFAULT 0", "notify INTEGER NOT NULL DEFAULT 1"],
        }.items():
            columns = {r['name'] for r in self.connection.execute(f'PRAGMA table_info({table})')}
            for definition in additions:
                if definition.split()[0] not in columns:
                    self.connection.execute(f'ALTER TABLE {table} ADD COLUMN {definition}')
        self.connection.execute("CREATE INDEX IF NOT EXISTS runs_queue ON runs(status,retry_at)")
        # User-facing folders deliberately do not reuse execution projects: the latter
        # own workspaces and locks and must remain stable for existing tasks.
        self.connection.execute("""CREATE TABLE IF NOT EXISTS task_projects (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, instructions TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        project_columns={r['name'] for r in self.connection.execute('PRAGMA table_info(task_projects)')}
        if 'icon' not in project_columns: self.connection.execute("ALTER TABLE task_projects ADD COLUMN icon TEXT NOT NULL DEFAULT ''")
        if 'color' not in project_columns: self.connection.execute("ALTER TABLE task_projects ADD COLUMN color TEXT NOT NULL DEFAULT ''")
        job_columns = {r['name'] for r in self.connection.execute('PRAGMA table_info(jobs)')}
        if 'task_project_id' not in job_columns:
            self.connection.execute('ALTER TABLE jobs ADD COLUMN task_project_id INTEGER REFERENCES task_projects(id)')
        self.connection.execute("""CREATE TABLE IF NOT EXISTS attachments (
            id INTEGER PRIMARY KEY, owner_type TEXT NOT NULL CHECK(owner_type IN ('project','task')),
            owner_id INTEGER NOT NULL, name TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
            path TEXT NOT NULL, size INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            replaced_by INTEGER REFERENCES attachments(id), deleted_at TEXT)""")
        self.connection.execute('CREATE INDEX IF NOT EXISTS attachments_owner ON attachments(owner_type,owner_id,deleted_at)')
        self.connection.execute("""CREATE TABLE IF NOT EXISTS notification_events (
            id TEXT PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES runs(id), event TEXT NOT NULL,
            payload TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS notification_deliveries (
            id INTEGER PRIMARY KEY, event_id TEXT NOT NULL REFERENCES notification_events(id), destination TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('webhook','desktop')), status TEXT NOT NULL DEFAULT 'queued',
            attempt INTEGER NOT NULL DEFAULT 0, retry_at TEXT, error TEXT, delivered_at TEXT,
            UNIQUE(event_id,destination))""")
        self.connection.execute('CREATE INDEX IF NOT EXISTS notification_queue ON notification_deliveries(status,retry_at)')
        self.connection.execute("""INSERT OR IGNORE INTO messages(job_id,role,run_id,created_at)
            SELECT job_id,'assistant',id,COALESCE(finished_at,started_at) FROM runs
            WHERE status IN ('succeeded','failed','timed_out')""")
        self.connection.commit()

    def task_projects(self):
        return self.connection.execute("""SELECT task_projects.*, COUNT(jobs.id) AS task_count
            FROM task_projects LEFT JOIN jobs ON jobs.task_project_id=task_projects.id AND jobs.archived=0
            GROUP BY task_projects.id ORDER BY name COLLATE NOCASE""").fetchall()

    def create_task_project(self, name: str, instructions: str = '', icon: str = '', color: str = ''):
        name = str(name).strip()
        if not name or len(name) > 120: raise ValueError('Project name must be 1 to 120 characters')
        if len(instructions) > 16000: raise ValueError('Project instructions must be at most 16,000 characters')
        icon,color=self._project_identity(icon,color)
        cur=self.connection.execute('INSERT INTO task_projects(name,instructions,icon,color) VALUES (?,?,?,?)',(name,instructions,icon,color));self.connection.commit();return cur.lastrowid

    @staticmethod
    def _project_identity(icon, color):
        icon=str(icon or '').strip()
        color=str(color or '').strip().lower()
        if len(icon)>8: raise ValueError('Project emoji is too long')
        if color and not re.fullmatch(r'#[0-9a-f]{6}',color): raise ValueError('Project color must be a hex color')
        return icon,color

    def update_task_project(self, project_id: int, name=None, instructions=None, icon=None, color=None):
        row=self.connection.execute('SELECT * FROM task_projects WHERE id=?',(project_id,)).fetchone()
        if not row: raise ValueError('Project not found')
        name=row['name'] if name is None else str(name).strip(); instructions=row['instructions'] if instructions is None else str(instructions)
        icon,color=self._project_identity(row['icon'] if icon is None else icon,row['color'] if color is None else color)
        if not name or len(name)>120 or len(instructions)>16000: raise ValueError('Invalid project details')
        self.connection.execute('UPDATE task_projects SET name=?,instructions=?,icon=?,color=? WHERE id=?',(name,instructions,icon,color,project_id));self.connection.commit()

    def delete_task_project(self, project_id: int):
        self.connection.execute('UPDATE jobs SET task_project_id=NULL WHERE task_project_id=?',(project_id,))
        self.connection.execute("UPDATE attachments SET deleted_at=CURRENT_TIMESTAMP WHERE owner_type='project' AND owner_id=? AND deleted_at IS NULL",(project_id,))
        cur=self.connection.execute('DELETE FROM task_projects WHERE id=?',(project_id,));self.connection.commit()
        if not cur.rowcount: raise ValueError('Project not found')

    def set_task_project(self, slug: str, project_id):
        if project_id is not None and not self.connection.execute('SELECT 1 FROM task_projects WHERE id=?',(project_id,)).fetchone(): raise ValueError('Project not found')
        cur=self.connection.execute('UPDATE jobs SET task_project_id=? WHERE slug=?',(project_id,slug));self.connection.commit()
        if not cur.rowcount: raise ValueError('Task not found')

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
        timezone: str, sandbox: str, auto_approve: bool, *, enabled: bool = True, commit: bool = True,
    ) -> None:
        validate_slug(slug, "job slug")
        validate_schedule(schedule, timezone)
        if not command.strip():
            raise ValueError("instructions cannot be empty")
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
                                 runner, model, reasoning_effort, timezone, sandbox, auto_approve, enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (slug, project_id["id"], schedule, command, connection_id, timeout, runner, model,
             reasoning_effort, timezone, sandbox, int(auto_approve), int(enabled)),
        )
        if commit:
            self.connection.commit()

    def update_job(
        self, slug: str, schedule: str, timeout: int, runner: str, model: str | None,
        reasoning_effort: str | None, timezone: str, sandbox: str, auto_approve: bool,
        connection: str | None, enabled: bool, command: str | None = None, *, commit: bool = True,
    ) -> None:
        """Update job configuration while preserving its slug and history."""
        existing = self.job(slug, include_archived=True)
        if not existing:
            raise ValueError(f"unknown job: {slug}")
        validate_schedule(schedule, timezone)
        if existing["runner"] != runner and command is None:
            raise ValueError("Changing runner requires new instructions")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if runner not in ("command", "codex"):
            raise ValueError("runner must be command or codex")
        if runner == "codex" and not model:
            raise ValueError("Codex jobs require a model")
        if runner == "command" and sandbox != "read-only":
            raise ValueError("sandbox selection applies only to Codex jobs")
        if runner == "command" and auto_approve:
            raise ValueError("automatic approval applies only to Codex jobs")
        if auto_approve and sandbox != "workspace-write":
            raise ValueError("automatic approval requires the workspace-write sandbox")
        connection_id = None
        if connection:
            row = self.connection.execute("SELECT id FROM connections WHERE slug = ?", (connection,)).fetchone()
            if not row:
                raise ValueError(f"unknown connection: {connection}")
            connection_id = row["id"]
        fields = [
            "schedule = ?", "timeout_seconds = ?", "runner = ?", "model = ?",
            "reasoning_effort = ?", "timezone = ?", "sandbox = ?", "auto_approve = ?",
            "connection_id = ?", "enabled = ?",
        ]
        values: list[object] = [schedule, timeout, runner, model, reasoning_effort, timezone,
                                sandbox, int(auto_approve), connection_id, int(enabled)]
        if command is not None:
            if not command.strip():
                raise ValueError("command cannot be empty")
            fields.append("command = ?")
            values.append(command)
        values.append(slug)
        self.connection.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE slug = ?", values)
        if not enabled:
            self._skip_queued_runs(slug, "job paused before execution")
        if commit:
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
        """Operational job data safe to present in the local dashboard."""
        return self.connection.execute(
            """SELECT jobs.slug, jobs.title, projects.slug AS project_slug, task_projects.name AS task_project_name, jobs.task_project_id, jobs.schedule, jobs.enabled, jobs.archived,
                      jobs.runner, jobs.model, jobs.reasoning_effort, jobs.timezone, jobs.sandbox, jobs.auto_approve,
                      jobs.timeout_seconds, connections.slug AS connection_slug,
                      runs.status AS last_status, runs.finished_at AS last_finished_at
               FROM jobs JOIN projects ON projects.id = jobs.project_id
               LEFT JOIN task_projects ON task_projects.id = jobs.task_project_id
               LEFT JOIN connections ON connections.id = jobs.connection_id
               LEFT JOIN runs ON runs.id = (SELECT id FROM runs WHERE job_id = jobs.id ORDER BY id DESC LIMIT 1)
               ORDER BY jobs.archived, jobs.slug"""
        ).fetchall()

    def recent_runs(self, limit: int):
        """Recent run metadata, deliberately excluding output paths and error contents."""
        return self.connection.execute(
            """SELECT runs.id, jobs.slug AS job, runs.scheduled_for, runs.started_at, runs.finished_at,
                      runs.status, runs.exit_code, runs.notify
               FROM runs JOIN jobs ON jobs.id = runs.job_id
               ORDER BY runs.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()

    def job(self, slug: str, include_archived: bool = False):
        archived_filter = "" if include_archived else "AND jobs.archived = 0"
        return self.connection.execute(
            """SELECT jobs.*, projects.slug AS project_slug, projects.path AS project_path, task_projects.name AS task_project_name,
                      connections.slug AS connection_slug, connections.kind AS connection_kind
               FROM jobs JOIN projects ON projects.id = jobs.project_id
               LEFT JOIN task_projects ON task_projects.id = jobs.task_project_id
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

    def delete_job(self, slug: str) -> bool:
        """Permanently remove one task and its retained files after explicit UI/CLI action."""
        job = self.job(slug, include_archived=True)
        if not job:
            return False
        run_ids = [row['id'] for row in self.connection.execute('SELECT id FROM runs WHERE job_id=?',(job['id'],))]
        attachment_paths = [row['path'] for row in self.connection.execute("SELECT path FROM attachments WHERE owner_type='task' AND owner_id=?",(job['id'],))]
        with self.connection:
            if run_ids:
                marks=','.join('?' for _ in run_ids)
                event_ids=[row['id'] for row in self.connection.execute(f'SELECT id FROM notification_events WHERE run_id IN ({marks})',run_ids)]
                if event_ids:
                    event_marks=','.join('?' for _ in event_ids)
                    self.connection.execute(f'DELETE FROM notification_deliveries WHERE event_id IN ({event_marks})',event_ids)
                    self.connection.execute(f'DELETE FROM notification_events WHERE id IN ({event_marks})',event_ids)
            self.connection.execute('DELETE FROM messages WHERE job_id=?',(job['id'],))
            self.connection.execute('DELETE FROM runs WHERE job_id=?',(job['id'],))
            self.connection.execute("DELETE FROM attachments WHERE owner_type='task' AND owner_id=?",(job['id'],))
            self.connection.execute('DELETE FROM jobs WHERE id=?',(job['id'],))
            remaining=self.connection.execute('SELECT 1 FROM jobs WHERE project_id=?',(job['project_id'],)).fetchone()
            if not remaining: self.connection.execute('DELETE FROM projects WHERE id=?',(job['project_id'],))
        attachments_root=(self.path.parent/'attachments').resolve()
        for raw in attachment_paths:
            path=Path(raw).resolve()
            if path.is_relative_to(attachments_root):
                try:path.unlink()
                except FileNotFoundError:pass
        for root in (self.path.parent/'runs'/slug, Path(job['project_path'])):
            managed=(self.path.parent/('runs' if root.name==slug and root.parent.name=='runs' else 'workspaces')).resolve()
            resolved=root.resolve()
            if resolved.is_relative_to(managed) and resolved.is_dir(): shutil.rmtree(resolved)
        return True

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
            self.connection.rollback()
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
            self.connection.rollback()
            return None

    def queued_runs(self):
        return self.connection.execute(
            "SELECT id FROM runs WHERE status = 'queued' AND (retry_at IS NULL OR julianday(retry_at)<=julianday('now')) ORDER BY id"
        ).fetchall()

    def claim_queued_run(self, run_id: int, process_id: int, process_start_ticks: int | None):
        """Atomically move one queued occurrence into a worker process."""
        cursor = self.connection.execute(
            """UPDATE runs SET status = 'running', started_at = CURRENT_TIMESTAMP, process_id = ?,
                   process_start_ticks = ?, error = NULL
               WHERE id = ? AND status = 'queued' AND (retry_at IS NULL OR julianday(retry_at)<=julianday('now'))
                 AND EXISTS (
                   SELECT 1 FROM jobs
                   WHERE jobs.id = runs.job_id AND (jobs.enabled = 1 OR runs.kind IN ('chat','plan') OR runs.scheduled_for LIKE 'manual:%' OR runs.scheduled_for LIKE 'retry:manual:%') AND jobs.archived = 0
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
            """UPDATE runs SET status = CASE WHEN EXISTS (
                   SELECT 1 FROM jobs WHERE jobs.id = runs.job_id AND (jobs.enabled = 1 OR runs.kind IN ('plan','chat')) AND jobs.archived = 0
               ) THEN 'queued' ELSE 'skipped' END,
               finished_at = CASE WHEN EXISTS (
                   SELECT 1 FROM jobs WHERE jobs.id = runs.job_id AND (jobs.enabled = 1 OR runs.kind IN ('plan','chat')) AND jobs.archived = 0
               ) THEN NULL ELSE CURRENT_TIMESTAMP END,
               process_id = NULL, process_start_ticks = NULL, error = ?
               WHERE id = ? AND status = 'running'""",
            (reason, run_id),
        )
        self.connection.commit()

    def run_job(self, run_id: int):
        return self.connection.execute(
            """SELECT jobs.*, projects.slug AS project_slug, projects.path AS project_path, task_projects.name AS task_project_name,
                      connections.slug AS connection_slug, connections.kind AS connection_kind,
                      runs.scheduled_for AS run_scheduled_for
               FROM runs JOIN jobs ON jobs.id = runs.job_id
               JOIN projects ON projects.id = jobs.project_id
               LEFT JOIN task_projects ON task_projects.id = jobs.task_project_id
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
