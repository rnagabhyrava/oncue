# Architecture

```
systemd timer
    |
    v
codex-local-scheduler run-due
    |
    +--> SQLite: projects, connections, jobs, run history
    |
    +--> SQLite: persist due runs as queued
    |
    +--> systemd worker service per queued run
              |
              +--> project-scoped command or Codex runner
                    |
                    +--> local project folder
                    +--> owner-only run log
                    +--> future: connection adapter and notifications

codex-local-scheduler dashboard
    |
    +--> loopback-only, read-only HTTP view of job and run metadata
```

## Boundaries

The scheduler stores a connection's name and kind so projects can reuse a
connection without copying its credentials. Authentication belongs to the
runner's configured credential mechanism. The first real integration will
define this mechanism for one connection and verify it with a health check.

`run-due` holds an exclusive scheduler lock while it records due occurrences.
A unique record for each job and scheduled minute prevents duplicate execution,
and a project lock is held while the runner works in that project's directory.
Each active runner records its process ID, so a manual run cannot be mistaken
for an abandoned run by an overlapping scheduler tick. Runs left active after
their process ends are marked failed during a later tick.

The data directory, SQLite database, lock directories, and run logs are owned
by the local account. The runner starts with a small environment and passes a
connection's name and kind only; it never stores connection credentials.
Command jobs execute with the local account's permissions. Codex jobs record a
sandbox and may use automatic approval only with `workspace-write`.

`run-due --dispatch systemd` persists due occurrences, then asks a dedicated
`codex-local-scheduler-worker@<run-id>` service to claim each one. A worker claims a
run atomically, records its process ID, and holds only its project's lock while
it executes. If the project is busy, the run returns to the queue for the next
tick. The command-line default (`run-due`) dispatches queued work inline for
local testing.

The scheduler does not yet replay occurrences missed while the computer is
offline. That policy must be explicit because workflows differ: a report may
run once after downtime, while a financial action should usually be skipped.

Codex jobs also record a model and reasoning effort. For example, use
`gpt-5.6-terra` with `medium` for routine summaries, then reserve stronger
models or higher effort for complex review and planning jobs. The scheduler
passes the recorded settings to `codex exec` at run time.

The dashboard is deliberately separate from the execution path. It reads the
same SQLite store in one local HTTP process and exposes operational metadata
only: job identity, schedule, state, runner/model, and recent run timing and
status. It excludes commands, prompts, connection data, logs, errors, and any
write routes. Its server rejects non-loopback bind addresses. Job controls and
remote access require explicit authentication, CSRF protection, and a separate
security design before they are added.

## First real workflow checklist

1. Create or choose the local project folder.
2. Register it with `project add`.
3. Add a connection reference if the workflow reads an external service.
4. Put the workflow command or script in the project folder.
5. Add a job and run it manually by choosing a schedule matching the current
   minute.
6. Inspect the generated log and database record before enabling the timer.
7. Run `codex-local-scheduler doctor`, then enable the timer and inspect its first
   scheduled result.
