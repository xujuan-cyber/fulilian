# ============================================================================
# FuLiLian CMD Edition - fll.completion.ps1
# ============================================================================
# Tab completion for `fll` in Windows PowerShell / PowerShell 7.
#
#   . .\fll.completion.ps1              load for the current session only
#   .\fll.completion.ps1 -Install       wire into $PROFILE (idempotent)
#   .\fll.completion.ps1 -Uninstall     remove that wiring again
#
# cmd\install.cmd calls -Install for you (pass /no-profile to skip it) and
# /uninstall reverses it. Loading it by hand just needs the dot-source line.
#
# ---------------------------------------------------------------------------
# NOTE ON DRIFT. The subcommand list below mirrors `fll --help`. It is a static
# list on purpose: the real parser lives inside WSL, and asking it on every Tab
# press would cost a WSL round trip plus an interpreter start (about a second)
# per keystroke. When the CLI grows a subcommand, add it here too - the list is
# the only thing in this file that can go stale.
#
# Raw cmd.exe has no completion hook of its own; there, completion needs clink
# (https://chrisant996.github.io/clink/), which is out of scope here. This file
# is for the PowerShell prompt.
# ============================================================================

[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Uninstall
)

$script:FllSubcommands = @(
    'chat', 'model', 'moa', 'fallback', 'worktree', 'browser', 'secrets',
    'egress', 'migrate', 'gateway', 'proxy', 'lsp', 'setup', 'whatsapp',
    'whatsapp-cloud', 'slack', 'send', 'login', 'logout', 'auth', 'status',
    'pause', 'resume', 'cron', 'sync', 'webhook', 'peer', 'kanban', 'project',
    'hooks', 'doctor', 'verify', 'security', 'approvals', 'dump', 'debug',
    'backup', 'checkpoints', 'import', 'import-agent', 'config', 'skin',
    'console', 'pairing', 'skills', 'bundles', 'plugins', 'curator', 'pets',
    'journey', 'learning', 'memory-graph', 'memory', 'tools', 'computer-use',
    'mcp', 'sessions', 'insights', 'monitoring', 'claw', 'update', 'uninstall',
    'acp', 'profile', 'completion', 'dashboard', 'serve', 'desktop', 'gui',
    'logs', 'prompt-size', 'solve', 'solve-all', 'writeup', 'replay',
    'knowledge', 'ctfd'
)

$script:FllFlags = @(
    '-h', '--help', '--version', '-z', '--usage-file', '-m', '--provider',
    '--reasoning', '-t', '--resume', '--no-restore-cwd', '--in', '--continue',
    '--worktree', '--accept-hooks', '--skills', '--yolo', '--pass-session-id',
    '--ignore-user-config', '--ignore-rules', '--safe-mode', '--tui', '--cli',
    '--dev'
)

# Subcommands whose first argument is itself a verb, so that the second Tab
# press is useful too. Only ones with a stable, small verb set are listed.
$script:FllSubSubcommands = @{
    'sessions' = @('list', 'show', 'export', 'delete', 'prune')
    'memory'   = @('search', 'add', 'list', 'forget')
    'skills'   = @('list', 'search', 'show', 'sync')
    'plugins'  = @('list', 'enable', 'disable', 'info')
    'config'   = @('get', 'set', 'list', 'edit')
    'cron'     = @('list', 'add', 'remove', 'run')
    'model'    = @('list', 'set', 'show')
    'gateway'  = @('start', 'stop', 'status', 'restart')
    'tools'    = @('list', 'enable', 'disable')
}

$script:FllCompletionBlock = {
    param($wordToComplete, $commandAst, $cursorPosition)

    $els = @($commandAst.CommandElements)
    $names = @($els | ForEach-Object { $_.ToString() })
    # Drop the leading command name itself.
    $seen = @()
    if ($names.Count -gt 1) { $seen = @($names[1..($names.Count - 1)]) }

    # The token under the cursor is the final element only when the cursor sits
    # inside it. After a typed space (`fll sessions <TAB>`) the cursor is past
    # that element's end, so every seen token is already a preceding one - this
    # distinction is what makes the second Tab press complete the right set.
    $cursorInsideLast = $false
    if ($els.Count -gt 1) {
        $cursorInsideLast = ($els[$els.Count - 1].Extent.EndOffset -ge $cursorPosition)
    }

    $preceding = $seen
    if ($cursorInsideLast) {
        # NB: $seen[0..-1] selects first AND last in PowerShell, so the
        # single-element case must be handled explicitly.
        if ($seen.Count -le 1) { $preceding = @() }
        else { $preceding = @($seen[0..($seen.Count - 2)]) }
    }

    $candidates = @()
    $positional = @($preceding | Where-Object { $_ -and -not $_.StartsWith('-') })

    if ($positional.Count -eq 0) {
        # First non-flag token: the subcommands, plus the flags.
        $candidates = $FllSubcommands + $FllFlags
    } elseif ($positional.Count -eq 1 -and $FllSubSubcommands.ContainsKey($positional[0])) {
        # Second token of a known two-level subcommand: its verbs, plus flags.
        $candidates = $FllSubSubcommands[$positional[0]] + $FllFlags
    } else {
        $candidates = $FllFlags
    }

    $candidates |
        Where-Object { $_ -like "$wordToComplete*" } |
        Sort-Object -Unique |
        ForEach-Object {
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
        }
}

# --- $PROFILE wiring ---------------------------------------------------------
# Idempotent in both directions: the marker comment is what identifies our line.
$script:FllProfileMarker = '# fulilian-cmd completion'
$script:FllProfileLine = '. "$env:USERPROFILE\bin\fll.completion.ps1"'

if ($Install) {
    $profileDir = Split-Path -Parent $PROFILE
    if ($profileDir -and -not (Test-Path -LiteralPath $profileDir)) {
        New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
    }
    if (-not (Test-Path -LiteralPath $PROFILE)) {
        New-Item -ItemType File -Path $PROFILE -Force | Out-Null
    }
    $existing = @(Get-Content -LiteralPath $PROFILE -ErrorAction SilentlyContinue)
    if ($existing -match [regex]::Escape($script:FllProfileMarker)) {
        Write-Host "[fll] completion already wired into $PROFILE"
    } else {
        Add-Content -LiteralPath $PROFILE -Value ''
        Add-Content -LiteralPath $PROFILE -Value $script:FllProfileMarker
        Add-Content -LiteralPath $PROFILE -Value $script:FllProfileLine
        Write-Host "[fll] completion wired into $PROFILE"
    }
    Write-Host "[fll] reload with:  . `$PROFILE"
    # `return`, never `exit`: this file is meant to be dot-sourced, and `exit`
    # in a dot-sourced script tears down the caller's whole session.
    # NB: $PROFILE is host-specific - Windows PowerShell 5.1 and PowerShell 7
    # each read their own file, so run -Install once under each.
    return
}

if ($Uninstall) {
    if (Test-Path -LiteralPath $PROFILE) {
        $kept = @(Get-Content -LiteralPath $PROFILE -ErrorAction SilentlyContinue |
            Where-Object { $_ -ne $script:FllProfileMarker -and $_ -ne $script:FllProfileLine })
        Set-Content -LiteralPath $PROFILE -Value $kept
        Write-Host "[fll] completion unwired from $PROFILE"
    } else {
        Write-Host "[fll] no profile at $PROFILE - nothing to unwire"
    }
    return
}

# `fll` is the command on the Windows side; `fulilian` is the same entry point,
# registered too so an alias or a hand-made shim still completes.
Register-ArgumentCompleter -Native -CommandName fll, fulilian -ScriptBlock $script:FllCompletionBlock
