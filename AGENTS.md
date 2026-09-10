# OnCue project guide

OnCue is a local AI task app: describe work and timing, run it in the background,
and keep each task's conversation and results. Read [START.md](START.md) first.

## Code map

- `__main__.py`, `dashboard.py`, `mcp_server.py`: CLI, local HTTP, and agent entry points.
- `tasks.py`, `schedules.py`, `cron.py`: validation and timing.
- `scheduler.py`, `runner.py`, `service.py`: dispatch, execution and background lifecycle.
- `store.py`: additive SQLite migrations and persistence.
- `conversations.py`, `exports.py`: planning, context, retries, monitors and history.
- `providers.py`, `auth.py`, `runtime.py`, `settings.py`: provider boundaries and preferences.
- `frontend/`: React UI source. `compatibility.py`: legacy commands. `migration.py`: naming/data migration.
- `static/`: packaged UI. Python files above live in `oncue/`.
- `integrations/oncue/`: distributable MCP plugin and companion skill.
- `scripts/`: portable Linux build/installer. `systemd/`: legacy compatible timer templates.

## Working agreements

- Python 3.11+; keep the scheduler free of runtime dependencies unless needed.
- Preserve SQLite migrations, task history, unique job/occurrence records, and locks.
- Never copy credentials into SQLite, source, logs, or generated task content.
  Provider authentication remains in provider-owned storage.
- Global defaults seed new tasks. Existing tasks retain model/effort; runs snapshot
  execution configuration and retries retain the failed attempt's configuration.
- Keep UI, CLI and MCP on the shared task service. Project/connection registration
  is a compatibility interface, not the normal onboarding flow.
- Test an actual due-run flow in temporary storage after persistence or scheduling
  changes. Include retry/monitor cases when their semantics change.
- Update human-facing README only for the overview; put detail in START and docs.
  Update architecture for boundary changes and CHANGELOG for visible behavior.

## Checks

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q oncue
python3 -m oncue --help
npm ci
npm run build
```

Use `unittest`; do not add pytest solely for this project. See CONTRIBUTING for
release checks. Preserve legacy package/command/data paths until a tested migration
replaces them. Prioritize useful scheduling, clear failures, and retained results.
