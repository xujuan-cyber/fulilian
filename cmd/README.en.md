# FuLiLian — Windows CMD frontend

Lets Windows CMD (and PowerShell) treat `fll` as a native command. **Execution still happens inside the full FuLiLian installation in WSL**, so config, sessions, skills and logs are identical to running inside WSL. This is a frontend, not a second implementation.

## Pick your path first

This repository ships **two different `install.cmd` files**, and picking the wrong one wastes your time:

| What you want | Which installer | What it installs |
|---|---|---|
| **Type `fll` in CMD, actually run the fulilian inside WSL** | `cmd\install.cmd` (this directory) | Four launchers into `%USERPROFILE%\bin`. Does not install fulilian itself — WSL must already have it. |
| **Run fulilian natively on Windows, no WSL** | [`scripts\install.cmd`](../scripts/install.cmd) | The native Windows fulilian itself (uv / Python / Node / PortableGit) |

The two can coexist: the `fll` installed by `cmd\install.cmd` only hands you off to WSL and never touches the native install. **Delegating to WSL is the whole point of this directory** — it will not, and should not, guess whether you meant native or WSL.

## Components

| File | Purpose |
|---|---|
| `fll.bat` | CMD entry point: UTF-8 code page switch/restore, delegates to `fll.ps1`; degraded fallback when PowerShell is absent |
| `fll.cmd` | Alias of `fll.bat`, for hosts whose PATHEXT omits `.BAT` |
| `fll.ps1` | **The real logic**: WSL and `fll` path probing, Windows path → `/mnt/...` rewriting, argument forwarding |
| `fll.completion.ps1` | PowerShell Tab completion; `-Install` / `-Uninstall` read and write `$PROFILE` |
| `install.cmd` | Installer: copies launchers to `%USERPROFILE%\bin`, idempotent USER PATH append, self-check; supports `/check`, `/uninstall`, `/no-profile` |

## Why the real logic lives in `fll.ps1`, not `fll.bat`

cmd.exe **cannot forward arguments faithfully**. `%*` is text substitution and is not re-tokenised, so `wsl.exe --exec <bin> %*` splits every quoted argument containing a space (`"C:\Program Files\x"` arrives as three arguments with the quote characters kept) and mangles CJK arguments. Windows PowerShell's parser re-tokenises correctly, so probing, path rewriting and argument forwarding all live in `fll.ps1`; `fll.bat` only hands it the argument text.

The `:no_powershell` branch in `fll.bat` is a degraded path for hosts without PowerShell: interactive use and simple arguments are fine, but arguments containing spaces, quotes or CJK may be split or garbled — which is exactly why `fll.ps1` exists.

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

`install.cmd /check` reports without changing anything; `/no-profile` skips the `$PROFILE` write; `/uninstall` reverses everything (completion and PATH included).

## Usage

```bat
fll                        :: interactive session
fll --version
fll solve C:\ctf\chall     :: Windows paths are rewritten to /mnt/c/ctf/chall
fll <any fll args...>      :: all subcommands/args forwarded verbatim
```

### Do you get the TUI or the classic REPL?

fulilian picks the interface from terminal capability; this frontend does not choose for you (see `_resolve_use_tui` in `fulilian_cli/main.py`):

- **Ink TUI** — requires stdin **and** stdout to both be terminals.
- **Classic REPL** — the automatic fallback when either is not. It never hangs.
- To force it: `fll --cli` always runs the classic REPL; `fll --tui` forces the TUI and prints a clear message instead of hanging when the terminal cannot host it.

A pipe is not a terminal, so `fll > log` and `fll | more` take the classic REPL. That is deliberate: the TUI's only move on a non-terminal is to print `no TTY` and exit, which would hand scripted callers an empty result.

To see which one your machine actually gets, run a bare `fll` in CMD and look for a full-screen bordered TUI versus the line-oriented `╭─…╮` banner.

PowerShell side:

```powershell
fll                        :: available on PATH after install
.\fll.ps1 -z "prompt"      :: or use the ps1 explicitly (safer quoting)
```

**Tab completion** (PowerShell): `install.cmd` runs `fll.completion.ps1 -Install` to wire it into `$PROFILE`. The word list is **static** — the real parser lives inside WSL, and asking it on every Tab press would cost a WSL round trip plus interpreter start (about a second). When the CLI grows a subcommand, update the list in `fll.completion.ps1`; that list is the only part of that file that can go stale. Raw cmd.exe has no completion hook of its own — that needs clink, which is out of scope here.

## Configuration (optional environment variables)

| Variable | Meaning | Default |
|---|---|---|
| `FLL_DISTRO` | Pin the WSL distro | auto (no `-d`; wsl.exe uses its own default) |
| `FLL_BIN` | Pin the fll path inside WSL | probes `~/.local/bin/fll`, then `/usr/local/bin/fll` |
| `FLL_QUIET` | `1` hides the `[fll] distro: ...` banner | unset |
| `FLL_DEBUG` | any value prints exit code and resolved values | unset |
| `FLL_NO_PATH_TRANSLATE` | `1` disables Windows path → `/mnt/...` rewriting | unset |

## Design notes

- **Why WSL**: FuLiLian's full capability set (CTF toolchain, plugins, `~/.fulilian/` config) lives in WSL. The CMD frontend keeps both sides identical instead of building a second stack.
- **Exit codes** are forwarded from `wsl.exe --exec`, so scripted calls are reliable.
- **Code page**: switches to UTF-8 (65001) for correct box-drawing/CJK output, restores the previous page on exit.
- **Idempotent PATH**: `install.cmd` only appends `%USERPROFILE%\bin` when missing; repeated installs are no-ops. Note `setx` truncates PATH beyond 1024 chars.
- **UNC notice**: if CMD starts in a `\\wsl.localhost\...` directory, CMD itself prints a UNC warning and falls back to a Windows directory. That comes from CMD, not this tool; it is harmless.

## Prerequisites

- Windows 10/11 + WSL2 with at least one distro (kali-linux, Ubuntu, ...)
- FuLiLian installed inside WSL (see the repository root `README.md`)
