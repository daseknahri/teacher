# Teacher Progress App

Teacher-first web app to track class progress by session:
- Add class
- Import students from Excel
- Start a unit (chapter/exercise series/exam/exam correction)
- AI converts chapter/exercise docs into a todo checklist
- For each session: mark absences, check completed todo items, end/save session
- Download full PDF report for administration
- Import exam notes from Excel and export official notes file

## Quick Start (Docker)
```bash
docker compose up --build
```

Open:
- `http://127.0.0.1:8000/app` (simple teacher UI)
- `http://127.0.0.1:8000/docs` (API docs)

## OpenAI Extraction
Set in your environment before `docker compose up`:
```bash
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o-mini
```

If OpenAI is not available, extraction automatically falls back to local heuristic parsing.

## NotebookLM Extraction
NotebookLM support is now integrated for:
- unit checklist generation from a unit PDF
- session write-up generation after checklist items are confirmed

Recommended first-time setup:
1. On your own machine, install the backend requirements.
2. Run `python -m notebooklm login`.
3. Sign in with the Google account that can access NotebookLM.
4. Use the generated `storage_state.json` with the app.

Relevant env vars:
```bash
UNIT_PLANNER_PROVIDER=notebooklm
SESSION_WRITER_PROVIDER=notebooklm
NOTEBOOKLM_HOME=/data/notebooklm
NOTEBOOKLM_PROFILE=default
NOTEBOOKLM_TIMEOUT_SECONDS=45
```

For deployed environments, the easiest path is:
1. keep `NOTEBOOKLM_HOME` on a persistent volume
2. authenticate locally
3. upload the `storage_state.json` file from the Owner panel

See `docs/deployment/COOLIFY_NOTEBOOKLM.md` for the production/Coolify setup.

## Optional SMTP (Owner Invite Emails)
Set these to enable owner "Send Invite Email":
```bash
SMTP_HOST=smtp.yourprovider.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM_EMAIL=owner@school.com
SMTP_USE_SSL=false
SMTP_USE_STARTTLS=true
```

## Core Teacher Flow
1. Login.
2. Create/select class.
3. Import roster Excel.
4. Start a workflow unit and upload document when required.
5. Start session, mark absent students, check done items, end session.
6. Edit past sessions from calendar if needed.
7. Download PDF report when needed.

Quick-submit screenshot flow is still available as compatibility mode.

Optional exam flow:
1. Create exam.
2. Import exam results Excel.
3. Export official notes Excel for principal/administration.

Excel formats supported:
- Students import: `id, name, birth_date` (your NotesCC class list format is supported).
- Exam import: `id, name, birth_date, note_1, note_2, note_3, note` (also accepts `note1/note2/note3`).

## Operations
- Database backup/restore scripts: `infra/db/backup.ps1`, `infra/db/restore.ps1`
- Daily backup scheduler: `infra/db/schedule-daily-backup.ps1`
- Structured rotating app logs: `storage/logs/app.log`
- Optional API alerting (webhook/email) for exceptions, 5xx, and slow responses

## Owner (Super User) Flow
1. First run only: create owner from Login card (`First setup only: create owner account`) or `/auth/bootstrap-owner`.
2. Login as owner.
3. Open `Owner Control` in the app.
4. Create teacher account (full name + email + temporary password).
5. Copy invitation text and send it to teacher (or send invite email if SMTP is configured).
6. Assign or unassign teacher while managing classes, view assigned teachers per class, and view classes per teacher.
7. Reset/deactivate/activate teacher accounts when needed.
8. Check owner analytics overview (global counts + per-teacher activity).

## Project Docs
- `docs/roadmap/ROADMAP.md` current implemented scope and architecture
- `docs/roadmap/APP-FUNCTIONALITY-WORKFLOWS.md` module-by-module functionality and workflows
- `docs/roadmap/FUTURE-TODO.md` prioritized next backlog + ready-to-test checklist
- `docs/roadmap/PROD-ENV-CHECKLIST.md` production env and secret rotation checklist
- `docs/roadmap/INTEGRATION-AUTH-PATTERNS.md` reusable guide for choosing between API, OAuth, restored-session, and browser-automation integrations
- `docs/roadmap/AI-CONTENT-BANK-HANDOFF.md` fastest handoff for the NotebookLM unit-brain and leaf-content direction
- `docs/roadmap/CLAUDE-CONTINUATION-PROMPT.md` paste-ready prompt for handing the repo to Claude safely
- `docs/roadmap/AI-COLLABORATION-PROTOCOL.md` how to let multiple AI helpers work on the same repo without breaking direction
- `docs/roadmap/AI-WORKLOG.md` shared handoff log for active AI and engineering work
- `docs/roadmap/NOTEBOOKLM-UNIT-BRAIN-ARCHITECTURE.md` target architecture for moving from PDF extraction to a reusable unit brain
- `docs/roadmap/LEAF-CONTENT-BANK-SPEC.md` proposed per-leaf content storage contract using Markdown + LaTeX
- `docs/roadmap/LEAF-CONTENT-READER-ROADMAP.md` phased implementation plan for leaf content generation, reader UI, and session integration
- `docs/deployment/COOLIFY_APP_SETUP.md` exact Coolify deployment steps for this repo/domain
- `docs/deployment/COOLIFY_NOTEBOOKLM.md` NotebookLM persistence and auth upload flow
- `backend/README.md` backend setup and full endpoint list
