@echo off
setlocal
cd /d "%~dp0"
echo Checking required Python libraries from requirements.txt...
py -3 check_requirements.py
if errorlevel 1 (
    echo.
    echo Easython has missing or incompatible libraries. Run install.bat and try again.
    pause
    exit /b 1
)
py -3 app.py
if errorlevel 1 (
    echo.
    echo Easython could not start. Run install.bat first and check the error above.
    pause
)
