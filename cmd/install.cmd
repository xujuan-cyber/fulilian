@echo off
setlocal EnableExtensions

rem ============================================================================
rem FuLiLian CMD Edition - installer / uninstaller / self-check
rem ============================================================================
rem Installs the fllkali / fuliliankali launchers into %USERPROFILE%\bin and adds
rem that directory to the USER PATH (only when missing). Optionally wires Tab
rem completion into the PowerShell $PROFILE. The WSL side must already have
rem fulilian installed (fll shim present in ~/.local/bin or /usr/local/bin).
rem
rem WHY fllkali: in a CMD window `fll` and `fulilian` belong to the NATIVE Windows
rem fulilian (scripts\install.ps1 puts those on PATH). This installer ships the
rem other door - the one that forwards into WSL - so it is named apart, and the
rem two installs coexist without fighting over a name.
rem
rem Files installed (all six, side by side - they reference each other):
rem   fllkali.bat            entry point for CMD; delegates to fllkali.ps1
rem   fllkali.cmd            alias of fllkali.bat, for hosts where PATHEXT omits .BAT
rem   fuliliankali.bat       alias of fllkali.bat, so the long name works too
rem   fuliliankali.cmd       alias of fllkali.bat, same reason as fllkali.cmd
rem   fllkali.ps1            the real launcher logic (PowerShell)
rem   fllkali.completion.ps1 Tab completion + $PROFILE wiring
rem
rem Usage (from CMD, any directory):
rem   cmd\install.cmd                install
rem   cmd\install.cmd /no-profile    install, but do not touch $PROFILE
rem   cmd\install.cmd /check         self-check only (no changes)
rem   cmd\install.cmd /uninstall     unwire completion, remove the files + PATH
rem
rem Upgrading from a pre-rename install: %USERPROFILE%\bin is on the USER PATH,
rem so the OLD bare names this installer used to ship (fll.bat, fll.cmd, fll.ps1,
rem fll.completion.ps1, fulilian.bat, fulilian.cmd) would keep shadowing the
rem NATIVE fulilian that scripts\install.ps1 puts on PATH. Install and
rem /uninstall both sweep them; see :sweep_legacy at the foot of this file.
rem ============================================================================

rem Capture the script's own directory BEFORE the parse loop below: `shift`
rem also shifts %0, so %~dp0 stops meaning "where this script lives" the moment
rem the loop runs (it silently becomes the drive of the last argument).
set "SRC_DIR=%~dp0"

set "ACTION=install"
set "NO_PROFILE=0"
:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="/check"      set "ACTION=check"
if /i "%~1"=="/uninstall"  set "ACTION=uninstall"
if /i "%~1"=="/no-profile" set "NO_PROFILE=1"
shift
goto :parse_args
:args_done

set "DEST_DIR=%USERPROFILE%\bin"
set "SRC_BAT=%SRC_DIR%fllkali.bat"
set "SRC_PS1=%SRC_DIR%fllkali.ps1"
set "SRC_CMD=%SRC_DIR%fllkali.cmd"
set "SRC_FULBAT=%SRC_DIR%fuliliankali.bat"
set "SRC_FULCMD=%SRC_DIR%fuliliankali.cmd"
set "SRC_COMP=%SRC_DIR%fllkali.completion.ps1"
set "DEST_BAT=%DEST_DIR%\fllkali.bat"
set "DEST_PS1=%DEST_DIR%\fllkali.ps1"
set "DEST_CMD=%DEST_DIR%\fllkali.cmd"
set "DEST_FULBAT=%DEST_DIR%\fuliliankali.bat"
set "DEST_FULCMD=%DEST_DIR%\fuliliankali.cmd"
set "DEST_COMP=%DEST_DIR%\fllkali.completion.ps1"

echo.
echo  FuLiLian CMD Edition installer
echo  ------------------------------
echo  action : %ACTION%
echo  source : %SRC_BAT%
echo  target : %DEST_DIR%
echo.

rem --- Sanity: source exists ----------------------------------------------------
if not exist "%SRC_BAT%" (
    echo [install] ERROR: fllkali.bat not found next to install.cmd.
    echo [install]        Run this from the repo's cmd\ directory or pass its full path.
    exit /b 1
)

if "%ACTION%"=="uninstall" goto :uninstall
if "%ACTION%"=="check"     goto :check

rem ============================ INSTALL ========================================

rem 0) Drop the pre-rename bare names BEFORE copying, so an upgrade cannot leave
rem    a stale `fll` on PATH shadowing the native one. See :sweep_legacy.
call :sweep_legacy

rem 1) Copy launchers
if not exist "%DEST_DIR%" mkdir "%DEST_DIR%"
copy /y "%SRC_BAT%" "%DEST_BAT%" >nul
echo [install] copied fllkali.bat
if exist "%SRC_PS1%"  (copy /y "%SRC_PS1%"  "%DEST_PS1%"  >nul && echo [install] copied fllkali.ps1)
if exist "%SRC_CMD%"  (copy /y "%SRC_CMD%"  "%DEST_CMD%"  >nul && echo [install] copied fllkali.cmd)
if exist "%SRC_FULBAT%" (copy /y "%SRC_FULBAT%" "%DEST_FULBAT%" >nul && echo [install] copied fuliliankali.bat)
if exist "%SRC_FULCMD%" (copy /y "%SRC_FULCMD%" "%DEST_FULCMD%" >nul && echo [install] copied fuliliankali.cmd)
if exist "%SRC_COMP%" (copy /y "%SRC_COMP%" "%DEST_COMP%" >nul && echo [install] copied fllkali.completion.ps1)

rem 2) Ensure %USERPROFILE%\bin is on the USER PATH (idempotent)
set "ADD_PATH=1"
for /f "usebackq tokens=2,*" %%a in (`reg query HKCU\Environment /v Path 2^>nul`) do set "USER_PATH_NOW=%%b"
if defined USER_PATH_NOW (
    echo %USER_PATH_NOW% | findstr /i /c:"%DEST_DIR%" >nul
    if not errorlevel 1 set "ADD_PATH=0"
)
if "%ADD_PATH%"=="1" (
    rem Append with a trailing semicolon; setx truncates >1024 chars, so warn.
    if defined USER_PATH_NOW (
        call setx PATH "%%USER_PATH_NOW%%;%DEST_DIR%" >nul
    ) else (
        call setx PATH "%DEST_DIR%" >nul
    )
    echo [install] added %DEST_DIR% to USER PATH
) else (
    echo [install] %DEST_DIR% already on USER PATH
)

rem 3) Wire Tab completion into $PROFILE (skippable)
rem    Done before the self-check so step 5 can report the real state.
if "%NO_PROFILE%"=="1" (
    echo [install] skipped $PROFILE wiring ^(/no-profile^)
    goto :check
)
if not exist "%DEST_COMP%" goto :check
where powershell.exe >nul 2>&1
if errorlevel 1 (
    echo [install] skipped $PROFILE wiring ^(powershell.exe not found^)
    goto :check
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%DEST_COMP%" -Install
if errorlevel 1 echo [install] WARNING: $PROFILE wiring failed - completion will not load automatically.

rem 4) Post-install self-check
goto :check

rem ============================ UNINSTALL ======================================

:uninstall
rem Unwire completion FIRST - it needs fllkali.completion.ps1 to still be on disk.
if exist "%DEST_COMP%" (
    where powershell.exe >nul 2>&1
    if not errorlevel 1 (
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%DEST_COMP%" -Uninstall
    )
)
rem Sweep the pre-rename bare names too: /uninstall must not leave a shadow.
call :sweep_legacy
if exist "%DEST_BAT%"  del /q "%DEST_BAT%"  && echo [uninstall] removed fllkali.bat
if exist "%DEST_PS1%"  del /q "%DEST_PS1%"  && echo [uninstall] removed fllkali.ps1
if exist "%DEST_CMD%"  del /q "%DEST_CMD%"  && echo [uninstall] removed fllkali.cmd
if exist "%DEST_FULBAT%" del /q "%DEST_FULBAT%" && echo [uninstall] removed fuliliankali.bat
if exist "%DEST_FULCMD%" del /q "%DEST_FULCMD%" && echo [uninstall] removed fuliliankali.cmd
if exist "%DEST_COMP%" del /q "%DEST_COMP%" && echo [uninstall] removed fllkali.completion.ps1
set "REMOVED_PATH=0"
for /f "usebackq tokens=2,*" %%a in (`reg query HKCU\Environment /v Path 2^>nul`) do set "USER_PATH_NOW=%%b"
if defined USER_PATH_NOW (
    echo %USER_PATH_NOW% | findstr /i /c:"%DEST_DIR%" >nul
    if not errorlevel 1 (
        rem Rewrite PATH without this directory (handles both ; separators cases)
        set "NEW_PATH=%USER_PATH_NOW%"
        call set "NEW_PATH=%%NEW_PATH:;%DEST_DIR%=%%"
        call set "NEW_PATH=%%NEW_PATH:%DEST_DIR%;=%%"
        call set "NEW_PATH=%%NEW_PATH:%DEST_DIR%=%%"
        call setx PATH "%%NEW_PATH%%" >nul
        set "REMOVED_PATH=1"
    )
)
if "%REMOVED_PATH%"=="1" (echo [uninstall] removed %DEST_DIR% from USER PATH) else echo [uninstall] %DEST_DIR% not on USER PATH
echo [uninstall] done. Open a new CMD window for PATH changes.
exit /b 0

rem ============================ SELF-CHECK =====================================

:check
echo.
echo [check] 1/5 wsl.exe present
where wsl.exe >nul 2>&1
if errorlevel 1 (
    echo [check]    FAIL - WSL not installed. Run: wsl --install
    exit /b 1
) else (
    echo [check]    OK
)

echo [check] 2/5 fulilian reachable inside WSL
set "CHECK_BIN="
for /f "usebackq delims=" %%p in (`wsl.exe --exec sh -c "echo $HOME/.local/bin/fll" 2^>nul`) do set "CHECK_BIN=%%p"
wsl.exe --exec sh -c "test -x $HOME/.local/bin/fll" >nul 2>&1
if not errorlevel 1 (
    echo [check]    OK - %CHECK_BIN%
) else (
    wsl.exe --exec sh -c "test -x /usr/local/bin/fll" >nul 2>&1
    if not errorlevel 1 (
        echo [check]    OK - /usr/local/bin/fll
    ) else (
        echo [check]    FAIL - fll shim not found in WSL default distro.
        echo [check]           Install fulilian inside WSL first, or set FLLKALI_BIN/FLLKALI_DISTRO.
        exit /b 1
    )
)

if "%ACTION%"=="check" goto :check_installed

echo [check] 3/5 launchers installed
set "MISSING="
if not exist "%DEST_BAT%"  set "MISSING=%MISSING% fllkali.bat"
if not exist "%DEST_PS1%"  set "MISSING=%MISSING% fllkali.ps1"
if not exist "%DEST_CMD%"  set "MISSING=%MISSING% fllkali.cmd"
if not exist "%DEST_FULBAT%" set "MISSING=%MISSING% fuliliankali.bat"
if not exist "%DEST_FULCMD%" set "MISSING=%MISSING% fuliliankali.cmd"
if not exist "%DEST_COMP%" set "MISSING=%MISSING% fllkali.completion.ps1"
if defined MISSING (
    echo [check]    FAIL - missing:%MISSING%
) else (
    echo [check]    OK - all 6 files in %DEST_DIR%
)

echo [check] 4/5 fllkali on PATH for NEW windows
echo %PATH% | findstr /i /c:"%DEST_DIR%" >nul
if not errorlevel 1 (
    echo [check]    OK
) else (
    echo [check]    NOTE - %DEST_DIR% not on PATH of THIS window.
    echo [check]           Open a new CMD window, then run: fllkali --version
)

echo [check] 5/5 Tab completion wired into $PROFILE
if "%NO_PROFILE%"=="1" (
    echo [check]    SKIPPED ^(/no-profile^)
    goto :check_done
)
where powershell.exe >nul 2>&1
if errorlevel 1 (
    echo [check]    SKIPPED ^(powershell.exe not found^)
    goto :check_done
)
rem Ask PowerShell whether the marker line is present - do not grep $PROFILE by
rem hand, because $PROFILE can live outside %USERPROFILE% (a redirected
rem Documents folder, for instance) and its path is host-specific.
rem NB: no \" escapes here - cmd.exe does not honour them, they would reach
rem PowerShell as literal backslash-quote. Single-quoted PS strings + concatenation
rem keep every double quote out of the command line.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p=$PROFILE; if ((Test-Path -LiteralPath $p) -and ((Get-Content -LiteralPath $p -ErrorAction SilentlyContinue) -match [regex]::Escape('# fllkali completion'))) { Write-Host ('[check]    OK - ' + $p); exit 0 } else { Write-Host ('[check]    NOT WIRED - run: . ' + $p); exit 1 }"
if errorlevel 1 echo [check]           Completion is optional; `fllkali` works without it.
goto :check_done

:check_installed
echo [check] 3/5 skipped (check mode, install step not run)
echo [check] 4/5 skipped (check mode, install step not run)
echo [check] 5/5 skipped (check mode, install step not run)

:check_done
echo.
echo [check] done.
exit /b 0

rem ============================ LEGACY SWEEP ===================================
rem Names this installer shipped BEFORE the *kali rename. They must not survive
rem an upgrade, for two independent reasons:
rem   1. %DEST_DIR% is on the USER PATH. A leftover fll.bat / fll.cmd / fll.ps1
rem      is a live `fll` that shadows the NATIVE fulilian - the exact collision
rem      the rename exists to remove. Same for fulilian.bat / fulilian.cmd.
rem   2. fll.completion.ps1 is gone from the new install, but the old
rem      '# fulilian-cmd completion' block it wrote into $PROFILE dot-sources
rem      it - so every new PowerShell session errors. (fllkali.completion.ps1
rem      strips that block; this removes the file it pointed at.)
rem
rem Scope is deliberately narrow: %DEST_DIR% only, and only these six exact
rem names. The NATIVE launchers live in %FULILIAN_HOME%\bin
rem (%LOCALAPPDATA%\fulilian\bin), a different directory this never reaches -
rem so a native fll.exe / fulilian.exe cannot be caught by it.
rem
rem %%f is correct here: this is a batch FILE, not a command line.
:sweep_legacy
for %%f in (fll.bat fll.cmd fll.ps1 fulilian.bat fulilian.cmd fll.completion.ps1) do (
    if exist "%DEST_DIR%\%%f" (
        del /q "%DEST_DIR%\%%f"
        echo [migrate] removed pre-rename %%f
    )
)
exit /b 0
