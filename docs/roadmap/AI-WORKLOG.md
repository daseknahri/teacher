# AI Worklog

Last updated: 2026-05-20

Use this file as a shared handoff log between coding sessions, AI helpers, and engineers.

## How To Use

Before starting work:
- add a new entry at the top
- claim the task
- list expected files
- list assumptions

After finishing:
- update the same entry
- record what changed
- record open risks or follow-up work

Keep entries short and factual.

---

## Entry Template

### YYYY-MM-DD HH:MM - Owner

- Status: planned | in_progress | done | blocked
- Goal:
- Files expected:
  - `path/to/file`
- Assumptions:
- Notes:
- Result:
- Follow-up:

---

## Current Entries

### 2026-05-21 00:15 - Codex

- Status: done
- Goal: Test whether NotebookLM can return a full unit content package in one pass with exact section content instead of broad rewritten teaching blocks.
- Files expected:
  - `backend/scripts/test_notebooklm_full_unit_extract.py`
  - `docs/roadmap/AI-WORKLOG.md`
- Assumptions:
  - One strict full-unit extraction pass is preferable if the schema stays narrow and source-faithful.
- Notes:
  - Benchmarked current `content_pack` prompt against a stricter full-unit prompt on real uploaded PDFs.
  - Result: the current prompt maps sections better than expected but rewrites too much; the stricter prompt preserves more exact text and, after refinement, also keeps strong section paths.
  - One geometry PDF failed during NotebookLM source processing, so any final architecture still needs a fallback path for PDFs NotebookLM cannot ingest.
- Result:
  - Added `backend/scripts/test_notebooklm_full_unit_extract.py` to repeat this benchmark on multiple PDFs.
  - The refined prompt produced materially better section-first results on at least two real math PDFs.
- Follow-up:
  - Use this script on the 3-PDF benchmark set before wiring the refined full-unit output into the app.

### 2026-05-20 22:05 - Codex

- Status: done
- Goal: Implement the section-first preparation pipeline so Lesson reads stored prepared sections instead of rebuilding ad hoc leaf content.
- Files expected:
  - `backend/app/models.py`
  - `backend/app/database.py`
  - `backend/app/schemas.py`
  - `backend/app/services/workflow_generation.py`
  - `backend/app/routers/workflow.py`
  - `backend/tests/test_app_flows.py`
  - `frontend/src/utils/leafContent.js`
  - `frontend/src/views/WorkflowView.js`
- Assumptions:
  - First benchmark version can derive section indexing/preparation from the saved blueprint `content_blocks_json`.
  - NotebookLM remains the only provider in this phase, but the stored section shape should stay provider-friendly.
- Notes:
  - Added persisted `workflow_prepared_sections`.
  - Added section APIs: index, list, prepare, get, and repointed `section-lesson` to stored prepared sections.
  - Added a Workflow `Prepare Sections` modal so teachers can build the index and prepare sections one by one.
  - Simplified `leafContent.js` down to a section-first reader instead of the old leaf authoring helper.
- Result:
  - `Lesson` now opens only prepared section content.
  - Unprepared sections show a simple “prepare this section first” state.
  - Focused backend tests and `npm run build` passed.
- Follow-up:
  - Test 3 representative PDFs on cloud and judge section fidelity before revisiting leaf splitting or slide generation.

### 2026-05-20 19:35 - Codex

- Status: done
- Goal: Simplify the confusing leaf lesson flow into a section-first teaching surface that shows only exact extracted section content.
- Files expected:
  - `backend/app/routers/workflow.py`
  - `backend/app/schemas.py`
  - `backend/app/services/workflow_generation.py`
  - `backend/tests/test_app_flows.py`
  - `frontend/src/utils/leafContent.js`
  - `frontend/src/views/WorkflowView.js`
  - `frontend/src/views/CalendarView.js`
  - `frontend/src/style/components.css`
- Assumptions:
  - First testable version should be read-only and exact-source-first.
  - Section-level correctness matters more right now than per-leaf generation/editing.
- Notes:
  - Added a new `/workflow/classes/{class_id}/units/{unit_id}/section-lesson` route.
  - Lesson buttons now open a section reader instead of the old leaf authoring modal.
  - Removed leaf lesson status dots from the main flow to reduce noise.
- Result:
  - Section lesson now shows exact extracted section blocks only, in a cleaner reading modal.
  - Backend and focused tests pass, and frontend build passes.
- Follow-up:
  - Test this exact section-reader flow on cloud.
  - If section extraction is still weak for some PDFs, improve source block quality before adding any more AI layers.

---

### 2026-05-20 18:25 - Codex

- Status: done
- Goal: recover pipe-separated table-style source rows so flattened worksheet/table content stays teachable in the app
- Files expected:
  - `backend/app/services/workflow_generation.py`
  - `backend/tests/test_app_flows.py`
- Assumptions:
  - `|` separators often come from flattened table or column layouts and should become separate lesson rows when at least two parts look like math or action fragments
  - this is a safe extension of the existing column-style split logic
- Notes:
  - kept the split narrow so ordinary prose with an occasional pipe is unlikely to be affected
- Result:
  - source markdown normalization now splits pipe-separated rows into separate lines
  - the exact-source builder then turns those parts into separate teachable source blocks
  - added regression coverage for a pipe-separated exercise row
- Follow-up:
  - we are reaching the practical limit of text-only recovery; the next major fidelity step would need PDF layout geometry or OCR box structure

### 2026-05-20 18:05 - Codex

- Status: done
- Goal: preserve short source headings like `Calculer :` above separated substeps so the lesson keeps context instead of flattening the heading into another row
- Files expected:
  - `backend/app/services/workflow_generation.py`
  - `backend/tests/test_app_flows.py`
- Assumptions:
  - a short heading ending with `:` should stay as context when it is followed by several short math/action rows
  - this should help worksheet-style blocks where the PDF gives a visible heading then several compact lines
- Notes:
  - limited this to the non-numbered/non-lettered split path so it does not interfere with explicit markers
- Result:
  - exact-source splitting now keeps a leading heading as a preamble and separates the following short rows into their own source steps
  - added regression coverage for a `Calculer :` block followed by three short math rows
- Follow-up:
  - next fidelity pass should target true table-like layouts where row/column meaning is still weak after plain-text extraction

### 2026-05-20 17:45 - Codex

- Status: done
- Goal: recover column-style exercise rows that flatten into one source line with wide spaces or tabs
- Files expected:
  - `backend/app/services/workflow_generation.py`
  - `backend/tests/test_app_flows.py`
- Assumptions:
  - worksheet-style rows separated by large spaces should become separate lesson rows when at least two parts look like action or math fragments
  - this should help projector readability without inventing structure
- Notes:
  - used a narrow column split on tabs or repeated spaces to avoid breaking ordinary sentences
- Result:
  - source markdown normalization now splits column-style rows into separate lines
  - the existing exact-source segment builder then turns those rows into separate teachable source blocks
  - added regression coverage for a single-line column-style exercise block
- Follow-up:
  - next fidelity pass should target indentation-based substeps and table-like layouts that still lose meaning during text extraction

### 2026-05-20 17:25 - Codex

- Status: done
- Goal: preserve short line-by-line exercise instructions even when the source does not use numbers or letters
- Files expected:
  - `backend/app/services/workflow_generation.py`
  - `backend/tests/test_app_flows.py`
- Assumptions:
  - short imperative rows like `Calculer ...`, `Simplifier ...`, `Comparer ...` should be teachable as separate steps when they are already split by lines in the source
  - this should stay limited to activity/example/exercise/assessment kinds
- Notes:
  - used a narrow action-verb heuristic to avoid splitting longer prose blocks
- Result:
  - exact-source segment building now splits short action rows into separate source blocks when they arrive on separate lines
  - added regression coverage for a short three-line exercise block without numbering
- Follow-up:
  - next fidelity pass should target table-like layouts and visually indented substeps that still lose structure during extraction

### 2026-05-20 17:00 - Codex

- Status: done
- Goal: preserve lettered workbook-style rows so exercise leaves keep source content that uses `a)`, `b)`, `c)` instead of only numbered steps
- Files expected:
  - `backend/app/services/workflow_generation.py`
  - `backend/tests/test_app_flows.py`
- Assumptions:
  - lettered exercise rows should behave like numbered rows for exact-source preservation
  - this should improve textbook-style practice leaves without affecting long prose
- Notes:
  - reused the same conservative splitting path as numbered rows to keep behavior predictable
- Result:
  - markdown normalization now splits inline lettered rows like `a) ... b) ... c) ...`
  - exact-source segment building now splits lettered rows into separate teachable source blocks
  - added regression coverage for a lettered practice block
- Follow-up:
  - next fidelity pass should focus on layout-only structures like table-style rows or visually indented substeps

### 2026-05-20 16:35 - Codex

- Status: done
- Goal: preserve short statement groups from source text so concise rules and definitions can teach as separate steps without needing explicit numbering
- Files expected:
  - `backend/app/services/workflow_generation.py`
  - `backend/tests/test_app_flows.py`
- Assumptions:
  - short line groups in definition/property content should remain separate when the PDF already gave them as distinct lines
  - this should stay conservative and not split long prose paragraphs
- Notes:
  - limited the heuristic to lesson/definition/property kinds with 2 to 4 short statement lines
- Result:
  - exact-source segment building now splits short statement groups into separate source blocks for concise rules and definitions
  - added regression coverage for a compact rule block with three short lines
- Follow-up:
  - next fidelity pass should target source rows that rely on PDF visual indentation or table-like layout rather than punctuation or line breaks

### 2026-05-20 16:10 - Codex

- Status: done
- Goal: preserve compact symbolic math sequences and short exercise rows when the PDF implies separate teaching steps without explicit numbering
- Files expected:
  - `backend/app/services/workflow_generation.py`
  - `backend/tests/test_app_flows.py`
- Assumptions:
  - compact math rows separated by semicolons should become separate readable lines
  - short exact-source math rows should become separate teachable source segments only when they clearly look like formula steps
- Notes:
  - kept the detection narrow so prose paragraphs do not get over-split
- Result:
  - source markdown normalization now splits compact semicolon-separated math rows into separate lines
  - exact-source segment building now splits short symbolic math sequences into separate source blocks for teach mode
  - added regression coverage for a compact example like `A = 2/3 ; B = 4/5 ; A × B = 8/15`
- Follow-up:
  - next fidelity pass should target visually separate statement groups that are implied by PDF layout but not strongly marked in text

### 2026-05-20 15:45 - Codex

- Status: done
- Goal: preserve compact symbolic math sequences more faithfully and turn them into separate teachable exact-source segments when appropriate
- Files expected:
  - `backend/app/services/workflow_generation.py`
  - `backend/tests/test_app_flows.py`
- Assumptions:
  - short math rows separated by semicolons should not stay as one dense sentence
  - we should only split compact math rows for teachable block kinds:
    - activity
    - example
    - exercise
    - assessment
- Notes:
  - kept the detection conservative so normal prose paragraphs do not get broken apart
- Result:
  - source markdown normalization now splits compact semicolon-based math rows into separate lines
  - exact-source segment building now splits short math-line sequences into separate stored source blocks
  - added regression coverage for a compact example like:
    - `A = 2/3 ; B = 4/5 ; A × B = 8/15`
- Follow-up:
  - next fidelity pass should preserve short statement groups without numbers or semicolons when the PDF still implies separate steps visually

### 2026-05-20 15:05 - Codex

- Status: done
- Goal: split dense exact-source exercise blocks into separate teachable source segments so one leaf can behave more like a small slide deck without inventing content
- Files expected:
  - `backend/app/services/workflow_generation.py`
  - `backend/tests/test_app_flows.py`
  - `frontend/src/utils/leafContent.js`
- Assumptions:
  - if one exact source block clearly contains multiple numbered tasks, we should preserve them as separate source segments
  - segment titles should stay short in the teaching outline so the teacher does not see the full leaf title repeated
- Notes:
  - kept the split conservative: it only triggers when there are at least two clearly marked task rows
- Result:
  - exact-source blocks for activities/examples/exercises/assessments now split into multiple stored source segments when the text contains multiple numbered rows
  - teach mode outline now shows shorter labels like `Part 1`, `Part 2` when the backend split titles would otherwise repeat the leaf title
  - added regression coverage proving one numbered exercise block becomes three exact source segments
  - review mode now hides duplicated structured sections when the same content is already shown in the exact source layer
- Follow-up:
  - next fidelity pass should preserve short symbolic math lines and compact statement groups even when they are not numbered

### 2026-05-20 14:05 - Codex

- Status: done
- Goal: make exact-source leaf lessons easier to teach from by preserving numbered source rows and simplifying the multi-block teaching surface
- Files expected:
  - `backend/app/services/workflow_generation.py`
  - `backend/tests/test_app_flows.py`
  - `frontend/src/utils/leafContent.js`
  - `frontend/src/style/components.css`
- Assumptions:
  - exact source line breaks and numbered exercise steps matter more than another round of AI generation polish
  - multi-block leaves need direct block jumping, not only previous/next navigation
  - teaching mode should speak in teacher language:
    - `Teach`
    - `Review`
    - `Edit`
- Notes:
  - kept this slice local to save Claude tokens and focused on source fidelity plus teaching readability
- Result:
  - source-derived lesson content now splits inline numbered rows like `1) ... 2) ... 3) ...` into separate preserved lines
  - markdown rendering now preserves line breaks in exact-source and teach surfaces
  - teach mode now shows a simple clickable block outline for multi-part leaves
  - stale wording was cleaned so empty states point to `Review` and `Edit`
- Follow-up:
  - next source-fidelity pass should preserve short math line sequences and list structure even more faithfully

### 2026-05-20 13:10 - Codex

- Status: done
- Goal: make source-seeded lesson cards preserve an exact source layer so the teacher can see document-faithful content inside the app before any added AI help
- Files expected:
  - `backend/app/services/workflow_generation.py`
  - `backend/tests/test_app_flows.py`
  - `frontend/src/utils/leafContent.js`
  - `docs/roadmap/EXACT-SOURCE-LESSON-MODE.md`
  - `docs/roadmap/CLAUDE-CONTINUATION-PROMPT.md`
  - `docs/roadmap/CLAUDE-TASK-EXACT-SOURCE-BLOCK-EXTRACTION.md`
- Assumptions:
  - exact source preservation is more important than adding another generated summary layer
  - we can use the existing `source_payload_json` shape instead of forcing a new migration first
  - lesson cards should show extracted source blocks first, while still keeping editable structured fields
- Notes:
  - kept this slice local to save Claude tokens; prepared a narrow follow-up Claude task for the next extraction-quality pass
- Result:
  - source-derived leaf content now stores ordered `extracted_blocks` in `source_payload_json`
  - lesson cards now render an `Exact Source Content` layer when extracted blocks exist
  - added regression coverage proving extracted blocks are preserved on source-seeded leaf cards
  - documented the product rule in `EXACT-SOURCE-LESSON-MODE.md`
- Follow-up:
  - next extraction-quality pass should improve splitting and classification when a coarse PDF block contains multiple pedagogical parts

### 2026-05-20 02:35 - Codex

- Status: done
- Goal: make source-derived leaf-content seeding more order-aware inside a section so repeated examples/exercises map to the right leaf instead of duplicating
- Files expected:
  - `backend/app/services/workflow_generation.py`
  - `backend/tests/test_app_flows.py`
- Assumptions:
  - exact title match should still win first
  - when exact match fails, repeated example/exercise leaves should use section order as a fallback
  - narrower source assignment is better than duplicating all same-kind blocks across multiple leaves
- Notes:
  - focused only on source-derived seeding quality; no frontend changes needed
- Result:
  - added order-aware source block selection for leaf seeding
  - sequence hints like `Exemple 1`, `Exemple 2` now map to the corresponding content block within the same section
  - added regression coverage proving two example leaves receive different extracted examples in order
- Follow-up:
  - next extraction-quality step is better classification of activity vs explanation vs practice when the PDF structure is weak or implicit

### 2026-05-20 02:05 - Codex

- Status: done
- Goal: make leaf lesson cards source-first so extracted content is preserved and NotebookLM generation fills missing parts by default
- Files expected:
  - `backend/app/schemas.py`
  - `backend/app/routers/workflow.py`
  - `backend/tests/test_app_flows.py`
  - `frontend/src/utils/leafContent.js`
  - `frontend/src/style/components.css`
  - `docs/roadmap/CLAUDE-TASK-LEAF-CARD-SOURCE-FIRST.md`
- Assumptions:
  - extracted leaf content should remain the primary lesson source when present
  - lesson generation should be additive by default, with full replacement still available explicitly
  - keeping the existing modal and status-dot contract is more important than a broad UI rewrite
- Notes:
  - attempted to dispatch the modal UX slice to Claude in a separate worktree, but Claude CLI exited before producing code, so the implementation was completed locally to keep momentum
- Result:
  - generation endpoint now accepts `merge_strategy` with `fill_missing` default and `replace` explicit
  - source-derived leaf content is preserved during generation unless replace is requested
  - hybrid source payload metadata now records retained vs filled lesson fields
  - lesson modal now explains content origin, shows section readiness, and presents:
    - `Fill Missing with Unit Brain`
    - `Regenerate All`
  - added test coverage for preserving extracted fields while filling missing ones
- Follow-up:
  - next quality step is improving how extraction maps raw PDF content blocks into the right leaf fields, especially for activity/example/exercise separation


### 2026-05-19 23:05 - Claude

- Status: done
- Goal: make saved/generated leaf content visible across Workflow and Calendar, and open the same lesson card from Calendar
- Files expected:
  - `backend/app/schemas.py`
  - `backend/app/routers/workflow.py`
  - `backend/tests/test_app_flows.py`
  - `frontend/src/utils/leafContent.js`
  - `frontend/src/views/WorkflowView.js`
  - `frontend/src/views/CalendarView.js`
  - `frontend/src/style/components.css`
  - `docs/roadmap/AI-WORKLOG.md`
- Assumptions:
  - the safest next slice is a unit-level leaf-content summary endpoint plus frontend status cues
  - the first Calendar integration should open the existing lesson card, not add a second editor
  - content status should be visible but visually quiet
- Notes:
  - task prompt lives in `docs/roadmap/CLAUDE-TASK-LEAF-CONTENT-VISIBILITY.md`
  - this task should not change session semantics, checklist semantics, or partial regeneration
- Result:
  - added `WorkflowLeafContentSummaryOut` schema and `GET /workflow/classes/{class_id}/units/{unit_id}/leaf-content` summary endpoint
  - added backend test coverage for the summary endpoint (`test_leaf_content_list_by_unit`)
  - added unit-level leaf-content summary caching in `frontend/src/utils/leafContent.js`
  - summary cache now updates immediately after generate/save in the lesson card
  - Workflow now shows a quiet lesson-content status dot on leaf rows in:
    - Unit Setup checklist
    - Active Session Teaching Flow View
    - Active Session Full Unit Checklist
  - Calendar now shows the same status cue on supported route leaves
  - Calendar can now open the same lesson card from:
    - grouped Teaching Flow View
    - planned route tree leaf rows
  - lesson-card open actions now pass checklist path context where available
  - page rerenders after lesson-card generate/save so status cues refresh without a manual reload
- Follow-up:
  - consider a clearer visual distinction between `draft` and `ready` if teachers need more than a dot
  - recorded fallback routes in Calendar still cannot open a leaf card when only flat checked titles exist and no checklist item id was preserved

### 2026-05-19 22:45 - Claude

- Status: done
- Goal: implement the first Workflow-only leaf content reader/editor on top of the new leaf-content backend endpoints
- Files expected:
  - `frontend/package.json`
  - `frontend/src/utils/leafContent.js` (new helper)
  - `frontend/src/views/WorkflowView.js`
  - `frontend/src/style/components.css`
  - `docs/roadmap/AI-WORKLOG.md`
- Assumptions:
  - the safest next slice is Workflow only, not Calendar yet
  - the UI should open from leaf checklist rows without changing checklist toggle semantics
  - rendered mode should support Markdown + LaTeX, while source mode keeps the raw editable content
  - missing content should lead to a Generate-first empty state, not an error wall
  - installing marked + katex as npm deps for Markdown + LaTeX rendering inside Vite
  - "Lesson" button added to leaf rows (no children) in Unit Setup checklist and Active Session Full Unit Checklist
  - modal is large (max-w-2xl) to give content space; scrollable body
- Notes:
  - task prompt lives in `docs/roadmap/CLAUDE-TASK-WORKFLOW-LEAF-READER.md`
  - this task should not change session completion logic, calendar flow, or partial regeneration
- Result:
  - installed `marked` (v18) and `katex` (v0.16) as npm dependencies
  - created `frontend/src/utils/leafContent.js`:
    - `openLeafContentModal(classId, unitId, item)` — full lesson card modal
    - `renderMarkdownLatex(text)` — extracts $$/$$ and $$ blocks, runs marked, injects KaTeX HTML
    - rendered mode: per-section cards with prose styling; source_excerpt_md in `<details>`
    - source mode: textareas per field with Markdown + LaTeX hint
    - Generate button → POST .../generate; Save button → PUT .../leaf-content/{item_id}
    - loading / 404 empty state handled cleanly
  - added `import { openLeafContentModal }` to WorkflowView.js
  - added "Lesson" button to leaf rows (no children) in Unit Setup DnD checklist (in row-hover-actions)
  - added "Lesson" button to leaf rows in Active Session Full Unit Checklist
  - restructured Teaching Flow View item rows with wrapper div to add "Lesson" button as sibling of check button
  - added `.btn-leaf-lesson` event handler in `_bindWorkflowEvents` — resolves item from `_checklist(unit)`, calls `openLeafContentModal`
  - added CSS in `components.css`: `.leaf-content-modal`, `.lcm-header`, `.lcm-body`, `.lcm-footer`, `.lcm-prose`, `.lcm-math-err`
  - `npm run build` passes (27 modules, no errors; chunk size warning is pre-existing)
- Follow-up:
  - next: connect leaf content status to checklist row visual indicator (e.g. a small blue dot when content exists)
  - next: add partial regeneration per field (Phase 5 in LEAF-CONTENT-READER-ROADMAP.md)
  - next: connect leaf lesson card to session flow navigation (Phase 6)
  - consider lazy-loading katex/marked to reduce initial bundle size

### 2026-05-19 22:05 - Claude

- Status: done
- Goal: implement a backend endpoint that generates and saves content for one leaf checklist item using the saved unit brain
- Files expected:
  - `backend/app/schemas.py`
  - `backend/app/routers/workflow.py`
  - `backend/app/services/workflow_generation.py`
  - `backend/tests/test_app_flows.py`
  - `docs/roadmap/AI-WORKLOG.md`
- Assumptions:
  - the next safe slice is per-leaf generation, not frontend reader work yet
  - the generation contract should follow the existing package style already used for write-ups and unit helpers
  - fallback provider produces a stub result when NotebookLM is not configured (error_message set, status=degraded)
  - blueprint must exist for generation; missing blueprint returns 409
  - provider_context in blueprint.blueprint_json is used for the existing notebook; if absent a temporary notebook is created
  - item_path / section_path derived via existing _derive_leaf_item_paths if not stored yet on the row
- Notes:
  - task prompt lives in `docs/roadmap/CLAUDE-TASK-LEAF-CONTENT-GENERATION.md`
  - this task should not modify checklist/session semantics
  - no frontend code added; no partial regeneration added
- Result:
  - added WorkflowLeafContentGenerateIn and WorkflowLeafContentGenerateOut Pydantic schemas
  - added SUPPORTED_LEAF_CONTENT_PROVIDERS constant to workflow_generation.py
  - added generate_leaf_content_package (public), _notebooklm_generate_leaf_content (sync), _notebooklm_generate_leaf_content_async, _normalize_leaf_content_payload, _build_notebooklm_leaf_content_prompt helpers
  - added POST /workflow/classes/{class_id}/units/{unit_id}/leaf-content/{item_id}/generate endpoint
  - endpoint: ensure_class_writable, active unit required, leaf-only check, blueprint required (409), derives paths if missing, upserts WorkflowLeafContent, logs audit
  - added test_leaf_content_generate_happy_path (monkeypatched), test_leaf_content_generate_rejects_non_leaf, test_leaf_content_generate_requires_blueprint
  - compile check passes; all 5 leaf_content tests pass
- Follow-up:
  - after this lands, the next step is the first frontend leaf reader/editor (Phase 4 in LEAF-CONTENT-READER-ROADMAP.md)
  - consider adding a fallback stub path for generate_leaf_content_package when NotebookLM is not configured (currently raises 409)

### 2026-05-19 21:35 - Codex

- Status: done
- Goal: turn the repo handoff docs into a practical Claude CLI workflow with safe worktrees and task prompts
- Files expected:
  - `README.md`
  - `.gitignore`
  - `docs/roadmap/CLAUDE-CLI-WORKFLOW.md`
  - `scripts/ai/New-ClaudeWorktree.ps1`
  - `scripts/ai/Invoke-ClaudeTask.ps1`
  - `docs/roadmap/AI-WORKLOG.md`
- Assumptions:
  - Claude CLI is installed and authenticated on this machine
  - the safest first usage is one task per worktree, reviewed before merge
- Notes:
  - verified `claude -p` works on this machine
  - smoke-tested the helper scripts
  - cleaned the temporary smoke worktree after validation
- Result:
  - the repo now has a working Claude CLI workflow with:
    - task markdown files
    - worktree helper
    - task runner
    - log storage under `storage/ai/claude/`
- Follow-up:
  - next real use should be the leaf-content persistence task in its own Claude worktree

### 2026-05-19 19:35 - Claude

- Status: done
- Goal: implement the first backend leaf content persistence slice without changing existing workflow/session behavior
- Files expected:
  - `backend/app/models.py`
  - `backend/app/database.py`
  - `backend/app/schemas.py`
  - `backend/app/routers/workflow.py`
  - `backend/tests/test_app_flows.py`
  - `docs/roadmap/AI-WORKLOG.md`
- Assumptions:
  - the safest first implementation is persistence plus read/write only
  - generation and frontend reader should wait until storage is stable
  - GET returns 404 if no leaf content record exists yet
  - PUT is upsert (create or update) for any leaf checklist item
  - leaf detection: an item is a leaf if it has no child rows in workflow_checklist_items
  - GET uses ensure_class_access; PUT uses ensure_class_writable + active unit check
- Notes:
  - task prompt lives in `docs/roadmap/CLAUDE-TASK-LEAF-CONTENT-PERSISTENCE.md`
  - this task should not modify checklist completion semantics or session matching logic
- Result:
  - added WorkflowLeafContent model (workflow_leaf_content table, unique on unit_id+checklist_item_id)
  - added schema compatibility block in database.py with _ensure_column entries for all new columns
  - added WorkflowLeafContentOut and WorkflowLeafContentUpsertIn Pydantic schemas
  - added GET /workflow/classes/{class_id}/units/{unit_id}/leaf-content/{item_id} (ensure_class_access, any unit status)
  - added PUT /workflow/classes/{class_id}/units/{unit_id}/leaf-content/{item_id} (ensure_class_writable, active unit only, upsert)
  - both endpoints return 400 if the checklist item is not a leaf (has children)
  - added test_leaf_content_happy_path and test_leaf_content_rejects_non_leaf_item; both pass
  - compile check passes; targeted leaf-content tests pass
- Follow-up:
  - after this lands, the next step is one leaf content generation endpoint (Phase 3) or one minimal frontend reader (Phase 4)

### 2026-05-19 19:10 - Codex

- Status: done
- Goal: add stable handoff docs so Claude or another AI can continue the NotebookLM content-bank direction safely
- Files expected:
  - `README.md`
  - `docs/roadmap/AI-CONTENT-BANK-HANDOFF.md`
  - `docs/roadmap/NOTEBOOKLM-UNIT-BRAIN-ARCHITECTURE.md`
  - `docs/roadmap/LEAF-CONTENT-BANK-SPEC.md`
  - `docs/roadmap/LEAF-CONTENT-READER-ROADMAP.md`
  - `docs/roadmap/CLAUDE-CONTINUATION-PROMPT.md`
  - `docs/roadmap/AI-COLLABORATION-PROTOCOL.md`
  - `docs/roadmap/AI-WORKLOG.md`
- Assumptions:
  - the next collaborator needs both architecture context and safety rails
  - the repo should preserve the current workflow/session logic while moving toward a leaf-content bank
- Notes:
  - added a Claude-ready continuation prompt
  - added a collaboration protocol for multi-AI work
  - added this worklog template
- Result:
  - another AI can now start from a clear read order, known guardrails, and a shared handoff file
- Follow-up:
  - next implementation step should be persisted leaf content records and one leaf reader/editor slice
### 2026-05-20 14:05 - Codex

- Status: done
- Goal: improve exact-source leaf extraction when one PDF block contains multiple pedagogical parts
- Files changed:
  - `backend/app/services/workflow_generation.py`
  - `backend/tests/test_app_flows.py`
- Notes:
  - split mixed source blocks like `Definition: ... Exemple 1: ... Exercice 1: ...` into ordered normalized content blocks
  - preserve richer teaching material in `source_payload.extracted_blocks` so lesson cards show the fuller exact source text
  - added regression coverage for ordered splitting and leaf matching from split blocks
- Validation:
  - `python -m compileall -q backend/app`
  - `PYTHONPATH=backend python -m pytest -p no:cacheprovider backend/tests/test_app_flows.py -k "leaf_content"`
- Follow-up:
  - next quality step is broader reconstruction for weak PDFs where one coarse block still mixes unlabeled explanation, example, and practice
### 2026-05-20 14:40 - Codex

- Status: done
- Goal: make leaf lessons usable for real teaching instead of only authoring
- Files changed:
  - `frontend/src/utils/leafContent.js`
  - `frontend/src/style/components.css`
- Notes:
  - added `Teach` mode to the leaf lesson modal
  - if exact source blocks exist, the lesson now opens in teach mode by default
  - teach mode shows one block at a time in larger projector-friendly typography with previous/next navigation
  - kept `Rendered` and `Source` as author/edit views
- Validation:
  - `npm run build`
- Follow-up:
  - next step is improving the exact source extraction quality for harder PDFs, not adding more UI noise
### 2026-05-20 15:05 - Codex

- Status: done
- Goal: preserve fuller exact source text for leaf lessons instead of flattening everything into short one-line summaries
- Files changed:
  - `backend/app/services/workflow_generation.py`
  - `backend/tests/test_app_flows.py`
- Notes:
  - added multiline-preserving normalization for content block markdown
  - exact source segments now prefer richer raw teaching material when available
  - source-derived leaf markdown now preserves line breaks better for exercises and worked content
  - kept the existing lighter summary fields, but stopped degrading the exact-source teaching layer so heavily
- Validation:
  - `python -m compileall -q backend/app`
  - `PYTHONPATH=backend python -m pytest -p no:cacheprovider backend/tests/test_app_flows.py -k "leaf_content or source_derived_leaf_content_preserves_multiline_exact_source"`
- Follow-up:
  - next extraction-quality step is to preserve more PDF structure like short lists and numbered steps without over-splitting a leaf that represents one full exercise series
### 2026-05-20 15:20 - Codex

- Status: done
- Goal: reduce duplicated title/path noise inside leaf teach mode so the same exact source block reads like one clean teaching page
- Files changed:
  - `frontend/src/utils/leafContent.js`
  - `frontend/src/style/components.css`
- Notes:
  - teach mode now hides the repeated modal title/path in the header
  - the teaching stage keeps one main title and one compact path only
  - added content cleaning for teach mode to strip duplicated first-line heading/path echoes before rendering exact source blocks
- Validation:
  - `npm run build`
- Follow-up:
  - next likely step is preserving numbered step structure from extraction even better when the PDF block is good but the OCR/text extraction is coarse
