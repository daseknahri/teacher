# AI Content Bank Handoff

Last updated: 2026-05-19

This note is the fastest handoff for another coding model or engineer who needs to continue the `NotebookLM -> unit brain -> leaf content bank` direction in this repo.

## Read Order

Read these files in this order:

1. `docs/roadmap/AI-CONTENT-BANK-HANDOFF.md`
2. `docs/roadmap/NOTEBOOKLM-UNIT-BRAIN-ARCHITECTURE.md`
3. `docs/roadmap/LEAF-CONTENT-BANK-SPEC.md`
4. `docs/roadmap/LEAF-CONTENT-READER-ROADMAP.md`

## Current Product Reality

The app already has a strong workflow base:

- one NotebookLM context per unit
- extracted checklist tree
- session tracking in Workflow and Calendar
- path-aware checked session context
- grouped teaching flow for sessions
- session write-up generation that already uses grouped teaching sections

This is important: do not restart from a blank architecture. Extend the current `unit brain` direction that already exists in the app.

## Core Direction

The next big move is:

- from `PDF -> checklist only`
- to `PDF/source pack -> unit understanding -> leaf-by-leaf teaching content`

The target teaching object is no longer only the checklist row. It is:

- the checklist leaf
- plus its stored teaching content

Each last child checklist item should eventually become a real lesson card with editable content.

## Non-Negotiable Rules

### 1. NotebookLM generates, the app renders

NotebookLM should produce structured content.

The app should:
- store it
- render it
- edit it
- review it
- reuse it

Do not depend on NotebookLM for final classroom UI rendering.

### 2. Leaf item is the core teaching object

Do not make the session depend only on broad section summaries if we can tie work back to the exact leaf path.

The leaf item should be the durable unit of:
- progress
- teaching content
- regeneration
- reuse

### 3. Store structured fields, not one giant blob

Do not store one huge raw LaTeX document per leaf as the first design.

Preferred format:
- structured fields
- Markdown + LaTeX inside each field

Example fields:
- teaching goal
- launch activity
- explanation
- worked example
- practice
- solution
- assessment
- teacher notes

### 4. Keep path-aware context

The app has already moved toward:
- checked item paths
- checked section paths
- grouped teaching flow

Do not flatten this back down to title-only matching.

Repeated titles like:
- `Examples`
- `Exercises`
- `Definition`

must be matched through their full path whenever possible.

### 5. Parent headings stay structural

Checklist parent headings are structural context first.

The app should preserve the started outline in session summaries and future textbook work, but actual completion truth should stay tied to actionable leaf rows.

### 6. Missing activity is a generation problem, not a blocker

If a source PDF lacks explicit labels like:
- activity
- example
- exercise

the system should still be able to infer or generate the missing pedagogical piece in the correct place.

## Best Output Format

For math-heavy content, the best first storage/rendering format is:

- Markdown for prose and structure
- LaTeX for formulas and worked steps

This gives the teacher:
- rendered math view
- source/code view
- easy editing of numbers, signs, and formulas

Recommended frontend rendering:
- Markdown renderer
- KaTeX for math

## What We Want the Teacher to Experience

For each checklist leaf:

1. open the leaf
2. read the explanation/activity/example/exercise
3. view it rendered cleanly
4. switch to source mode when needed
5. edit a formula or number directly
6. regenerate only the weak part
7. teach it
8. mark it done

That is the target experience.

## Good First Implementation Sequence

1. persist one leaf content record per last-child checklist item
2. add one backend API to get/save leaf content
3. add one backend API to generate leaf content from NotebookLM
4. build one frontend lesson card with render/source toggle
5. support regenerating one field at a time
6. connect that lesson card to live session flow

## Things To Avoid

Avoid these as first-version decisions:

- one giant raw LaTeX document per unit
- regenerating the entire unit every time one example is weak
- title-only matching for repeated headings
- storing final teaching content only inside raw provider responses
- making progress depend on generated documents instead of checklist truth

## Why This Direction Is Worth It

The current checklist/session/write-up work already proves the app can track teaching progress well.

The next jump is to make the app useful during teaching, not only after extraction.

That happens when each leaf item becomes:
- readable
- editable
- regenerable
- reusable

Once that exists, the same content can power:
- session delivery
- session write-ups
- textbook pages
- worksheets
- slides
- quizzes
- exams

## Handoff Note

If you are continuing implementation from this file, preserve this design intent:

- `NotebookLM` is the grounded generator
- `our app` is the structured teaching workspace
- `the leaf item` is the durable teaching object
- `Markdown + LaTeX` is the most practical first content format
