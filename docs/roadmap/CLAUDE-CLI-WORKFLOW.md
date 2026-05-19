# Claude CLI Workflow

Last updated: 2026-05-19

This file explains how to use Claude CLI as a bounded coding worker for this repo.

## Goal

Use Claude safely:
- on a separate git worktree
- with a task-specific prompt
- with repo docs as the architecture guardrails

The best pattern is:
- Codex or the human defines the task
- Claude works in a separate branch/worktree
- Codex or the human reviews the result before merging

## Files That Matter

- `docs/roadmap/CLAUDE-CONTINUATION-PROMPT.md`
- `docs/roadmap/CLAUDE-TASK-LEAF-CONTENT-PERSISTENCE.md`
- `docs/roadmap/AI-COLLABORATION-PROTOCOL.md`
- `docs/roadmap/AI-WORKLOG.md`
- `scripts/ai/New-ClaudeWorktree.ps1`
- `scripts/ai/Invoke-ClaudeTask.ps1`

## One-Time Rule

Before asking Claude to code, make sure the task is:
- small
- bounded
- assigned to its own file area if possible

Avoid starting Claude on a broad rewrite task.

## Standard Flow

### 1. Create a Claude worktree

Example:

```powershell
.\scripts\ai\New-ClaudeWorktree.ps1 -TaskName "leaf-content-persistence"
```

This creates:
- branch: `claude/leaf-content-persistence`
- worktree path: `.worktrees/claude-leaf-content-persistence`

### 2. Run a Claude task prompt

Example:

```powershell
.\scripts\ai\Invoke-ClaudeTask.ps1 `
  -TaskFile "docs/roadmap/CLAUDE-TASK-LEAF-CONTENT-PERSISTENCE.md" `
  -TaskName "leaf-content-persistence"
```

This script:
- reads the fenced `text` prompt from the task file
- runs Claude in the matching worktree
- stores logs under `storage/ai/claude/...`

### 3. Review Claude's result

Check:
- Claude response in `storage/ai/claude/.../response.txt`
- git diff inside the worktree
- test results Claude reported

### 4. Merge only after review

Recommended:
- inspect the branch/worktree diff first
- then merge or cherry-pick intentionally

## Practical Commands

### See worktree status

```powershell
git worktree list
```

### Review Claude branch diff

```powershell
git -C .worktrees/claude-leaf-content-persistence status
git -C .worktrees/claude-leaf-content-persistence diff
```

### Remove a finished Claude worktree

```powershell
git worktree remove .worktrees/claude-leaf-content-persistence
git branch -D claude/leaf-content-persistence
```

Only do this after the work is merged or intentionally discarded.

## Recommended Team Pattern

Best setup:

- Claude:
  - bounded implementation task
  - separate worktree

- Codex:
  - task design
  - repo-aware review
  - integration and follow-up fixes

That way Claude speeds up implementation without owning project direction.

## Notes About The Scripts

### `New-ClaudeWorktree.ps1`

Creates a predictable worktree and branch for the task.

### `Invoke-ClaudeTask.ps1`

Extracts the first fenced `text` block from the task markdown file and sends it to Claude with:
- selected model
- selected effort
- permission mode

Logs are saved automatically.

## Suggested First Use

Start with:

- `docs/roadmap/CLAUDE-TASK-LEAF-CONTENT-PERSISTENCE.md`

This is a safe backend-only slice and a good test of the workflow.
