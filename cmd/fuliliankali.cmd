@echo off
setlocal EnableExtensions

rem ============================================================================
rem FuLiLian CMD Edition - fuliliankali.cmd
rem ============================================================================
rem Alias for fllkali.bat, so the long name works in CMD exactly as the short one -
rem including on hosts whose PATHEXT omits .BAT, which is why there is a .cmd
rem twin of fuliliankali.bat next to it. Both call fllkali.bat with an explicit
rem extension, so neither depends on PATHEXT or on the other resolving.
rem
rem This file holds NO logic of its own, for the same reason fllkali.cmd does not.
rem fllkali.bat -> fllkali.ps1 is the one code path that probes WSL, rewrites Windows
rem paths and forwards the argument text; a copy here would be a second code
rem path, and the two would eventually disagree. Expect the `[fllkali]` prefix on
rem the messages below - `fllkali` is the canonical name, and the tag is the same
rem one every file in this directory uses.
rem
rem See fllkali.bat and fllkali.ps1 for the configuration variables (FLLKALI_DISTRO,
rem FLLKALI_BIN, FLLKALI_QUIET, FLLKALI_DEBUG, FLLKALI_NO_PATH_TRANSLATE) and the design notes.
rem ============================================================================

set "FLLKALI_BAT=%~dp0fllkali.bat"
if not exist "%FLLKALI_BAT%" (
    echo [fllkali] ERROR: fllkali.bat not found next to fuliliankali.cmd. >&2
    echo [fllkali]        Reinstall with cmd\install.cmd >&2
    exit /b 1
)

call "%FLLKALI_BAT%" %*
exit /b %ERRORLEVEL%
