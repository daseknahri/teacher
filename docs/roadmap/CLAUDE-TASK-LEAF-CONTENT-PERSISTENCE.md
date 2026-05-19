# Claude Task - Leaf Content Persistence Slice

Last updated: 2026-05-19

Use this when you want Claude to take the first safe implementation slice for the `leaf content bank` direction.

## Goal

Add persisted leaf content records to the backend, with basic read/write API only.

This task should lay the foundation for the future lesson reader without changing existing checklist, session, or NotebookLM workflow behavior.

## Paste-Ready Prompt

```text
You are working on the Teacher Progress app.

Before coding, read these files in this order:

1. docs/roadmap/AI-CONTENT-BANK-HANDOFF.md
2. docs/roadmap/NOTEBOOKLM-UNIT-BRAIN-ARCHITECTURE.md
3. docs/roadmap/LEAF-CONTENT-BANK-SPEC.md
4. docs/roadmap/LEAF-CONTENT-READER-ROADMAP.md
5. docs/roadmap/AI-COLLABORATION-PROTOCOL.md
6. docs/roadmap/AI-WORKLOG.md

Then update AI-WORKLOG.md with an in_progress entry for this task before editing code.

Your task is intentionally narrow:

Implement persisted leaf content records with basic backend read/write support.

Scope:

- add one new SQLAlchemy model for leaf content
- add runtime schema compatibility support in backend/app/database.py
- add Pydantic schemas for leaf content read/write
- add workflow API endpoints for:
  - get one leaf content record by checklist item
  - create or update one leaf content record by checklist item
- keep all existing workflow/session/checklist behavior unchanged

Suggested files:

- backend/app/models.py
- backend/app/database.py
- backend/app/schemas.py
- backend/app/routers/workflow.py
- backend/tests/test_app_flows.py

Recommended model shape:

- unit_id
- checklist_item_id
- item_path_json
- section_path_json
- provider
- model
- status
- reviewed
- reviewed_at
- reviewed_by_user_id
- source_payload_json
- raw_provider_response_json
- teaching_goal_md
- launch_activity_md
- explanation_md
- worked_example_md
- practice_md
- solution_md
- assessment_md
- teacher_notes_md
- source_excerpt_md
- created_at
- updated_at

Recommended API shape:

- GET /workflow/classes/{class_id}/units/{unit_id}/leaf-content/{item_id}
- PUT /workflow/classes/{class_id}/units/{unit_id}/leaf-content/{item_id}

Behavior rules:

- endpoint must verify class access and active/owned unit context the same way workflow routes do
- only last-child checklist items should be accepted for leaf content storage
- return 400 if the checklist item is not a leaf
- do not generate content yet
- do not add frontend work yet
- do not modify session completion logic
- do not modify NotebookLM unit extraction logic

Repo-specific implementation note:

- this project uses runtime schema compatibility in backend/app/database.py
- do not introduce Alembic or a new migration framework for this slice

Definition of done:

- one leaf content record can be saved for one last-child checklist item
- the same record can be fetched again
- tests cover happy path and non-leaf rejection
- compile/test commands pass

Validation commands:

- python -m compileall -q backend/app
- python -m pytest -p no:cacheprovider tests/test_app_flows.py -k "leaf_content or workflow"

When finished:

- update AI-WORKLOG.md with result and follow-up
- provide changed files
- provide assumptions
- provide any risk or next step
```

## Why This Is A Good First Claude Task

It is:
- foundational
- backend-only
- easy to review
- low risk to current teacher workflow

It also creates a clean handoff for the next step:
- one leaf content generation endpoint
- then one frontend leaf reader
