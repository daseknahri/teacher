# Production Env Checklist and Secret Rotation Plan

## Environment Variables (Required)

- `DATABASE_URL` points to managed PostgreSQL (not local sqlite).
- `STORAGE_DIR` points to persistent volume.
- `OPENAI_API_KEY` set for AI extraction.
- `OPENAI_MODEL` set and validated.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL` set.
- `SMTP_USE_SSL` / `SMTP_USE_STARTTLS` validated.
- `AUTH_TOKEN_TTL_HOURS` reviewed for policy.
- `LOG_LEVEL`, `LOG_JSON`, `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT` set.
- Alerting configured (recommended):
  - `ALERT_WEBHOOK_URL` and/or `ALERT_EMAIL_TO`
  - `ALERT_SLOW_MS`, `ALERT_MIN_INTERVAL_SECONDS`
- `PRINCIPAL_EXPORT_TEMPLATE` set if official NotesCC rendering is required.

## Pre-Go-Live Validation

- Owner account login works.
- Teacher account creation + invite email works.
- Class creation/import/session submit/exam import/export flows validated.
- Backup script test completed:
  - `infra/db/backup.ps1`
  - `infra/db/restore.ps1` in staging
- `storage/logs/app.log` receives JSON request logs.
- App health endpoint responds: `GET /health`.

## Secret Rotation Plan

- Rotate `OPENAI_API_KEY` every 90 days or on incident.
- Rotate SMTP credentials every 90 days or on incident.
- Rotate DB password every 90 days (staging first, then production).
- Rotate owner bootstrap password immediately after deployment and every 90 days.
- Revoke old credentials immediately after successful rotation.

## Rotation Procedure

1. Generate new secret in provider.
2. Update secret in deployment environment.
3. Restart app container.
4. Run smoke test:
   - `POST /auth/login`
   - one invite email send
   - one screenshot extraction
5. Revoke old secret.
6. Record date and operator in change log.

## Incident Response (Secret Leak)

1. Disable leaked credential at provider immediately.
2. Rotate credential and redeploy.
3. Force owner and affected teacher password reset.
4. Review `storage/logs/app.log` and audit endpoints for suspicious usage.
5. Export incident report and remediation timeline.
