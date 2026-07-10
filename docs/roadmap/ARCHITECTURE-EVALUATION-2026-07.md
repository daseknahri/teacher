# Architecture Evaluation — from scratch, assumptions challenged

Date: 2026-07-10. Reviewer: Claude (Opus 4.8), after reading the models, routers, services,
frontend views, running the full backend suite, and fixing several real bugs.

This is a blunt review requested by the owner ("challenge every assumption; if the architecture
is poor, tell me why"). It is deliberately critical. See the "What's actually good" section so the
criticism is kept in proportion — **this is a solid, functional MVP that has outgrown some early
choices, not a bad project.**

---

## TL;DR ranking of problems

1. **The product fights its own data model.** Content is per-class and AI-extracted from uploads;
   the product's value is a *shared, authoritative, trackable curriculum*. These are opposites.
2. **NotebookLM-via-browser-automation is a production liability.**
3. **No migrations** — 117 hand-rolled runtime `ALTER TABLE`s that diverge dev↔prod.
4. **Monolith files** — 7.9k / 7.8k / 7.4k / 5.2k-line single files; a 9.4k-line test file.
5. **The frontend is a hand-rolled framework** — vanilla JS string-templating, manual state,
   manual escaping (XSS footgun), whole-view re-renders.

---

## 1. The biggest problem: the product fights its own data model

**The core value proposition** (owner's words): "an app that replaces the textbook, makes teacher
follow-through easy, and lets the supervisor see what's done and what's left."

**What the architecture actually does:** `WorkflowUnit` is per `class_id`. A teacher uploads a PDF,
and AI extracts a checklist *structure unique to that upload*. Every class re-derives its own
structure. There is no shared curriculum entity anywhere in the model.

**Why this is backwards:**

- **No shared denominator → cohort tracking is impossible.** Two teachers of the same level get
  different checklists, so "Teacher A is at 40% of the year, B at 55%" cannot be computed. The
  supervisor "coverage %" that exists today is only *per-unit* (checked items ÷ that unit's items),
  never *per-year*. The single most-requested capability is structurally unavailable.
- **Content is duplicated and inconsistent per class**, and re-generated (and re-paid-for) every time.
- **The curriculum is treated as unknown input to be discovered.** But a national programme is a
  *fixed, public, authoritative artifact*. Discovering it per-upload with an LLM is the wrong tool
  for a known problem — and it is exactly where the 10 flaky AI tests live.

**The fix (inverts the flow from bottom-up to top-down):**

- Make **Curriculum a first-class, shared, versioned entity**: `Curriculum (level, subject, year)`
  → `CurriculumNode` (hierarchical) → `CurriculumNodeContent` (the digitized textbook material).
  Authored/digitized **once**, owned centrally.
- A **class instantiates** a curriculum; progress is recorded against shared node ids.
- Supervisor tracking becomes trivial and consistent: `covered nodes ÷ curriculum nodes`, identical
  across every teacher of that level.

Almost everything else simplifies once this is done: the per-upload AI extraction is no longer on
the critical path, content quality becomes controllable, and tracking is exact. This is the change
that matters most.

---

## 2. NotebookLM via browser automation is a production liability

There is a real feature built on Playwright-automating **Google's unofficial NotebookLM web UI**,
with a whole ops apparatus around keeping it alive: `storage_state.json` auth, a downloadable
`refresh_notebooklm.cmd` helper, keepalive seconds, smoke tests, runtime auth-health tracking, temp
notebook cleanup.

Why this is a strategic risk:

- It automates an **unsanctioned third-party UI**. It will break without warning whenever Google
  changes the DOM or their ToS, and it may violate those ToS.
- It **cannot run reliably headless / in CI** and needs **manual human auth refresh**.
- You are betting content generation — for a product you want to be "professional" — on the most
  brittle possible integration.

Given you can digitize official PDFs, you very likely **do not need it for the core flow**. Keep a
*supported* LLM API (you already have OpenAI wired) as optional authoring assist, and treat
NotebookLM as an experiment, not a dependency the product stands on.

---

## 3. No migrations — 117 lines of runtime DDL

`backend/app/database.py :: ensure_schema_compatibility()` runs ~117 hand-written `ALTER TABLE` /
`_ensure_column` statements **on every startup**, branching on SQLite vs Postgres.

- It cannot drop, rename, or retype columns — only add.
- It silently **diverges dev (SQLite) from prod (Postgres)**; the DDL is dialect-conditional by hand.
- It grows unboundedly (I had to add to it for the `version` column this session).
- There is no history, no down-migrations, no reproducible schema.

Alembic was deferred by choice, and that's fine short-term — but this is genuine debt, and the
longer the baseline migration is delayed the more painful it gets. It should not be "never."

---

## 4. Monolith files kill velocity

Measured this session:

| File | Lines |
|---|---:|
| `backend/app/services/workflow_generation.py` | 7,912 |
| `backend/app/routers/workflow.py` | 7,788 |
| `frontend/src/views/WorkflowView.js` | 7,433 |
| `frontend/src/views/CalendarView.js` | 5,183 |
| `backend/tests/test_app_flows.py` | 9,362 (one file) |

These are too large to hold in your head, review, or change safely. Concrete evidence of the cost:
the 9.4k-line test file had **no per-test DB isolation** until this session (the engine is a
module-level singleton), so the suite silently shared one database and gave order-dependent,
unreliable results. Nobody noticed because the file is too big to reason about.

Split by domain: `workflow.py` → units / checklist / sessions / timetable / holidays routers;
`test_app_flows.py` → one file per area; the giant views into sub-view modules.

---

## 5. The frontend is a hand-rolled framework

Vanilla JS with string-template rendering, a hash router, manual event binding, module-level state
caches, and hand-written HTML escaping.

- Every view **re-renders wholesale and re-binds events** on any change; you manage
  `_mutationInFlight` flags, cache invalidation, and re-selection by hand (I had to thread all of
  that through four call sites just to add optimistic locking this session).
- **Manual `_escapeHtml` everywhere is an XSS footgun** — every interpolation of user/teacher data
  into an HTML string must be escaped by hand; miss one and it's an injection. In a 7.4k-line view,
  that's a matter of when, not if.
- No types, no components, no reactivity → high change-cost. This is the friction the owner has been
  feeling.

For an app this size a small component framework (Svelte or Vue are the least-ceremony options)
would cut the view code substantially and remove whole classes of bugs. This is a big lift, so it's
a "when you can," not "now" — but it's the frontend's central problem.

---

## Smaller notes

- **SQLite dev / Postgres prod** with dialect-branched DDL — dev/prod parity risk; ties into #3.
- **Custom bearer-token auth** (`AuthToken` table, manual TTL/lockout) — acceptable at this scale,
  but rolling your own auth is always some risk. Leave it, but know it's there.
- **`created_at` uses `datetime.utcnow`** (deprecated) and there was a real local-vs-UTC bug in
  `start_workflow_session` (fixed this session). Standardize on one UTC helper everywhere.
- **No API versioning / no generated client** — the frontend hard-codes paths. Minor.
- **10 AI/NotebookLM tests assert on generated content** and are inherently non-deterministic /
  provider-dependent. They should be quarantined (skip-if-no-provider) rather than sitting red.

---

## What's actually good (keep it in proportion)

- Clean **routers / services / models / schemas** layering; Pydantic validation throughout.
- Real **operational maturity**: audit log, rate limiting, structured JSON logging, alerting,
  `/ops` health + retention.
- Sensible **RBAC** (owner/teacher, per-class access).
- The **checklist → session → attendance** domain model is reasonable, and the tracking works.
- It is a **genuinely functional, feature-rich MVP**. The issues above are "outgrew its MVP
  choices," not incompetence.

---

## Recommended target (evolve, don't rewrite)

A ground-up rewrite would throw away a working app and its ops maturity — don't. Evolve:

1. **Introduce shared Curriculum** (Program → Node → NodeContent), versioned, owner-authored.
   Digitize 1AC maths PDFs into it once. (See `CONTENT-CURRICULUM-STRATEGY.md`.)
2. **Classes instantiate a curriculum**; record progress against shared node ids → consistent
   supervisor tracking.
3. **Demote AI extraction** from core pipeline to optional authoring assist; drop NotebookLM as a
   hard dependency.
4. **Adopt Alembic**, baseline the current schema, stop runtime patching.
5. **Split** the monolith files (routers, tests, views).
6. **Later:** migrate the frontend to a component framework.

Sequence: #1–#3 are the high-value product change and should come first; #4–#5 are debt paydown you
can interleave; #6 is the big long-term investment.
