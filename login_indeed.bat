@echo off
title Indeed - Manual Login & Session Persistence
cd /d "%~dp0"
echo ========================================================
echo   INDEED MANUAL LOGIN
echo ========================================================
echo.
.\venv\Scripts\python.exe -m src.main login --sites indeed
pause
