@echo off
setlocal EnableExtensions

rem ============================================================================
rem FuLiLian CMD Edition - fll.cmd
rem ============================================================================
rem Alias for fll.bat. Some hosts have a PATHEXT that omits .BAT, or a policy
rem that treats .cmd differently from .bat; shipping both means `fll` resolves
rem either way. This file deliberately holds NO logic of its own - it calls the
rem sibling fll.bat with an explicit extension (so the lookup does not depend
rem on PATHEXT), and the argument text is passed through untouched for fll.bat
rem to hand to fll.ps1.
rem
rem See fll.bat / fll.ps1 for the configuration variables and design notes.
rem ============================================================================

set "FLL_BAT=%~dp0fll.bat"
if not exist "%FLL_BAT%" (
    echo [fll] ERROR: fll.bat not found next to fll.cmd. >&2
    echo [fll]        Reinstall with cmd\install.cmd >&2
    exit /b 1
)

call "%FLL_BAT%" %*
exit /b %ERRORLEVEL%
