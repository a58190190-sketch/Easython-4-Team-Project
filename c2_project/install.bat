@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo Easython - Python setup
 echo ==========================================

py -3 --version >nul 2>nul
if errorlevel 1 goto INSTALL_PYTHON

echo Python is available:
py -3 --version
goto INSTALL_LIBRARIES

:INSTALL_PYTHON
if not exist "%~dp0python-3.14.10-amd64.exe" (
    echo [ERROR] Bundled Python installer was not found.
    echo Download Python from https://www.python.org/downloads/
    pause
    exit /b 1
)
echo Python 3 is missing. Starting the bundled Python 3.14.10 setup.
start /wait "" "%~dp0python-3.14.10-amd64.exe" /passive InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1 Include_tcltk=1 Include_test=0
if errorlevel 1 (
    echo [ERROR] Python setup did not complete. Run install_python.bat to retry.
    pause
    exit /b 1
)
echo Python setup completed. Close this window, then run install.bat again.
pause
exit /b 0

:INSTALL_LIBRARIES
echo Installing required Python libraries...
py -3 -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo [ERROR] Library installation failed. Check your internet connection and rerun install.bat.
    pause
    exit /b 1
)
py -3 "%~dp0check_requirements.py"
if errorlevel 1 (
    echo.
    echo [ERROR] Dependency verification failed. Check requirements.txt and rerun install.bat.
    pause
    exit /b 1
)
echo.
echo Required libraries installed and verified. NVIDIA NIM API key setup is available in the app.
echo Start Easython with: run.bat
pause
exit /b 0

