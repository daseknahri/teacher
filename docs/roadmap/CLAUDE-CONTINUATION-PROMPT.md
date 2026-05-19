# Claude Continuation Prompt

Last updated: 2026-05-19

Use this prompt when handing the repo to Claude and you want it to continue the work without breaking the current app direction.

## Prompt To Paste

```text
You are continuing work on the Teacher Progress app.

Before changing code, read these files in this order:

1. docs/roadmap/AI-CONTENT-BANK-HANDOFF.md
2. docs/roadmap/NOTEBOOKLM-UNIT-BRAIN-ARCHITECTURE.md
3. docs/roadmap/LEAF-CONTENT-BANK-SPEC.md
4. docs/roadmap/LEAF-CONTENT-READER-ROADMAP.md
5. docs/roadmap/AI-COLLABORATION-PROTOCOL.md
6. docs/roadmap/AI-WORKLOG.md

Project direction to preserve:

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

Current workflow reality to preserve:

- Workflow and Calendar already share session context.
- Session routes already use checked item paths and grouped teaching flow.
- Session write-ups already use grouped teaching sections.
- Headlines/session outline should preserve the path from top heading down to the taught row.

How to work safely:

- Make small changes.
- Do not rewrite unrelated architecture.
- If changing a contract, update the relevant docs.
- Before and after work, update docs/roadmap/AI-WORKLOG.md.
- If working in parallel with another AI or engineer, claim file ownership in the worklog first.

Best next direction if no other task is specified:

- build persisted leaf content records
- add one leaf content generation endpoint
- build one leaf reader/editor with Markdown + LaTeX rendering
- connect that reader to session flow

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
