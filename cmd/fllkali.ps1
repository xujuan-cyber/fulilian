# ============================================================================
# FuLiLian CMD Edition - fllkali.ps1   (the single implementation)
# ============================================================================
# PowerShell frontend for FuLiLian running inside WSL, reached as `fllkali` (or
# `fuliliankali`). This file owns ALL of the launcher logic; fllkali.bat /
# fllkali.cmd are thin shims that call into it.
#
# WHY THE SEPARATE NAME. In a Windows CMD window, `fll` and `fulilian` are the
# NATIVE Windows fulilian - scripts\install.ps1 installs those. This launcher is
# the other door: it hands the command to the fulilian installed inside WSL. Two
# different programs under one name would be a coin flip, so the WSL door is
# named apart: `fllkali` / `fuliliankali`. Inside WSL nothing changes - `fll`
# there is still the ordinary command this launcher execs.
#
# Usage:
#   .\fllkali.ps1                     interactive session
#   .\fllkali.ps1 --version
#   .\fllkali.ps1 --tui -z "solve the challenge in C:\ctf\1"
#
# Configuration:
#   $env:FLLKALI_DISTRO              WSL distro name for -d (default: WSL's default)
#   $env:FLLKALI_BIN                 absolute fll path inside WSL (default: probe)
#   $env:FLLKALI_QUIET=1             hide the banner line
#   $env:FLLKALI_DEBUG               print resolved values + exit code
#   $env:FLLKALI_NO_PATH_TRANSLATE=1 do not rewrite Windows paths to /mnt/...
#
# ---------------------------------------------------------------------------
# Design notes (hard-won, each one cost a real debugging session):
#
# * ARGUMENT FIDELITY. `wsl.exe --exec <bin> arg1 arg2` preserves argument
#   boundaries correctly - but ONLY when the caller hands wsl.exe a real argv.
#   cmd.exe cannot do that: text substituted by `%*` is not re-tokenised for
#   quoting, so `fllkali.bat "C:\Program Files\x"` used to arrive as three
#   arguments with the quote characters intact. PowerShell's parser DOES
#   re-tokenise correctly, which is the entire reason this file exists and
#   fllkali.bat delegates here.
#
# * NO SHELL LAYER. Inserting `sh -c 'exec "$@"' sh <bin>` in front of the
#   binary re-splits space-containing arguments (verified: `"a b"` arrives as
#   two args). The binary must be exec'd directly, which in turn means its
#   path must be resolved to an absolute one up front - `wsl --exec` does NOT
#   search PATH (`execvpe(fll) failed`), and ~/.local/bin is not on the PATH
#   of a non-login exec anyway.
#
# * STDIN IS PRECIOUS. Every `wsl.exe` invocation inherits the caller's stdin
#   and drains it on exit. A probe call before the real launch therefore left
#   the agent with an immediate EOF - piped input was lost and an interactive
#   REPL could swallow buffered keystrokes. All probes here go through
#   Invoke-WslSh, which shields stdin with `< nul`; only the final launch is
#   allowed to own it.
#
# * `wsl -l -v` emits UTF-16LE with NUL bytes that break matching in Windows
#   PowerShell 5.1, so this launcher never parses it: wsl.exe resolves its own
#   default distro when -d is not given.
#
# * PS double-quoted strings interpolate $HOME/$? BEFORE WSL sees them; every
#   shell snippet handed to WSL is therefore built from single-quoted strings,
#   and values that must reach WSL verbatim are passed as arguments, never
#   interpolated into the script text.
# ============================================================================

$ErrorActionPreference = 'Continue'   # 'Stop' turns wsl stderr noise into terminating NativeCommandError

function Write-FllError([string]$Message) {
    [Console]::Error.WriteLine("[fllkali] $Message")
}

# --- Resolve WSL -------------------------------------------------------------
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    Write-FllError "ERROR: wsl.exe not found. Install WSL2 first: wsl --install"
    exit 1
}

# --- Build the wsl invocation (with or without -d) -----------------------------
$wslArgs = @()
if ($env:FLLKALI_DISTRO) { $wslArgs = @('-d', $env:FLLKALI_DISTRO) }

# --- Probe helper: run a shell snippet inside WSL with stdin shielded ----------
# `< nul` is what keeps a probe from consuming the caller's stdin; without it
# every probe steals the input that belongs to the real launch (see notes).
# Output is returned as a string array; callers take the first line.
function Invoke-WslSh([string]$ShCommand) {
    $distro = ''
    if ($env:FLLKALI_DISTRO) { $distro = ' -d "' + ($env:FLLKALI_DISTRO -replace '"', '') + '"' }
    $cmdLine = 'wsl.exe' + $distro + ' --exec sh -c "' + $ShCommand + '" < nul 2>nul'
    return (& cmd.exe /c $cmdLine 2>$null)
}

# Resolve a shell expression to the path it names, or $null when not executable.
function Resolve-WslBin([string]$ShPathExpr) {
    $out = Invoke-WslSh ('test -x ' + $ShPathExpr + ' && echo ' + $ShPathExpr)
    if (-not $out) { return $null }
    $first = ([string]($out | Select-Object -First 1)).Trim()
    if ($first) { return $first }
    return $null
}

# --- Resolve fll inside the distro (returns an ABSOLUTE path) ------------------
$bin = $null
if ($env:FLLKALI_BIN) {
    # Never interpolate this value into a shell string unquoted - validate the
    # charset first so a crafted FLLKALI_BIN cannot inject a command.
    if ($env:FLLKALI_BIN -notmatch '^[A-Za-z0-9._/@,+=:-]+$') {
        Write-FllError "ERROR: FLLKALI_BIN contains characters that are not allowed in a path."
        Write-FllError "       Got: $($env:FLLKALI_BIN)"
        exit 1
    }
    if (-not (Resolve-WslBin ("'" + $env:FLLKALI_BIN + "'"))) {
        Write-FllError "ERROR: FLLKALI_BIN='$($env:FLLKALI_BIN)' is not executable in WSL."
        exit 1
    }
    $bin = $env:FLLKALI_BIN
} else {
    foreach ($pathExpr in @('$HOME/.local/bin/fll', '/usr/local/bin/fll')) {
        $bin = Resolve-WslBin $pathExpr
        if ($bin) { break }
    }
    if (-not $bin) {
        Write-FllError "ERROR: fulilian not found in WSL."
        Write-FllError "       Looked for: ~/.local/bin/fll, /usr/local/bin/fll"
        Write-FllError "       Fix: install fulilian inside WSL, or pin the path:"
        Write-FllError "         setx FLLKALI_BIN /home/you/.local/bin/fll"
        exit 1
    }
}

if ($env:FLLKALI_QUIET -ne '1') {
    # Distro name from inside WSL - no UTF-16 parsing on this side.
    $distroName = (Invoke-WslSh 'echo ${WSL_DISTRO_NAME:-default}' | Select-Object -First 1)
    $distroName = ([string]$distroName).Trim()
    if (-not $distroName) { $distroName = 'default' }
    Write-Host "[fllkali] distro: $distroName  bin: $bin"
}

# --- Windows -> WSL path translation ------------------------------------------
# Only arguments that START with a Windows path shape are rewritten, so a
# prompt like "分析一下这个文件" passes through untouched. Set
# FLLKALI_NO_PATH_TRANSLATE=1 to switch this off entirely.
#
#   C:\Users\me\a.bin         -> /mnt/c/Users/me/a.bin
#   C:/Users/me/a.bin         -> /mnt/c/Users/me/a.bin
#   D:                        -> /mnt/d
#   \\wsl.localhost\kali\home\x  -> /home/x
#   \\wsl$\kali\home\x           -> /home/x
function ConvertTo-WslPath([string]$Value) {
    if ($env:FLLKALI_NO_PATH_TRANSLATE -eq '1') { return $Value }
    if ($Value -match '^([A-Za-z]):[\\/](.*)$') {
        return '/mnt/' + $Matches[1].ToLower() + '/' + ($Matches[2] -replace '\\', '/')
    }
    if ($Value -match '^([A-Za-z]):$') {
        return '/mnt/' + $Matches[1].ToLower()
    }
    if ($Value -match '^\\\\wsl(?:\.localhost|\$)\\[^\\]+\\(.*)$') {
        return '/' + ($Matches[1] -replace '\\', '/')
    }
    return $Value
}

$forward = @()
foreach ($a in $args) {
    $forward += (ConvertTo-WslPath $a)
}

# --- Launch: forward arguments verbatim, one wsl.exe call, no shell layer ------
# The binary is exec'd directly (see notes) - this is the only invocation that
# is allowed to inherit stdin.
& wsl.exe @wslArgs --exec $bin @forward
$code = $LASTEXITCODE

if ($env:FLLKALI_DEBUG) {
    Write-FllError "debug: exit=$code bin=$bin args=$($forward.Count)"
}
exit $code
