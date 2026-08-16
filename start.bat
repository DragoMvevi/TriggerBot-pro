@echo off
title TriggerBot Pro Launcher
cd /d "%~dp0"

:: Check if python is available
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not found in PATH!
    echo Please ensure Python is installed and added to PATH.
    pause
    exit /b 1
)

echo Starting TriggerBot Pro...
start "" python main.py
exit /b 0
