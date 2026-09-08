"""Command-line entry point."""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .cron import matches
from .runner import run_job, run_queued_job, scheduler_lock
from .store import Store


DEFAULT_DATA_DIR = Path(
    os.environ.get("CODEX_LOCAL_SCHEDULER_DATA", Path.home() / ".local" / "share" / "codex-local-scheduler")
)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="codex-local-scheduler")
    root.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    commands = root.add_subparsers(dest="action", required=True)
    commands.add_parser("init")
    project = commands.add_parser("project").add_subparsers(dest="project_action", required=True)
    project_add = project.add_parser("add")
    project_add.add_argument("slug")
    project_add.add_argument("path", type=Path)
    connection = commands.add_parser("connection").add_subparsers(dest="connection_action", required=True)
    connection_add = connection.add_parser("add")
    connection_add.add_argument("slug")
    connection_add.add_argument("kind")
    job = commands.add_parser("job").add_subparsers(dest="job_action", required=True)
    job_add = job.add_parser("add")
    job_add.add_argument("slug")
    job_add.add_argument("project")
    job_add.add_argument("schedule")
    job_add.add_argument("--command", required=True, help="Shell command, or Codex prompt with --runner codex")
    job_add.add_argument("--connection")
    job_add.add_argument("--timeout", type=int, default=1800)
    job_add.add_argument("--runner", choices=("command", "codex"), default="command")
    job_add.add_argument("--model")
    job_add.add_argument("--effort", choices=("minimal", "low", "medium", "high", "xhigh", "max", "ultra"))
    job_add.add_argument("--timezone", default="America/Chicago", help="IANA timezone, e.g. America/Chicago")
    job_add.add_argument("--sandbox", choices=("read-only", "workspace-write"), default="read-only")
    job_add.add_argument("--auto-approve", action="store_true", help="Allow Codex to act without interactive approvals")
    job_pause = job.add_parser("pause"); job_pause.add_argument("slug")
    job_resume = job.add_parser("resume"); job_resume.add_argument("slug")
    job_remove = job.add_parser("remove"); job_remove.add_argument("slug")
    job_run = job.add_parser("run"); job_run.add_argument("slug")
    job_history = job.add_parser("history"); job_history.add_argument("slug"); job_history.add_argument("--limit", type=int, default=20)
    job_list = job.add_parser("list")
    job_list.add_argument("--all", action="store_true", help="Include archived jobs")
    run_due = commands.add_parser("run-due")
    run_due.add_argument("--dispatch", choices=("inline", "systemd"), default="inline")
    run_queued = commands.add_parser("run-queued")
    run_queued.add_argument("run_id", type=int)
    commands.add_parser("status")
    commands.add_parser("doctor")
    return root


def main() -> int:
    args = parser().parse_args()
    store: Store | None = None
    try:
        store = Store(args.data_dir / "scheduler.sqlite3")
        store.initialize()
        if args.action == "init":
            print(f"Initialized {args.data_dir}")
        elif args.action == "project":
            store.add_project(args.slug, args.path)
            print(f"Added project {args.slug}")
        elif args.action == "connection":
            store.add_connection(args.slug, args.kind)
            print(f"Added connection reference {args.slug}")
        elif args.action == "job":
            if args.job_action == "add":
                ZoneInfo(args.timezone)  # validate before persistence
                matches(args.schedule, datetime.now())
                store.add_job(args.slug, args.project, args.schedule, args.command, args.connection,
                              args.timeout, args.runner, args.model, args.effort, args.timezone,
                              args.sandbox, args.auto_approve)
                print(f"Added job {args.slug}")
            elif args.job_action in ("pause", "resume"):
                if not store.set_job_enabled(args.slug, args.job_action == "resume"):
                    raise ValueError(f"unknown job: {args.slug}")
                print(f"{args.job_action.title()}d job {args.slug}")
            elif args.job_action == "remove":
                if not store.archive_job(args.slug):
                    raise ValueError(f"unknown job: {args.slug}")
                print(f"Archived job {args.slug}; its run history remains available.")
            elif args.job_action == "run":
                row = store.job(args.slug)
                if not row:
                    raise ValueError(f"unknown job: {args.slug}")
                result = run_job(store, row, args.data_dir, datetime.now(timezone.utc), manual=True)
                print(f"{args.slug}: {result}")
                return 0 if result == "succeeded" else 1
            elif args.job_action == "history":
                for row in store.history(args.slug, args.limit):
                    print(f"{row['scheduled_for']}  {row['status']}  exit={row['exit_code']}  {row['output_path'] or ''}")
            else:
                for row in store.jobs(include_archived=args.all):
                    state = "archived" if row["archived"] else ("enabled" if row["enabled"] else "paused")
                    print(f"{row['slug']}  {state}  {row['schedule']}  {row['timezone']}")
        elif args.action == "run-due":
            had_failure = False
            queued_ids: list[int] = []
            with scheduler_lock(args.data_dir) as acquired:
                if not acquired:
                    print("Another scheduler tick is already active.")
                    return 0
                recovered = store.recover_interrupted_runs()
                if recovered:
                    print(f"Recovered {recovered} interrupted run(s).")
                now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
                for job in store.jobs():
                    if not job["enabled"]:
                        continue
                    try:
                        due = matches(job["schedule"], now.astimezone(ZoneInfo(job["timezone"])))
                    except ValueError as error:
                        print(f"{job['slug']}: invalid schedule or timezone: {error}", file=sys.stderr)
                        had_failure = True
                        continue
                    if due:
                        scheduled_key = now.isoformat()
                        run_id = store.queue_run(job["id"], scheduled_key)
                        if run_id:
                            print(f"{job['slug']}: queued")
                queued_ids = [row["id"] for row in store.queued_runs()]
            for run_id in queued_ids:
                if args.dispatch == "inline":
                    result = run_queued_job(store, run_id, args.data_dir)
                    print(f"run {run_id}: {result}")
                    had_failure = had_failure or result not in (
                        "succeeded", "already-claimed", "queued-project-busy"
                    )
                else:
                    dispatched = subprocess.run(
                        ["systemctl", "--user", "start", "--no-block", f"codex-local-scheduler-worker@{run_id}.service"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if dispatched.returncode:
                        detail = dispatched.stderr.strip() or dispatched.stdout.strip() or "systemctl dispatch failed"
                        print(f"run {run_id}: could not dispatch worker: {detail}", file=sys.stderr)
                        had_failure = True
            return 1 if had_failure else 0
        elif args.action == "run-queued":
            result = run_queued_job(store, args.run_id, args.data_dir)
            print(f"run {args.run_id}: {result}")
            return 0 if result in ("succeeded", "already-claimed", "queued-project-busy") else 1
        elif args.action == "status":
            for row in store.status():
                state = "enabled" if row["enabled"] else "paused"
                model = f"  {row['model']}:{row['reasoning_effort'] or 'default'}" if row["runner"] == "codex" else ""
                print(f"{row['slug']}  {state}  {row['schedule']}  {row['timezone']}  {row['runner']}{model}  last={row['last_status'] or 'never'}")
        elif args.action == "doctor":
            problems = []
            if not os.access(args.data_dir, os.W_OK):
                problems.append(f"data directory is not writable: {args.data_dir}")
            for row in store.jobs():
                if not Path(row["project_path"]).is_dir():
                    problems.append(f"{row['slug']}: project directory is missing")
                try:
                    ZoneInfo(row["timezone"])
                except Exception:
                    problems.append(f"{row['slug']}: invalid timezone {row['timezone']}")
                if row["runner"] == "codex" and not row["model"]:
                    problems.append(f"{row['slug']}: Codex job has no model")
                if row["runner"] == "codex" and not shutil.which("codex"):
                    problems.append(f"{row['slug']}: Codex executable is not on PATH")
            if problems:
                print("Issues found:")
                for problem in problems:
                    print(f"- {problem}")
            else:
                print("OK: data directory, registered projects, and job configuration are healthy.")
        return 0
    except (ValueError, sqlite3.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
