@echo off
title Naukri Auto-Apply 24/7 Daemon (Hourly Top 20 + Excel Export)
cd /d "%~dp0"
echo ========================================================
echo   NAUKRI 24/7 FULLY AUTOMATED JOB APPLY DAEMON
echo   Interval: Every 1 Hour
echo   Limit: Top 20 Applications / Hour
echo   Output: reports/applied_jobs_latest.xlsx
echo ========================================================
echo.
.\venv\Scripts\python.exe -m src.main schedule
pause
