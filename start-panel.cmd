@echo off
setlocal
cd /d "%~dp0"
set "PANEL_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PANEL_PYTHON%" (
    python -m venv "%~dp0.venv"
    if errorlevel 1 goto failed
)
"%PANEL_PYTHON%" -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
    "%PANEL_PYTHON%" -m pip install -r "%~dp0requirements.lock"
    if errorlevel 1 goto failed
)
set "PYTHONPATH=%~dp0src"
if not defined OPTIONS_APP_ROOT set "OPTIONS_APP_ROOT=%~dp0"
"%PANEL_PYTHON%" -m options_panel --open %*
if errorlevel 1 goto failed
exit /b 0
:failed
echo Startup failed. Check Python, network, or whether port 8780 is already in use.
pause
exit /b 1
