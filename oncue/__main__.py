"""Command-line entry point."""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .dashboard import serve
from .runner import run_queued_job
from .store import Store
from .tasks import save_task, read_output, queue_manual


from .migration import default_data_dir, migrate_data_dir, worker_unit

DEFAULT_DATA_DIR = default_data_dir()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="oncue")
    root.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    commands = root.add_subparsers(dest="action", required=True)
    commands.add_parser("init")
    for action in ('open','start','stop','install-startup','prepare-update','mcp'):
        commands.add_parser(action)
    launcher=commands.add_parser('install-launcher',help='Add the application menu launcher')
    launcher.add_argument('--prefix',type=Path)
    uninstall=commands.add_parser('uninstall',help='Remove the portable app; retain task history by default')
    uninstall.add_argument('--prefix',type=Path)
    uninstall.add_argument('--purge-data',action='store_true',help='Also permanently delete default task storage, including the separate OnCue login')
    say=commands.add_parser('say',help='Schedule or discuss a task in natural language')
    say.add_argument('text')
    say.add_argument('--task')
    config=commands.add_parser('settings')
    config.add_argument('--set',dest='settings_patch',help='JSON object of non-secret settings')
    task = commands.add_parser("task").add_subparsers(dest="task_action", required=True)
    task_add = task.add_parser("add", help="Schedule a task without registering a project")
    task_add.add_argument("--instructions", required=True)
    task_add.add_argument("--title", default="")
    task_add.add_argument("--model", default=argparse.SUPPRESS)
    task_add.add_argument("--provider", choices=("codex","opencode"), default=argparse.SUPPRESS)
    task_add.add_argument("--mode", choices=("task","monitor"), default="task")
    task_add.add_argument("--condition", default="")
    task_add.add_argument("--frequency", choices=("once", "daily", "weekdays", "weekly", "custom"), default="daily")
    task_add.add_argument("--time", default="09:00")
    task_add.add_argument("--date")
    task_add.add_argument("--weekday", type=int, default=1)
    task_add.add_argument("--cron")
    task_add.add_argument("--timezone", default=argparse.SUPPRESS)
    task_add.add_argument("--paused", action="store_true")
    task_edit = task.add_parser("edit")
    task_edit.add_argument("slug")
    for name in ("instructions", "title", "model", "provider", "mode", "condition", "timezone", "time", "date", "cron"):
        task_edit.add_argument("--" + name, default=argparse.SUPPRESS)
    task_edit.add_argument("--frequency", choices=("once", "daily", "weekdays", "weekly", "custom"), default=argparse.SUPPRESS)
    task_edit.add_argument("--weekday", type=int, default=argparse.SUPPRESS)
    task.add_parser("list")
    for action in ("run", "pause", "resume", "archive", "history"):
        task.add_parser(action).add_argument("slug")
    task_output = task.add_parser("response")
    task_output.add_argument("run_id", type=int)
    task_output.add_argument("--log", action="store_true")
    from .compatibility import add_commands
    add_commands(commands)
    run_due = commands.add_parser("run-due")
    run_due.add_argument("--dispatch", choices=("inline", "systemd"), default="inline")
    run_queued = commands.add_parser("run-queued")
    run_queued.add_argument("run_id", type=int)
    commands.add_parser("status")
    commands.add_parser("doctor")
    dashboard = commands.add_parser("dashboard", help="Serve the local job-management dashboard")
    dashboard.add_argument("--host", default="127.0.0.1", help="Loopback address (default: 127.0.0.1)")
    dashboard.add_argument("--port", default=8765, type=int, help="Local port (default: 8765)")
    return root


def main() -> int:
    args = parser().parse_args(None if len(sys.argv)>1 else ['open'])
    store: Store | None = None
    try:
        if args.action == 'uninstall':
            from .service import uninstall
            print(uninstall(args.data_dir,args.prefix,args.purge_data))
            return 0
        args.data_dir = migrate_data_dir(args.data_dir)
        store = Store(args.data_dir / "scheduler.sqlite3")
        store.initialize()
        if args.action in ('open','start','stop','install-startup','install-launcher','prepare-update'):
            from . import service
            from .migration import migrate_launchers
            if args.action in ("open","start","install-startup"): migrate_launchers()
            if args.action=='stop':service.stop(args.data_dir)
            elif args.action=='prepare-update':service.prepare_update(args.data_dir)
            elif args.action=='install-launcher':print(service.install_launcher(args.data_dir,args.prefix))
            elif args.action=='install-startup':print(service.install_startup(args.data_dir))
            else:print(service.start(args.data_dir,open_window=args.action=='open'))
        elif args.action=='settings':
            import json
            from .settings import get_settings,update_settings
            print(json.dumps(update_settings(store,json.loads(args.settings_patch)) if args.settings_patch else get_settings(store),indent=2))
        elif args.action=='say':
            import json
            from .conversations import queue_message
            from .service import start
            result=queue_message(store,args.task,args.text)
            start(args.data_dir)
            print(json.dumps(result))
        elif args.action=='mcp':
            from .mcp_server import serve as serve_mcp
            serve_mcp(store)
        elif args.action == "init":
            print(f"Initialized {args.data_dir}")
        elif args.action == "task":
            if args.task_action == "add":
                payload = vars(args).copy()
                payload["enabled"] = not args.paused
                print(save_task(store, payload))
            elif args.task_action == "edit":
                payload = {k: v for k, v in vars(args).items() if k not in ("slug", "action", "task_action", "data_dir")}
                if any(k in payload for k in ("frequency", "time", "date", "weekday", "cron")):
                    from .schedules import to_form
                    current = store.job(args.slug)
                    if not current:
                        raise ValueError("Task not found")
                    payload = {"timezone": current["timezone"], **to_form(current["schedule"], current["timezone"]), **payload}
                print(save_task(store, payload, args.slug))
            elif args.task_action == "response":
                print(read_output(store, args.run_id, args.log)["text"])
            elif args.task_action == "list":
                for row in store.jobs():
                    print(f"{row['slug']}  {row['title'] or row['slug']}  {row['schedule']}  {row['timezone']}")
            elif args.task_action == "history":
                for row in store.history(args.slug):
                    print(f"{row['id']}  {row['scheduled_for']}  {row['status']}")
            elif args.task_action == "run":
                result = run_queued_job(store, queue_manual(store,args.slug), args.data_dir)
                print(result)
                return 0 if result == "succeeded" else 1
            else:
                ok = store.archive_job(args.slug) if args.task_action == "archive" else store.set_job_enabled(args.slug, args.task_action == "resume")
                if not ok:
                    raise ValueError("Task not found")
                print("Updated task")
        elif args.action in ('project','connection','job'):
            from .compatibility import dispatch
            return dispatch(store,args)
        elif args.action == "run-due":
            had_failure = False
            from .scheduler import enqueue_due
            queued_ids = enqueue_due(store)
            for run_id in queued_ids:
                if args.dispatch == "inline":
                    result = run_queued_job(store, run_id, args.data_dir)
                    print(f"run {run_id}: {result}")
                    had_failure = had_failure or result not in (
                        "succeeded", "already-claimed", "queued-project-busy"
                    )
                else:
                    dispatched = subprocess.run(
                        ["systemctl", "--user", "start", "--no-block", worker_unit(run_id)],
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
                if row["runner"] == "codex" and not __import__("oncue.providers",fromlist=["executable"]).executable(row["provider"],args.data_dir):
                    problems.append(f"{row['slug']}: provider runtime is not installed")
            if problems:
                print("Issues found:")
                for problem in problems:
                    print(f"- {problem}")
            else:
                print("OK: data directory, registered projects, and job configuration are healthy.")
            return 1 if problems else 0
        elif args.action == "dashboard":
            serve(store, args.host, args.port)
        return 0
    except (ValueError, sqlite3.Error, OSError, subprocess.SubprocessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
