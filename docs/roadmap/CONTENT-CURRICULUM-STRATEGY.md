# Content & Curriculum Strategy

Date: 2026-07-10. Status: **proposed direction, not yet implemented, and not yet reconciled with
existing work.**

> **Read this first.** An in-progress content-bank / leaf-content implementation already exists on
> six branches on `origin`: `claude/leaf-content-generation`, `leaf-content-persistence`,
> `leaf-content-visibility`, `workflow-leaf-reader`, `leaf-card-source-first`,
> `exact-source-block-extraction` (plus the `CLAUDE-TASK-LEAF-*` specs in this folder). An earlier
> draft of this document claimed to "supersede" that direction. It does not — that claim was written
> without knowledge of those branches. What follows is a proposal for the *shared curriculum
> skeleton*, which is a **layer above** the leaf-content work, not a replacement for it. Reconcile,
> don't discard.

`CLAUDE.md` already states a compatible intent: build "a stable content-bank builder outside the live
teacher workflow," store content "with provenance, exact source references, Markdown/LaTeX math… and
supervisor approval state," and treat NotebookLM as "an assistant/context tool rather than the only
source of structure." This document sharpens *where the structure comes from*: a shared, authoritative
curriculum rather than per-class AI extraction.

---

## The problem (owner's framing)

> "I want an app that replaces the textbook for teachers and makes teacher follow-through easy. The
> problem is content — if we have the full-year content it's easier and more professional, so the
> supervisor can see what teachers have done and what's left."

## The core insight

"Content" is two different things, and conflating them is the root confusion:

1. **Curriculum map (skeleton)** — the official year programme as chapters → lessons → objectives.
   Small, stable, public. This is the fixed **100%** the supervisor tracks against. It MUST be
   shared and identical for every teacher of the same level, or cohort tracking is impossible.
2. **Teaching content (textbook replacement)** — the actual per-node material: course text,
   definitions/theorems, worked examples, exercises + solutions, activities. Large, higher-effort.

Today the app has neither as a shared entity — structure is AI-extracted per class from uploads, so
there is no common denominator. Fixing that is the whole game.

---

## Decisions locked with the owner

- **First target:** **7th grade mathematics = Morocco 1ère Année Collège (1AC) — Mathématiques.**
  Build ONE level end-to-end as the proof before expanding.
- **Source:** the owner **has all the official PDFs** (programme + textbook) and **we may digitize
  official book content** (owner confirmed copyright is acceptable for their use).
- **Approach:** digitize the PDFs once into a shared, owner-authored curriculum + content bank.
  This is authoring, not per-class AI discovery.

## Still open (ask the owner before building)

1. **Tracking granularity** — chapter (~8–12/yr), **lesson (~40–60, recommended)**, or objective
   (100+). Sets the resolution of "done vs. left."
2. **Ownership/workflow** — master curriculum authored/edited by the **owner** once, teachers
   consume read-only? (Assumed yes; confirm.)
3. **Where the PDFs live** — owner was asked to drop the 1AC maths files on disk and share the path.
   Not yet provided. Needed to assess: text-based vs scanned, French (+Arabic?), math-notation
   fidelity → determines whether extraction is clean or needs OCR.

---

## Proposed data model (top-down, shared)

New tables (names indicative):

```
Curriculum
  id, level ("1AC"), subject ("Mathématiques"), country ("MA"),
  academic_year / version, title, status (draft|published), created_by

CurriculumNode            # the skeleton; hierarchical
  id, curriculum_id, parent_id,
  kind (domain|chapter|lesson|objective|...),
  code ("CH1", "1.2"), title, order_index, estimated_hours

CurriculumNodeContent     # the textbook material for a node (mirror the existing leaf-content fields)
  id, node_id,
  teaching_goal_md, explanation_md, worked_example_md, practice_md,
  solution_md, assessment_md, teacher_notes_md, source_excerpt_md,
  source_ref (which PDF + page), provider (manual|ai), status, reviewed
```

Linking to the existing per-class machinery (reuse, don't replace):

- When a class starts the year it **instantiates** the curriculum: the existing
  `WorkflowUnit` / `WorkflowChecklistItem` rows are **seeded from the curriculum nodes** (each
  checklist item carries a `curriculum_node_id` back-reference) instead of from a per-class PDF.
- The **session → checked-checklist-item** tracking built this session then works unchanged, but now
  every class shares the same node ids → the supervisor can aggregate coverage across teachers.
- The teacher opens a node and sees its `CurriculumNodeContent` → this is the textbook replacement.

This keeps everything already built (sessions, attendance, coverage %, the supervisor dashboard) and
just changes *where the structure comes from* and *adds shared content*.

---

## Digitization pipeline (once per level+subject)

1. Ingest the **programme PDF** → produce the `CurriculumNode` tree (skeleton). Review it against
   the official table of contents.
2. Ingest the **textbook PDF**, chapter by chapter → produce `CurriculumNodeContent` per node
   (course, examples, exercises, solutions). AI may draft; a human approves. **Pilot on ONE chapter
   first** to validate quality and the notation handling before doing all of them.
3. Publish the curriculum (status → published); classes can now instantiate it.

Math-notation caveat: Moroccan maths PDFs are French with heavy math typography. Confirm whether the
PDFs are text-based (clean extraction) or scanned (needs OCR — the repo already has Tesseract +
rapidocr). Store content as Markdown + KaTeX (the frontend already bundles KaTeX + marked).

---

## Immediate next step

Get the 1AC maths PDFs onto disk and share the path. Then: build the `Curriculum*` tables + a
minimal owner authoring/import screen, digitize the programme skeleton, pilot one chapter of
content, and wire class instantiation + the teacher node-reader.
