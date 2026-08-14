@echo off
rem ---------------------------------------------------------------------
rem start_app.bat
rem
rem Run the Thermal Monitoring System v2 on this PC.
rem   - Creates .venv and installs dependencies on first run
rem     (delegates to setup_environment.py).
rem   - Then starts the application with the venv python.
rem ---------------------------------------------------------------------
setlocal

set "ROOT=%~dp0"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo [start_app] Virtual environment not found. Running setup first...
    python "%ROOT%setup_environment.py" --yes
    if errorlevel 1 (
        echo [start_app] Environment setup failed. See messages above.
        pause
        exit /b 1
    )
)

if not exist "%VENV_PY%" (
    echo [start_app] .venv still missing after setup. Cannot continue.
    pause
    exit /b 1
)

echo [start_app] Launching Thermal Monitoring System v2 ...
"%VENV_PY%" "%ROOT%main.py"

echo [start_app] Application exited with code %ERRORLEVEL%.
pause
endlocal
