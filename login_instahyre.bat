@echo off
title Instahyre - Manual Login & Session Persistence
cd /d "%~dp0"
echo ========================================================
echo   INSTAHYRE MANUAL LOGIN
echo ========================================================
echo.
.\venv\Scripts\python.exe -m src.main login --sites instahyre
pause
