@echo off
setlocal EnableExtensions

rem ============================================================================
rem FuLiLian CMD Edition - installer / uninstaller / self-check
rem ============================================================================
rem Installs fll.bat into %USERPROFILE%\bin and adds that directory to the
rem USER PATH (only when missing). The WSL side must already have fulilian
rem installed (fll shim present in ~/.local/bin or /usr/local/bin).
rem
rem Usage (from CMD, any directory):
rem   cmd\install.cmd              install
rem   cmd\install.cmd /check       self-check only (no changes)
rem   cmd\install.cmd /uninstall   remove from PATH and delete fll.bat
rem ============================================================================

set "ACTION=install"
if /i "%~1"=="/check"     set "ACTION=check"
if /i "%~1"=="/uninstall" set "ACTION=uninstall"

set "SRC=%~dp0fll.bat"
set "SRC_PS1=%~dp0fll.ps1"
set "DEST_DIR=%USERPROFILE%\bin"
set "DEST=%DEST_DIR%\fll.bat"
set "DEST_PS1=%DEST_DIR%\fll.ps1"

echo.
echo  FuLiLian CMD Edition installer
echo  ------------------------------
echo  action : %ACTION%
echo  source : %SRC%
echo  target : %DEST%
echo.

rem --- Sanity: source exists ----------------------------------------------------
if not exist "%SRC%" (
    echo [install] ERROR: fll.bat not found next to install.cmd.
    echo [install]        Run this from the repo's cmd\ directory or pass its full path.
    exit /b 1
)

if "%ACTION%"=="uninstall" goto :uninstall
if "%ACTION%"=="check"     goto :check

rem ============================ INSTALL ========================================

rem 1) Copy launcher(s)
if not exist "%DEST_DIR%" mkdir "%DEST_DIR%"
copy /y "%SRC%" "%DEST%" >nul
if exist "%SRC_PS1%" copy /y "%SRC_PS1%" "%DEST_PS1%" >nul
echo [install] copied fll.bat (and fll.ps1 if present) to %DEST_DIR%

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

rem 3) Post-install self-check
goto :check

rem ============================ UNINSTALL ======================================

:uninstall
if exist "%DEST%" del /q "%DEST%" && echo [uninstall] removed %DEST%
if exist "%DEST_PS1%" del /q "%DEST_PS1%" && echo [uninstall] removed %DEST_PS1%
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
echo [check] 1/4 wsl.exe present
where wsl.exe >nul 2>&1
if errorlevel 1 (
    echo [check]    FAIL - WSL not installed. Run: wsl --install
    exit /b 1
) else (
    echo [check]    OK
)

echo [check] 2/4 fulilian reachable inside WSL
set "CHECK_BIN="
for /f "usebackq delims=" %%p in (`wsl.exe --exec sh -lc "echo $HOME/.local/bin/fll" 2^>nul`) do set "CHECK_BIN=%%p"
wsl.exe --exec sh -lc "test -x $HOME/.local/bin/fll" >nul 2>&1
if not errorlevel 1 (
    echo [check]    OK - %CHECK_BIN%
) else (
    wsl.exe --exec sh -lc "test -x /usr/local/bin/fll" >nul 2>&1
    if not errorlevel 1 (
        echo [check]    OK - /usr/local/bin/fll
    ) else (
        echo [check]    FAIL - fll shim not found in WSL default distro.
        echo [check]           Install fulilian inside WSL first, or set FLL_BIN/FLL_DISTRO.
        exit /b 1
    )
)

if "%ACTION%"=="check" goto :check_installed

echo [check] 3/4 fll.bat installed
if exist "%DEST%" (echo [check]    OK - %DEST%) else echo [check]    FAIL - %DEST% missing

echo [check] 4/4 fll on PATH for NEW windows
echo %PATH% | findstr /i /c:"%DEST_DIR%" >nul
if not errorlevel 1 (
    echo [check]    OK
) else (
    echo [check]    NOTE - %DEST_DIR% not on PATH of THIS window.
    echo [check]           Open a new CMD window, then run: fll --version
)
goto :check_done

:check_installed
echo [check] 3/4 skipped (check mode, install step not run)
echo [check] 4/4 skipped (check mode, install step not run)

:check_done
echo.
echo [check] done.
exit /b 0
