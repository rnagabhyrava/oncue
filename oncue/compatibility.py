"""Compatibility CLI for existing installations; new workflows use task/say/MCP.

Kept to preserve public command paths, registered workspaces and existing timers.
No connection adapter or project-first onboarding is implemented here.
"""
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .cron import matches
from .runner import run_job

def add_commands(commands):
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


def dispatch(store,args):
    if args.action == "project":
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
    return 0
