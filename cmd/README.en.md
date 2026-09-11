# FuLiLian — Windows CMD frontend (`fllkali`)

Lets Windows CMD (and PowerShell) run the full FuLiLian inside WSL as `fllkali`. **Execution still happens in WSL**, so config, sessions, skills and logs are identical to running inside WSL. This is a frontend, not a second implementation.

## Get the names straight first

There are **two fulilian installs on Windows**, each with its own entry points. The names are deliberately kept apart:

| Where | Type | What actually runs |
|---|---|---|
| **CMD** | `fll`, `fulilian` | The **native Windows** fulilian (installed by `scripts\install.cmd` into `%FULILIAN_HOME%\bin`) |
| **CMD** | `fllkali`, `fuliliankali` | The fulilian **inside WSL**, through the forwarder in this directory |
| **WSL** | `fll`, `fulilian` | The fulilian inside WSL (untouched by this directory — byte-for-byte the behaviour you had) |

The `kali` suffix means "the WSL door". Both installs coexist; there is no name collision, because **this directory no longer puts `fll` on PATH** and so can never shadow the native one.

## Pick your path first

This repository ships **two different `install.cmd` files**, and picking the wrong one wastes your time:

| What you want | Which installer | What it installs |
|---|---|---|
| **Type `fllkali` / `fuliliankali` in CMD and actually run the fulilian inside WSL** | `cmd\install.cmd` (this directory) | Six launchers into `%USERPROFILE%\bin`. Does not install fulilian itself — WSL must already have it. |
| **Run fulilian natively on Windows, no WSL** | [`scripts\install.cmd`](../scripts/install.cmd) | The native Windows fulilian itself (uv / Python / Node / PortableGit), and puts `fll` / `fulilian` on PATH |

The two can coexist: the `fllkali` installed by `cmd\install.cmd` only hands you off to WSL and never touches the native install. **Delegating to WSL is the whole point of this directory** — it will not, and should not, guess whether you meant native or WSL.

## Components

| File | Purpose |
|---|---|
| `fllkali.bat` | CMD entry point: UTF-8 code page switch/restore, delegates to `fllkali.ps1`; degraded fallback when PowerShell is absent |
| `fllkali.cmd` | Alias of `fllkali.bat`, for hosts whose PATHEXT omits `.BAT` |
| `fuliliankali.bat` | Alias of `fllkali.bat`, so the long name works too |
| `fuliliankali.cmd` | Alias of `fllkali.bat`, same reason as `fllkali.cmd` |
| `fllkali.ps1` | **The real logic**: WSL and `fll` path probing, Windows path → `/mnt/...` rewriting, argument forwarding |
| `fllkali.completion.ps1` | PowerShell Tab completion; `-Install` / `-Uninstall` read and write `$PROFILE` |
| `install.cmd` | Installer: copies launchers to `%USERPROFILE%\bin`, idempotent USER PATH append, self-check; supports `/check`, `/uninstall`, `/no-profile` |

## Why the real logic lives in `fllkali.ps1`, not `fllkali.bat`

cmd.exe **cannot forward arguments faithfully**. `%*` is text substitution and is not re-tokenised, so `wsl.exe --exec <bin> %*` splits every quoted argument containing a space (`"C:\Program Files\x"` arrives as three arguments with the quote characters kept) and mangles CJK arguments. Windows PowerShell's parser re-tokenises correctly, so probing, path rewriting and argument forwarding all live in `fllkali.ps1`; `fllkali.bat` only hands it the argument text.

The `:no_powershell` branch in `fllkali.bat` is a degraded path for hosts without PowerShell: interactive use and simple arguments are fine, but arguments containing spaces, quotes or CJK may be split or garbled — which is exactly why `fllkali.ps1` exists.

## Install (from CMD)

```bat
git clone https://github.com/xujuan-cyber/fulilian.git
cd fulilian\cmd
install.cmd
```

Open a **new** CMD window, then verify from any directory:

```bat
fllkali --version
```

`install.cmd /check` reports without changing anything; `/no-profile` skips the `$PROFILE` write; `/uninstall` reverses everything (completion and PATH included).

## Usage

```bat
fllkali                        :: interactive session
fllkali --version
fllkali solve C:\ctf\chall     :: Windows paths are rewritten to /mnt/c/ctf/chall
fllkali <any fll args...>      :: all subcommands/args forwarded verbatim
fuliliankali <any fll args...> :: the same command under its long name
```

`fllkali` and `fuliliankali` are two names for one entry point: the installer ships both, and argument and exit-code handling is identical. The rest of this document says `fllkali`; substitute `fuliliankali` freely.

> What is forwarded finally reaches `fll` inside WSL, so subcommands, `--flags` and behaviour are exactly what you get typing `fll` in WSL.

### Do you get the TUI or the classic REPL?

fulilian picks the interface from terminal capability; this frontend does not choose for you (see `_resolve_use_tui` in `fulilian_cli/main.py`):

- **Ink TUI** — requires stdin **and** stdout to both be terminals.
- **Classic REPL** — the automatic fallback when either is not. It never hangs.
- To force it: `fllkali --cli` always runs the classic REPL; `fllkali --tui` forces the TUI and prints a clear message instead of hanging when the terminal cannot host it.

A pipe is not a terminal, so `fllkali > log` and `fllkali | more` take the classic REPL. That is deliberate: the TUI's only move on a non-terminal is to print `no TTY` and exit, which would hand scripted callers an empty result.

To see which one your machine actually gets, run a bare `fllkali` in CMD and look for a full-screen bordered TUI versus the line-oriented `╭─…╮` banner.

PowerShell side:

```powershell
fllkali                        :: available on PATH after install
.\fllkali.ps1 -z "prompt"      :: or use the ps1 explicitly (safer quoting)
```

**Tab completion** (PowerShell): `install.cmd` runs `fllkali.completion.ps1 -Install` to wire it into `$PROFILE`, completing `fllkali` / `fuliliankali`. The word list is **static** — the real parser lives inside WSL, and asking it on every Tab press would cost a WSL round trip plus interpreter start (about a second). When the CLI grows a subcommand, update the list in `fllkali.completion.ps1`; that list is the only part of that file that can go stale. Raw cmd.exe has no completion hook of its own — that needs clink, which is out of scope here.

## Configuration (optional environment variables)

| Variable | Meaning | Default |
|---|---|---|
| `FLLKALI_DISTRO` | Pin the WSL distro | auto (no `-d`; wsl.exe uses its own default) |
| `FLLKALI_BIN` | Pin the fll path inside WSL | probes `~/.local/bin/fll`, then `/usr/local/bin/fll` |
| `FLLKALI_QUIET` | `1` hides the `[fllkali] distro: ...` banner | unset |
| `FLLKALI_DEBUG` | any value prints exit code and resolved values | unset |
| `FLLKALI_NO_PATH_TRANSLATE` | `1` disables Windows path → `/mnt/...` rewriting | unset |

Example:

```bat
setx FLLKALI_DISTRO Ubuntu-24.04
setx FLLKALI_BIN /home/me/.local/bin/fll
```

(The `KALI` in the variable names keeps the two installs' configuration separate — same-named settings on the native side do not interfere.)

## Design notes

- **Why WSL**: FuLiLian's full capability set (CTF toolchain, plugins, `~/.fulilian/` config) lives in WSL. The CMD frontend keeps both sides identical instead of building a second stack.
- **Exit codes** are forwarded from `wsl.exe --exec`, so scripted calls are reliable.
- **Code page**: switches to UTF-8 (65001) for correct box-drawing/CJK output, restores the previous page on exit.
- **Idempotent PATH**: `install.cmd` only appends `%USERPROFILE%\bin` when missing; repeated installs are no-ops. Note `setx` truncates PATH beyond 1024 chars.
- **UNC notice**: if CMD starts in a `\\wsl.localhost\...` directory, CMD itself prints a UNC warning and falls back to a Windows directory. That comes from CMD, not this tool; it is harmless.

## Prerequisites

- Windows 10/11 + WSL2 with at least one distro (kali-linux, Ubuntu, ...)
- FuLiLian installed inside WSL (see the repository root `README.md`)
