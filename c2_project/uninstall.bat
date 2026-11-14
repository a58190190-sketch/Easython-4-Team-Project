@echo off
setlocal
cd /d "%~dp0"
title Easython - uninstall

echo ==========================================
echo Easython - uninstall
echo ==========================================
echo This removes Easython's local .venv and all libraries inside it.
echo Python is removed only if install.bat recorded that it installed Python 3.14.10.
echo The bundled Python installer and saved API credentials are kept for reuse.
echo.
choice /c YN /m "Remove Easython's isolated environment"
if errorlevel 2 (
    echo Cancelled. Nothing was removed.
    exit /b 0
)

if exist "%~dp0.venv\pyvenv.cfg" (
    call :FIND_PYTHON
    if not defined PYTHON_CMD (
        echo [ERROR] Python is needed to safely remove the isolated environment.
        echo Install Python or restore the interpreter, then rerun uninstall.bat.
        pause
        exit /b 1
    )
    echo Removing the Easython virtual environment...
    %PYTHON_CMD% "%~dp0remove_venv.py"
    if errorlevel 1 (
        echo [ERROR] The isolated environment was not removed.
        pause
        exit /b 1
    )
) else (
    echo No Easython .venv was found. No system-wide packages will be removed.
)

if not exist "%~dp0.easython-python-owned" goto FINISH
if not exist "%~dp0python-3.14.10-amd64.exe" (
    echo Python was installed by Easython, but the bundled installer is missing.
    echo Remove Python 3.14.10 from Windows Installed apps if you want to remove it.
    goto FINISH
)

echo.
echo The ownership record confirms Python 3.14.10 was installed by Easython.
choice /c YN /m "Also uninstall this Easython-installed Python runtime"
if errorlevel 2 goto FINISH
start /wait "" "%~dp0python-3.14.10-amd64.exe" /uninstall /passive InstallAllUsers=0
if errorlevel 1 (
    echo [WARNING] Python uninstallation did not complete. See Windows Installed apps.
) else (
    del /f /q "%~dp0.easython-python-owned"
    echo Easython-installed Python 3.14.10 was uninstalled.
)

:FINISH
echo.
echo Easython's isolated libraries have been removed.
echo Existing global Python installations, global libraries, API credentials, and the installer file were kept.
pause
exit /b 0

:FIND_PYTHON
set "PYTHON_CMD="
py -3 -c "import sys; raise SystemExit(sys.version_info.major != 3)" >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
    exit /b 0
)
if exist "%LocalAppData%\Programs\Python\Launcher\py.exe" (
    "%LocalAppData%\Programs\Python\Launcher\py.exe" -3 -c "import sys; raise SystemExit(sys.version_info.major != 3)" >nul 2>nul
    if not errorlevel 1 (
        set PYTHON_CMD="%LocalAppData%\Programs\Python\Launcher\py.exe" -3
        exit /b 0
    )
)
if exist "%LocalAppData%\Programs\Python\Python314\python.exe" (
    "%LocalAppData%\Programs\Python\Python314\python.exe" -c "import sys; raise SystemExit(sys.version_info.major != 3)" >nul 2>nul
    if not errorlevel 1 (
        set PYTHON_CMD="%LocalAppData%\Programs\Python\Python314\python.exe"
        exit /b 0
    )
)
exit /b 0
