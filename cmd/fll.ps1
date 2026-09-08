# ============================================================================
# FuLiLian CMD Edition - fll.ps1
# ============================================================================
# PowerShell frontend for FuLiLian running inside WSL. Prefer this over
# fll.bat when passing arguments containing quotes, parentheses, or CJK.
#
# Usage:
#   .\fll.ps1                     interactive session
#   .\fll.ps1 --version
#   .\fll.ps1 --tui -z "solve the challenge in /tmp/ctf1"
#
# Configuration:
#   $env:FLL_DISTRO   WSL distro name for -d   (default: WSL's default distro)
#   $env:FLL_BIN      absolute fll path inside WSL (default: auto-probe)
#   $env:FLL_QUIET    set to 1 to hide the banner line
#
# Exit codes are forwarded from WSL so scripts can rely on them.
#
# Design notes (hard-won):
# - `wsl -l -v` emits UTF-16LE with NUL bytes that break matching in Windows
#   PowerShell 5.1, so this launcher never parses it: wsl.exe resolves the
#   default distro itself when -d is not given.
# - PS double-quoted strings interpolate $HOME/$? BEFORE WSL sees them; all
#   shell snippets passed to WSL are built with single-quoted strings.
# - wsl --exec does NOT go through a shell, so the launched binary must be an
#   absolute path; $HOME expansion happens only inside `sh -lc` probes.
# ============================================================================

$ErrorActionPreference = 'Continue'   # 'Stop' turns wsl stderr noise into terminating NativeCommandError

function Write-FllError([string]$Message) {
    [Console]::Error.WriteLine("[fll] $Message")
}

# --- Resolve WSL -------------------------------------------------------------
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    Write-FllError "ERROR: wsl.exe not found. Install WSL2 first: wsl --install"
    exit 1
}

# --- Build the wsl invocation (with or without -d) -----------------------------
$wslArgs = @()
if ($env:FLL_DISTRO) { $wslArgs = @('-d', $env:FLL_DISTRO) }

# --- Probe fll inside the distro (returns an ABSOLUTE path) --------------------
$bin = $env:FLL_BIN
if ($bin) {
    $null = & wsl.exe @wslArgs --exec sh -lc ('test -x ' + $bin) 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-FllError "ERROR: FLL_BIN='$bin' is not executable in WSL."
        exit 1
    }
} else {
    foreach ($pathExpr in @('$HOME/.local/bin/fll', '/usr/local/bin/fll')) {
        $null = & wsl.exe @wslArgs --exec sh -lc ('test -x ' + $pathExpr) 2>$null
        if ($LASTEXITCODE -eq 0) {
            $bin = (& wsl.exe @wslArgs --exec sh -lc ('echo ' + $pathExpr) 2>$null | Select-Object -First 1)
            if ($bin) { $bin = ([string]$bin).Trim(); break }
        }
    }
    if (-not $bin) {
        Write-FllError "ERROR: fulilian not found in WSL."
        Write-FllError "       Fix: install fulilian inside WSL, or pin: `$env:FLL_BIN='/home/you/.local/bin/fll'"
        exit 1
    }
}

if ($env:FLL_QUIET -ne '1') {
    # Distro name from inside WSL - no UTF-16 parsing on this side.
    $distroName = (& wsl.exe @wslArgs --exec sh -lc 'echo ${WSL_DISTRO_NAME:-default}' 2>$null | Select-Object -First 1)
    $distroName = ([string]$distroName).Trim()
    Write-Host "[fll] distro: $distroName  bin: $bin"
}

# --- Launch: forward all arguments verbatim -----------------------------------
& wsl.exe @wslArgs --exec $bin @args
exit $LASTEXITCODE
