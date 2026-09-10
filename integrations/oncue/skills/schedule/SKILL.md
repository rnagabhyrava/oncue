---
name: schedule
description: Schedule, inspect, update, pause, or retry local AI tasks and monitors through OnCue. Use when the user asks this agent to do work later or repeatedly using OnCue.
---

# Schedule with OnCue

Use the OnCue MCP tools when available. The prerequisite is an installed `oncue`
command on PATH and a configured provider/model in OnCue Settings. The app owns
execution; the calling agent's model, login, permissions, and tools are not
implicitly inherited by scheduled tasks.

1. Read `scheduler_settings` and `list_tasks` to resolve defaults and existing tasks.
2. Translate the user's request into instructions and an explicit schedule. Use
   the configured IANA timezone unless the user specifies another. Ask a concise
   clarification only when timing, requested work, or a monitoring stop condition
   is materially ambiguous. Distinguish an event date being announced from the
   event taking place.
3. Call `create_task`, or `update_task` for an existing task. Ordinary scheduling
   requests already authorize creating the task; don't ask redundant permission.
   Never invent a schedule or provider access. Leave permissions at defaults.
   Set `retry_safe` only when repeating the work cannot duplicate external actions.
4. Report the task's title, interpreted schedule/timezone, and next occurrence.
   Successful creation persists the task and starts the local service. This
   computer must be running, awake, and connected at execution time.
5. Use `read_history` with `before` pagination for older responses. `read_response`
   reads one response or log; large output is previewed, and the UI can export all
   originals. Use `retry_run` for a failed attempt, with the requested delay.

Monitors use `mode: monitor` and a precise `condition`. They keep observations,
notify on meaningful changes/completion/errors, and stop when an AI response
reports completion with source evidence. Evidence is model-reported, so high-stakes
conclusions still need human review. They default to a maximum of 365 checks.

If MCP is unavailable, use `oncue say "<request>"` for natural-language setup, or
`oncue task --help` for explicit controls. Read `oncue --help`; never hand-edit
SQLite, copy credentials, or create a parallel cron service. Preserve history
when pausing or archiving. If creation succeeded but service startup failed,
inspect `list_tasks` before retrying creation to avoid a duplicate.
