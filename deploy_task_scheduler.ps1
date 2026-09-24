# PowerShell Script to register Naukri Agent in Windows Task Scheduler
$TaskName = "Naukri_AutoApply_Daemon"
$WorkingDir = "D:\D_Drive\Job_search_apply_agent"
$ScriptPath = "$WorkingDir\venv\Scripts\python.exe"
$Arguments = "-m src.main schedule"

$Action = New-ScheduledTaskAction -Execute $ScriptPath -Argument $Arguments -WorkingDirectory $WorkingDir
$Trigger = New-ScheduledTaskTrigger -AtLogon
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Runs Naukri automated job search & apply daemon every hour" -Force
Write-Host "Windows Scheduled Task '$TaskName' successfully registered!" -ForegroundColor Green
