@echo off
title Foundit (Monster) - Manual Login & Session Persistence
cd /d "%~dp0"
echo ========================================================
echo   FOUNDIT (MONSTER INDIA) MANUAL LOGIN
echo ========================================================
echo.
.\venv\Scripts\python.exe -m src.main login --sites foundit
pause
