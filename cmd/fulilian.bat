@echo off
setlocal EnableExtensions

rem ============================================================================
rem FuLiLian CMD Edition - fulilian.bat
rem ============================================================================
rem Alias for fll.bat, so the long name works in CMD exactly as the short one:
rem the installer puts both on PATH, and `fulilian --version` behaves identically
rem to `fll --version`.
rem
rem This file holds NO logic of its own, for the same reason fll.cmd does not.
rem fll.bat -> fll.ps1 is the one code path that probes WSL, rewrites Windows
rem paths and forwards the argument text; a copy here would be a second code
rem path, and the two would eventually disagree. Expect the `[fll]` prefix on
rem the messages below - `fll` is the canonical name, and the tag is the same one
rem every other file in this directory uses.
rem
rem See fll.bat and fll.ps1 for the configuration variables (FLL_DISTRO,
rem FLL_BIN, FLL_QUIET, FLL_DEBUG, FLL_NO_PATH_TRANSLATE) and the design notes.
rem ============================================================================

set "FLL_BAT=%~dp0fll.bat"
if not exist "%FLL_BAT%" (
    echo [fll] ERROR: fll.bat not found next to fulilian.bat. >&2
    echo [fll]        Reinstall with cmd\install.cmd >&2
    exit /b 1
)

call "%FLL_BAT%" %*
exit /b %ERRORLEVEL%
