# Naming and migration

The product, Python package, distribution, repository and primary command are
**OnCue** (`oncue`). Run source checkouts with `python3 -m oncue open`.

Data now lives in `~/.local/share/oncue/data`; bundled executables live alongside
it in `~/.local/share/oncue/bin`. `ONCUE_DATA` or `--data-dir` selects a custom store.

On first launch, an existing `~/.local/share/codex-local-scheduler` directory is
moved intact to the new data location. The old path becomes a symlink so saved
absolute log paths, workspaces and retry snapshots still resolve. Keep this alias
while old history or tools reference it. No credentials are copied or rewritten.
The old scheduler is stopped before moving, and migration refuses to move active
workers or merge two existing stores. Let running tasks finish, then launch again.
Back up the data directory before manually resolving a conflicting-store warning.

Only compatibility names remain:

- The deprecated `codex-local-scheduler` command invokes the same OnCue entry point.
- The old data environment variable and shell-task variables remain accepted.
- Installed old timer/worker names remain usable; new templates use OnCue names.
- Generated launchers are updated without enabling services or changing accounts.

Python callers must update imports from the former package to `oncue`. Reinstall
the new wheel in existing virtual environments. The SQLite schema, job identifiers,
occurrence records and retained responses are unchanged by the naming migration.
