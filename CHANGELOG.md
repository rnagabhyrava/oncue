# Changelog

## Unreleased

- Added required Auth0 Google sign-in when an account service is configured.
- Added explicit installation claiming, revocable computer credentials, outbound
  cloud synchronization, offline history, and deduplicated remote controls.
- Added a separate FastAPI/PostgreSQL service and Render blueprint for account-owned
  computers, snapshots, and 24-hour commands. Gmail mailbox scopes are not used.

## 0.3.0 — 2026-09-09

- Added reference-file selection before scheduling, with a visible composer action,
  file validation, removable pending files, and paused creation until uploads finish.

- Reworked the UI with neutral light/dark themes, larger conversation text, roomier
  navigation, task-state filters, illustrated task starters, and a rounded composer.
  Improved mobile layouts, keyboard focus, and responsive message content.

- Added flat task projects, inherited project instructions, private versioned `.txt` and
  `.md` references, and run-context snapshots for reproducible retries.
- Added customizable project emojis and colors with consistent sidebar identity.
- Added permanent task deletion with an explicit confirmation and managed history/file cleanup.
- Increased light/dark theme contrast with a more vivid indigo visual system and added an OnCue browser icon.
- Added durable outgoing webhook and Linux desktop notification delivery with bounded
  retries, stable event IDs, private endpoint/token storage, and result/failure routing.

- Added a checksum-verified single-script Linux bundle installer, application-menu
  launcher, guarded updates, and portable uninstall with opt-in data deletion.
  Documented launch, stop, sign-in startup, update, and removal commands.

- Completed the OnCue package/distribution, repository and service-template rename.
  Added guarded data migration with a legacy-path alias, active-worker checks,
  conflict refusal and recovery after an interrupted move.


- Added a visible Run now action and direct Run now chat command.
- Improved dark-mode contrast and minimum label sizes.
- Defaulted new installations to OpenCode’s no-login Big Pickle model.
- Enforced MCP argument schemas and blocked shell-task execution through the AI
  integration; protected overview metadata and bounded incomplete HTTP/MCP input.

- Open a conversation-specific model picker from the composer, without changing
  global defaults or sending users into settings.
- Fully hide collapsed sidebars, including their controls and mobile shadow.
- Added the discovered-model picker to fallback settings and cleared incompatible
  model selections when switching fallback providers.
- Made discovered models visible in a shared dropdown, with native OpenCode model
  names and zero-cost labels. Discovery failures now explain how to recover.
- Rewrote onboarding/docs for OnCue with UI screenshots; removed the obsolete
  project demo, duplicate Codex invocation and unused frontend/backend imports.
- Isolated old command handling in a compatibility module to preserve existing
  installations without keeping project registration in the primary workflow.

- Rebuilt the frontend with React: a minimalist responsive chat layout, stable
  conversation updates, Markdown responses, loading states, and focused settings.

- Renamed the interface and primary command to OnCue; preserved package, data,
  legacy commands, migrations and history for existing installations.
- Added conversation-based natural-language task setup, clarification, follow-ups,
  per-task context, dark/light/system appearance and a sidebar of task chats.
- Added settings for provider/model defaults, Codex-owned separate login, OpenCode,
  optional fallback, bounded retries, notifications and Linux startup.
- Added monitors with stop conditions, source-evidence requirements, retained
  observations, quiet unchanged checks and a maximum-check limit.
- Added readable error classification, retry-now/later, cancellation, paginated
  responses and ZIP export of full original run output.
- Added a stdio MCP bridge, agent skill/plugin, standalone background launcher,
  and a Linux bundle builder including Python and both AI runtimes.
- Simplified documentation and onboarding; project and connection registration
  are no longer required for ordinary tasks.
- Added one-time/friendly schedules, next-run previews, automatic task workspaces,
  embedded scheduling and separate final response files.

## 0.2.0 — 2026-09-08

- Renamed the project and command to Codex Local Scheduler.
- Added durable queued runs and independent systemd worker services.
- Added process-aware recovery, safer timeout cleanup, private scheduler data,
  and job archiving.
- Added public-package metadata, release documentation, and CI scaffolding.

## 0.1.0

- Initial local command and Codex scheduler prototype.
