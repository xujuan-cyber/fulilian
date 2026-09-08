@echo off
setlocal EnableExtensions

rem ============================================================================
rem FuLiLian CMD Edition - fll.bat
rem ============================================================================
rem CMD frontend for FuLiLian running inside WSL. Forwards every argument
rem verbatim to the `fll` entry point in the WSL default distro.
rem
rem Usage (any directory):
rem   fll                        interactive session
rem   fll --version              version
rem   fll <any fll args...>      all arguments forwarded as-is
rem
rem Configuration (optional environment variables):
rem   FLL_DISTRO   WSL distro name for -d   (default: WSL's own default distro)
rem   FLL_BIN      path to fll inside WSL   (default: auto-probe ~/.local/bin/fll
rem                                          then /usr/local/bin/fll)
rem   FLL_QUIET    set to 1 to hide the banner line
rem   FLL_DEBUG    set to anything to print resolved values + exit code
rem
rem Exit codes are forwarded from WSL so scripts can rely on them.
rem Design note: `wsl -l -v` emits UTF-16LE which CMD cannot parse reliably,
rem so this launcher never parses it - wsl.exe resolves the default distro
rem itself when -d is not given.
rem ============================================================================

rem --- UTF-8 code page so WSL output (box drawing, CJK) renders correctly ----
rem The previous code page is restored before exiting.
for /f "tokens=2 delims=:" %%c in ('chcp') do set "FLL_PREV_CP=%%c"
set "FLL_PREV_CP=%FLL_PREV_CP: =%"
chcp 65001 >nul

rem --- Build the wsl prefix (with or without -d) -------------------------------
set "WSL_CMD=wsl.exe"
if defined FLL_DISTRO set "WSL_CMD=wsl.exe -d %FLL_DISTRO%"

rem --- Detect WSL --------------------------------------------------------------
where wsl.exe >nul 2>&1
if errorlevel 1 (
    echo [fll] ERROR: wsl.exe not found. Install WSL2 first:
    echo [fll]        wsl --install
    goto :fail
)

rem --- Probe fulilian inside the distro ----------------------------------------
set "FLL_WSL_BIN="
if defined FLL_BIN (
    %WSL_CMD% --exec test -x "%FLL_BIN%" >nul 2>&1
    if not errorlevel 1 set "FLL_WSL_BIN=%FLL_BIN%"
    goto :probe_done
)
%WSL_CMD% --exec sh -lc "test -x $HOME/.local/bin/fll" >nul 2>&1
if not errorlevel 1 (
    rem NB: never use printf %s here - CMD eats the percent sign inside for /f.
    for /f "usebackq delims=" %%p in (`%WSL_CMD% --exec sh -lc "echo $HOME/.local/bin/fll"`) do set "FLL_WSL_BIN=%%p"
    goto :probe_done
)
%WSL_CMD% --exec sh -lc "test -x /usr/local/bin/fll" >nul 2>&1
if not errorlevel 1 set "FLL_WSL_BIN=/usr/local/bin/fll"

:probe_done
if not defined FLL_WSL_BIN (
    echo [fll] ERROR: fulilian not found in WSL.
    echo [fll]        Looked for: ~/.local/bin/fll and /usr/local/bin/fll
    echo [fll]        Fix: install fulilian inside WSL, or pin the path:
    echo [fll]          setx FLL_BIN /home/you/.local/bin/fll
    goto :fail
)

rem --- Banner (distro name comes from inside WSL, no CMD parsing) --------------
if defined FLL_QUIET goto :launch
for /f "usebackq delims=" %%d in (`%WSL_CMD% --exec sh -lc "echo ${WSL_DISTRO_NAME:-default}" 2^>nul`) do set "FLL_DISTRO_NAME=%%d"
echo [fll] distro: %FLL_DISTRO_NAME%  bin: %FLL_WSL_BIN%

:launch
rem --- Launch -------------------------------------------------------------------
rem WSL translates the Windows working directory into a WSL path automatically.
rem Using --exec keeps signal/exit-code semantics close to a native run.
%WSL_CMD% --exec %FLL_WSL_BIN% %*
set "FLL_EXIT=%ERRORLEVEL%"

if defined FLL_PREV_CP chcp %FLL_PREV_CP% >nul 2>&1
if defined FLL_DEBUG echo [fll] debug: exit=%FLL_EXIT% bin=%FLL_WSL_BIN%
exit /b %FLL_EXIT%

:fail
if defined FLL_PREV_CP chcp %FLL_PREV_CP% >nul 2>&1
exit /b 1
