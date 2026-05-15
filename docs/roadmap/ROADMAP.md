# Teacher Progress App - Built Roadmap (Current State)

Last updated: 2026-03-03

## 1) Product Scope Implemented

The app is now a teacher platform with owner-managed access:

- Owner creates and manages teacher accounts.
- Teachers create/manage their own classes.
- Student rosters are imported from Excel (`id`, `name`, `birth_date`) including NotesCC-style lists.
- Teaching work is tracked as workflow units:
  - `chapter`
  - `exercise_series`
  - `exam`
  - `exam_correction`
- For chapter/exercise units, teacher uploads a PDF and AI builds a checklist.
- Each session stores:
  - date and start/end time
  - absent students
  - checked checklist items done in that session
  - note/comment
- Saved sessions appear in calendar/timeline and are editable.
- Exam notes can be imported/exported in Excel formats.
- Admin exports are available (full PDF report + official notes Excel).

## 2) Actual Technical Architecture (As Built)

- Frontend: single-page HTML/CSS/JavaScript in `frontend/index.html`.
- Backend: FastAPI (`backend/app`).
- ORM: SQLAlchemy models.
- DB runtime:
  - SQLite by default/local.
  - PostgreSQL via Docker compose (configured service exists).
- Storage:
  - local filesystem under `storage/` for uploads, exports, logs, backups.
- AI extraction:
  - OpenAI when `OPENAI_API_KEY` is configured.
  - deterministic local fallback when OpenAI is unavailable.

## 3) Functional Modules Delivered

### A. Authentication and Roles
- Owner bootstrap/login, token auth, refresh/logout.
- Owner can create, activate/deactivate, reset/unlock teacher users.
- Class access control (teachers see assigned classes only).

### B. Class and Student Management
- Create/list/archive/restore classes.
- Import roster from Excel.
- Download roster template.
- Student profile + profile PDF export.

### C. Workflow Teaching Engine
- Start one active unit per class.
- Upload PDF for chapter/exercise units.
- AI generates hierarchical todo checklist.
- Manual checklist add/edit/delete for correction.
- Start session -> mark attendance -> toggle checklist -> end/save session.
- Parent/child checkbox behavior supported.
- Edit past saved workflow session from calendar.
- Close unit and keep it in history with collapse/expand UI.

### D. Calendar and Progress Tracking
- Day/time agenda style timeline for sessions.
- Session entry includes absences, checked items, note, and time range.
- Calendar export to Excel.
- Planned vs delivered vs remaining hours indicators.

### E. Exams and Notes
- Create/edit/archive/restore exams.
- Import exam results from normalized and NotesCC-style sheets.
- Export official notes Excel (including template mode when configured).
- Results list with filtering/sorting and student drilldown.

### F. Reporting, Audit, and Operations
- Class full report PDF export.
- Export history tracking and artifact download.
- Audit logs (class/session/exam/security events).
- Structured logs + basic ops status endpoint.
- Backup/restore scripts for database operations.

## 4) Current UX Flow (Teacher)

1. Login.
2. Create/select class.
3. Import student Excel list.
4. Start workflow unit and upload PDF if required.
5. Start session and mark absent students.
6. Check completed todo items.
7. End session with date/time and note.
8. Use calendar to review/edit past sessions.
9. Export reports when needed.

## 5) Current UX Flow (Owner)

1. Bootstrap owner account (first run only).
2. Login as owner.
3. Open Owner Control panel.
4. Create teacher account and share credentials/invite.
5. Assign teachers to classes and monitor overview.

## 6) Verification Baseline

The implemented project includes:

- Backend test suite in `backend/tests`.
- Frontend script parse check (`node --check frontend/index.html`).
- Python compile check (`python -m compileall -q backend/app`).

Recommended pre-handoff command set:

```bash
docker compose up -d --build
python -m compileall -q backend/app
python -m pytest -q -p no:cacheprovider tests
node --check frontend/index.html
```

## 7) Handoff Notes for UI/UX Designer

- Keep teacher flow minimal around:
  - class selection
  - active unit/checklist
  - attendance + end session
  - calendar review
- Owner management already exists in UI and API; redesign can focus on clarity and mobile ergonomics.
- Workflow logic is backend-complete enough for full UI redesign without changing core data contracts.
