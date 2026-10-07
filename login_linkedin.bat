@echo off
title LinkedIn - Manual Login & Session Persistence
cd /d "%~dp0"
echo ========================================================
echo   LINKEDIN MANUAL LOGIN
echo ========================================================
echo.
.\venv\Scripts\python.exe -m src.main login --sites linkedin
pause
