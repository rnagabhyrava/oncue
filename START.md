# Start here

This guide gets Codex Local Scheduler running from a fresh clone. It is also the
entry point for agents making changes to this repository.

## Requirements

- Linux with a user-level systemd manager for persistent schedules.
- Python 3.11 or later with `pip`.
- Codex on `PATH` only when using `--runner codex` jobs.

The scheduler has no third-party runtime dependencies. Packaging uses
setuptools only when installing or building a release.

## Install from a clone

```bash
git clone https://github.com/rnagabhyrava/codex-local-scheduler.git
cd codex-local-scheduler
python3 -m pip install --user .
codex-local-scheduler --help
```

Ensure `~/.local/bin` is on your shell `PATH`. The user-level systemd templates
use this same installed command, so the clone may live anywhere.

For development without installation, run commands as `python3 -m codex_local_scheduler`.
For release tooling, install the optional development dependency with
`python3 -m pip install --user '.[dev]'`.

For an isolated installation instead, use a virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/codex-local-scheduler --help
```

When using this option with systemd, set `PATH` in the environment file below
to include the absolute `.venv/bin` directory.

## Prove the demo workflow

Use a temporary data directory so the demo does not touch your normal jobs:

```bash
demo_data=$(mktemp -d)
codex-local-scheduler --data-dir "$demo_data" init
codex-local-scheduler --data-dir "$demo_data" project add demo examples/demo-project
codex-local-scheduler --data-dir "$demo_data" job add daily-status demo "* * * * *" --command "./scripts/daily-status.sh"
codex-local-scheduler --data-dir "$demo_data" run-due
codex-local-scheduler --data-dir "$demo_data" job history daily-status
```

The job should succeed and create a report beneath the demo project. Inspect
the log path printed by `job history` before scheduling real work.

## Enable persistent schedules

After a real job has passed a manual run:

```bash
loginctl enable-linger "$USER"
mkdir -p ~/.config/systemd/user
cp systemd/codex-local-scheduler.service systemd/codex-local-scheduler.timer systemd/codex-local-scheduler-worker@.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now codex-local-scheduler.timer
systemctl --user list-timers codex-local-scheduler.timer
```

The timer records due work once per minute. Individual worker services execute
the queued runs. If Codex is installed outside `~/.local/bin`, create
`~/.config/codex-local-scheduler/environment` from
[`systemd/environment.example`](systemd/environment.example) with a `PATH=`
that includes its directory.

Use `systemctl --user status 'codex-local-scheduler-worker@*'` and
`journalctl --user -u 'codex-local-scheduler-worker@*'` to inspect asynchronous
job failures.

## For agents and contributors

Read [AGENTS.md](AGENTS.md) before changing code. The important constraints are
preserving SQLite migrations, keeping `run-due` idempotent for each scheduled
minute, and never storing credentials in the project, database, or logs.

Run this before opening a pull request:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q codex_local_scheduler
python3 -m build
```

Use [CONTRIBUTING.md](CONTRIBUTING.md) for the project workflow and
[SECURITY.md](SECURITY.md) for vulnerability reporting.
