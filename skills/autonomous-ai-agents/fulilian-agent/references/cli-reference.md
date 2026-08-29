# Fulilian CLI Reference

Live sources when anything looks stale: `fulilian --help`, `fulilian <command> --help`,
https://hermes-agent.nousresearch.com/docs/reference/cli-commands

### Global Flags

```
fulilian [flags] [command]        (no subcommand = interactive chat)

  --version, -V             Show version
  -z, --oneshot PROMPT      One-shot: print ONLY the final response (for scripts/pipes)
  -m MODEL  --provider P    Model/provider override for this invocation
  -t, --toolsets LIST       Comma-separated toolsets for this invocation
  --resume, -r SESSION      Resume session by ID or title
  --continue, -c [NAME]     Resume by name, or most recent session
  --worktree, -w            Isolated git worktree mode (parallel agents)
  --skills, -s SKILL        Preload skills (comma-separate or repeat)
  --profile, -p NAME        Use a named profile
  --yolo                    Skip dangerous command approval
  --tui / --cli             Force the Ink TUI / classic REPL
  --ignore-rules            Skip AGENTS.md/SOUL.md/memory/skill injection
  --safe-mode               Disable ALL customizations (troubleshooting)
  --pass-session-id         Include session ID in system prompt
```

### Chat

```
fulilian chat [flags]
  -q, --query TEXT          Single query, non-interactive
  --image PATH              Attach a local image to a single query
  -Q, --quiet               Suppress banner, spinner, tool previews
  --checkpoints             Enable filesystem checkpoints (/rollback)
  --max-turns N             Cap tool-calling iterations
  --source TAG              Session source tag (default: cli)
```
(plus the global flags above)

### Configuration

```
fulilian setup [section]      Wizard (model|tts|terminal|gateway|tools|agent)
fulilian model                Interactive model/provider picker
fulilian fallback [add|remove|list]  Fallback provider chain
fulilian config [show|edit|get|set|unset|path|env-path|check|migrate]
fulilian login / logout       OAuth sign-in / clear stored auth
fulilian doctor [--fix]       Check dependencies and config
fulilian status [--all]       Component status
```

### Tools & Skills

```
fulilian tools [list|enable NAME|disable NAME]   Per-platform toolsets (curses UI with no args)

fulilian skills list|browse|search QUERY|inspect ID
fulilian skills install ID    Hub identifier OR a direct https://…/SKILL.md URL
fulilian skills config        Enable/disable skills per platform
fulilian skills check|update|uninstall|publish PATH
fulilian skills tap add REPO  Add a GitHub repo as a skill source
fulilian bundles              Skill bundles (one /<name> alias loads several skills)
```

### MCP Servers

```
fulilian mcp add NAME (--url or --command) | remove | list | test NAME
fulilian mcp catalog | install NAME     Curated catalog install
fulilian mcp configure NAME             Toggle tool selection
fulilian mcp serve                      Run Fulilian as an MCP server
```
Details (transport, tool discovery, catalog): `references/native-mcp.md`.

### Gateway (Messaging Platforms)

```
fulilian gateway run|install|start|stop|restart|status|setup
```

20+ platforms: Telegram, Discord, Slack, WhatsApp (Baileys + Business Cloud API), iMessage (Photon — `fulilian photon setup`), Signal, Email, SMS, Matrix, Mattermost, Teams, LINE, SimpleX, ntfy, Google Chat, Home Assistant, DingTalk, Feishu, WeCom, Weixin, API Server, Webhooks. Open WebUI connects via the API Server adapter. Most adapters ship under `plugins/platforms/`.
Docs: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/

### Sessions

```
fulilian sessions list|browse|rename ID TITLE|delete ID|export OUT|prune|stats
```

### Cron / Webhooks

```
fulilian cron list|create SCHED|edit ID|pause|resume|run ID|remove|status
    Schedules: '30m', 'every 2h', '0 9 * * *', ISO timestamp
fulilian webhook subscribe NAME|list|remove NAME|test NAME
```
Webhook payloads/routes: `references/webhooks.md`.

### Profiles

```
fulilian profile list|create NAME (--clone|--clone-all|--clone-from)|use|show|delete
fulilian profile rename A B | alias NAME | export NAME | import FILE
```

### Credentials & Pools

```
fulilian auth                 Interactive credential manager
fulilian auth add [PROVIDER]  Add OAuth or API-key credential (nous, openai-codex, qwen-oauth, …)
fulilian auth list|remove P IDX|reset PROVIDER|status
```
Multiple credentials per provider form a pool that rotates automatically and skips exhausted keys.

### Other

```
fulilian desktop / gui        Native desktop app
fulilian dashboard            Web admin panel + embedded chat (--stop / --status)
fulilian proxy                OpenAI-compatible local proxy backed by an OAuth provider
fulilian portal               Quick setup / sign in via Nous Portal
fulilian kanban <verb>        Multi-agent work-queue board
fulilian project              Named multi-folder workspaces
fulilian skin list|use|set    Switch/tweak skins (see references/themes.md)
fulilian pets <verb>          Pet mascots (see references/petdex.md)
fulilian memory setup|status|off|reset   Memory provider
fulilian secrets bitwarden|onepassword   External secret stores
fulilian moa                  Mixture-of-Agents slots
fulilian hooks / security / backup / import / checkpoints / console
fulilian logs [-f] [errors]   View agent/error logs
fulilian send                 One-off message through a gateway platform
fulilian pairing / plugins / insights / journey / computer-use
fulilian acp                  ACP server (IDE integration)
fulilian completion bash|zsh|fish
fulilian update / uninstall / claw migrate
```

Plugin- and provider-supplied subcommands (e.g. `fulilian photon setup`) only appear once their plugin is installed/active.

### Where to Find Things

| Looking for... | Location |
|---|---|
| Config options | `fulilian config edit` · [Configuration docs](https://hermes-agent.nousresearch.com/docs/user-guide/configuration) |
| Tools / toolsets | `fulilian tools list` · [Tools reference](https://hermes-agent.nousresearch.com/docs/reference/tools-reference) |
| Skills catalog | `fulilian skills browse` · [Skills catalog](https://hermes-agent.nousresearch.com/docs/reference/skills-catalog) |
| Provider setup | `fulilian model` · [Providers guide](https://hermes-agent.nousresearch.com/docs/integrations/providers) |
| Env variables | `fulilian config env-path` · [Env vars reference](https://hermes-agent.nousresearch.com/docs/reference/environment-variables) |
| Gateway logs | `~/.fulilian/logs/gateway.log` (or `fulilian logs`) |
| Sessions | `fulilian sessions browse` (reads state.db) |
