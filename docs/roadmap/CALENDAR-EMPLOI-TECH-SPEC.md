# Calendar + Emploi Technical Spec (Implementation Blueprint)

Last updated: 2026-03-04
Status: Draft technical plan for build

## 1) Data Model

## Core Entities

1. `schedule_versions`
   - `id`
   - `teacher_user_id`
   - `name`
   - `status` (`draft`, `active`, `archived`)
   - `effective_from`
   - `effective_to` (nullable)
   - `source_type` (`ics`, `csv`, `xlsx`, `ai_scan`, `manual`)
   - `created_at`, `created_by_user_id`

2. `schedule_rules`
   - `id`
   - `schedule_version_id`
   - `class_id`
   - `weekday` (0-6 or 1-7)
   - `start_time`, `end_time`
   - `subject` (optional)
   - `room` (optional)
   - `group_label` (optional)
   - `is_active`

3. `holiday_days`
   - `id`
   - `date`
   - `name`
   - `region` (nullable)
   - `is_blocked`
   - `source`

4. `schedule_exceptions`
   - `id`
   - `class_id`
   - `date`
   - `start_time`, `end_time`
   - `exception_type` (`cancel`, `move`, `override_holiday`, `custom`)
   - `target_session_id` (nullable)
   - `note` (nullable)

## Session Extensions

1. Extend sessions with:
   - `planning_source` (`manual`, `rule_generated`)
   - `planning_rule_id` (nullable)
   - `planning_version_id` (nullable)
   - `status` (`planned`, `in_progress`, `done`, `cancelled`)
   - `unit_session_number` (nullable, for workflow-linked sessions)

2. Uniqueness recommendation:
   - unique planned slot key: `(class_id, session_date, start_time, planning_rule_id, planning_version_id)`

## 2) Generation Engine

Use rolling materialization, not year-long hard generation.

1. Nightly or on-demand job generates planned sessions for next 4 to 8 weeks.
2. Skip blocked `holiday_days` unless explicit override exception exists.
3. Respect `schedule_exceptions` before creating/updating planned sessions.
4. Upsert idempotently using planned slot key.
5. Never rewrite delivered (`done`) past sessions.

## 3) Workflow Session Numbering

1. On session create with `unit_id`:
   - compute `next = max(unit_session_number where class_id + unit_id) + 1`
   - assign to new session
2. Keep numbering stable once session exists.
3. Display numbering in calendar chips and workflow recent sessions.

## 4) Import Pipeline

## Phase A: Deterministic Imports

1. Parse ICS/CSV/XLSX to normalized rows.
2. Resolve class matching:
   - exact match
   - normalized match
   - manual mapping fallback
3. Validate conflicts:
   - same teacher overlapping times
   - same class overlapping times
   - malformed time ranges

## Phase B: Preview + Apply

1. `/import/preview` returns:
   - parsed rows
   - class matches
   - conflicts
   - proposed adds/removes/changes
2. `/import/apply` options:
   - `replace_future_from` date
   - `append_only`
   - `dry_run`

## Phase C: AI Scan Imports

1. Upload scanned PDF/image.
2. OCR + LLM outputs strict JSON:
   - class name
   - weekday
   - start/end time
   - subject (optional)
   - room (optional)
3. Attach confidence per row.
4. User review/edits before apply.
5. Store extraction artifact + audit.

## 5) API Surface (Proposed)

1. `GET /calendar/classes/{class_id}/week?date=YYYY-MM-DD`
2. `POST /calendar/classes/{class_id}/slots/create`
   - mode: `new_unit_start` | `continue_unit` | `generic`
3. `GET /holidays?year=YYYY&region=...`
4. `POST /holidays/import`
5. `POST /emploi/import/preview`
6. `POST /emploi/import/apply`
7. `GET /schedule/versions?teacher_id=...`
8. `POST /schedule/versions/{id}/activate`
9. `POST /schedule/versions/{id}/rollback`

## 6) Frontend UX Modules

1. Slot action menu (`+`) in calendar cell.
2. Modal: start new unit + first session.
3. Modal: continue existing unit + absent students.
4. Visual labels:
   - `Planned`
   - `In Progress`
   - `Done`
   - `Cancelled`
5. Holiday day badges and blocked interactions.
6. Import wizard:
   - upload
   - preview
   - fix mapping
   - apply
7. Schedule version timeline:
   - draft
   - active
   - archived
   - rollback

## 7) State and Integrity Rules

1. Past delivered sessions are immutable except controlled edits.
2. Future planned sessions can be regenerated.
3. New active version ends previous active version for future horizon.
4. Rule changes should not delete historical delivered evidence.

## 8) QA and Observability

1. Unit tests:
   - generation idempotency
   - holiday blocking + overrides
   - unit session numbering
2. Integration tests:
   - preview/apply import
   - version activation
   - slot quick actions
3. Metrics:
   - planned sessions generated
   - skipped by holiday
   - import conflict count
   - AI extraction confidence distribution

## 9) Practical Rollout

1. Release 1:
   - slot quick actions
   - unit session numbering
2. Release 2:
   - holiday model + blocking
   - deterministic import preview/apply
3. Release 3:
   - schedule versions + rollback
4. Release 4:
   - AI scan import with review
