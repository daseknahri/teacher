# Calendar + Emploi Strategy (Teacher-First)

Last updated: 2026-03-04
Status: Agreed product direction

## Why This Matters

Teachers need a workflow that matches real school life:

1. Start the day and see planned sessions already in the weekly calendar.
2. Open a slot and either:
   - start a new unit and begin session 1, or
   - continue an existing unit and check more items.
3. Keep progress visible by both:
   - unit completion (checklist progress),
   - session sequence (Session 1, Session 2, ...),
   - delivered vs planned for the week.
4. Adapt quickly when timetable changes during the year.

## Best-Practice Pattern (Used by mature scheduling apps)

Do not pre-store the whole year as fixed manual sessions.

Use this layered model:

1. Timetable rules (recurrence): weekly emploi structure.
2. Planned sessions: generated from rules for a rolling window.
3. Delivered sessions: what actually happened in class.
4. Exceptions: one-off changes (move/cancel/override).
5. Versioned schedules: new emploi activates from an effective date.

This keeps UX fast, history safe, and change management clean.

## Recommended User Experience

### Calendar Slot Actions (`+`)

- `Start New Unit + Start Session`
- `Continue Existing Unit`
- `Create Generic Session`

### Unit-Session Tracking

- Every workflow-linked session gets `unit_session_number`.
- Calendar card displays `Session N` for that unit.
- Unit view shows ordered session history and checklist progress.

### Holidays (Morocco)

- Holiday days shown and blocked by default.
- Optional override (`Allow session on holiday`) for exceptional cases.

### Emploi Import

Preferred order:

1. ICS (Google Calendar export) and CSV/XLSX template.
2. Review + conflict preview before applying.
3. AI extraction for scanned PDF/image as reviewed workflow only.

## Handling Timetable Changes

When teacher receives a new emploi:

1. Import as a new draft schedule version.
2. Compare diff with active version.
3. Activate with `effective_from`.
4. Regenerate future planned sessions only.
5. Keep past delivered sessions unchanged.

## Delivery Order (Best Feasible Road)

1. Calendar slot quick actions for `new unit` / `continue unit`.
2. Unit session numbering + display in workflow/calendar.
3. Morocco holiday blocking + override.
4. ICS/CSV/XLSX import wizard with preview/apply.
5. Schedule versioning + rollback.
6. AI scanned-emploi extraction with review and confirm.

## Why This Is the Best Road

- Fast immediate value for teachers.
- Deterministic and auditable before AI automation.
- Preserves historical truth.
- Supports ongoing timetable changes without data corruption.
