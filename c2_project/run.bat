@echo off
setlocal
cd /d "%~dp0"
set "EASYTHON_PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%EASYTHON_PYTHON%" (
    echo Easython's isolated Python environment is missing.
    echo Run install.bat to install Python and the required libraries.
    pause
    exit /b 1
)

echo Checking required libraries in Easython's isolated environment...
"%EASYTHON_PYTHON%" check_requirements.py
if errorlevel 1 (
    echo.
    echo Required libraries are missing or incompatible. Run install.bat and try again.
    pause
    exit /b 1
)

"%EASYTHON_PYTHON%" main.py
if errorlevel 1 (
    echo.
    echo Easython could not start. Review the error above.
    pause
)
