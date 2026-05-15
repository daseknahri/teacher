# App Functionality and Workflows (Current Build)

Last updated: 2026-03-03

## 1) Platform Roles

- Owner:
  - Bootstrap owner account.
  - Create/manage teacher users.
  - Assign teachers to classes.
  - Monitor platform activity.
- Teacher:
  - Manage assigned classes.
  - Run teaching workflow sessions.
  - Track attendance and progress.
  - Manage exams and exports.

## 2) Module: Authentication and Access

Purpose:
- Secure login and role-based access for owner/teacher.

Main workflow:
1. Owner bootstraps account (first run only).
2. User logs in and receives bearer token.
3. Token is used for all protected actions.
4. Owner manages teacher accounts and status.

Primary endpoints:
- `POST /auth/bootstrap-owner`
- `POST /auth/login`
- `POST /auth/logout`
- `POST /auth/refresh`
- `GET /auth/me`
- `POST /auth/users` (owner)
- `PATCH /auth/users/{user_id}/status` (owner)
- `POST /auth/users/{user_id}/reset-password` (owner)
- `POST /auth/users/{user_id}/unlock` (owner)

## 3) Module: Class and Student Management

Purpose:
- Create classes and load student roster from Excel.

Main workflow:
1. Teacher creates a class.
2. Teacher imports roster Excel.
3. Students become available for attendance and exams.
4. Owner can assign/unassign teachers to class.

Primary endpoints:
- `POST /classes`
- `GET /classes`
- `GET /classes/{class_id}`
- `POST /classes/{class_id}/students/import`
- `GET /classes/{class_id}/students`
- `POST /classes/{class_id}/assign-teacher/{teacher_user_id}` (owner)
- `DELETE /classes/{class_id}/assign-teacher/{teacher_user_id}` (owner)

Accepted roster format:
- `id, name, birth_date` (NotesCC class list format is supported).

## 4) Module: Teaching Workflow Units

Purpose:
- Track progress by units: chapter, exercise series, exam, exam correction.

Main workflow:
1. Teacher starts a unit for class.
2. For `chapter` and `exercise_series`, teacher uploads PDF.
3. AI/parser builds checklist tree.
4. Teacher can manually add/edit/delete checklist items.
5. Unit stays active until teacher closes it.

Primary endpoints:
- `POST /workflow/classes/{class_id}/units/start`
- `GET /workflow/classes/{class_id}`
- `POST /workflow/classes/{class_id}/units/{unit_id}/items`
- `PUT /workflow/classes/{class_id}/units/{unit_id}/items/{item_id}`
- `DELETE /workflow/classes/{class_id}/units/{unit_id}/items/{item_id}`
- `POST /workflow/classes/{class_id}/units/{unit_id}/close`
- `GET /workflow/units/{unit_id}/document`

## 5) Module: Session and Attendance Lifecycle

Purpose:
- Save what was taught in each session with absences and completed checklist items.

Main workflow:
1. Teacher selects absent students.
2. Teacher starts workflow session.
3. Teacher checks completed items.
4. Teacher ends session with date/time/note.
5. Teacher can later select a saved session and edit it.

Primary endpoints:
- `POST /workflow/classes/{class_id}/sessions/start`
- `POST /workflow/classes/{class_id}/sessions/{session_id}/items/{item_id}/toggle`
- `POST /workflow/classes/{class_id}/sessions/{session_id}/end`
- `GET /workflow/classes/{class_id}/calendar`

Session data saved:
- `session_date`
- `start_time`
- `end_time`
- absent student IDs
- checked checklist items
- note

## 6) Module: Calendar and Progress Review

Purpose:
- Review daily session history and progress delivery.

Main workflow:
1. Teacher opens workflow calendar.
2. Filters by day or sees all days timeline.
3. Opens a saved session for edit/review.
4. Exports calendar log to Excel when needed.

Primary endpoints:
- `GET /workflow/classes/{class_id}/calendar`
- `GET /workflow/classes/{class_id}/calendar/export.xlsx`

## 7) Module: Exams and Notes

Purpose:
- Manage exams and import/export notes sheets.

Main workflow:
1. Teacher creates exam record.
2. Teacher imports results Excel.
3. Teacher reviews exam results list.
4. Teacher exports official notes sheet.

Primary endpoints:
- `POST /classes/{class_id}/exams`
- `GET /classes/{class_id}/exams`
- `PUT /exams/{exam_id}`
- `POST /exams/{exam_id}/results/import`
- `GET /exams/{exam_id}/results`
- `GET /classes/{class_id}/reports/official-notes.xlsx`

Accepted exam format:
- `id, name, birth_date, note_1, note_2, note_3, note`
- also supports `note1/note2/note3`.

## 8) Module: Reports and Exports

Purpose:
- Generate school-ready files for administration.

Main workflow:
1. Teacher generates full class PDF report.
2. Teacher generates official notes Excel.
3. Export artifacts are tracked and downloadable.

Primary endpoints:
- `GET /classes/{class_id}/reports/full.pdf`
- `GET /classes/{class_id}/reports/official-notes.xlsx`
- `GET /classes/{class_id}/exports/history`
- `GET /exports/{export_id}/download`

## 9) Module: AI Extraction

Purpose:
- Convert uploaded course PDF text into actionable checklist structure.

Current behavior:
- Uses OpenAI when `OPENAI_API_KEY` is configured.
- Falls back to local deterministic parser when unavailable.
- Output populates workflow checklist for teacher execution.

Main code paths:
- `backend/app/services/workflow.py`
- `backend/app/services/extraction.py`

## 10) Module: Ops and Audit

Purpose:
- Maintain traceability and operational visibility.

Features:
- Audit log of critical actions.
- Health/status endpoints.
- Structured logs in storage.
- Backup/restore scripts.

Primary endpoints/scripts:
- `GET /health`
- `GET /ops/status` (owner)
- `GET /audit/logs` (owner)
- `infra/db/backup.ps1`
- `infra/db/restore.ps1`
- `infra/db/schedule-daily-backup.ps1`

## 11) Current Constraints

- Frontend is still monolithic (`frontend/index.html`) and should be modularized in redesign.
- Session save conflict protection (optimistic lock) is not implemented yet.
- Per-item AI confidence and review state are not yet implemented.
- Alembic migrations are not yet introduced.
