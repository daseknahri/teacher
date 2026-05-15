# Future TODO (Post-Revision Backlog)

Last updated: 2026-03-03

This file is the forward backlog after the current implementation baseline.

## P0 - Must Do Before Production

- [ ] Add DB migrations with Alembic and stop relying on runtime schema patching.
- [ ] Add optimistic locking/versioning on session updates to prevent concurrent overwrite.
- [ ] Add owner self-service password reset flow (email token or secure reset path).
- [ ] Add configurable retention policy + scheduled cleanup for uploads/exports/logs.
- [ ] Add integration tests for owner-teacher permission boundaries.

## P1 - AI and Workflow Quality

- [ ] Add per-checklist-item confidence score in AI output.
- [ ] Add explicit extraction review state (pending/approved/rejected) before checklist becomes active.
- [ ] Add teacher feedback controls (`wrong split`, `wrong heading`, `missing item`) linked to unit and file.
- [ ] Build benchmark dataset from real school PDFs and expected checklist structures.
- [ ] Improve French math heading parser for edge cases (numberless sections, mixed typography).

## P1 - UX and Mobile Redesign Support

- [ ] Split current single-file frontend into modular components (views + state + API layer).
- [ ] Introduce a consistent design token system (spacing/type/color/interaction states).
- [ ] Replace dense list layouts with mobile-first session actions and sticky controls.
- [ ] Add keyboard and accessibility pass (`tab`, ARIA labels, contrast).
- [ ] Add loading skeletons and explicit empty states for every major panel.

## P1 - Reporting and Admin Reliability

- [ ] Add scheduled weekly export package per class.
- [ ] Add email delivery for report exports (PDF/Excel) with queue + retries.
- [ ] Add signed URL expiration and download audit details per export file.
- [ ] Add stricter template validation and preview for official notes export.

## P2 - QA and Release Engineering

- [ ] Add Playwright E2E flows (owner bootstrap, teacher workflow, exam import/export).
- [ ] Add performance/load scenarios for 50-60 students and long session histories.
- [ ] Add CI pipeline gate with lint, tests, and smoke checks before release.
- [ ] Add staging seed scripts and deterministic demo data.

## P2 - Integrations

- [ ] Add SIS webhook/API integration layer.
- [ ] Add CSV import adapters for schools without standard Excel templates.
- [ ] Add calendar sync export (ICS) for teacher schedules.

## Ready For Next Testing Round

- [ ] Bootstrap owner and create one teacher account from UI.
- [ ] Create class, import roster, and assign teacher.
- [ ] Start chapter unit with a real PDF and validate generated checklist quality.
- [ ] Run two sessions on same day and verify timeline ordering by time.
- [ ] Edit one past session and confirm attendance/todo/time are updated correctly.
- [ ] Import exam sheet and export official notes Excel.
- [ ] Generate full class PDF and review formatting consistency.
