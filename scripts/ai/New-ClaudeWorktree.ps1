param(
    [Parameter(Mandatory = $true)]
    [string]$TaskName,
    [string]$BaseBranch = "main"
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

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repoRoot

$slug = Get-Slug -Value $TaskName
$branchName = "claude/$slug"
$worktreeRoot = Join-Path $repoRoot ".worktrees"
$worktreePath = Join-Path $worktreeRoot "claude-$slug"

if (-not (Test-Path $worktreeRoot)) {
    New-Item -ItemType Directory -Path $worktreeRoot | Out-Null
}

if (Test-Path $worktreePath) {
    Write-Host "Claude worktree already exists:" -ForegroundColor Yellow
    Write-Host "  Path: $worktreePath"
    Write-Host "  Branch: $branchName"
    exit 0
}

$existingBranch = git branch --list $branchName
if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect existing git branches."
}

if ($existingBranch) {
    git worktree add $worktreePath $branchName
} else {
    git worktree add $worktreePath -b $branchName $BaseBranch
}

if ($LASTEXITCODE -ne 0) {
    throw "Failed to create Claude worktree."
}

Write-Host "Claude worktree ready." -ForegroundColor Green
Write-Host "  Path:   $worktreePath"
Write-Host "  Branch: $branchName"
