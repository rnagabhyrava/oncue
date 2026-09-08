# Security policy

Codex Local Scheduler runs commands under the local account and may invoke Codex with
workspace-write access. Treat every job command and prompt as trusted code.

Do not place credentials, tokens, or access keys in jobs, connection records,
logs, issues, or pull requests. Connection records are labels only; credentials
belong in the operating system, a dedicated credential mechanism, or the
integration that uses them.

Before publishing, enable GitHub private vulnerability reporting in the
repository's Security settings. Report vulnerabilities through that channel;
do not open a public issue until a fix is available.

Reports are most helpful with affected versions, reproduction steps, impact,
and any suggested mitigation.
