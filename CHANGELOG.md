# Changelog

## 0.3.0 — Unreleased

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
