# OnCue

**Schedule AI tasks. Come back to the results.**

Tell OnCue what to do and when. It schedules the task—or asks a clarification—and
keeps every response in a conversation of its own.

- Run once, repeat on a schedule, or monitor until a condition is met.
- Use Codex with ChatGPT, or try OpenCode’s available free models without a login.
- Read earlier results, retry failures, pause tasks, and export complete history.
- Schedule from the web UI, command line, or your coding agent through MCP.

![OnCue task conversations](docs/screenshots/conversation.png)

## Get started

Install on Linux x86_64 with glibc 2.38+ (for example, Ubuntu 24.04+):

```bash
curl -fsSL https://github.com/rnagabhyrava/oncue/releases/latest/download/install.sh -o install.sh
sh install.sh
```

The bundle includes Python, the web UI, and both AI runtimes. Installation starts
scheduling and opens the UI; no sudo or separate Python/Node setup is needed.
Later, launch **OnCue** from your application menu or run `~/.local/bin/oncue open`.
See [START.md](START.md) for updates, startup at login, uninstalling, and running
from source.

First boot selects **OpenCode → Big Pickle**, a free model that needs no login.
Use the model picker below the message box to choose another model.
The bundled app includes both runtimes; source installs can add one from Settings.
To use Codex instead, connect your local Codex login or sign in through OnCue.
Then type something like: **“Every weekday at 9, give me a writing exercise.”**

![OnCue model settings](docs/screenshots/models.png)

Runs on your computer, so it needs to be awake and connected. Free-model
availability can change. Linux x86_64 bundles include Python and both AI runtimes.

[Install and configure](START.md) · [CLI and agent integration](docs/api.md) ·
[How it works](docs/architecture.md) · [Contribute](CONTRIBUTING.md)

**Alpha.** Developers and coding agents: start with [AGENTS.md](AGENTS.md).
