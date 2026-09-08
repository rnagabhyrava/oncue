# Demo project

This is a safe fixture for testing Codex Local Scheduler end to end. Its daily-status
workflow reads a small project activity log and writes a Markdown report to
`reports/`.

The workflow deliberately has no external connections and makes no changes
outside this directory. Once it works through the scheduler, we can replace it
with a real project and connection-backed workflow.
