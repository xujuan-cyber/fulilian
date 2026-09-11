@echo off
setlocal EnableExtensions

rem ============================================================================
rem FuLiLian CMD Edition - fllkali.bat
rem ============================================================================
rem CMD frontend for FuLiLian running inside WSL. Forwards every argument to
rem the `fll` entry point in the WSL distro; configuration, sessions, skills
rem and logs are identical to running fll inside WSL.
rem
rem Usage (any directory):
rem   fllkali                        interactive session
rem   fllkali --version              version
rem   fllkali solve C:\ctf\chall     Windows paths rewritten to /mnt/... for you
rem   fllkali <any fll args...>      all arguments forwarded as-is
rem
rem Configuration (optional environment variables):
rem   FLLKALI_DISTRO   WSL distro name for -d   (default: WSL's own default distro)
rem   FLLKALI_BIN      path to fll inside WSL   (default: auto-probe ~/.local/bin/fll
rem                                          then /usr/local/bin/fll)
rem   FLLKALI_QUIET    set to 1 to hide the banner line
rem   FLLKALI_DEBUG    set to anything to print resolved values + exit code
rem   FLLKALI_NO_PATH_TRANSLATE=1  do not rewrite Windows paths to /mnt/...
rem
rem Exit codes are forwarded from WSL so scripts can rely on them.
rem
rem WHY THIS FILE IS SO SHORT: cmd.exe cannot forward arguments faithfully.
rem Text substituted by `%*` is not re-tokenised for quoting, so a launcher
rem that runs `wsl.exe --exec <bin> %*` splits every quoted argument that
rem contains a space ("C:\Program Files\x" used to arrive as three arguments
rem with the quote characters kept) and mangles CJK arguments. Windows
rem PowerShell's parser re-tokenises correctly, so all of the real logic -
rem probing, path translation, argument forwarding - lives in fllkali.ps1 and this
rem file just hands the argument text over to it. The :no_powershell branch
rem below is a degraded fallback for the rare host with no PowerShell.
rem ============================================================================

rem --- UTF-8 code page so WSL output (box drawing, CJK) renders correctly ----
rem The previous code page is restored before exiting.
for /f "tokens=2 delims=:" %%c in ('chcp') do set "FLLKALI_PREV_CP=%%c"
set "FLLKALI_PREV_CP=%FLLKALI_PREV_CP: =%"
chcp 65001 >nul

rem --- Delegate to the PowerShell twin, which owns the real logic -------------
set "FLLKALI_PS1=%~dp0fllkali.ps1"
if not exist "%FLLKALI_PS1%" goto :no_powershell
where powershell.exe >nul 2>&1
if errorlevel 1 goto :no_powershell

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%FLLKALI_PS1%" %*
set "FLLKALI_EXIT=%ERRORLEVEL%"
if defined FLLKALI_PREV_CP chcp %FLLKALI_PREV_CP% >nul 2>&1
exit /b %FLLKALI_EXIT%

rem ============================================================================
rem Degraded fallback: no PowerShell, or fllkali.ps1 not next to this launcher.
rem Handles interactive use (`fll`) and simple arguments correctly; arguments
rem containing spaces, quotes or CJK may be split or garbled - that is the
rem cmd.exe `%*` limitation described above, and the reason fllkali.ps1 exists.
rem ============================================================================

:no_powershell
if defined FLLKALI_QUIET goto :probe
echo [fllkali] WARNING: PowerShell not found - falling back to direct wsl.exe. >&2
echo [fllkali]          Arguments containing spaces or quotes may be mangled. >&2

:probe
set "WSL_CMD=wsl.exe"
if defined FLLKALI_DISTRO set "WSL_CMD=wsl.exe -d %FLLKALI_DISTRO%"

where wsl.exe >nul 2>&1
if errorlevel 1 (
    echo [fllkali] ERROR: wsl.exe not found. Install WSL2 first: >&2
    echo [fllkali]        wsl --install >&2
    goto :fail
)

set "FLLKALI_WSL_BIN="
if defined FLLKALI_BIN (
    %WSL_CMD% --exec test -x "%FLLKALI_BIN%" >nul 2>&1
    if not errorlevel 1 set "FLLKALI_WSL_BIN=%FLLKALI_BIN%"
    goto :probe_done
)
rem One wsl call per candidate: test -x AND resolve the path in the same sh,
rem so the for /f below captures the absolute path only on success.
rem NB: never use printf %s here - CMD eats the percent sign inside for /f.
for /f "usebackq delims=" %%p in (`%WSL_CMD% --exec sh -c "test -x $HOME/.local/bin/fll && echo $HOME/.local/bin/fll"`) do set "FLLKALI_WSL_BIN=%%p"
if defined FLLKALI_WSL_BIN goto :probe_done
for /f "usebackq delims=" %%p in (`%WSL_CMD% --exec sh -c "test -x /usr/local/bin/fll && echo /usr/local/bin/fll"`) do set "FLLKALI_WSL_BIN=%%p"

:probe_done
if not defined FLLKALI_WSL_BIN (
    echo [fllkali] ERROR: fulilian not found in WSL. >&2
    echo [fllkali]        Looked for: ~/.local/bin/fll and /usr/local/bin/fll >&2
    echo [fllkali]        Fix: install fulilian inside WSL, or pin the path: >&2
    echo [fllkali]          setx FLLKALI_BIN /home/you/.local/bin/fll >&2
    goto :fail
)

rem --- Banner (distro name comes from inside WSL, no CMD parsing) --------------
if defined FLLKALI_QUIET goto :launch
for /f "usebackq delims=" %%d in (`%WSL_CMD% --exec sh -c "echo ${WSL_DISTRO_NAME:-default}" 2^>nul`) do set "FLLKALI_DISTRO_NAME=%%d"
echo [fllkali] distro: %FLLKALI_DISTRO_NAME%  bin: %FLLKALI_WSL_BIN%

:launch
rem WSL translates the Windows working directory into a WSL path automatically.
rem Using --exec keeps signal/exit-code semantics close to a native run.
%WSL_CMD% --exec %FLLKALI_WSL_BIN% %*
set "FLLKALI_EXIT=%ERRORLEVEL%"

if defined FLLKALI_PREV_CP chcp %FLLKALI_PREV_CP% >nul 2>&1
if defined FLLKALI_DEBUG echo [fllkali] debug: exit=%FLLKALI_EXIT% bin=%FLLKALI_WSL_BIN% >&2
exit /b %FLLKALI_EXIT%

:fail
if defined FLLKALI_PREV_CP chcp %FLLKALI_PREV_CP% >nul 2>&1
exit /b 1
