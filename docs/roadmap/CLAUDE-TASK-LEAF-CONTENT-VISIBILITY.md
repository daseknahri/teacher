# Claude Task - Leaf Content Visibility and Calendar Access

Last updated: 2026-05-19

Use this when you want Claude to implement the next teacher-facing slice after the first Workflow leaf lesson card.

## Goal

Make saved/generated leaf content visible and reachable across the main teaching surfaces:

- Workflow
- Calendar

This task should help the teacher see which leaf items already have lesson-card content, and open the same card from Calendar too.

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

Make leaf lesson content visible and accessible across Workflow and Calendar.

Scope:

- add one lightweight backend list endpoint for saved leaf-content summaries per unit
- add frontend unit-level leaf-content status caching
- show a small status cue on leaf rows when content exists
- allow opening the same lesson card from Calendar route views

Suggested files:

- backend/app/schemas.py
- backend/app/routers/workflow.py
- backend/tests/test_app_flows.py
- frontend/src/utils/leafContent.js
- frontend/src/views/WorkflowView.js
- frontend/src/views/CalendarView.js
- frontend/src/style/components.css
- docs/roadmap/AI-WORKLOG.md

Recommended backend endpoint:

- GET /workflow/classes/{class_id}/units/{unit_id}/leaf-content

Recommended response shape:

- one row per saved leaf-content record
- include only summary-safe fields such as:
  - id
  - checklist_item_id
  - status
  - reviewed
  - updated_at
  - provider

Behavior rules:

- keep existing per-item GET/PUT/generate endpoints unchanged
- keep session completion logic unchanged
- keep checklist toggle behavior unchanged
- do not add partial regeneration yet
- do not add Calendar editing beyond opening the same leaf card

Frontend requirements:

Workflow:
- use the unit-level leaf-content summary to show a subtle status indicator on leaf rows
- show it in:
  - Unit Setup checklist
  - Active Session Teaching Flow View
  - Active Session Full Unit Checklist

Calendar:
- add the same lesson-card access in:
  - grouped Teaching Flow View
  - Full Planned Route / Recorded Checklist Route when practical
- show the same subtle content status cue when available

UX guidance:

- indicator should be calm and easy to scan
- for example:
  - small dot
  - small badge like Saved / Draft / Ready
- do not make the checklist visually noisy

Implementation style:

- reuse the existing openLeafContentModal helper
- prefer small helper functions for:
  - fetching unit leaf-content summaries
  - mapping checklist_item_id -> summary
- keep the first implementation simple and robust

Testing / validation expectations:

- backend happy-path test for the new list endpoint
- npm run build

When finished:

- update AI-WORKLOG.md with result and follow-up
- provide changed files
- provide assumptions
- provide any risk or next step
```

## Why This Is The Right Next Slice

It closes the biggest usability gaps after the first leaf reader:

- teachers can see where content already exists
- teachers can access the same lesson card from Calendar
- the content bank becomes visible across the actual workflow, not hidden behind one screen
