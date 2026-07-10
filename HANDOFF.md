# HANDOFF — Teacher Progress App

Continuation guide for picking this project up on another machine. Last updated 2026-07-10.
**Source of truth is GitHub** (`main` @ `fdcd4f5`). Always push before switching machines.

> Read next: [`docs/roadmap/ARCHITECTURE-EVALUATION-2026-07.md`](docs/roadmap/ARCHITECTURE-EVALUATION-2026-07.md)
> (honest critique) and [`docs/roadmap/CONTENT-CURRICULUM-STRATEGY.md`](docs/roadmap/CONTENT-CURRICULUM-STRATEGY.md)
> (the decided next direction).

---

## What this is

A web app for teachers to track curriculum progress and for a supervisor (owner) to monitor it.
Teachers run **workflow units → hierarchical checklists → sessions** (with attendance); the owner
sees per-teacher coverage. Targets the Moroccan curriculum (French maths, NotesCC exam export).

- **Backend:** FastAPI + SQLAlchemy 2.0 + Pydantic. SQLite (dev) / PostgreSQL (prod).
- **Frontend:** vanilla JS + Vite + Tailwind v4 (no framework), hash router, KaTeX + marked.
- **AI (optional):** OpenAI for extraction; NotebookLM via Playwright (fragile — see eval doc).
- **Deploy:** Docker Compose / Coolify (**manual deploy — push does not auto-deploy**).

---

## Get it running on a fresh machine

Prereqs: Python 3.12, Node 18+, git.

```bash
git clone https://github.com/daseknahri/teacher.git
cd teacher
```

### Backend (serves the API and the built frontend at /app)
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```
- Health check: `GET http://127.0.0.1:8000/health` → `{"status":"ok"}`  (note: `/health`, NOT `/api/health`)
- API docs (Swagger): `http://127.0.0.1:8000/docs`
- DB is SQLite at `teacher/app.db`, created automatically. No secret key or special env needed for dev.
- This is a **FastAPI** app — ignore any note about `DJANGO_SECRET_KEY` (that belongs to a different project).

### First-run: create the owner, then log in
```
POST /auth/bootstrap-owner   {"email":"owner@school.edu","full_name":"School Owner","password":"OwnerPass123"}
POST /auth/login             {"email":"owner@school.edu","password":"OwnerPass123"}  -> {"access_token": "..."}
```
Use `Authorization: Bearer <access_token>` for all other calls. (Login returns `access_token`, not `token`.)

### Frontend
```powershell
cd frontend
npm install
npm run dev     # Vite dev server; proxies /api -> http://localhost:8000
# or
npm run build   # outputs dist/, which the backend serves at http://127.0.0.1:8000/app
```

### Tests
Run from the repo root (this is the invocation `CLAUDE.md` documents):
```powershell
$env:PYTHONPATH='backend'
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q --tb=short
```
**Baseline: 201 passed / 0 failed** (~8 min). The suite is fully green. `conftest.py` pins
`DATABASE_URL`/`STORAGE_DIR` and forces the AI providers to deterministic `fallback` *before* the
app is imported — that is what makes the NotebookLM/OpenAI tests reproducible without any provider.
Do not "fix" a test by loosening it before checking that `conftest.py` is being honoured.

---

## Current status (2026-07-10)

`main` is at `99b3f0b`. It contains two streams of work that were reconciled:

- **Supervisor dashboard redesign** — the owner panel is sidebar-driven with six sub-routes
  (Teacher Progress, Classes, Accounts, Calendar, NotebookLM, Settings); a Teacher Progress
  overview (coverage %, health) + a **Session Checklist Log** (what each teacher checked off per
  session); a Storage & Retention panel in Settings. Files: `frontend/src/views/OwnerView.js`,
  `components/AppShell.js`, `main.js`.
- **Optimistic locking on session updates** — `ClassSession.version`, 409 on stale `expected_version`
  (update + attendance), wired through all calendar edit paths. Prevents concurrent overwrite.
- **Retention policy + cleanup** — `RETENTION_*_DAYS` config (0 = disabled), `backend/app/services/
  retention.py`, owner-only `GET`/`POST /ops/retention`, opt-in startup sweep, owner UI panel.
- **Session-reuse + timetable correctness** — `_session_has_been_started()` (audit-based) so a
  finished session is never silently reused, `_class_has_timetable_rules()` so timetable classes take
  the next valid slot, and an `end_time` clamp on legacy empty close payloads.
- **Date-robust tests** — several tests hardcoded dates that expired (a "future" session dated in the
  past, a session on a Sunday). They now derive dates from `date.today()`.

Deferred by owner decision: **Alembic migrations**.

---

## Gotchas / things that will bite you

- **The dev `app.db` can get wiped** (test runs / env cleanup). If login fails with "Invalid
  credentials", just re-run `POST /auth/bootstrap-owner`.
- **A working copy vanished once** (environment/disk cleanup, not disk full). Nothing was lost because
  it was pushed. Treat GitHub as the only durable copy; push often. Related: the content-bank work
  lived on six local-only branches for weeks. They are now on `origin`.
- **NotebookLM won't work headless / in CI** — it automates Google's web UI and needs a manual auth
  file (`storage_state.json`). Do not build critical paths on it (see eval doc §2). Tests never need
  it: `conftest.py` forces `fallback`.
- **Hardcoded dates in tests are a recurring bug.** Anything compared against `date.today()` (future
  session cleanup, non-working Sundays, holidays) must be computed relative to today.
- **Windows/PowerShell**: run the backend via the venv python directly (`.\.venv\Scripts\python.exe`).
  `gh` is NOT installed here; open PRs from the GitHub web link or install it.
- **Local-only files**: `.env`, `.venv`, `node_modules`, `dist`, `app.db`, `storage/` are gitignored —
  recreate them per machine (see setup above). The 1AC source PDFs live outside the repo entirely.

---

## Where to go next (recommended order)

0. **Read the six `claude/*` branches on `origin` first.** They contain an in-progress content-bank /
   leaf-content implementation (generation, persistence, visibility, reader, source-block extraction).
   Any curriculum work must reconcile with them, not ignore them.
1. **Content / curriculum** (the owner's priority) — see `CONTENT-CURRICULUM-STRATEGY.md`. Blocked
   on the owner sharing the 1AC-maths PDFs on disk. Then: add `Curriculum`/`CurriculumNode`/
   `CurriculumNodeContent` tables, an owner authoring/import screen, digitize the programme skeleton,
   pilot one chapter of content, wire class instantiation + a teacher node-reader.
2. **Fix the session timezone.** `start_workflow_session` records machine-local time while
   `end_workflow_session` records UTC. The `end_time` clamp hides the resulting inversion by
   producing **zero-duration sessions** on any host ahead of UTC. Pick one clock — ideally a
   configured school timezone (`Africa/Casablanca`) — and use it for both.
3. **Alembic** — baseline the current schema, stop the 117-statement runtime patching in
   `database.py`. (Changes the Coolify deploy step — coordinate with the owner.)
4. **Split the monolith files** — `workflow.py` (7.8k), `workflow_generation.py` (7.9k),
   `WorkflowView.js` (7.4k), `CalendarView.js` (5.2k), `test_app_flows.py` (9.4k).
5. **Long-term:** move the frontend to a component framework (Svelte/Vue) — see eval doc §5.

---

## Key files map

- Models: `backend/app/models.py` · Schema-compat (no migrations): `backend/app/database.py`
- Routers: `backend/app/routers/{auth,classes,sessions,workflow,exams,reports,ops,audit}.py`
- Services: `backend/app/services/{retention,workflow_generation,report,extraction,...}.py`
- Frontend views: `frontend/src/views/{OwnerView,WorkflowView,CalendarView,ClassView,ExamView}.js`
- Frontend shell/router: `frontend/src/components/AppShell.js`, `src/router.js`, `src/main.js`
- Docs: `docs/roadmap/` (this handoff + the eval + content strategy live here and at repo root)
