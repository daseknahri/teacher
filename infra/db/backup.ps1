param(
  [string]$DbContainer = "teacher-progress-db",
  [string]$DbName = "teacher_progress",
  [string]$DbUser = "teacher",
  [string]$OutputDir = ".\\storage\\backups"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw "Docker is required. Install Docker Desktop and try again."
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$fileName = "backup_${DbName}_${timestamp}.sql"
$target = Join-Path $OutputDir $fileName

Write-Host "Creating database backup from container '$DbContainer'..."
cmd /c "docker exec $DbContainer sh -lc ""pg_dump -U '$DbUser' '$DbName'"" > ""$target"""
if (-not (Test-Path $target)) {
  throw "Backup failed. Output file was not created."
}

$size = (Get-Item $target).Length
Write-Host "Backup completed: $target ($size bytes)"
