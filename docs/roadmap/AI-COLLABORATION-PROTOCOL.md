# AI Collaboration Protocol

Last updated: 2026-05-19

This file explains the safest way to let multiple coding models or engineers work on the same repo without breaking the project direction.

## Short Answer

Direct live AI-to-AI communication is usually not available in a reliable way.

The practical replacement is:
- shared git history
- shared markdown handoff files
- small task ownership
- frequent commits

Think of the repo docs as the communication layer.

## The Safest Collaboration Model

### 1. Shared source of truth

Treat these files as the architecture truth:

1. `docs/roadmap/AI-CONTENT-BANK-HANDOFF.md`
2. `docs/roadmap/NOTEBOOKLM-UNIT-BRAIN-ARCHITECTURE.md`
3. `docs/roadmap/LEAF-CONTENT-BANK-SPEC.md`
4. `docs/roadmap/LEAF-CONTENT-READER-ROADMAP.md`
5. `docs/roadmap/AI-WORKLOG.md`

### 2. One owner per active area

At any moment, try to have one owner per write scope.

Good examples:
- one model on backend generation
- one model on frontend reader UI
- one model on docs only

Bad example:
- two models editing the same session rendering file at the same time without coordination

### 3. Use the worklog as a mailbox

Before starting:
- claim the task
- list the files you expect to touch
- write the goal and assumptions

After finishing:
- write what changed
- list any follow-up risk
- release the file ownership

### 4. Prefer small commits

Do not keep large uncommitted AI work if another helper may need to continue.

Better:
- one coherent feature
- one clear commit
- one short summary in the worklog

### 5. Preserve the current architecture

Any collaborator should preserve:

- NotebookLM generates, app renders
- leaf item is the future teaching object
- progress truth stays tied to checklist/session state
- path-aware matching stays intact
- structural headings are preserved as context, not confused with actionable leaf completion

## Recommended Parallel Work Split

If two AIs are helping at the same time, split by write scope.

Good split:

- AI 1:
  - `backend/app/services/workflow_generation.py`
  - `backend/app/services/workflow_content.py`
  - schemas/models for leaf content

- AI 2:
  - `frontend/src/views/WorkflowView.js`
  - `frontend/src/views/CalendarView.js`
  - reader/editor UX only

- Shared:
  - docs

If both need the same file, switch back to sequential handoff.

## Sequential Handoff Pattern

This is the safest way to collaborate:

1. AI A reads the handoff docs
2. AI A updates `AI-WORKLOG.md` with active task
3. AI A implements and commits
4. AI A updates `AI-WORKLOG.md` with result and open issues
5. AI B starts from the updated worklog and latest commit

## What To Write In The Worklog

Every handoff should record:

- current goal
- files touched
- assumptions
- risks
- next recommended step

That is enough to make another AI useful quickly.

## Rules For Risky Changes

Pause and document before making changes that:

- alter checklist completion semantics
- change workflow/session contract payloads
- change NotebookLM auth/session handling
- change how path-aware matching works
- flatten or replace the grouped teaching-flow logic

These are core behaviors now.

## Collaboration Reality Check

If you want "on the fly" teamwork, the closest practical version is:

- keep one shared branch
- commit often
- keep `AI-WORKLOG.md` current
- let each AI read the latest docs before touching code

That gives you near-live continuity even though the models are not directly chatting with each other.
