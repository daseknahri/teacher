# Database Operations (PowerShell)

These scripts target the Docker PostgreSQL service (`teacher-progress-db`).

## 1) Create Backup

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\db\backup.ps1
```

Optional parameters:
- `-DbContainer teacher-progress-db`
- `-DbName teacher_progress`
- `-DbUser teacher`
- `-OutputDir .\storage\backups`

## 2) Restore Backup

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\db\restore.ps1 -InputFile .\storage\backups\backup_teacher_progress_YYYYMMDD_HHMMSS.sql
```

Optional:
- `-ResetSchema` to clear `public` schema before restoring.

## 3) Schedule Daily Backups (Windows Task Scheduler)

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\db\schedule-daily-backup.ps1 -At 22:00
```

This registers a task named `TeacherProgressDailyBackup`.
