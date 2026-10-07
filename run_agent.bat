@echo off
title Multi-Platform Job Search & Apply Agent
cd /d "%~dp0"
echo Starting Multi-Platform Job Search & Apply Agent...
.\venv\Scripts\python.exe -m src.main run
pause

