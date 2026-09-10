# Set up OnCue

OnCue runs scheduled AI tasks on your computer and keeps their results. You do not
need to create a project, register a connection, or manage task folders.

## Install the bundled app

The Linux x86_64 bundle includes Python, the React UI, Codex, and OpenCode. It needs
no separate Python or Node installation and contains no accounts or credentials.

Download and run the installer:

```bash
curl -fsSL https://github.com/rnagabhyrava/oncue/releases/latest/download/install.sh -o install.sh
sh install.sh
```

The script downloads the bundle over HTTPS, checks its SHA-256 checksum, installs
it for your user, starts scheduling, and opens the web UI. No sudo, Python, Node,
or npm setup is needed. Linux x86_64 with glibc 2.38+ (for example, Ubuntu
24.04+) is required, along with `curl` or `wget`, `tar`, and `sha256sum`. A checksum detects download corruption;
it is not a separate publisher signature.

For an offline install, download `install.sh`, `oncue-linux-x86_64.tar.gz`, and
`oncue-linux-x86_64.tar.gz.sha256` from the same
[GitHub release](https://github.com/rnagabhyrava/oncue/releases). Put them in one
folder, open a terminal there, and run:

```bash
sh install.sh --archive ./oncue-linux-x86_64.tar.gz
```

For a locally built bundle, run `sh install.sh --archive
dist/oncue-linux-x86_64.tar.gz` from the checkout instead.

Or extract the archive and run `sh oncue/install.sh`. App files go to
`~/.local/share/oncue/bin`; commands go to `~/.local/bin`. An **OnCue** application
menu shortcut is added. Installation does not change shell configuration.

### Launch, stop, and update

```bash
~/.local/bin/oncue open              # Start in background and open the UI
~/.local/bin/oncue start             # Start without opening a browser
~/.local/bin/oncue stop              # Stop scheduling; active tasks may finish
~/.local/bin/oncue install-startup   # Optional: start at Linux sign-in
```

If `~/.local/bin` is on your PATH, use `oncue open`, or choose **OnCue** from your
application menu. Closing the browser leaves scheduling running. The default UI
is at `http://127.0.0.1:8765`; the start command prints its address.

Run the installer again to update. It retains tasks/settings, stops dispatch,
and refuses replacement while a task is active. Startup failures restore the
previous app when available. Installer options include `--version v0.3.0`,
`--no-open`, `--no-start`, `--startup`, and `--prefix /absolute/path`.
Startup at sign-in requires a systemd user session; manual launch does not.

### Uninstall

```bash
~/.local/bin/oncue uninstall
```

This stops scheduling and removes the portable app, its command links, menu
shortcut, and OnCue login-startup service. Task history, outputs, settings, and
OnCue's separate provider login stay in `~/.local/share/oncue/data` so you can
reinstall. Active tasks must finish before uninstalling.

To also permanently delete that default data directory:

```bash
~/.local/bin/oncue uninstall --purge-data
```

Shared Codex/OpenCode logins outside OnCue's data directory are retained.
Custom data directories require manual removal after backup. If invoking the
uninstaller from source for a custom install, supply `--prefix /absolute/path`.
For a pip installation, stop OnCue with that environment's command and uninstall
from the same environment, for example:

```bash
.venv/bin/oncue stop
.venv/bin/pip uninstall oncue
```

This retains task data. The portable uninstaller only removes portable installs.

## Run from this checkout

Use Linux and Python 3.11 or newer:

```bash
python3 -m oncue open
```

For an installed Python command:

```bash
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/oncue open
```

`open` starts the app in the background and opens its UI. Closing the browser does
not stop scheduling. `oncue stop` stops the app; `oncue start` starts it without
opening a browser. `oncue dashboard --port 8766` runs in the foreground.

## Build the bundle

To build the bundle yourself, install Node 22.12+ / npm and Python 3.11+:

```bash
npm ci
npm run build
python3 -m venv .build-venv
.build-venv/bin/pip install pyinstaller
.build-venv/bin/python scripts/build_portable.py
```

The archive appears in `dist/`. Build on the oldest Linux distribution you intend
to support. This bundle requires glibc; macOS, Windows and musl builds are not
currently provided.

## Choose a provider

First boot starts with **OpenCode → Big Pickle**, a no-login free model in the
bundled catalog. Existing saved preferences are preserved. If that model becomes
unavailable, choose another model marked Free.

Open **Settings → Models**. Defaults apply to new tasks; existing tasks keep their
own model. The dropdown shows discovered models and groups zero-cost OpenCode
models under **Free models**. Refresh retrieves the provider's current catalog.
**Enter a model ID…** is available for models not listed.

Click the model name below the message box to change only that conversation.
Use **Run now** in a scheduled task’s header, or send exactly **“Run now”** in its
chat, to queue the saved task immediately without changing its schedule. Finish
scheduling a draft before running it.

### OpenCode

Choose OpenCode and a model marked Free. The bundled runtime can use its available
free models without an OpenCode login. Availability and provider data policies
can change; [OpenCode’s documentation](https://opencode.ai/docs/zen/) describes
its service. Other providers/models may require `opencode auth login` and billing.
OnCue does not sign you up for a paid plan or add credits.

If the runtime is missing, use **Install runtime**. Source installations need npm
for this step; the portable bundle already includes the native runtime.

### Codex / ChatGPT

Choose Codex and an account-eligible model. Two sign-in modes are available:

- **Use my local Codex login:** first sign in using `codex login` or a Codex app
  that shares its local account storage. A ChatGPT website session alone is not
  sufficient.
- **Use a separate OnCue login:** click **Connect ChatGPT**, follow the provider’s
  sign-in link, and save. Codex stores this login separately for OnCue.

OnCue uses the supported Codex login flow. Passwords and tokens are not copied
into its task database. Model availability and usage limits belong to the account.

## Schedule and follow up

Type what should happen and when. OnCue asks when important details are missing.
Use the **+** button or **Task details** for explicit timing and execution controls.
Each task gets a working folder automatically.

## Organize work and add references

Create flat projects from the task sidebar to group tasks. Projects are organizational:
they do not change a task's working folder, lock, model, or schedule. A task can remain
**Unassigned**, and deleting a project returns its tasks there while retaining history.

Projects can contain shared instructions and text reference files. Open **Task details**
to choose a project and attach task-specific references. OnCue accepts UTF-8 `.txt` and
`.md` copies up to 64 KiB each; active project/task material may total 128 KiB. Each run
saves the referenced text in its execution snapshot, so later edits do not change it.

## Background notifications

Settings can send result and terminal-failure notifications through Linux desktop alerts
or outgoing webhooks. Webhooks receive a versioned JSON event with a stable event ID,
task/run identity, status, complete response, and error details. Delivery retries do not
rerun the task. Add a webhook as JSON in Settings; for example
`{"name":"Automation","url":"https://example.test/oncue"}`. HTTP is allowed only
when that destination explicitly sets `"allow_local":true`. Bearer tokens may be passed
as `"token"`; webhook URLs and tokens live outside SQLite and exports.

The task sidebar opens its conversation. Ask follow-ups there, change the schedule,
or use its menu to run, pause, resume, archive, and export. Earlier messages remain
available. Export includes all messages and complete response/log files; on-screen
output previews are limited to 256 KiB each.

Recent conversation context is included in later runs. This is OnCue’s own history,
not a mirrored ChatGPT chat. Replies appear after each run finishes; token streaming
is not currently implemented.

## Errors, retries and monitors

Failures stay in history with an explanation and **Retry now** / **In N min**.
Automatic retries use a bounded delay/count for planning, monitors, and tasks marked
safe to repeat. Do not mark tasks safe when repetition could duplicate external
actions. Sign-in, permission and invalid-model failures need attention.

Fallback is optional. Enabling it permits sending task context to that provider
on eligible retries. A different model may still share the same quota limit.

A monitor needs a precise stop condition. “The IPO date is announced” differs from
“the IPO happens.” It keeps observations, records unchanged checks quietly, and
stops when the model reports completion with source evidence. This is AI-interpreted
evidence, not independent verification. Monitors pause after their maximum check
count (365 by default) if they have not completed.

## Background operation and storage

**Settings → General** offers startup at Linux sign-in and an optional sleep
inhibitor. The computer must be powered on and connected; OnCue is not a cloud
scheduler. Browser notifications need permission and an open tab.

Schedules have minute precision. Missed recurring occurrences are skipped; one-time
tasks and queued retries can run after restart. Busy workspaces or worker limits
can delay execution. Repeated daylight-saving minutes may run twice; nonexistent
recurring times are skipped. Invalid one-time local times are rejected.

Back up the entire data directory, including SQLite and run files. See
[compatibility and storage](docs/compatibility.md) for existing installations and
custom locations. See [CLI/API/MCP](docs/api.md) for coding agents and automation.
