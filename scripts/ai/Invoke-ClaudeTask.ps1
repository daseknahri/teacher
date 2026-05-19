param(
    [Parameter(Mandatory = $true)]
    [string]$TaskFile,
    [Parameter(Mandatory = $true)]
    [string]$TaskName,
    [string]$Model = "sonnet",
    [ValidateSet("low", "medium", "high", "xhigh", "max")]
    [string]$Effort = "medium",
    [ValidateSet("acceptEdits", "auto", "bypassPermissions", "default", "dontAsk", "plan")]
    [string]$PermissionMode = "bypassPermissions",
    [switch]$SkipClaude,
    [switch]$UseCurrentRepo
)

$ErrorActionPreference = "Stop"

function Get-Slug {
    param([string]$Value)
    $slug = $Value.ToLowerInvariant()
    $slug = [regex]::Replace($slug, "[^a-z0-9]+", "-")
    $slug = $slug.Trim("-")
    if (-not $slug) {
        throw "TaskName produced an empty slug."
    }
    return $slug
}

function Get-TaskPrompt {
    param([string]$Path)
    $content = Get-Content -Raw -Path $Path
    $match = [regex]::Match($content, '(?s)```text\s*(.*?)```')
    if ($match.Success) {
        return $match.Groups[1].Value.Trim()
    }
    return $content.Trim()
}

$repoRoot = (Resolve-Path -Path (Join-Path -Path $PSScriptRoot -ChildPath '..\..')).Path
Set-Location $repoRoot

$taskPath = (Resolve-Path $TaskFile).Path
$slug = Get-Slug -Value $TaskName
$worktreeRoot = Join-Path -Path $repoRoot -ChildPath ".worktrees"
$worktreePath = if ($UseCurrentRepo) {
    $repoRoot
} else {
    Join-Path -Path $worktreeRoot -ChildPath "claude-$slug"
}

if (-not (Test-Path $worktreePath)) {
    throw "Worktree path does not exist: $worktreePath"
}

$prompt = Get-TaskPrompt -Path $taskPath
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$runRoot = Join-Path -Path $repoRoot -ChildPath "storage\ai\claude\$timestamp-$slug"
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null

$promptLog = Join-Path -Path $runRoot -ChildPath "prompt.txt"
$responseLog = Join-Path -Path $runRoot -ChildPath "response.txt"
$metaLog = Join-Path -Path $runRoot -ChildPath "meta.json"

Set-Content -Path $promptLog -Value $prompt -Encoding UTF8

$meta = [ordered]@{
    task_name = $TaskName
    task_file = $taskPath
    repo_root = $repoRoot
    worktree_path = $worktreePath
    model = $Model
    effort = $Effort
    permission_mode = $PermissionMode
    created_at = (Get-Date).ToString("s")
}
$meta | ConvertTo-Json -Depth 4 | Set-Content -Path $metaLog -Encoding UTF8

Write-Host "Claude task prepared." -ForegroundColor Green
Write-Host "  Task file:   $taskPath"
Write-Host "  Worktree:    $worktreePath"
Write-Host "  Prompt log:  $promptLog"
Write-Host "  Response log:$responseLog"

if ($SkipClaude) {
    Write-Host "Skipping Claude execution by request." -ForegroundColor Yellow
    return
}

Push-Location $worktreePath
try {
    $response = claude -p $prompt --model $Model --effort $Effort --permission-mode $PermissionMode
    if ($LASTEXITCODE -ne 0) {
        throw "Claude exited with code $LASTEXITCODE."
    }
    Set-Content -Path $responseLog -Value $response -Encoding UTF8
    Write-Host ""
    Write-Host "Claude response:" -ForegroundColor Cyan
    Write-Host $response
} finally {
    Pop-Location
}
