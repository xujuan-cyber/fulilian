# FuLiLian CMD Edition

**CMD terminal edition** frontend for FuLiLian. Lets Windows CMD (and PowerShell) treat `fll` as a native command — execution still happens inside the full FuLiLian installation in WSL, so config, sessions, skills, and logs are identical to running inside WSL.

## Components

| File | Purpose |
|---|---|
| `fll.bat` | CMD launcher: UTF-8 code page switch/restore, WSL distro & fll probing, verbatim argument forwarding, exit-code forwarding |
| `fll.ps1` | PowerShell launcher: prefer this when arguments contain quotes/parentheses/CJK |
| `install.cmd` | Installer: copies launchers to `%USERPROFILE%\bin`, idempotent USER PATH append, self-check; supports `/check`, `/uninstall` |

## Install (from CMD)

```bat
git clone https://github.com/xujuan-cyber/fulilian.git
cd fulilian\cmd
install.cmd
```

Open a **new** CMD window, then verify from any directory:

```bat
fll --version
```

## Usage

```bat
fll                        :: interactive session
fll --tui                  :: TUI mode
fll solve <...>            :: all subcommands/args forwarded verbatim
fll --version
```

PowerShell side:

```powershell
fll                        :: available on PATH after install
.\fll.ps1 -z "prompt"      :: or use the ps1 explicitly (safer quoting)
```

## Configuration (optional environment variables)

| Variable | Meaning | Default |
|---|---|---|
| `FLL_DISTRO` | Pin the WSL distro | auto-detect (prefers the Running default distro) |
| `FLL_BIN` | Pin the fll path inside WSL | probes `~/.local/bin/fll`, then `/usr/local/bin/fll` |
| `FLL_QUIET` | `1` hides the `[fll] distro: ...` banner | unset |
| `FLL_DEBUG` | any value prints exit code and resolved values | unset |

## Design notes

- **Why WSL**: FuLiLian's full capability set (CTF toolchain, plugins, `~/.fulilian/` config) lives in WSL. The CMD edition is a first-class frontend, not a re-implementation, so both sides behave identically.
- **Exit codes** are forwarded from `wsl --exec`, so scripted calls are reliable.
- **Code page**: switches to UTF-8 (65001) for correct box-drawing/CJK output, restores the previous page on exit.
- **Idempotent PATH**: `install.cmd` only appends `%USERPROFILE%\bin` when missing; repeated installs are no-ops. Note `setx` truncates PATH beyond 1024 chars.
- **UNC notice**: if CMD starts in a `\\wsl.localhost\...` directory, CMD itself prints a UNC warning and falls back to a Windows directory. That comes from CMD, not this tool; it is harmless.

## Prerequisites

- Windows 10/11 + WSL2 with at least one distro (kali-linux, Ubuntu, ...)
- FuLiLian installed inside WSL (see the repository root `README.md`)
