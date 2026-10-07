@echo off
title Shine.com - Manual Login & Session Persistence
cd /d "%~dp0"
echo ========================================================
echo   SHINE.COM MANUAL LOGIN
echo ========================================================
echo.
.\venv\Scripts\python.exe -m src.main login --sites shine
pause
