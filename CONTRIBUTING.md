# Contributing to OnCue

Start with [START.md](START.md), [AGENTS.md](AGENTS.md), and
[the architecture](docs/architecture.md). Keep the main flow focused on describing
work, scheduling it, and reading the result.

## Develop and check

Python 3.11+ and Node 22.12+ are required for development. The installed app does
not need Node. Frontend source is in `frontend/`; built assets are checked in under
`oncue/static/` for source and Python-package users.

```bash
npm ci
npm run build
python3 -m unittest discover -s tests -v
python3 -m compileall -q oncue
python3 -m oncue --help
```

After UI changes, rebuild and reload the running app. Test loading, errors, keyboard
interaction, and light/dark layouts. README screenshots live in `docs/screenshots`;
use an isolated data directory with non-private example tasks when refreshing them.

Use `unittest` and temporary storage for scheduler tests. Exercise actual queue,
subprocess and output transitions. Keep paid-provider calls out of automated tests;
perform bounded live-provider checks separately before a release.

## Package

Install `.[dev]`, run `python -m build`, install the wheel into a fresh environment,
and verify `oncue --help`. Follow START to build the portable app. Test it outside
the checkout and keep runtime licenses in the bundle.

Preserve migrations, original run files, occurrence uniqueness and execution locks.
Use shared task/provider services instead of duplicate UI or CLI logic. Changes to
execution or persistence require focused regression tests and architecture updates.

Never commit credentials, databases or private run output. Reports should include
reproduction steps, relevant versions and redacted errors. Historical aliases belong
in the compatibility layer; new features should use OnCue's task API.
