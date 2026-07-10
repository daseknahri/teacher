# Claude Code Handoff

This repo is a teacher progress platform with two main users:
- Teachers use the app to manage classes, upload unit/exercise PDFs, receive a clean checklist, run class sessions, mark attendance, check covered content, and export reports.
- Owners/supervisors use the app to manage teachers/classes and inspect teacher progress through dashboard and calendar views.

The project is intentionally moving toward a stable teacher workflow first: clean extracted checklists are the source of truth, and richer AI/content-bank features should be added one by one only after they are verified.

## Current Status

Current verified state after the latest stabilization pass:
- Backend tests: `199 passed` with `python -m pytest backend/tests -q --tb=short`.
- Frontend build: `npm run build` passes. Vite still warns that the main JS chunk is larger than 500 kB.
- Frontend smoke: `npm run smoke:ui` passes.

Important local rule:
- Root `.env`, `backend/.env`, `storage/`, `app.db`, `frontend/dist/`, and temporary NotebookLM folders are local/ignored. Do not copy secrets into docs, tests, or commits.

## Tech Stack

Backend:
- FastAPI app in `backend/app`.
- SQLAlchemy models in `backend/app/models.py`.
- SQLite by default, configured by `DATABASE_URL`.
- Upload/export storage under `STORAGE_DIR` or `storage/`.
- Tests are in `backend/tests/test_app_flows.py` with shared fixtures in `backend/tests/conftest.py`.

Frontend:
- Vite app in `frontend`.
- Plain JavaScript view modules under `frontend/src/views`.
- Shared shell/router/state utilities under `frontend/src/components`, `frontend/src/router.js`, and `frontend/src/state`.
- CSS lives under `frontend/src/style`.

AI/extraction providers:
- Deterministic fallback parsing always exists.
- OpenAI can be enabled with `OPENAI_API_KEY` and `OPENAI_MODEL`.
- NotebookLM can be enabled with `UNIT_PLANNER_PROVIDER=notebooklm`, `SESSION_WRITER_PROVIDER=notebooklm`, and a persisted NotebookLM auth state.

## How To Run Locally

Backend:
```powershell
$env:PYTHONPATH='backend'
uvicorn app.main:app --reload --app-dir backend
```

Frontend:
```powershell
cd frontend
npm install
npm run dev
```

Verification:
```powershell
$env:PYTHONPATH='backend'
python -m pytest backend/tests -q --tb=short

cd frontend
npm run smoke:ui
npm run build
```

Docker:
```powershell
docker compose up --build
```

## Backend Map

Core files:
- `backend/app/main.py`: FastAPI startup, middleware, router registration.
- `backend/app/config.py`: environment configuration and defaults.
- `backend/app/database.py`: SQLAlchemy engine/session setup.
- `backend/app/models.py`: users, classes, students, sessions, workflow units/items, exams, exports, audit logs, timetable rules.
- `backend/app/schemas.py`: request/response schemas.
- `backend/app/security.py`: auth token and password helpers.

Routers:
- `backend/app/routers/auth.py`: owner bootstrap, login, token refresh/logout, teacher account management.
- `backend/app/routers/classes.py`: class CRUD, class assignments, rosters, dashboards, timelines, attendance exports, timetable setup.
- `backend/app/routers/sessions.py`: generic class session CRUD, attendance, uploads, extraction confirmation.
- `backend/app/routers/workflow.py`: the main teaching workflow: units, extracted checklists, session start/end, progress toggles, calendar, NotebookLM context start, assistant/material/leaf endpoints.
- `backend/app/routers/exams.py`: exams, exam result imports, archive/restore, templates.
- `backend/app/routers/reports.py`: PDF and Excel report exports.
- `backend/app/routers/audit.py`: owner audit log views/CSV.
- `backend/app/routers/ops.py`: owner operational status.

Services:
- `backend/app/services/workflow.py`: document text extraction wrapper and provider selection for unit checklist generation.
- `backend/app/services/workflow_generation.py`: extraction prompts, NotebookLM/OpenAI/fallback checklist generation, unit maps, content blocks, section plans, assistant/material/leaf generation.
- `backend/app/services/workflow_content.py`: session route/context serialization helpers.
- `backend/app/services/extraction.py`: screenshot/OCR-style extraction utilities.
- `backend/app/services/excel.py`: roster/exam Excel parsing and export helpers.
- `backend/app/services/report.py`: PDF/report generation.
- `backend/app/services/timetable_import.py`: timetable import/preview helpers.
- `backend/app/services/holidays.py`: Morocco holiday and non-working-day logic.
- `backend/app/services/audit.py`: audit log creation helpers.
- `backend/app/services/logging_setup.py`, `alerts.py`, `rate_limit.py`, `upload_validation.py`, `mailer.py`: operations/security support.

## Frontend Map

Views:
- `frontend/src/views/LoginView.js`: login and first owner bootstrap.
- `frontend/src/views/ClassView.js`: class setup, roster import, timetable import/editing, teacher class context.
- `frontend/src/views/WorkflowView.js`: main teacher workflow: active unit card, checklist, create/extract next unit, session active view, attachments/notes/Ask actions.
- `frontend/src/views/CalendarView.js`: teacher calendar with session cards and session detail expansion.
- `frontend/src/views/ExamView.js`: exam management, result import/export flows.
- `frontend/src/views/OwnerView.js`: supervisor/owner dashboard, teacher filters, analytics sections, calendar-like supervision tracker.
- `frontend/src/views/QuickPlannerView.js`: quick planning entry point.

Shared frontend files:
- `frontend/src/api/client.js`: API calls and auth-aware fetch helpers.
- `frontend/src/components/AppShell.js`: global layout/sidebar/topbar.
- `frontend/src/state/*.js`: local state modules for auth, class, workflow, exams.
- `frontend/src/utils/*.js`: formatting, modal, toast, retry helpers, leaf content helpers.
- `frontend/src/style/*.css`: tokens, layout, components, app-specific styles.

## Main Teacher Workflow

1. Owner creates a teacher and assigns classes.
2. Teacher selects a class from the top dropdown.
3. Teacher creates a unit or extracts from a PDF.
4. Unit type controls extraction behavior:
   - `chapter`: preserve a pedagogical checklist for teaching a unit.
   - `exercise_series`: preserve the series title and exact exercise headlines only.
   - `exam`: deterministic template: one checklist item, `Supervision d'examen`.
   - `exam_correction`: deterministic template: one checklist item, `Correction de l'examen`.
5. Teacher reviews/approves the extracted checklist.
6. Teacher starts a session, marks attendance, checks only content really covered, and ends the session.
7. Calendar/session detail pages show what was done and what remains.
8. Reports and exports use the stored class/session/exam data.

## Extraction Rules That Matter

Exercise series:
- Keep one root title for the exercise series.
- Keep exact visible exercise headlines, including compound titles such as `Exercice 2B.3 - POLYNESIE 2001`.
- Do not store rewritten exercise content at this stage.
- If NotebookLM returns only weak headings but the PDF layout seed has richer/more complete headings, the app repairs the checklist from the PDF layout seed.

Chapter/unit extraction:
- Drop teacher meta sections such as objectives, prerequisites, resources, time management, and pedagogical process.
- Preserve student-facing buckets: `Activites`, `Contenu de la lecon`, `Evaluation`.
- Resequence content into teaching order: activities, lesson/content, topic headings, rules/definitions/properties, examples, exercises/evaluation.
- Prefer a stronger NotebookLM unit map when it contains a better ordered outline than the raw outline response.
- If NotebookLM is too weak and a document reference exists, OpenAI can run as a shadow candidate and win only when its structure scores better.

Exam/exam correction:
- Current direction is deliberately simple.
- Exam unit creates a title plus one `Supervision d'examen` checklist item.
- Exam correction creates one `Correction de l'examen` checklist item.
- Do not call NotebookLM by default for exam templates. Use a separate future action if the teacher wants NotebookLM to open the PDF for scoring/rubric analysis.

NotebookLM context:
- `POST /workflow/classes/{class_id}/units/{unit_id}/notebooklm/start` starts or stores provider context for the unit.
- The workflow router imports the workflow generation service module, not the function directly, so tests and future provider swaps can monkeypatch it safely.
- Keep NotebookLM sessions separated by unit role (`chapter_outline`, `exercise_outline`, `exam_outline`, `correction_outline`) so future content-bank work can reuse the right context.

## Session And Timetable Logic

Important behavior:
- A teacher may have several classes and can switch class from the top dropdown.
- When starting the current workflow session without choosing a calendar session, classes with timetable rules should use the next valid timetable slot after the latest session for that unit.
- Explicitly selecting a planned calendar session is still allowed and reuses that session.
- A finished session that was already started is not silently reused for a new live session.
- Empty legacy session close payloads clamp `end_time` so it cannot become earlier than `start_time`.
- Sundays and Morocco holidays are blocked for normal session creation.

Key code:
- `backend/app/routers/workflow.py`: `_find_reusable_workflow_session_for_unit_start`, `_class_has_timetable_rules`, `start_workflow_session`, `end_workflow_session`.
- `backend/app/services/holidays.py`: non-working-day rules.

## Owner/Supervisor App

Current intent:
- The owner dashboard should be readable and sectioned.
- Owner can filter/select a teacher and inspect that teacher's classes, recent work, analytics, and calendar-style session activity.
- Calendar interaction should show what the teacher checked in a session, similar to the teacher app calendar.

Key frontend file:
- `frontend/src/views/OwnerView.js`

Key backend endpoints:
- `GET /classes/owner-overview`
- `GET /classes/by-teacher/{teacher_user_id}`
- `GET /workflow/classes/{class_id}/calendar`
- `GET /audit/logs`

## Recent Stabilization Work

Backend test isolation:
- `backend/tests/conftest.py` now pins test env before importing the app.
- Tests use a temporary SQLite database and storage root.
- AI providers are forced to fallback unless a test explicitly monkeypatches them.
- This prevents local `.env`, live OpenAI keys, NotebookLM auth state, and persistent app DB data from leaking into tests.

Workflow session fixes:
- Added audit-based detection so already-started sessions are not reused as fresh sessions.
- Timetable classes now create/use the next valid timetable slot unless the user explicitly selected a session.
- Legacy empty session close payloads no longer accidentally create invalid end times.

Extraction fixes:
- NotebookLM chapter normalizer now preserves student buckets and resequences teaching flow.
- Exercise-series repair now initializes PDF layout context in the NotebookLM path.
- Weak NotebookLM output can be replaced by richer PDF layout seed for exercise headings.
- OpenAI shadow extraction can replace weak NotebookLM output when a document reference exists and OpenAI scores better.
- Exact source section rendering can preserve both excerpt and teaching material when needed.

Compatibility fixes:
- `ensure_notebooklm_generation_ready` remains available from `backend/app/services/workflow.py` for existing tests/monkeypatches, but unit extraction no longer pre-fails just because NotebookLM is not ready.

## Current Known Warnings And Risks

- Vite warns that the main JS chunk is larger than 500 kB. This is not failing the build, but future work should split large views or lazy-load owner/workflow/exam modules.
- `workflow_generation.py` is large and central. Prefer small tested changes around one behavior at a time.
- NotebookLM is browser/session driven. Real provider tests depend on local auth state and should not be required for CI.
- Content bank / leaf content APIs exist but are experimental. Treat them as a future layer, not the current source of truth.
- The app currently stores extracted structure and some content-block metadata, but the durable reusable content-bank/RAG foundation still needs a separate design and migration plan.

## Safe Development Process

Before changing behavior:
```powershell
git status --short
```

After backend edits:
```powershell
$env:PYTHONPATH='backend'
python -m pytest backend/tests/test_app_flows.py -q --tb=short -k "name_of_relevant_test"
python -m pytest backend/tests -q --tb=short
```

After frontend edits:
```powershell
cd frontend
npm run smoke:ui
npm run build
```

When changing extraction:
- Add or update focused tests in `backend/tests/test_app_flows.py`.
- Test the exact provider behavior with monkeypatches first.
- Keep deterministic fallback behavior stable.
- Do not make NotebookLM required for tests.

When changing UI:
- Keep teacher workflow simple: current unit, checklist, session state, calendar/session detail.
- Avoid adding AI actions into the main path before they work reliably.
- The checklist remains the main communication structure with NotebookLM.

## Future Direction

Recommended next product phases:
1. Finish supervisor dashboard polish and calendar detail UX.
2. Add a stable content-bank builder outside the live teacher workflow.
3. Store atomic unit content with provenance, exact source references, Markdown/LaTeX math, screenshots/assets when needed, and supervisor approval state.
4. Generate v1 teacher flows from approved content-bank atoms.
5. Let teachers use the bank by default, with NotebookLM as an assistant/context tool rather than the only source of structure.
6. Later add student assistant/RAG only after teacher workflows and content provenance are reliable.
