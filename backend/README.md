# Teacher Progress API (MVP)

## Run locally
```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Optional local `.env`:
- The app auto-loads `backend/.env` if present.
- Set `OPENAI_API_KEY` there to enable real OpenAI extraction.
- Set SMTP values there to enable owner invitation emails.
- Optional login lockout controls:
  - `MAX_FAILED_LOGIN_ATTEMPTS=5`
  - `LOGIN_LOCKOUT_MINUTES=15`
- Optional logging controls:
  - `LOG_LEVEL=INFO`
  - `LOG_JSON=true`
  - `LOG_MAX_BYTES=5242880`
  - `LOG_BACKUP_COUNT=7`
- Optional alerting controls:
  - `ALERT_WEBHOOK_URL=https://...`
  - `ALERT_EMAIL_TO=admin@school.com`
  - `ALERT_ON_5XX=true`
  - `ALERT_ON_EXCEPTION=true`
  - `ALERT_SLOW_MS=2500`
  - `ALERT_MIN_INTERVAL_SECONDS=300`
  - `ALERT_TIMEOUT_SECONDS=10`

Swagger UI: `http://127.0.0.1:8000/docs`
Simple browser UI: `http://127.0.0.1:8000/app`

## Run with Docker
From project root:
```bash
docker compose up --build
```
App URL: `http://127.0.0.1:8000/app`
API docs: `http://127.0.0.1:8000/docs`

## Inline test suite
```bash
pytest -q
```

## Authentication model
- One owner account (bootstrap once).
- Owner can create teacher users.
- All business endpoints require `Authorization: Bearer <token>`.
- Teachers only see classes assigned to them.
- Owner can assign teachers to classes.

Bootstrap/login example:
```bash
curl -X POST http://127.0.0.1:8000/auth/bootstrap-owner -H "Content-Type: application/json" -d "{\"email\":\"owner@app.local\",\"password\":\"OwnerPass123\",\"full_name\":\"Owner\"}"
curl -X POST http://127.0.0.1:8000/auth/login -H "Content-Type: application/json" -d "{\"email\":\"owner@app.local\",\"password\":\"OwnerPass123\"}"
```

## Optional official template mode
If you want exports to match your official `NotesCC` layout, set:
```bash
set PRINCIPAL_EXPORT_TEMPLATE=c:\path\to\export_notesCC_2APIC-3_0019.xlsx
```
Then `GET /classes/{class_id}/reports/official-notes.xlsx` will render inside that template format.
If not set, the app also auto-discovers the newest `~/Downloads/export_notesCC*.xlsx` file.

## Implemented endpoints
- `POST /auth/bootstrap-owner`
- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`
- `GET /auth/me`
- `POST /auth/change-password`
- `POST /auth/users` (owner only)
- `GET /auth/users` (owner only)
- `POST /auth/users/{user_id}/send-invite` (owner only, requires SMTP config)
- `PATCH /auth/users/{user_id}/status` (owner only)
- `POST /auth/users/{user_id}/reset-password` (owner only)
- `POST /auth/users/{user_id}/unlock` (owner only)
- `POST /classes`
- `GET /classes` (supports `include_archived=true`)
- `GET /classes/owner-overview` (owner only)
- `GET /classes/{class_id}`
- `POST /classes/{class_id}/archive`
- `POST /classes/{class_id}/restore`
- `POST /classes/{class_id}/assign-teacher/{teacher_user_id}` (owner only)
- `GET /classes/{class_id}/teachers` (owner only)
- `DELETE /classes/{class_id}/assign-teacher/{teacher_user_id}` (owner only)
- `GET /classes/by-teacher/{teacher_user_id}` (owner only)
- `GET /classes/{class_id}/students`
- `GET /classes/{class_id}/students/{student_id}/profile`
- `GET /classes/{class_id}/students/{student_id}/reports/profile.pdf`
- `GET /classes/{class_id}/dashboard` (includes `attendance_trend`, `extraction_metrics`, `exam_trend`)
- `GET /classes/{class_id}/timeline` (supports `date_from`, `date_to`, `note_query`, `has_progress`, `has_reviewed_upload`)
- `GET /classes/{class_id}/attendance-summary`
- `GET /classes/{class_id}/attendance-export.csv` (supports `date_from`, `date_to`, `mask_personal_data`)
- `GET /classes/{class_id}/exam-summary`
- `GET /classes/{class_id}/audit-logs`
- `POST /classes/{class_id}/students/import`
- `GET /classes/{class_id}/students/template`
- `POST /classes/{class_id}/sessions`
- `POST /classes/{class_id}/quick-submit`
- `GET /classes/{class_id}/sessions`
- `GET /sessions/{session_id}`
- `PUT /sessions/{session_id}`
- `PUT /sessions/{session_id}/attendance`
- `POST /sessions/{session_id}/uploads`
- `POST /sessions/{session_id}/confirm-extraction`
- `POST /workflow/classes/{class_id}/units/start` (unit types: `chapter`, `exercise_series`, `exam`, `exam_correction`)
- `POST /workflow/classes/{class_id}/units/{unit_id}/items` (manual checklist item add for active unit)
- `POST /workflow/classes/{class_id}/units/{unit_id}/items/reorder` (reorder + re-parent checklist tree for active unit)
- `PUT /workflow/classes/{class_id}/units/{unit_id}/items/{item_id}` (manual checklist item update for active unit)
- `DELETE /workflow/classes/{class_id}/units/{unit_id}/items/{item_id}` (manual checklist item delete for active unit)
- `GET /workflow/classes/{class_id}` (active unit, closed units, active session, recent sessions)
- `POST /workflow/classes/{class_id}/sessions/start`
- `POST /workflow/classes/{class_id}/sessions/{session_id}/items/{item_id}/toggle`
- `POST /workflow/classes/{class_id}/sessions/{session_id}/end` (editable for past sessions)
- `POST /workflow/classes/{class_id}/units/{unit_id}/close`
- `POST /workflow/classes/{class_id}/units/{unit_id}/reopen`
- `DELETE /workflow/classes/{class_id}/units/{unit_id}` (deletes the unit and all its linked sessions)
- `GET /workflow/classes/{class_id}/calendar`
- `GET /workflow/classes/{class_id}/calendar/export.xlsx`
- `GET /workflow/classes/{class_id}/calendar/export.pdf` (supports `date_from`, `date_to`, `ai_enhance=true`)
- `GET /workflow/units/{unit_id}/document`
- `POST /classes/{class_id}/exams`
- `GET /classes/{class_id}/exams` (supports `include_archived=true`)
- `PUT /exams/{exam_id}`
- `POST /exams/{exam_id}/archive`
- `POST /exams/{exam_id}/restore`
- `GET /exams/{exam_id}/template` (supports `?format=notescc`)
- `POST /exams/{exam_id}/results/import`
- `GET /exams/{exam_id}/results`
- `GET /classes/{class_id}/reports/official-notes.xlsx` (official notes export format)
- `GET /classes/{class_id}/reports/principal-notes.xlsx` (legacy alias)
- `GET /classes/{class_id}/reports/full.pdf` (supports `mask_personal_data`)
- `GET /classes/{class_id}/students/{student_id}/reports/profile.pdf` (supports `mask_personal_data`)
- `GET /classes/{class_id}/exports/history`
- `GET /exports/{export_id}/download`
- `GET /audit/logs` (owner only)
- `GET /audit/logs.csv` (owner only)
- `GET /ops/status` (owner only)

Archived classes are hidden from `GET /classes` by default and become read-only (no new sessions, attendance updates, extraction confirmation, or exam imports) until restored.

Audit trail and export versioning:
- Critical actions (class/session/exam/import/export/security changes) create rows in `audit_logs`.
- Generated reports are versioned in `export_artifacts` and stored on disk under `storage/exports/class_{id}`.
- Owner audit endpoints support filters: `action`, `class_id`, `user_id`, `date_from`, `date_to`, `limit`.

`/exams/{exam_id}/results/import` accepts:
- normalized file with headers: `student_code, full_name, score, note, teacher_comment`
- notes list format with headers: `id, name, birth_date, note_1, note_2, note_3, note` (also accepts `note1/note2/note3`)
- `NotesCC`-style file (score parsed from `M` then `K/I/G` as fallback)

`/classes/{class_id}/students/import` accepts:
- normalized file with headers `student_code, full_name` (optionally `birth_date`, `external_id`)
- `NotesCC` class list layout (rows from 18 with ID/code/name/birth date)

Upload validation rules:
- Excel uploads (`students/import`, `exam results/import`) accept `.xlsx`/`.xlsm` only and enforce `MAX_EXCEL_UPLOAD_BYTES`.
- Session screenshots accept image files (`.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`) and enforce `MAX_SCREENSHOT_UPLOAD_BYTES`.

Rate limiting (in-memory):
- Upload endpoints enforce `UPLOAD_RATE_LIMIT_COUNT` within `UPLOAD_RATE_LIMIT_WINDOW_SECONDS`.
- Export endpoints enforce `EXPORT_RATE_LIMIT_COUNT` within `EXPORT_RATE_LIMIT_WINDOW_SECONDS`.
- Exceeded limits return HTTP `429`.

Privacy controls for exports:
- `mask_personal_data=true` is supported on attendance CSV, official notes Excel, class PDF, and student profile PDF endpoints.
- Masked mode anonymizes student identity fields (`ANON###`, `Student ###`) and clears attendance comments in CSV exports.

OpenAI extraction integration:
- If `OPENAI_API_KEY` is set, session extraction calls OpenAI (`OPENAI_MODEL`) for structured parsing.
- If OpenAI is unavailable, extraction falls back to the deterministic local heuristic parser.
- Extraction response includes `provider` and `model` so you can verify which path was used.

Operational scripts:
- Create backup: `powershell -ExecutionPolicy Bypass -File .\infra\db\backup.ps1`
- Restore backup: `powershell -ExecutionPolicy Bypass -File .\infra\db\restore.ps1 -InputFile <path_to_sql>`
- Schedule daily backup: `powershell -ExecutionPolicy Bypass -File .\infra\db\schedule-daily-backup.ps1 -At 22:00`
- Structured rotating logs are written to `storage/logs/app.log`.
- Alerting supports webhook/email for exceptions, 5xx responses, and slow requests.

Teacher quick-submit flow:
- Use `POST /classes/{class_id}/quick-submit` with:
  - `file` (screenshot image),
  - `absent_student_ids` (JSON array string like `[12,15]`, optional),
  - `raw_text` (optional OCR override text).
- This endpoint creates one session, attendance rows, screenshot upload extraction, and progress items in one request.

Owner invitation email flow:
- Configure SMTP env vars:
  - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`
  - `SMTP_USE_SSL` / `SMTP_USE_STARTTLS`
- Send invite via `POST /auth/users/{user_id}/send-invite` with optional `temporary_password` and `app_url`.
