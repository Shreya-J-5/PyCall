@echo off
title PyCall - Local Voice Calling
cd /d "%~dp0"
echo Starting PyCall %*...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py %*
) else (
    python main.py %*
)
pause
