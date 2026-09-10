# OnCue security

OnCue is a single-user local app. Keep its HTTP server on loopback. It is not a
publicly hosted, multi-user service. Private requests require a session token;
browser mutations also validate origin and host. The token is an anti-cross-site
control, not an account login: other local processes/users that can access the
loopback port can load the UI and obtain it. Use a trusted single-user computer;
OnCue is not isolated from other local users.

Tasks run as the local user. Codex controls its sandbox; OpenCode controls its tool
permissions. OpenCode permissions are not an OS sandbox. Advanced shell commands
have the user's normal permissions. Retry tasks with external actions carefully.

Provider credentials remain in provider-owned storage. Managed Codex login uses
a separate local account directory. OnCue does not collect account passwords or
copy login tokens into SQLite. Prompts and run output are retained, so do not paste
secrets into task instructions. Treat history exports as private.

Model requests and permitted tool calls use the selected provider. Explicitly
enabling fallback permits task context to be sent to that provider too. Free-model
availability and data policies are controlled by the provider.

Monitoring uses AI-interpreted source evidence. Completion is not independent
verification; review consequential conclusions before acting on them.

Back up SQLite and its accompanying run files together. Report vulnerabilities
through the repository's private security reporting channel when available; do not
post credentials or private logs in public issues.
