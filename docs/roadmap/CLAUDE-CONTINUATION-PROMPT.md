# Claude Continuation Prompt

Last updated: 2026-06-03

Use this prompt when handing the repo to Claude and you want it to continue the work without breaking the current app direction.

## Prompt To Paste

```text
You are continuing work on the Teacher Progress app.

Before changing code, read these files in this order:

1. CLAUDE.md
2. docs/roadmap/AI-WORKLOG.md
3. docs/roadmap/AI-COLLABORATION-PROTOCOL.md
4. docs/roadmap/AI-CONTENT-BANK-HANDOFF.md
5. docs/roadmap/NOTEBOOKLM-UNIT-BRAIN-ARCHITECTURE.md
6. docs/roadmap/LEAF-CONTENT-BANK-SPEC.md
7. docs/roadmap/EXACT-SOURCE-LESSON-MODE.md
8. docs/roadmap/LEAF-CONTENT-READER-ROADMAP.md

Current stable app direction to preserve:

- The checklist/session workflow is the current source of truth.
- Teachers upload a unit/exercise PDF, review the extracted checklist, teach from it, and check only what was really covered.
- Supervisor/owner views should make teacher activity readable through filters, analytics, and calendar/session detail.
- Exam and exam-correction units are intentionally minimal templates for now.

Long-term direction to preserve:

- NotebookLM is the grounded understanding and generation layer for each unit.
- The app is the source of truth for workflow, progress, rendering, review, and stored teaching content.
- The long-term target is not only PDF -> checklist.
- The long-term target is unit understanding -> per-leaf teaching content bank -> reader/editor -> derived materials.

Do not break these rules:

1. NotebookLM generates, the app renders.
2. Keep path-aware session context. Do not flatten matching down to title-only logic.
3. Parent headings are structural. Actionable progress belongs to leaf items.
4. Preserve started outline context in sessions and future textbook/export work.
5. Prefer structured Markdown + LaTeX fields over one giant raw LaTeX blob.
6. Regeneration should be granular per part, not always whole-unit or whole-leaf.
7. If the PDF already contains a definition/example/exercise/activity, preserve that source content first and treat AI as an additive layer.

Current workflow reality to preserve:

- Workflow and Calendar already share session context.
- Session routes already use checked item paths and grouped teaching flow.
- Session write-ups already use grouped teaching sections.
- Headlines/session outline should preserve the path from top heading down to the taught row.
- Exercise-series extraction should store only the series title and exact exercise headlines.
- Chapter extraction should preserve student buckets such as Activites, Contenu de la lecon, and Evaluation while dropping teacher meta sections.

How to work safely:

- Make small changes.
- Do not rewrite unrelated architecture.
- If changing a contract, update the relevant docs.
- Before and after work, update docs/roadmap/AI-WORKLOG.md.
- If working in parallel with another AI or engineer, claim file ownership in the worklog first.

Best next direction if no other task is specified:

- continue supervisor dashboard/calendar UX cleanup
- make selected teacher analytics and calendar session details easier to read
- keep the teacher workflow stable while doing this

Only move to content-bank/RAG work when the user explicitly asks for that phase.

When you finish, leave:

- a short change summary
- exact files changed
- any assumptions made
- any follow-up risks
```

## Why This Prompt Exists

This project now has enough workflow-specific logic that a generic coding prompt is not enough.

Claude should start from:
- the current unit-brain architecture
- the current session/checklist rules
- the current long-term direction

not from a blank "AI content app" assumption.
