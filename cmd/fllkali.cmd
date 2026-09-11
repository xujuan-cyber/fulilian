@echo off
setlocal EnableExtensions

rem ============================================================================
rem FuLiLian CMD Edition - fllkali.cmd
rem ============================================================================
rem Alias for fllkali.bat. Some hosts have a PATHEXT that omits .BAT, or a policy
rem that treats .cmd differently from .bat; shipping both means `fll` resolves
rem either way. This file deliberately holds NO logic of its own - it calls the
rem sibling fllkali.bat with an explicit extension (so the lookup does not depend
rem on PATHEXT), and the argument text is passed through untouched for fllkali.bat
rem to hand to fllkali.ps1.
rem
rem See fllkali.bat / fllkali.ps1 for the configuration variables and design notes.
rem ============================================================================

set "FLLKALI_BAT=%~dp0fllkali.bat"
if not exist "%FLLKALI_BAT%" (
    echo [fllkali] ERROR: fllkali.bat not found next to fllkali.cmd. >&2
    echo [fllkali]        Reinstall with cmd\install.cmd >&2
    exit /b 1
)

call "%FLLKALI_BAT%" %*
exit /b %ERRORLEVEL%
