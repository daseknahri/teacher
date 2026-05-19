# AI Worklog

Last updated: 2026-05-19

Use this file as a shared handoff log between coding sessions, AI helpers, and engineers.

## How To Use

Before starting work:
- add a new entry at the top
- claim the task
- list expected files
- list assumptions

After finishing:
- update the same entry
- record what changed
- record open risks or follow-up work

Keep entries short and factual.

---

## Entry Template

### YYYY-MM-DD HH:MM - Owner

- Status: planned | in_progress | done | blocked
- Goal:
- Files expected:
  - `path/to/file`
- Assumptions:
- Notes:
- Result:
- Follow-up:

---

## Current Entries

### 2026-05-19 22:45 - Claude

- Status: planned
- Goal: implement the first Workflow-only leaf content reader/editor on top of the new leaf-content backend endpoints
- Files expected:
  - `frontend/package.json`
  - `frontend/src/views/WorkflowView.js`
  - `frontend/src/style/components.css`
  - `frontend/src/utils/*` (optional small helper only if needed)
  - `docs/roadmap/AI-WORKLOG.md`
- Assumptions:
  - the safest next slice is Workflow only, not Calendar yet
  - the UI should open from leaf checklist rows without changing checklist toggle semantics
  - rendered mode should support Markdown + LaTeX, while source mode keeps the raw editable content
  - missing content should lead to a Generate-first empty state, not an error wall
- Notes:
  - task prompt lives in `docs/roadmap/CLAUDE-TASK-WORKFLOW-LEAF-READER.md`
  - this task should not change session completion logic, calendar flow, or partial regeneration
- Result:
- Follow-up:

### 2026-05-19 22:05 - Claude

- Status: done
- Goal: implement a backend endpoint that generates and saves content for one leaf checklist item using the saved unit brain
- Files expected:
  - `backend/app/schemas.py`
  - `backend/app/routers/workflow.py`
  - `backend/app/services/workflow_generation.py`
  - `backend/tests/test_app_flows.py`
  - `docs/roadmap/AI-WORKLOG.md`
- Assumptions:
  - the next safe slice is per-leaf generation, not frontend reader work yet
  - the generation contract should follow the existing package style already used for write-ups and unit helpers
  - fallback provider produces a stub result when NotebookLM is not configured (error_message set, status=degraded)
  - blueprint must exist for generation; missing blueprint returns 409
  - provider_context in blueprint.blueprint_json is used for the existing notebook; if absent a temporary notebook is created
  - item_path / section_path derived via existing _derive_leaf_item_paths if not stored yet on the row
- Notes:
  - task prompt lives in `docs/roadmap/CLAUDE-TASK-LEAF-CONTENT-GENERATION.md`
  - this task should not modify checklist/session semantics
  - no frontend code added; no partial regeneration added
- Result:
  - added WorkflowLeafContentGenerateIn and WorkflowLeafContentGenerateOut Pydantic schemas
  - added SUPPORTED_LEAF_CONTENT_PROVIDERS constant to workflow_generation.py
  - added generate_leaf_content_package (public), _notebooklm_generate_leaf_content (sync), _notebooklm_generate_leaf_content_async, _normalize_leaf_content_payload, _build_notebooklm_leaf_content_prompt helpers
  - added POST /workflow/classes/{class_id}/units/{unit_id}/leaf-content/{item_id}/generate endpoint
  - endpoint: ensure_class_writable, active unit required, leaf-only check, blueprint required (409), derives paths if missing, upserts WorkflowLeafContent, logs audit
  - added test_leaf_content_generate_happy_path (monkeypatched), test_leaf_content_generate_rejects_non_leaf, test_leaf_content_generate_requires_blueprint
  - compile check passes; all 5 leaf_content tests pass
- Follow-up:
  - after this lands, the next step is the first frontend leaf reader/editor (Phase 4 in LEAF-CONTENT-READER-ROADMAP.md)
  - consider adding a fallback stub path for generate_leaf_content_package when NotebookLM is not configured (currently raises 409)

### 2026-05-19 21:35 - Codex

- Status: done
- Goal: turn the repo handoff docs into a practical Claude CLI workflow with safe worktrees and task prompts
- Files expected:
  - `README.md`
  - `.gitignore`
  - `docs/roadmap/CLAUDE-CLI-WORKFLOW.md`
  - `scripts/ai/New-ClaudeWorktree.ps1`
  - `scripts/ai/Invoke-ClaudeTask.ps1`
  - `docs/roadmap/AI-WORKLOG.md`
- Assumptions:
  - Claude CLI is installed and authenticated on this machine
  - the safest first usage is one task per worktree, reviewed before merge
- Notes:
  - verified `claude -p` works on this machine
  - smoke-tested the helper scripts
  - cleaned the temporary smoke worktree after validation
- Result:
  - the repo now has a working Claude CLI workflow with:
    - task markdown files
    - worktree helper
    - task runner
    - log storage under `storage/ai/claude/`
- Follow-up:
  - next real use should be the leaf-content persistence task in its own Claude worktree

### 2026-05-19 19:35 - Claude

- Status: done
- Goal: implement the first backend leaf content persistence slice without changing existing workflow/session behavior
- Files expected:
  - `backend/app/models.py`
  - `backend/app/database.py`
  - `backend/app/schemas.py`
  - `backend/app/routers/workflow.py`
  - `backend/tests/test_app_flows.py`
  - `docs/roadmap/AI-WORKLOG.md`
- Assumptions:
  - the safest first implementation is persistence plus read/write only
  - generation and frontend reader should wait until storage is stable
  - GET returns 404 if no leaf content record exists yet
  - PUT is upsert (create or update) for any leaf checklist item
  - leaf detection: an item is a leaf if it has no child rows in workflow_checklist_items
  - GET uses ensure_class_access; PUT uses ensure_class_writable + active unit check
- Notes:
  - task prompt lives in `docs/roadmap/CLAUDE-TASK-LEAF-CONTENT-PERSISTENCE.md`
  - this task should not modify checklist completion semantics or session matching logic
- Result:
  - added WorkflowLeafContent model (workflow_leaf_content table, unique on unit_id+checklist_item_id)
  - added schema compatibility block in database.py with _ensure_column entries for all new columns
  - added WorkflowLeafContentOut and WorkflowLeafContentUpsertIn Pydantic schemas
  - added GET /workflow/classes/{class_id}/units/{unit_id}/leaf-content/{item_id} (ensure_class_access, any unit status)
  - added PUT /workflow/classes/{class_id}/units/{unit_id}/leaf-content/{item_id} (ensure_class_writable, active unit only, upsert)
  - both endpoints return 400 if the checklist item is not a leaf (has children)
  - added test_leaf_content_happy_path and test_leaf_content_rejects_non_leaf_item; both pass
  - compile check passes; targeted leaf-content tests pass
- Follow-up:
  - after this lands, the next step is one leaf content generation endpoint (Phase 3) or one minimal frontend reader (Phase 4)

### 2026-05-19 19:10 - Codex

- Status: done
- Goal: add stable handoff docs so Claude or another AI can continue the NotebookLM content-bank direction safely
- Files expected:
  - `README.md`
  - `docs/roadmap/AI-CONTENT-BANK-HANDOFF.md`
  - `docs/roadmap/NOTEBOOKLM-UNIT-BRAIN-ARCHITECTURE.md`
  - `docs/roadmap/LEAF-CONTENT-BANK-SPEC.md`
  - `docs/roadmap/LEAF-CONTENT-READER-ROADMAP.md`
  - `docs/roadmap/CLAUDE-CONTINUATION-PROMPT.md`
  - `docs/roadmap/AI-COLLABORATION-PROTOCOL.md`
  - `docs/roadmap/AI-WORKLOG.md`
- Assumptions:
  - the next collaborator needs both architecture context and safety rails
  - the repo should preserve the current workflow/session logic while moving toward a leaf-content bank
- Notes:
  - added a Claude-ready continuation prompt
  - added a collaboration protocol for multi-AI work
  - added this worklog template
- Result:
  - another AI can now start from a clear read order, known guardrails, and a shared handoff file
- Follow-up:
  - next implementation step should be persisted leaf content records and one leaf reader/editor slice
