<p align="center">
  <img src="assets/banner.png" alt="FuLiLian" width="100%">
</p>

# FuLiLian ☤
<p align="center">
  <a href="https://github.com/xujuan-cyber/fulilian"><img src="https://img.shields.io/badge/CTF%20%26%20Forensics-Agent%20CLI-339AF0?style=for-the-badge" alt="CTF & Forensics Agent CLI"></a>
  <a href="https://github.com/xujuan-cyber/fulilian/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License: MIT"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/Lang-中文-red?style=for-the-badge" alt="中文"></a>
</p>

**FuLiLian — a dedicated CTF (Capture The Flag) & digital forensics agent CLI.** Tailored for security competitions, forensic analysis, and penetration testing workflows.

Equipped with a scheduling engine, verification gate, and knowledge system, FuLiLian automates repetitive CTF tasks, keeps track of discovered artifacts, and helps you focus on the puzzles that matter.

<table>
<tr><td><b>CTF Challenge Automation</b></td><td>Automated flag extraction, challenge environment setup, toolchain management, and structured writeup generation with evidence attachment.</td></tr>
<tr><td><b>Forensics Analysis</b></td><td>Disk image analysis, memory forensics, log analysis, file carving, and timeline reconstruction — all through natural language commands.</td></tr>
<tr><td><b>Scheduling Engine</b></td><td>Built-in cron scheduler for periodic recon, automated scans, and unattended monitoring. Set it and forget it.</td></tr>
<tr><td><b>Verification Gate</b></td><td>Multi-step approval workflows for potentially destructive operations. Safe to run in production environments.</td></tr>
<tr><td><b>Knowledge System</b></td><td>Persistent memory across sessions. Automatically captures discovered flags, exploited vulnerabilities, and forensic artifacts for cross-session recall.</td></tr>
<tr><td><b>Multi-Platform</b></td><td>Telegram, Discord, Slack, WhatsApp, and CLI — all from a single gateway process. Monitor your CTF progress from your phone.</td></tr>
<tr><td><b>Runs Anywhere</b></td><td>Local, Docker, SSH, or cloud VPS. Your agent environment persists across sessions.</td></tr>
</table>

## Fork Highlights

Beyond the core agent foundation, FuLiLian adds a CTF-focused layer:

- **Multi-agent solving** — racer/relay orchestration with six language specialists (crypto, pwn, reverse, web, forensics, misc), timeboxing, and stop-loss controls.
- **Verification gate** — flag-shaped candidate validation with grounding checks before an answer is accepted.
- **CTF knowledge cards** — curated exam-point cards per category (`skills/ctf-knowledge/`), plus a strategy playbook, reusable snippets, and extraction tooling for building cards from past writeups.
- **Context compression tuning** — anchor-index retention, segmented compression, and prune re-arm lockout to survive long, tool-heavy CTF sessions.
- **CLI quality-of-life** — `/workspace` directory switching, `/attach` file attachments, gradient banner, and light-mode color remapping.

## Quick Start

### From source (Linux / macOS / WSL)

```bash
git clone https://github.com/xujuan-cyber/fulilian.git
cd fulilian

# One-shot installer: creates the venv, installs dependencies, seeds bundled
# skills into ~/.fulilian/skills/, and symlinks `fulilian` / `fll` onto PATH
bash setup-fulilian.sh

# Interactive wizard: pick provider + model, write API key, generate
# ~/.fulilian/config.yaml and ~/.fulilian/.env
fulilian setup

# Start a chat session
fulilian chat
```

### Where does the config live?

Cloning the repo gives you **code only** — the runtime data directory is
created on first run, not by `git clone`:

| Path | Created by | Contents |
|------|-----------|----------|
| `~/.fulilian/` | first launch (auto-mkdir: `config.py::ensure_fulilian_home()`) | data dir root |
| `~/.fulilian/config.yaml` | `fulilian setup` wizard (or `fulilian model`) | model provider, display, feature settings |
| `~/.fulilian/.env` | `fulilian setup` / installer | API keys only (chmod 600) |
| `~/.fulilian/skills/` | `setup-fulilian.sh` (seeded from the repo's `skills/`) | bundled skills |
| `~/.fulilian/{sessions,memories,logs,cron,...}/` | first launch (auto) | runtime state |

Set `FULILIAN_HOME` to relocate the data directory; on native Windows it
defaults to `%LOCALAPPDATA%\fulilian`. Uninstalling code (deleting the repo)
never touches `~/.fulilian/`.

### Other install methods

```bash
# One-line remote install (downloads to ~/.fulilian/fulilian-agent)
curl -fsSL https://raw.githubusercontent.com/xujuan-cyber/fulilian/main/scripts/install.sh | bash

# Verify your install
fulilian status
fulilian doctor
```

### Windows CMD frontend

Prefer the Windows CMD terminal? [`cmd/`](cmd/README.en.md) installs a `fll` launcher that runs FuLiLian inside WSL while behaving like a native CMD command — UTF-8 output, verbatim argument and exit-code forwarding, installer with self-check and uninstall:

```bat
git clone https://github.com/xujuan-cyber/fulilian.git
cd fulilian\cmd
install.cmd          :: then open a new CMD window
fll --version
```

This delegates to WSL. To install FuLiLian **natively on Windows** instead (no WSL), use [`scripts\install.cmd`](scripts/install.cmd). See [`cmd/README.en.md`](cmd/README.en.md) for which one you want.

## Documentation

- [GitHub Wiki](https://github.com/xujuan-cyber/fulilian/wiki) — setup guides, CTF workflows, and API reference
- [Issues](https://github.com/xujuan-cyber/fulilian/issues) — bug reports and feature requests

## License

MIT — see [LICENSE](LICENSE).