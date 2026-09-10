# OnCue CLI, HTTP API, and coding agents

## CLI

Install using [START.md](../START.md). These examples assume `~/.local/bin` is on
your PATH; otherwise use `~/.local/bin/oncue` in place of `oncue`.

App lifecycle commands:

```bash
oncue open                 # Start scheduling and open the web UI
oncue start                # Start without opening a browser
oncue stop                 # Stop scheduling; active tasks may finish
oncue install-startup      # Optional Linux sign-in startup (systemd)
oncue install-launcher     # Create or refresh the application-menu shortcut
oncue uninstall            # Portable installs: remove app, retain history
```

`uninstall --purge-data` also permanently deletes default task storage, including
the separate OnCue login. Custom storage requires manual removal. Shared provider
logins outside the app data directory are retained. `install-launcher` and
`uninstall` accept `--prefix /absolute/path` for custom installation locations.
`prepare-update` stops dispatch and refuses to proceed while recorded workers
are alive; the portable installer uses it before replacing app files.

Task and settings commands:

```bash
oncue open
oncue settings --set '{"provider":"codex","model":"YOUR_MODEL","timezone":"America/Chicago"}'
oncue say 'Every weekday at 9 AM, give me a writing exercise'
oncue say 'Move this to 10 AM' --task TASK_SLUG
oncue task add --instructions 'Give me a writing exercise' --frequency weekdays --time 09:00
oncue task add --instructions 'Check the official event announcement' --frequency daily --time 08:00 --mode monitor --condition 'The official event date is announced'
oncue task list
oncue task history TASK_SLUG
oncue task response RUN_ID
oncue task run TASK_SLUG
oncue task pause TASK_SLUG
oncue task resume TASK_SLUG
oncue task archive TASK_SLUG
```

`--model` and `--provider` override defaults when creating a task. `say` returns a
slug/run ID: planning is asynchronous, and its reply appears in task history.
For explicit `task add`, keep the app or scheduler running. Use `--data-dir` before
any subcommand to select storage. `run-due` runs due work inline for scripts/tests.

## MCP and plugin

Generic stdio MCP client configuration:

```json
{"mcpServers":{"oncue":{"command":"oncue","args":["mcp"]}}}
```

For custom storage, use `args: ["--data-dir", "/absolute/path", "mcp"]`.
Use an absolute executable path if the client does not inherit your shell PATH.

OpenCode's configuration format uses an array command:

```json
{"mcp":{"oncue":{"type":"local","command":["oncue","mcp"],"enabled":true}}}
```

Codex users can use the distributable plugin at `integrations/oncue` through
their plugin marketplace, or register the MCP server directly:

```bash
codex mcp add oncue -- oncue mcp
```

The companion `integrations/oncue/skills/schedule/SKILL.md` can also be installed
in agents supporting skills. The skill is guidance; the MCP server/CLI is what
actually persists schedules. Host-specific plugin installation formats vary.

Tools: `create_task`, `update_task`, `list_tasks`, `task_action`, `read_history`,
`read_response`, `retry_run`, `scheduler_settings`. Inspect `tools/list` for their
JSON schemas. Creating/updating through MCP starts the local app; the client can
then exit. If startup fails after creation, inspect the task list before repeating
creation. The bridge currently uses newline JSON-RPC; no remote MCP endpoint.

## Local HTTP API

The UI is the reference client. Private reads and mutations require the
`X-CSRF-Token` from the root page's `csrf-token` meta element. Use the same loopback
Host; browser mutations also validate Origin. Tokens change on app restart.
Requests are JSON objects, at most 64 KiB. Errors return `{"error":"message"}`.

| Route | Purpose |
| --- | --- |
| `GET /api/tasks` | Task states, next runs, settings and scheduler health |
| `POST /api/tasks` | Explicit task creation |
| `PATCH /api/tasks/SLUG` | Partial update; omitted fields stay unchanged |
| `POST /api/tasks/SLUG/run` | Queue a manual run |
| `POST /api/tasks/SLUG/pause`, `/resume`, `/archive` | Lifecycle actions |
| `POST /api/message` | `{slug?: string, text: string}`: queue a conversation turn |
| `GET /api/conversation/SLUG?before=ID` | Earlier messages, run metadata, active runs |
| `GET /api/runs/ID`, `/api/runs/ID/log` | Response/log preview |
| `GET /api/export/SLUG` | ZIP with full history and original output |
| `POST /api/runs/ID/retry` | `{minutes: 0}` or a delayed retry |
| `POST /api/runs/ID/cancel` | Cancel queued/running work |
| `GET /api/settings`, `PATCH /api/settings` | Provider status and non-secret settings |
| `POST /api/providers/refresh` | Refresh installed runtimes and models |
| `POST /api/providers/install` | `{provider: "codex" | "opencode"}` |
| `POST /api/providers/login` | Start OnCue-owned Codex sign-in |
| `POST /api/startup` | Install Linux login startup and launcher |
| `POST /api/preview` | Validate friendly timing and show next occurrence |
| `GET /api/overview` | Operational metadata; session token required |

Explicit task fields include `instructions`, `title`, `provider`, `model`,
`frequency` (once/daily/weekdays/weekly/custom), `time`, `date`, `weekday` (0=Sun),
`cron`, `timezone`, `enabled`, `mode` (task/monitor), `condition`, `remember`,
`retry_safe`, and `max_checks`. UI-only advanced controls expose execution settings.
The task model is validated for shape, not account eligibility; execution establishes
actual access. Keep this API bound to loopback.

The MCP bridge enforces its published schemas. Undeclared execution fields and
shell-task edits, runs, and retries are rejected; use the local UI or CLI for shell tasks.
