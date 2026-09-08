# Codex Local Scheduler

An always-on, local-first scheduler for project workflows. It stores projects,
connections, jobs, and run history in SQLite and runs command or Codex jobs from
the relevant project directory.

> **Linux / systemd · Alpha** — review command jobs before scheduling them.

See [START.md](START.md) for a complete first-run and contributor guide.

## Quick start

```bash
python3 -m pip install --user .
codex-local-scheduler init
codex-local-scheduler project add alpha /home/you/Projects/alpha
codex-local-scheduler connection add work-drive google-drive
codex-local-scheduler job add weekly-update alpha "0 16 * * 5" --command "./scripts/weekly-update.sh" --connection work-drive
codex-local-scheduler job add alpha-review alpha "0 9 * * 1" --runner codex --model gpt-5.6-terra --effort medium --sandbox workspace-write --auto-approve --command "Review last week's project changes and save a concise status report in reports/."
codex-local-scheduler run-due
codex-local-scheduler status
```

Run the scheduler every minute with a user-level systemd timer once the first
workflow is verified. The scheduler itself does not store credentials; a job
inherits only the environment explicitly provided to its runner.

Templates live in [`systemd/`](systemd/). They run the installed
`codex-local-scheduler` command through the service `PATH`, so the checkout can live
anywhere.
This is intentionally left as an explicit operational step until the first real
workflow has passed its manual test.

For a computer that must continue running jobs after you log out, enable the
user manager's lingering once:

```bash
loginctl enable-linger "$USER"
mkdir -p ~/.config/systemd/user
cp systemd/codex-local-scheduler.service systemd/codex-local-scheduler.timer systemd/codex-local-scheduler-worker@.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now codex-local-scheduler.timer
systemctl --user list-timers codex-local-scheduler.timer
```

The service runs with a private log-friendly umask (`0077`). If the `codex`
binary is outside the standard user path, create
`~/.config/codex-local-scheduler/environment` from
[`systemd/environment.example`](systemd/environment.example) with a suitable
`PATH=/...` value.
Keep the computer powered and connected to the internet for Codex jobs;
command-only jobs can run offline.

## Operating jobs

Each job has a timezone (default: `America/Chicago`), timeout, runner, and
Codex sandbox setting. Codex jobs default to `read-only`; choose
`--sandbox workspace-write --auto-approve` only for a workflow you trust to
edit its registered project without a person present.

```bash
codex-local-scheduler job list
codex-local-scheduler job pause alpha-review
codex-local-scheduler job resume alpha-review
codex-local-scheduler job run alpha-review
codex-local-scheduler job history alpha-review
codex-local-scheduler doctor
codex-local-scheduler dashboard
```

`job run` is an explicit manual run and is recorded independently of the
scheduled occurrence. Output is streamed to
`$CODEX_LOCAL_SCHEDULER_DATA/runs/<job>/`, so a verbose job cannot exhaust scheduler
memory. A timeout stops the whole child process group and is persisted as a
completed `timed_out` run. On the next exclusive scheduler tick, an abandoned
`running` record is closed as failed instead of remaining stuck forever.

`job remove` archives a job instead of deleting it. Archived jobs stop running
but retain their history; use `job list --all` and `job history <slug>` to
inspect them. A failed manual run or due job exits non-zero, so systemd and
other callers can surface the failure.

Pausing or archiving a job cancels any queued runs that have not started. A
worker already running continues to its normal terminal state.

## Local dashboard

Run `codex-local-scheduler dashboard` and open
[`http://127.0.0.1:8765/`](http://127.0.0.1:8765/) to see live job state and
recent run metadata. The dependency-free view refreshes every 15 seconds and
allows adding, editing, pausing, resuming, and archiving jobs. Editing a job
leaves its stored command or Codex prompt unchanged unless a replacement is
entered. The dashboard deliberately never returns commands, prompts, log paths,
output, errors, or credentials. It only binds to `127.0.0.1` (or `::1` with
`--host ::1`), so do not expose it through a reverse proxy until the dashboard
has authentication and a deliberate remote-access design.

## Current scope

Codex Local Scheduler supports Linux systems with a user-level systemd manager and
Python 3.11+ with `pip`. It is alpha software; validate each job manually
before allowing it to run unattended.

- Project registry with a safe, explicit local directory per project.
- Reusable connection records, currently references rather than credentialed
  adapters. They label a job's intended integration but do not yet authenticate
  or check the health of an external service.
- Cron-style schedules using five fields: minute, hour, day-of-month, month,
  day-of-week. `*`, comma lists, ranges, and step values are supported.
- SQLite-backed job and run history.
- Durable queued occurrences, an exclusive scheduler tick, independent worker
  services, per-project locks, process-group timeout handling, SQLite WAL mode,
  and a `run-due` command suitable for a systemd timer.
- Scheduler data and run logs are created owner-only. This protects the
  commands, prompts, connection labels, and output from other local accounts.
- Command jobs and first-class Codex jobs. A Codex job saves its model and
  reasoning effort, sandbox, and approval mode with the schedule, then runs
  `codex exec` with those explicit settings.

## Demo project

`examples/demo-project/` is a self-contained fixture for proving the full
scheduler path before attaching it to a real project. Its `daily-status.sh`
workflow reads local activity data and generates a report under `reports/`.

## Deliberate next steps

Due occurrences are persisted before a worker claims them. The systemd timer
uses independent worker services, so a long job does not block the next minute
of scheduling. A worker that finds its project busy returns the occurrence to
the queue for a later tick. The next reliability milestone is explicit
missed-run and retry policies: `Persistent=true` wakes the timer after downtime
but does not replay every cron occurrence. Once that is in place, build a real
connection adapter with a health check, then notifications and a local
dashboard.
