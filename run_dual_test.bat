@echo off
title PyCall - Dual Instance Launcher
cd /d "%~dp0"
echo Starting PyCall Instance 1 (Port 5000)...
if exist ".venv\Scripts\python.exe" (
    start "" ".venv\Scripts\python.exe" main.py --port 5000
    timeout /t 1 /nobreak >nul
    echo Starting PyCall Instance 2 (Port 5002)...
    start "" ".venv\Scripts\python.exe" main.py --port 5002
) else (
    start "" python main.py --port 5000
    timeout /t 1 /nobreak >nul
    echo Starting PyCall Instance 2 (Port 5002)...
    start "" python main.py --port 5002
)
echo.
echo Both instances are launched side-by-side!
echo Instance 1 is on Port 5000
echo Instance 2 is on Port 5002
echo.
echo In Instance 1: Click CALL to call 127.0.0.1 on Port 5002!
timeout /t 3 >nul
