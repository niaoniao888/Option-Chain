@echo off
setlocal
cd /d "%~dp0"
set "PANEL_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PANEL_PYTHON%" (
    python -m venv "%~dp0.venv"
    if errorlevel 1 goto failed
)
"%PANEL_PYTHON%" -c "import fastapi, uvicorn, tzdata" >nul 2>&1
if errorlevel 1 (
    "%PANEL_PYTHON%" -m pip install -r "%~dp0requirements.lock"
    if errorlevel 1 goto failed
)
set "PYTHONPATH=%~dp0src"
if not defined OPTIONS_APP_ROOT set "OPTIONS_APP_ROOT=%~dp0"
"%PANEL_PYTHON%" -m options_panel.us_equities.admin %*
if errorlevel 1 goto failed
exit /b 0
:failed
echo Local administration failed. Check Python dependencies and port availability.
pause
exit /b 1
