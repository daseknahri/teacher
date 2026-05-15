# UI Revision Log (2026-03-03)

## Scope
- Review frontend API integration after recent UI changes.
- Fix regressions causing extraction/checklist confusion and empty/misaligned data in dashboard/exams.
- Track remaining UI gaps needed to complete the workflow.

## Fixed In This Revision
1. Workflow checklist not rendering after PDF/unit creation.
   - Root cause: frontend read `active_unit.checklist_items` while backend returns `active_unit.checklist`.
   - Fix: fallback parser now reads `checklist` first, then legacy keys.
   - Files:
     - `frontend/src/views/WorkflowView.js`

2. Repeated `409 Conflict` when creating/extracting unit while one is active.
   - Root cause: backend correctly blocks multiple active units; UI kept allowing the action.
   - Fix: hide/guard create-extract controls when a unit is active and show clear warning.
   - Files:
     - `frontend/src/views/WorkflowView.js`

3. Manual unit create payload mismatch.
   - Root cause: frontend was sending unsupported `unit_type=revision`.
   - Fix: frontend sends `unit_type=chapter`; backend accepts chapter/exercise_series when `source_text` is provided (no PDF required).
   - Files:
     - `frontend/src/views/WorkflowView.js`
     - `backend/app/routers/workflow.py`
     - `backend/tests/test_app_flows.py` (regression test)

4. Dashboard KPIs/trends showing wrong or empty values.
   - Root cause: frontend expected old fields (`session_count`, `avg_attendance`, `avg_exam_score`, `attendance_trend[].date/pct`, `exam_trend[].name/avg`).
   - Fix: map to backend schema:
     - `counts.sessions`
     - attendance average from `attendance_totals` + `counts.attendance_rows`
     - exam average from `exam_trend[].average_score`
     - trend keys `session_date`, `attendance_rate`, `title`, `average_score`
   - Files:
     - `frontend/src/views/ClassView.js`

5. Exam screen payload mismatches.
   - Root cause: frontend used `exam.name/date/archived`, but backend returns `title/exam_date/is_archived`.
   - Fix: aligned exam header, pills, archive/restore controls, and selection logic.
   - Files:
     - `frontend/src/views/ExamView.js`

6. Exam table sort and columns mismatched backend result shape.
   - Root cause: UI sorted on non-existent keys (`rank`, `max_score`, `grade`) and rendered inconsistent columns.
   - Fix: default sort by `full_name`, null-safe sorting, columns aligned to available result fields.
   - Files:
     - `frontend/src/views/ExamView.js`

7. Student detail modal from Exams was broken.
   - Root cause: frontend expected flattened profile object; backend returns nested `{student, attendance, exams}`.
   - Fix: added normalization adapter before rendering modal.
   - Files:
     - `frontend/src/views/ExamView.js`

8. Class switch stale-state issues.
   - Root cause: class switch only refreshed workflow data; attendance/students/dashboard could remain stale from previous class.
   - Fix: class change now refreshes students + dashboard + workspace together; handles empty class selection safely.
   - Files:
     - `frontend/src/main.js`
     - `frontend/src/components/AppShell.js`

9. Import accept filters misaligned with backend Excel import.
   - Fix: student and exam imports now accept `.xlsx,.xls`.
   - Files:
     - `frontend/src/views/ClassView.js`
     - `frontend/src/views/ExamView.js`

10. Backend `/app` static serving fallback was source-first.
   - Root cause: non-dev access could serve source `index.html` (expects `/src/main.js`) instead of built assets.
   - Fix: backend now prefers `frontend/dist` when present, with fallback to source.
   - Files:
     - `backend/app/main.py`

## UI Work Still Missing (To Complete Product Flow)
1. Session screenshot extraction UI is missing.
   - Backend endpoints exist:
     - `POST /sessions/{session_id}/uploads`
     - `POST /sessions/{session_id}/confirm-extraction`
   - Needed UI:
     - upload image during session
     - review extracted items
     - confirm and write progress items

2. Workflow unit types are incomplete in UI.
   - Backend supports: `chapter`, `exercise_series`, `exam`, `exam_correction`.
   - UI currently only creates `chapter`.
   - Needed UI: unit type selector and contextual form fields.

3. Owner teacher-class assignment UI is missing.
   - Backend supports assign/unassign endpoints.
   - Needed UI: assign/unassign teachers per class.

4. Owner invite email flow is missing from UI.
   - Backend supports `POST /auth/users/{id}/send-invite`.
   - Needed UI: send invite action with app URL + optional temporary password.

5. Exam maintenance UI is partial.
   - Backend supports `PUT /exams/{id}` and template download.
   - Needed UI:
     - edit exam metadata (title/date/max/weight)
     - download exam template (`/exams/{id}/template`)

6. Class creation UI is minimal.
   - Backend supports `subject`, `level`, and optional `teacher_user_id`.
   - Needed UI: include these fields.

7. Deployment build pipeline still needs to guarantee fresh frontend assets.
   - Backend now prefers `frontend/dist` if present.
   - Needed: ensure deploy flow always runs frontend build and ships updated `dist`.

## Validation Done
- `node --check` passed for all `frontend/src/**/*.js`.
- Targeted backend workflow tests passed for updated unit-start behavior.

---

## UI Revision Pass 2 — 2026-03-04 (UI Guy)

### Scope
Implemented the remaining UI TODO items from `UI-TODO-LIST.md` that were left to the UI developer.
Focused on: workflow polish, class/exam form enhancements, and consistent busy states.

### Delivered In This Pass

**WorkflowView.js**
1. **Unit Type Selector** — 4-tile grid (Chapter 📖 / Exercises ✏️ / Exam 📝 / Correction ✔️) above the unit create form. Sends `unit_type` to `POST /workflow/classes/{class_id}/units/start`.
2. **Button Busy States** — `_setBusy()` / `_setLabelBusy()` helpers applied to: Create Unit, PDF Upload label, Start Session (both), End Session (both), Save Attendance, Close Unit, Reopen Unit, Resume Extraction, Extract from PDF label.
3. **Input Validation Highlight** — `input-error` CSS class applied on invalid title / planned_hours inputs; cleared on next valid submit.
4. **Extraction Modal Polish** — mode-selector uses `.extraction-mode-card` (blue border + shadow on selected), horizontal divider, emoji-prefixed type options in item rows.
5. **Session Progress Viewer** — `.progress-type-badge.type-{lesson|activity|exercise}` color-coded pills; `.progress-item-row` card-style rows.
6. **Past Unit Re-open** — unit-type badge shown under unit title; Re-open button styled as ↩ pill with busy state.

**ClassView.js**
7. **Expanded Create Form** — 3-column layout: Class Name / Subject (optional) / Level (optional). Both optional fields sent to `POST /classes` when non-empty.
8. **Student Template Download** — 📋 Template button beside Import; calls `GET /classes/{id}/students/template`.
9. **Create Class Busy State** — button disabled + spinner during API call; `input-error` highlight on blank name.

**ExamView.js**
10. **Exam Date Field** — date picker added to Create Exam form (was missing; value was hardcoded to today).
11. **Edit Exam Modal** — ✏️ Edit button in exam header; calls `PUT /exams/{id}` for title / date / max score.
12. **Exam Template Download** — 📋 Template button; calls `GET /exams/{id}/template`.
13. **CSV Export Fallback** — tries `/exams/{id}/results.csv` first; falls back to `.xlsx` on error.
14. **Create Exam Busy State** — button disabled + spinner during API call.

**components.css**
- `.btn-busy`, `.label-btn-busy` — spinner overlay for buttons and label wrappers.
- `.unit-type-selector`, `.unit-type-btn` — responsive tile grid for type picker.
- `.extraction-mode-card`, `.extraction-mode-card.selected` — radio card with blue selected highlight.
- `.progress-type-badge.type-*` — color-coded type pills.
- `.progress-item-row` — card-style session progress item.
- `.input-error` — red border + glow on invalid inputs.
- `.btn-reopen` — pill-style re-open button.

### Validation
- `npm run build` (Vite) passed in 668ms with 0 errors after all changes.

### Remaining UI Work (Next Pass)
- Owner Panel: teacher-class assignment, invite email flow.
- Auth: Change Password screen, HTTP 423 lockout UX.
- Exam: Inline result editor (`note`, `teacher_comment`); archived exam filter toggle.
- Class: Archive reason input; extraction confidence panel.
- Calendar: Timetable density/readability, drag-resize handles, navigation polish.
- Cross-cutting: accessibility pass, mobile QA, smoke tests.
