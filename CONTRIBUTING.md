# Contributing

Thanks for improving Codex Local Scheduler. This project supports Python 3.11+ on
Linux and is currently alpha software.

Start with [START.md](START.md), then read [AGENTS.md](AGENTS.md). Keep changes
small and explain observable behavior in pull requests.

Before proposing a change, run:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q codex_local_scheduler
python3 -m build
```

Changes to execution, persistence, security boundaries, or connection handling
must update [docs/architecture.md](docs/architecture.md). Changes to public CLI
or installation behavior must update [README.md](README.md) and [START.md](START.md).

Do not commit scheduler databases, logs, `.env` files, credentials, tokens, or
real project output. Use the demo project and temporary data directories for
tests that exercise scheduling.
