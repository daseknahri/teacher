# Claude Task: Exact Source Block Extraction

Use this task only after reading:

1. `docs/roadmap/AI-CONTENT-BANK-HANDOFF.md`
2. `docs/roadmap/NOTEBOOKLM-UNIT-BRAIN-ARCHITECTURE.md`
3. `docs/roadmap/LEAF-CONTENT-BANK-SPEC.md`
4. `docs/roadmap/EXACT-SOURCE-LESSON-MODE.md`
5. `docs/roadmap/AI-WORKLOG.md`

## Goal

Improve source-derived leaf lesson cards so the app preserves the exact PDF content more faithfully before any AI enhancement.

## What To Work On

Focus only on the extraction-quality slice:

- `backend/app/services/workflow_generation.py`
- `backend/tests/test_app_flows.py`

Optional only if required by the backend contract:
- `docs/roadmap/AI-WORKLOG.md`

## Required Product Rule

If the source already contains:
- a definition
- an example
- an exercise
- an activity

then the leaf card should preserve that source content first.

AI should help fill missing parts, not replace the source by default.

## Concrete Task

Improve the exact-source extraction quality for seeded leaf content by doing one or more of these safely:

1. better preserve ordered source blocks
2. split weak combined blocks when one extracted block clearly contains multiple pedagogical parts
3. prefer exact source excerpt text over summarized teaching material when both exist
4. improve matching for repeated examples/exercises in the same section

## Do Not Do

- do not rewrite the frontend lesson card
- do not change session logic
- do not change checklist completion rules
- do not add a new broad schema migration unless absolutely required
- do not make AI generation replace source-derived content by default

## Deliverable

Leave:
- a short summary
- exact files changed
- tests run
- any assumptions or follow-up risk
