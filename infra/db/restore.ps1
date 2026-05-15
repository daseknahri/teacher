param(
  [Parameter(Mandatory = $true)]
  [string]$InputFile,
  [string]$DbContainer = "teacher-progress-db",
  [string]$DbName = "teacher_progress",
  [string]$DbUser = "teacher",
  [switch]$ResetSchema
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $InputFile)) {
  throw "Input file not found: $InputFile"
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw "Docker is required. Install Docker Desktop and try again."
}

Write-Host "Restoring database '$DbName' from file '$InputFile'..."
if ($ResetSchema) {
  Write-Host "Resetting schema 'public' before restore..."
  docker exec $DbContainer sh -lc "psql -U '$DbUser' -d '$DbName' -v ON_ERROR_STOP=1 -c ""DROP SCHEMA public CASCADE; CREATE SCHEMA public;"""
}

cmd /c "type ""$InputFile"" | docker exec -i $DbContainer sh -lc ""psql -U '$DbUser' -d '$DbName' -v ON_ERROR_STOP=1"""
Write-Host "Restore completed."
