param(
  [string]$TaskName = "TeacherProgressDailyBackup",
  [string]$At = "22:00",
  [string]$RepositoryRoot = "."
)

$ErrorActionPreference = "Stop"

$repoPath = (Resolve-Path $RepositoryRoot).Path
$scriptPath = Join-Path $repoPath "infra\\db\\backup.ps1"
if (-not (Test-Path $scriptPath)) {
  throw "Backup script not found: $scriptPath"
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
Write-Host "Scheduled task '$TaskName' created. Daily backup time: $At"
