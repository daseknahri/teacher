# Claude Task - Workflow Leaf Reader

Last updated: 2026-05-19

Use this when you want Claude to implement the first teacher-facing leaf content reader on top of the new backend leaf-content API.

## Goal

Add a Workflow-only leaf content reader/editor so a teacher can:

- open one leaf checklist item
- load existing saved leaf content
- generate leaf content from NotebookLM when missing
- switch between rendered view and source/edit view
- save edits back to the backend

This task should make the new content-bank direction visible in the app without changing existing checklist/session semantics.

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

Implement the first frontend leaf content reader/editor inside Workflow only.

Scope:

- add a teacher-facing "leaf lesson card" modal or panel in Workflow
- wire it to the new leaf-content backend endpoints
- allow generate / load / edit / save for one leaf item
- provide a rendered mode and a source/edit mode
- support Markdown + LaTeX rendering in the reader
- keep Calendar untouched for now

Suggested files:

- frontend/package.json
- frontend/src/views/WorkflowView.js
- frontend/src/style/components.css
- optionally one small helper file under frontend/src/utils/
- docs/roadmap/AI-WORKLOG.md

Required backend endpoints already exist:

- GET /workflow/classes/{class_id}/units/{unit_id}/leaf-content/{item_id}
- PUT /workflow/classes/{class_id}/units/{unit_id}/leaf-content/{item_id}
- POST /workflow/classes/{class_id}/units/{unit_id}/leaf-content/{item_id}/generate

Behavior rules:

- only leaf checklist items should show the new reader action
- do not change checklist toggle behavior
- do not change session completion logic
- do not change Calendar yet
- do not add partial regeneration yet

Recommended UX:

- add a small "Lesson Card" or "Open Card" action on leaf rows in:
  - Teaching Flow View
  - Full Unit Checklist
- open a modal
- modal supports:
  - rendered view
  - source/edit view
  - generate
  - save
  - close

Content sections to show:

- teaching goal
- launch activity
- explanation
- worked example
- practice
- solution
- assessment
- teacher notes
- source excerpt

Rendering rules:

- rendered mode should read like a teaching card
- source mode should expose the raw editable Markdown + LaTeX source
- if you add libraries, keep them lightweight and focused
- prefer a simple helper approach over a big frontend refactor

LaTeX rule:

- we want the app to preserve editable math source
- teacher should be able to switch to source mode, change numbers/formulas, save, and switch back

State rules:

- if GET returns 404, show an empty state with Generate action
- if content exists, show it immediately
- after generate, refresh the saved record in the UI
- after save, keep the modal open and show a success toast

Implementation style:

- keep the first slice Workflow-only
- avoid broad cleanup or unrelated UI refactors
- add only the minimum helper state needed

Testing / validation expectations:

- npm run build
- if you add a helper, keep imports clean and production-safe

When finished:

- update AI-WORKLOG.md with result and follow-up
- provide changed files
- provide assumptions
- provide any risk or next step
```

## Why This Is The Right Next Slice

It is the first point where the teacher can actually use the new leaf-content system in class:

- backend persistence already exists
- generation already exists
- this adds the first classroom reader/editor surface

That gives us a real vertical slice:
- unit brain
- per-leaf generation
- per-leaf reading/editing

without forcing Calendar or textbook/export changes yet.
