# OnCue security review — September 9, 2026

Direct source review found and fixed an MCP capability-boundary issue. Additional
hardening now protects overview metadata and limits incomplete HTTP/MCP input.
This is a manual engineering review, not a completed Codex Security plugin report.

## Scope and assumptions

Reviewed the local HTTP handlers, browser request/rendering paths, CLI and MCP
entry points, task validation, model-response parsing, native provider invocation,
authentication lifecycle, SQLite persistence, output/export paths, scheduling,
retries, runtime installation and Linux launch/build configuration. Reviewed the
current checkout, including uncommitted OnCue work. Validation used temporary
storage and harmless commands; no real credentials or user tasks were modified.

OnCue runs on a trusted single-user computer. The loopback token prevents foreign
web pages from using the API; it does not authenticate other local users/processes,
which can fetch the root page and obtain that token. Native providers are trusted
executables. OpenCode tool permissions are not an operating-system sandbox.

## Fixed finding: MCP accepted undeclared execution capabilities

**Medium severity, CWE-20 / CWE-862.** The affected boundary was an agent/client
permitted to use the advertised AI-scheduling tools without general shell access.
An already unrestricted local agent gains no additional privilege from this issue.

`mcp_server.call` previously passed tool arguments directly to `save_task` without
checking the published JSON schema. Although `create_task` advertised only AI task
fields and `additionalProperties: false`, a request could include `runner: command`
and shell text in `instructions`. The task service accepted that runner and the
scheduler eventually reached `runner._execute_started_run`, where shell tasks
intentionally use `subprocess.Popen(..., shell=True)` as the local user. Nested
`update_task.changes` offered the same path. Existing shell tasks could also be
modified and run through the bridge. This is a schema/authorization bypass, not
shell escaping failure: the local UI/CLI intentionally support shell tasks.

The bridge now validates required fields, exact types, enums and unknown fields
recursively before mutation. It also rejects editing, running or retrying existing
shell tasks through MCP. Local UI/CLI shell functionality remains available.
Regression checks verify both creation and nested-update bypasses fail before
launching the service or changing instructions.

## Additional hardening

- `/api/overview` now requires the session token, consistent with other API reads;
  titles can contain private prompt text and should not be treated as public data.
- HTTP connections have a 15-second read timeout. The existing 64 KiB body limit
  remains. This bounds stalled reads; it is not a comprehensive DoS defense.
- MCP reads at most 1 MiB plus one character before rejecting an oversized message
  and ending the connection, rather than allocating an unbounded line first.
- Security documentation explicitly describes the local-user trust boundary.

## Existing controls verified

- Loopback bind restriction, host/origin checks, per-process token, restrictive CSP,
  frame denial, no-sniff headers, and no CORS relaxation.
- React text rendering and react-markdown without raw-HTML execution. External
  images are restricted by CSP; response links open with `noreferrer`.
- Parameterized SQL; constant-only dynamic migration identifiers; safe slugs for
  task and lock paths. Database/data directories use owner-only permissions.
- Log and export paths resolve inside run storage. Exports retain original output;
  previews are bounded. Provider credentials are not stored in SQLite.
- Native model arguments are passed as argument arrays; shell mode is restricted
  to explicitly selected command tasks. Planner proposals cannot change model,
  runner, permission or approval fields.
- Unique occurrence records, atomic claims, process locks, cancellation/timeouts,
  retained retry configuration, and bounded monitor history/context.
- Runtime packages are versioned and installed with npm lifecycle scripts disabled.

## Validation and limits

The regression suite covers the MCP bypass, private API reads, malicious Host and
Origin values, path traversal, output-size limits, cancellation, retries, monitor
completion, and actual due-run execution in temporary storage. `npm audit` reported
zero known vulnerabilities for the frontend lockfile on this review date.

This review does not establish that the app is vulnerability-free. Native Codex/
OpenCode binaries, their hosted services and third-party package implementation
were not independently audited. No external penetration test, sustained DoS test,
or general prompt-injection-resistance claim is made. A model can still misinterpret
untrusted task/source text; permitted tools retain their documented authority.

The optional managed Codex Security scan stopped at preflight: the helper could
not identify this session's multi-agent runtime owner/version. It returned
`incomplete` for `usable_worker_slots_6` with no concrete configuration patch.
Its skill requires “Continue only after a ready result.” The pending scan was
preserved without changing the user's Codex configuration. The direct review
above is separate; plugin scan coverage and token measurements are unavailable.
