@echo off
title Naukri Agent - Job Search & Apply Pipeline
cd /d "%~dp0"
echo Starting Naukri Agent...
.\venv\Scripts\python.exe -m src.main run
pause
