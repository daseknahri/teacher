# Exact Source Lesson Mode

Last updated: 2026-05-20

This note defines the product rule for leaf lesson cards when the source PDF already contains usable teaching content.

## Core Rule

If the source document already contains:
- a definition
- an activity
- a worked example
- an exercise
- an evaluation prompt

then the lesson card should show that source content first, as faithfully as possible.

The app should not replace it with new generated wording by default.

## Product Goal

The teacher should be able to:
1. extract a unit from the PDF
2. open a leaf item
3. see the actual source-derived teaching content inside the app
4. teach from the app instead of reopening the PDF
5. optionally ask AI to fill missing parts or improve weak parts

This means `Lesson` should become:
- viewer first
- extraction-backed second
- AI enhancement third

not:
- blank card
- then generate everything from scratch

## Two Content Layers

Every leaf lesson card should distinguish between:

### 1. Exact source content

This is the content we believe comes directly from the extracted document.

Examples:
- `Definition: ...`
- `Exemple: ...`
- `Exercice 1: ...`
- `Activite: ...`

Rules:
- preserve order
- preserve wording as much as possible
- do not rewrite by default
- show this layer clearly in the UI

### 2. Added teaching support

This is content added by NotebookLM or the teacher when the source is incomplete.

Examples:
- missing launch activity
- simpler explanation
- extra guided example
- harder practice
- teacher notes

Rules:
- additive by default
- clearly labeled as added/generated
- should not silently replace exact source content

## Current Best Incremental Model

We do not need a full schema rewrite first.

We can use the current `workflow_leaf_content` record and preserve exact source blocks in:
- `source_payload_json.extracted_blocks`

Each extracted block should keep:
- `title`
- `kind`
- `teaching_phase`
- `content_md`
- `content_source`

Suggested `content_source` values:
- `source_excerpt`
- `teaching_material`

This lets the app show:
- exact extracted blocks first
- prepared lesson fields second

## Rendering Rule

The leaf lesson card should render:

1. `Exact Source Content`
- ordered blocks
- rendered with Markdown + LaTeX
- clear labels like `Definition`, `Example`, `Exercise`

2. `Prepared Lesson Content`
- structured fields already used by the app:
  - teaching goal
  - launch activity
  - explanation
  - worked example
  - practice
  - solution
  - assessment
  - teacher notes

This split keeps the teacher clear on:
- what came from the PDF
- what was added later

## Editing Rule

The teacher still needs editable source.

So the app should keep:
- rendered mode
- source mode

Recommended future direction:
- editable Markdown + LaTeX per lesson field
- exact source blocks shown clearly
- later allow block-level “promote into lesson field” or “replace this exercise only”

## NotebookLM Role

NotebookLM should help with:
- unit structure
- content classification
- missing activities
- missing examples
- missing exercises
- alternative versions

NotebookLM should not overwrite exact source content by default.

The safe default is:
- preserve exact source
- fill missing
- only fully replace when explicitly requested

## Why This Matters

This is the path from:
- PDF-assisted planning

to:
- direct in-app teaching

If we preserve exact source blocks well, then later we can reuse them for:
- datashow / projector mode
- textbook pages
- worksheets
- slide decks
- exams

without going back to the PDF every time.

## Next Technical Steps

1. Preserve exact extracted blocks in every seeded leaf card.
2. Render exact source blocks clearly in the lesson card.
3. Improve block classification when PDFs are structurally weak.
4. Split combined coarse blocks when one paragraph really contains multiple pedagogical parts.
5. Add projector-friendly lesson display later.
