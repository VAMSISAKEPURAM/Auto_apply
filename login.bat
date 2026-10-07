@echo off
title Multi-Platform Agent - Interactive Login
cd /d "%~dp0"
echo Starting Multi-Platform Login Flow...
.\venv\Scripts\python.exe -m src.main login
pause

