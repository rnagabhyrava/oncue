# Codex Local Scheduler project guide

## Purpose

This project is a local-first automation scheduler for persistent project
folders. `systemd` wakes the scheduler, SQLite stores durable state, and a job
runs either a local shell command or Codex with a task-specific model and
reasoning effort.

Read [START.md](START.md) for installation, the demo workflow, and the public
release checks.

## Code map

- `codex_local_scheduler/__main__.py`: CLI, argument parsing, and orchestration.
- `codex_local_scheduler/store.py`: SQLite schema and persistence API.
- `codex_local_scheduler/cron.py`: dependency-free five-field cron matching.
- `codex_local_scheduler/runner.py`: process execution, project locks, logs, and Codex
  invocation construction.
- `systemd/`: templates for the user-level scheduler timer and service.
- `docs/architecture.md`: runtime boundaries and real-workflow onboarding.
- `tests/`: built-in `unittest` coverage. Do not require pytest solely for this
  project.

## Working agreements

- Keep the runtime dependency-free unless a new capability clearly needs a
  dependency. Python 3.11+ is supported.
- Preserve SQLite migrations: `Store.initialize()` must upgrade existing data
  directories without deleting job or run history.
- Keep `run-due` idempotent for a job and scheduled minute. Do not remove the
  unique run record or project lock.
- Treat stored connection records as references only. Do not add credentials,
  access tokens, or copied secrets to the database, source tree, logs, or
  generated output.
- A Codex job's model and reasoning effort belong to the job record, not a
  global scheduler setting.
- Test an actual due-run flow in a temporary data directory when changing
  persistence, scheduling, or execution behavior.

## Commands

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q codex_local_scheduler
python3 -m codex_local_scheduler --help
```

## Change expectations

Update `README.md` for user-facing CLI or operating changes. Update
`docs/architecture.md` when changing execution, persistence, connection, or
security boundaries. Add narrowly scoped tests for changed scheduler behavior.

## Planned direction

The next milestones are a real connection adapter and health check, then
notifications, then a local dashboard. Keep the command-line and SQLite layer
as the stable foundation for each of those features.
