# How OnCue works

React UI / CLI / MCP → shared task service → SQLite queue → native AI runtime →
saved response and conversation.

## Responsibilities

OnCue owns scheduling, task definitions, execution supervision, retries, and retained
history. Codex and OpenCode own model requests, provider authentication, agent tools,
and tool execution. OnCue does not implement another model API client or agent loop.

`providers.py` is the single native-runtime adapter:

- Codex: `codex exec` with supported sandbox/model flags and final-message output.
- OpenCode: `opencode run --format json` with a provider/model ID.
- Models: the native OpenCode verbose catalog supplies names and zero-cost labels;
  Codex's local catalog supplies account model identifiers.
- Login: Codex app-server handles its supported account login protocol. OnCue only
  exchanges control messages and exposes transient sign-in status/URLs.

These CLI interfaces already provide the model and tool behavior needed for
scheduled work. Moving to SDK/server transports would make sense for native session
streaming, but would add persistent provider services and transport lifecycle work.
It would not replace OnCue's durable scheduling and history layer.

## Queue and execution

`tasks.py` validates tasks and allocates private working folders. `schedules.py`
converts timing controls into cron or a one-time timestamp. `scheduler.py` records
due occurrences under a lock and starts bounded worker processes. A unique
job/occurrence record prevents duplicate recording; workspace locks serialize work
sharing a folder. This does not guarantee exactly-once external side effects.

Workers atomically claim queued runs and save execution configuration snapshots.
Cancellation/timeouts terminate the provider process group. Interrupted worker
recovery checks PID and process-start identity. One-time tasks and deferred retries
survive restarts; missed recurring minutes are not replayed.

Each attempt has separate response and diagnostic log files. Retry attempts link
to the failed attempt and have a due time and bounded attempt count. Automatic
retry applies only to eligible work; provider fallback requires explicit opt-in.

## Conversations and monitors

The planning model returns a structured schedule proposal or a reply/clarification.
Only validated scheduling fields reach task persistence. Planning cannot change
models, providers, shell mode, or file permissions. Provider tools are restricted
during planning; explicit controls can schedule without model interpretation.

Up to 12 recent messages and 16,000 context characters are included in later
prompts. Monitor memory is bounded to 8,000 characters. These prompt limits do not
truncate saved history. Native provider sessions are not the persistence source.

Monitor results include summary, changed/completed flags, memory, and evidence.
Completion requires structurally valid source evidence before scheduling stops.
The model interprets evidence; OnCue does not independently establish its truth.
Unchanged checks remain saved with notification disabled. Maximum-check limits
pause unfinished monitors for review.

## Organization and notifications

User-facing flat projects are separate from execution projects. They own optional shared
instructions and uploaded text/Markdown references, while execution projects still own
workspaces and locks. The first attempt snapshots inherited reference text in its run
configuration; retries reuse that snapshot.

Final run outcomes create durable notification events and delivery attempts. Webhook URLs
and bearer tokens live in a private file outside SQLite, while event delivery status stays
inspectable in SQLite. Failed deliveries retry at 1, 5, and 30 minutes and cannot rerun AI work.

## UI and interfaces

`frontend/` contains React components, shared model selection, Markdown rendering,
and appearance styles. Vite builds local static assets packaged with Python. Node
is required to build the UI, not to run the installed app. Visible conversations
refresh every two seconds, preserving scroll state. Output appears after completion.

`dashboard.py` serves a loopback-only UI/API. Host/Origin checks and a per-process
session token protect mutations and private reads. Output paths must resolve inside
run storage. ZIP exports contain full output; previews read at most 256 KiB.

`mcp_server.py` exposes the same task service over stdio JSON-RPC. The companion
plugin/skill is in `integrations/oncue`. MCP schemas are enforced before dispatch,
including nested updates; shell execution is reserved for the local UI/CLI. Coding agents do not implicitly transfer
their account, model, or tool permissions into scheduled tasks.

## Credentials, storage and distribution

Credentials stay in provider-owned storage. Managed Codex login uses a separate
CODEX_HOME under the app data directory. Settings contain non-secret preferences.
OpenCode's tool restrictions are not an OS sandbox; Codex uses its own sandbox.
Advanced shell tasks run with the local account's OS permissions.

`Store.initialize()` adds schema without deleting history. Finished legacy runs
are linked into conversations once. Compatibility tables, command aliases and
storage paths are retained; see [compatibility](compatibility.md).

The Linux bundle packages Python, native runtimes, static UI, licenses and agent
integration. `service.py` starts either the source module or frozen executable.
Startup at sign-in and sleep inhibition are optional local operating-system features.
The root `install.sh` fetches a release and verifies its checksum; the bundled
installer stages files before activation. CLI lifecycle commands in `service.py`
stop dispatch, wait for the app to exit, and reject replacement/removal when
recorded workers are alive. Desktop launcher creation is independent of systemd.
Portable uninstall retains task storage unless explicitly asked to purge the
default directory; shared provider authentication stays outside its scope.

The composer keeps new-task model overrides in draft state and passes them to the
shared message service; existing-task choices use a partial task update. Exact
“Run now” messages bypass planning and queue saved work through `queue_manual`.
