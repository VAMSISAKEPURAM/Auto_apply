@echo off
title Multi-Platform Auto-Apply 24/7 Daemon (Hourly + Excel Export)
cd /d "%~dp0"
echo ========================================================
echo   MULTI-PLATFORM 24/7 AUTOMATED JOB APPLY DAEMON
echo   Sites: Naukri, LinkedIn, Foundit, Indeed, Shine, Instahyre
echo   Interval: Configured in settings.yaml (Default: Every 1 Hour)
echo   Output: reports/applied_jobs_latest.xlsx
echo ========================================================
echo.
.\venv\Scripts\python.exe -m src.main schedule
pause

