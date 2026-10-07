@echo off
title Naukri - Manual Login & Session Persistence
cd /d "%~dp0"
echo ========================================================
echo   NAUKRI.COM MANUAL LOGIN
echo ========================================================
echo.
.\venv\Scripts\python.exe -m src.main login --sites naukri
pause
