# Calendar + Emploi Workflow TODO

Last updated: 2026-03-05 (implementation update: slot actions, session numbering, holidays, timetable preview/apply backend + class mapping UX + effective window presets + unit session timeline + ICS import support + planned timetable ghost slots + date-level timetable exceptions cancel/move)
Owner: Product + Engineering
Status: Proposed implementation roadmap

Simplification note (2026-03-05):
- Calendar session creation is now intentionally constrained to active workflow unit flow (`+` => continue active unit with checklist checks).
- Drag-create generic session blocks were removed from Calendar to avoid bypassing unit/session continuity.
- Calendar session detail now includes `Edit Attendance` for non-future sessions (updates absent/present directly from Calendar).
- Calendar `+` quick action and `Submit Past Session` now also capture optional absent students at creation time.

Related docs:
- `docs/roadmap/CALENDAR-EMPLOI-STRATEGY.md`
- `docs/roadmap/CALENDAR-EMPLOI-TECH-SPEC.md`

## Product Intent

Build a calendar workflow that matches the real teacher day:

1. Teacher opens first class session.
2. Teacher either:
   - starts a new unit, then starts session 1 of that unit, or
   - continues an existing unit and checks more checklist items.
3. System tracks progress by:
   - unit progress (checklist completion),
   - session sequence (session 1, 2, 3...) inside each unit,
   - class timeline (all sessions).
4. Calendar respects Morocco holidays and supports timetable imports/updates.

## Core Decisions (Locked)

- [ ] Keep one active unit per class at a time (already aligned with backend).
- [x] Introduce explicit unit session numbering (`unit_session_number`).
- [ ] Keep class-level calendar as source of truth for real delivered sessions.
- [ ] Add schedule versions for emploi changes instead of destructive rewrites.
- [ ] Use AI extraction only with a review/confirm step before applying.

## Teacher-Centric UX Flow (Target)

### A) Slot Quick Actions

- [x] Click `+` on any calendar slot opens quick action for active workflow unit:
  - `Continue Active Unit`
  - optional checklist checks
  - optional absent students
  - holiday override when date is blocked

### B) Start New Unit from Calendar Header Action

- [x] Modal fields:
  - unit type, unit title, optional planned hours, optional note
  - start date and session count
- [x] On confirm:
  - create unit
  - auto-plan workflow sessions linked to that unit
  - initialize `unit_session_number` from first created session

### C) Continue Existing Unit from Calendar

- [x] Modal fields:
  - select active/eligible unit
  - date/time prefilled
  - optional absent students
- [x] On confirm:
  - create workflow session with `unit_id`
  - auto increment `unit_session_number`
  - persist optional `absent_student_ids`

### D) Session + Unit Visibility

- [x] Calendar card shows:
  - unit title
  - `Session N` inside that unit
  - done/total checklist stats
- [x] Unit screen shows ordered session history:
  - `Session 1`, `Session 2`, ...
  - date/time and checked items count
  - shipped in Workflow as `Unit Session Timeline` (backed by `GET /workflow/units/{unit_id}/sessions`)

## Morocco Holidays (Blocked Days)

- [x] Add holiday source model:
  - `date`, `name`, `is_blocked`, optional `region`, optional `source`
- [x] Add yearly import/update endpoint for Morocco holidays.
- [x] Render holidays in calendar with blocked style and label.
- [x] Block slot creation by default on blocked days.
- [x] Add teacher/admin override UI: `Allow session on holiday`.
  - Calendar slot quick-action modal now exposes holiday override for workflow actions.

## Emploi du Temps Import and Sync

## Phase 1 (Reliable Inputs First)

- [x] Support ICS import (Google Calendar export).
- [x] Support CSV/XLSX import via strict template (preview API with row validation).
- [ ] Normalize input rows to:
  - teacher key
  - class name
  - subject
  - weekday
  - start/end time
  - room/group (optional)

## Phase 2 (Apply with Safety)

- [x] Preview screen before apply:
  - class matching
  - duplicate/conflict detection
  - ambiguous rows
- [ ] Apply mode options:
  - `replace future from date` (backend apply endpoint shipped)
  - `append new slots` (backend apply endpoint shipped)
  - `dry run only`
- [ ] Auto-create missing classes if user confirms.
- [x] Generate timetable rules for each class calendar (backend table + apply endpoint).

## Phase 3 (AI Import for Unstructured Files)

- [ ] Accept scanned PDF/image emploi upload.
- [ ] OCR + LLM extraction to strict JSON schema.
- [ ] Confidence flags on each extracted row.
- [ ] Manual review editor before apply.
- [ ] Persist original file + extraction audit trail.

## Emploi Change Management (Teacher Schedule Changes)

- [ ] Add `schedule_versions` per teacher/class set:
  - `effective_from`
  - `effective_to` (nullable)
  - `status` (`draft`, `active`, `archived`)
- [x] Add date-level timetable exceptions (cancel/move planned slot for one date) with undo.
- [ ] New import creates a new version, never rewrites history.
- [ ] On activation:
  - old version closes at `effective_from - 1 day`
  - only future planned slots update
  - past delivered sessions remain unchanged
- [ ] Add rollback to previous schedule version.

## Data Model and API TODO

## Backend

- [x] Add `unit_session_number` on sessions linked to workflow units.
- [x] Add helper to compute next session number per unit.
- [x] Add calendar slot action endpoint(s):
  - create new unit + first session in one transaction
  - create session for existing unit from slot
- [x] Add holidays read/update endpoints (`GET /workflow/holidays`, `PATCH /workflow/holidays/{id}`, seed endpoint).
- [x] Add calendar auto-plan endpoint (`POST /workflow/classes/{class_id}/auto-plan`) for one-click week loading and unit/exam session batching.
- [x] Add schedule version tables.
- [x] Add emploi import endpoint (ICS/CSV/XLSX) with preview/apply mode.
  - CSV/XLSX preview shipped: `POST /workflow/timetable/import/preview`.
  - ICS preview shipped: `POST /workflow/timetable/import/preview` (VEVENT + RRULE BYDAY support).
  - CSV/XLSX apply shipped: `POST /workflow/timetable/import/apply` (modes: dry-run/append/replace, supports `effective_from` + optional `effective_to`).
  - ICS apply shipped: `POST /workflow/timetable/import/apply`.
  - Date exception endpoints shipped:
    - `GET /workflow/classes/{class_id}/timetable-exceptions`
    - `POST /workflow/classes/{class_id}/timetable-exceptions`
    - `DELETE /workflow/timetable-exceptions/{exception_id}`
    - supports `exception_type: cancel | move` with target date/time for move
  - Class mapping endpoints shipped:
    - `GET /workflow/timetable/class-mappings`
    - `POST /workflow/timetable/class-mappings/bulk-save`
    - `PATCH /workflow/timetable/class-mappings/{id}`
    - `DELETE /workflow/timetable/class-mappings/{id}`
- [ ] Add apply endpoint with replace/append semantics.
- [ ] Add AI extraction endpoint for scanned emploi (review-first).

## Frontend

- [x] Add `+` quick-action UI in calendar slot.
- [x] Add unit/session creation modals for slot actions.
- [x] Add holiday rendering and blocking notices.
- [x] Render planned weekly ghost slots from timetable rules so weeks appear auto-filled before delivery.
- [x] Add one-click `Load Week Plan` action to materialize planned weekly slots into real calendar sessions.
- [x] Add `Plan Unit / Exam` flow (choose unit type + title + session count) to auto-place upcoming sessions on valid timetable slots.
- [x] Add Unit Setup auto-plan toggle so creating a unit/exercise series can immediately generate timetable sessions by count.
- [x] Add active-unit planning preview (`dry_run`) before applying session creation from emploi.
- [x] Add planned-slot controls to skip/undo a specific date directly from calendar.
- [x] Add week exceptions panel (filter + edit + delete + conflict warning) to manage cancel/move overrides in one place.
  - move conflicts now hard-block in frontend and backend unless teacher explicitly sends `allow_overlap: true`.
- [x] Add timetable import wizard:
  - upload (shipped in Calendar modal)
  - parse preview (shipped)
  - mapping fixes (class resolution + create missing classes toggle + unresolved class mapping selector + saved alias reuse + saved alias inline manage + fuzzy suggestions + confidence filters + bulk apply high suggestions + undo auto-apply + save mappings now + save reviewed only + review queue navigation + keyboard shortcuts shipped)
  - effective window controls (`effective_from` + optional `effective_to` + open-ended toggle + presets: `This Term` / `School Year` / `Open-Ended`) shipped
  - wizard flow header (Preview -> Map -> Save -> Apply) with live status counters shipped
  - apply (dry-run/append/replace shipped)
  - UX diagnostics (preview/apply filters + search + action highlighting shipped)
- [x] Add schedule version history UI:
  - activate
  - compare
  - rollback

## Testing and QA TODO

- [ ] Unit tests:
  - session numbering per unit
  - holiday block/override
  - [x] schedule version activation and rollback
- [ ] Integration tests:
  - slot `+` flows
  - start new unit + session 1
  - continue unit increments session number
  - import preview/apply conflict handling
- [x] UI smoke checks:
  - `btn-checklist-expand-all`
  - slot action menu buttons
  - blocked holiday slot behavior
  - implemented in `frontend/scripts/ui-smoke.mjs`
- [ ] Performance tests for large timetable imports.

## Delivery Sequence (Best Road)

1. Slot `+` workflow actions for new/continue unit (highest day-to-day value).
2. Unit session numbering and display (`Session N`) in calendar + workflow views.
3. Morocco holiday blocking + override.
4. ICS/CSV/XLSX import wizard with preview and safe apply.
5. Schedule versioning and rollback for emploi changes.
6. AI extraction for scanned emploi as optional advanced path.

## Why This Order

- It ships immediate teacher value first.
- It avoids AI-first fragility for core scheduling.
- It preserves history when schedules change.
- It keeps imports deterministic and auditable before adding AI automation.
