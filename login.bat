@echo off
title Naukri Agent - Interactive Login
cd /d "%~dp0"
echo Starting Naukri Login...
.\venv\Scripts\python.exe -m src.main login
pause
