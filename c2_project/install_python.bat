@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0python-3.14.10-amd64.exe" (
    echo [ERROR] python-3.14.10-amd64.exe is missing from this folder.
    pause
    exit /b 1
)
echo Starting the official Python 3.14.10 installer for this Windows user...
start /wait "" "%~dp0python-3.14.10-amd64.exe" /passive InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1 Include_tcltk=1 Include_test=0
if errorlevel 1 (
    echo Python installation failed. Please rerun this file.
    pause
    exit /b 1
)
echo Python setup completed. Close and reopen the terminal before running install.bat.
pause
exit /b 0
