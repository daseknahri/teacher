# Claude Task - Leaf Content Generation Endpoint

Last updated: 2026-05-19

Use this when you want Claude to implement the next backend slice after leaf content persistence.

## Goal

Add one backend endpoint that generates and saves content for a single leaf checklist item using the saved unit brain context.

This task should build on the new `workflow_leaf_content` storage layer without changing checklist semantics or session behavior.

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

Implement one backend endpoint that generates and saves content for one leaf checklist item.

Scope:

- add request/response schemas for leaf content generation
- add one generation function that returns a normalized leaf content package
- add one workflow route that generates content for one leaf item and stores it in workflow_leaf_content
- reuse existing unit-brain context:
  - unit title
  - item path
  - section path
  - source_text_excerpt
  - provider_context
  - unit_map_json
  - content_blocks_json
- keep all existing session/checklist behavior unchanged

Suggested files:

- backend/app/schemas.py
- backend/app/routers/workflow.py
- backend/app/services/workflow_generation.py
- backend/tests/test_app_flows.py
- docs/roadmap/AI-WORKLOG.md

Recommended endpoint:

- POST /workflow/classes/{class_id}/units/{unit_id}/leaf-content/{item_id}/generate

Recommended request shape:

- provider: optional string, default notebooklm
- regenerate: bool, default true

Recommended response model:

- reuse WorkflowLeafContentOut if practical
- otherwise add a small generate-out model that includes:
  - requested_provider
  - provider used
  - status
  - saved leaf content record

Behavior rules:

- only last-child checklist items are allowed
- return 400 if item is not a leaf
- require class write access
- require active unit, same as leaf-content PUT
- if the unit has no blueprint/unit brain context, return 409
- if requested provider is notebooklm and auth is stale, keep the same 409-style behavior used elsewhere
- do not add frontend code yet
- do not add partial regeneration yet
- do not modify session completion logic

Generation rules:

- this is per leaf item, not per whole unit
- derive item_path and section_path if missing
- prefer NotebookLM as the requested provider
- normalize output into the existing leaf content fields:
  - teaching_goal_md
  - launch_activity_md
  - explanation_md
  - worked_example_md
  - practice_md
  - solution_md
  - assessment_md
  - teacher_notes_md
  - source_excerpt_md
- save provider, model, status, source_payload_json, raw_provider_response_json

Prompt strategy:

- do not ask NotebookLM to rewrite the whole unit
- ask it for one exact leaf based on:
  - unit title
  - item path
  - section path
  - section-matched content blocks
  - unit map context

Implementation style:

- follow the existing package pattern used for:
  - generate_session_writeup_package
  - generate_unit_assistant_package
  - generate_unit_material_package
- prefer a normalized helper such as generate_leaf_content_package(...)

Testing expectations:

- happy path test with monkeypatched generation function
- non-leaf rejection test
- missing unit brain / missing blueprint context test

Validation commands:

- python -m compileall -q backend/app
- python -m pytest -p no:cacheprovider tests/test_app_flows.py -k "leaf_content"

When finished:

- update AI-WORKLOG.md with result and follow-up
- provide changed files
- provide assumptions
- provide any risk or next step
```

## Why This Is The Right Next Slice

It connects the new persisted storage to the saved NotebookLM unit brain without forcing frontend work yet.

That gives us:
- stable per-leaf storage
- one real generation path
- a clean handoff into the future reader/editor UI
