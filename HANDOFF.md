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
```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```
**Baseline: 191 passed / 10 failed.** The 10 failures are all the AI/NotebookLM-generation cluster
(non-deterministic / need external providers) — they are **deferred, not regressions**. Everything
else is green. The full suite takes ~5–16 min.

---

## Current status (what was done 2026-07-10)

Committed as `fdcd4f5` "Supervisor dashboard UX + P0 production-hardening" (on `main`):

- **Supervisor dashboard redesign** — the owner panel is now sidebar-driven with six sub-routes
  (Teacher Progress, Classes, Accounts, Calendar, NotebookLM, Settings); a clean Teacher Progress
  overview (coverage %, health) + a **Session Checklist Log** (what each teacher checked off per
  session); a Storage & Retention panel in Settings. Files: `frontend/src/views/OwnerView.js`,
  `components/AppShell.js`, `main.js`.
- **Test baseline made reliable** — `backend/tests/conftest.py` now gives each test a clean DB (the
  engine is a module-level singleton, so the suite silently shared one DB and was order-dependent).
- **Real bug fixed** — `start_workflow_session` used machine-local `datetime.now()` while session
  end uses UTC → `end_time < start_time` 409/400 on hosts ahead of UTC. Now UTC everywhere.
- **Optimistic locking on session updates** — `ClassSession.version`, 409 on stale `expected_version`
  (update + attendance), wired through all calendar edit paths. Prevents concurrent overwrite.
- **Retention policy + cleanup** — `RETENTION_*_DAYS` config (0 = disabled), `backend/app/services/
  retention.py`, owner-only `GET`/`POST /ops/retention`, opt-in startup sweep, owner UI panel.

Deferred by owner decision: **Alembic migrations**, and the **10 AI tests**.

---

## Gotchas / things that will bite you

- **The dev `app.db` can get wiped** (test runs / env cleanup). If login fails with "Invalid
  credentials", just re-run `POST /auth/bootstrap-owner`.
- **The local working copy vanished once** during this session (environment/disk cleanup, not disk
  full). Nothing was lost because it was pushed. Treat GitHub as the only durable copy; push often.
- **NotebookLM won't work headless / in CI** — it automates Google's web UI and needs a manual auth
  file (`storage_state.json`). Do not build critical paths on it (see eval doc §2).
- **`OPENAI_API_KEY` is empty by default** → AI extraction falls back to a heuristic parser; the 10
  AI tests assert on generated content and will fail without a provider. Quarantine candidates.
- **Windows/PowerShell**: run the backend via the venv python directly (`.\.venv\Scripts\python.exe`).
  `git`/`gh`: `gh` is NOT installed here; open PRs from the GitHub web link or install it.
- **Two big machines, one repo**: `.env`, `.venv`, `node_modules`, `dist`, `app.db`, `storage/` are
  gitignored — you re-create them per machine (see setup above).

---

## Where to go next (recommended order)

1. **Content / curriculum** (the owner's priority) — see `CONTENT-CURRICULUM-STRATEGY.md`. Blocked
   on the owner sharing the 1AC-maths PDFs on disk. Then: add `Curriculum`/`CurriculumNode`/
   `CurriculumNodeContent` tables, an owner authoring/import screen, digitize the programme skeleton,
   pilot one chapter of content, wire class instantiation + a teacher node-reader.
2. **Alembic** — baseline the current schema, stop the 117-statement runtime patching in
   `database.py`. (Changes the Coolify deploy step — coordinate with the owner.)
3. **Split the monolith files** — `workflow.py` (7.8k), `workflow_generation.py` (7.9k),
   `WorkflowView.js` (7.4k), `CalendarView.js` (5.2k), `test_app_flows.py` (9.4k).
4. **Quarantine the 10 AI tests** (skip-if-no-provider) so the suite is green by default.
5. **Long-term:** move the frontend to a component framework (Svelte/Vue) — see eval doc §5.

---

## Key files map

- Models: `backend/app/models.py` · Schema-compat (no migrations): `backend/app/database.py`
- Routers: `backend/app/routers/{auth,classes,sessions,workflow,exams,reports,ops,audit}.py`
- Services: `backend/app/services/{retention,workflow_generation,report,extraction,...}.py`
- Frontend views: `frontend/src/views/{OwnerView,WorkflowView,CalendarView,ClassView,ExamView}.js`
- Frontend shell/router: `frontend/src/components/AppShell.js`, `src/router.js`, `src/main.js`
- Docs: `docs/roadmap/` (this handoff + the eval + content strategy live here and at repo root)
