@echo off
setlocal
cd /d "%~dp0"
title Easython - Python and library setup

echo ==========================================
echo Easython - Python and library setup
echo ==========================================
echo.

set "PYTHON_INSTALLED_BY_EASYTHON=0"
call :FIND_PYTHON
if defined PYTHON_CMD goto INSTALL_LIBRARIES

if not exist "%~dp0python-3.14.10-amd64.exe" (
    echo [ERROR] Bundled Python installer was not found.
    echo Download Python from https://www.python.org/downloads/ and rerun install.bat.
    pause
    exit /b 1
)

echo Python 3 was not found. Installing bundled Python 3.14.10 for this Windows user...
set "PYTHON_INSTALLED_BY_EASYTHON=1"
start /wait "" "%~dp0python-3.14.10-amd64.exe" /passive InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1 Include_tcltk=1 Include_test=0
if errorlevel 1 (
    echo [ERROR] Python installation did not complete.
    pause
    exit /b 1
)
if "%PYTHON_INSTALLED_BY_EASYTHON%"=="1" (
    >"%~dp0.easython-python-owned" echo Easython installed Python 3.14.10 for the current user.
)

call :FIND_PYTHON
if not defined PYTHON_CMD (
    echo [ERROR] Python setup finished, but Python could not be located.
    echo Restart Windows or install Python from python.org, then rerun install.bat.
    pause
    exit /b 1
)

:INSTALL_LIBRARIES
echo Using Python:
%PYTHON_CMD% --version
if errorlevel 1 goto PYTHON_ERROR
echo.
set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PYTHON%" (
    echo Creating Easython's isolated Python environment...
    %PYTHON_CMD% -m venv "%~dp0.venv"
    if errorlevel 1 goto VENV_ERROR
)
%VENV_PYTHON% -m pip --version >nul 2>nul
if errorlevel 1 (
    echo pip is missing in the Easython environment. Bootstrapping pip...
    %VENV_PYTHON% -m ensurepip --upgrade
    if errorlevel 1 goto VENV_ERROR
)
echo Checking and installing all libraries listed in requirements.txt...
%VENV_PYTHON% -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
if errorlevel 1 goto LIBRARY_ERROR

echo.
echo Verifying the installed library versions...
%VENV_PYTHON% "%~dp0check_requirements.py"
if errorlevel 1 goto VERIFY_ERROR

echo.
echo Python and required libraries are ready. Start Easython with run.bat.
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

for /f "delims=" %%P in ('where python 2^>nul') do (
    echo(%%P| findstr /i /c:"\WindowsApps\" >nul
    if errorlevel 1 (
        "%%P" -c "import sys; raise SystemExit(sys.version_info.major != 3)" >nul 2>nul
        if not errorlevel 1 (
            set PYTHON_CMD="%%P"
            exit /b 0
        )
    )
)
exit /b 0

:PYTHON_ERROR
echo [ERROR] The selected Python command could not be started.
pause
exit /b 1

:VENV_ERROR
echo [ERROR] The Easython virtual environment could not be created or prepared.
pause
exit /b 1

:LIBRARY_ERROR
echo.
echo [ERROR] Library installation failed. Check the network and rerun install.bat.
pause
exit /b 1

:VERIFY_ERROR
echo.
echo [ERROR] Dependency verification failed. Review requirements.txt and rerun install.bat.
pause
exit /b 1
