# Coolify App Setup

This project is ready to deploy on Coolify from:

- Repo: `https://github.com/daseknahri/teacher.git`
- Domain: `teacher.ibnbatoutaweb.com`

This guide assumes:
- you already use Coolify
- you want a separate PostgreSQL service, not the local compose Postgres
- you want NotebookLM available in production

## 1. Create the application in Coolify

Create a new application from GitHub:

- Repository: `daseknahri/teacher`
- Branch: your production branch
- Build pack: `Dockerfile`
- Dockerfile location: `backend/Dockerfile`
- Port: `8000`

## 2. Set the public domain

Add this domain:

- `teacher.ibnbatoutaweb.com`

Recommended health endpoint:

- `/health`

## 3. Add persistent volumes

Add these two persistent mounts:

1. App storage
- Mount path: `/app/storage`

2. NotebookLM storage
- Mount path: `/data/notebooklm`

Why:
- `/app/storage` keeps uploads, exports, logs
- `/data/notebooklm` keeps NotebookLM auth across redeploys

## 4. Provision PostgreSQL separately

Create a separate PostgreSQL service in Coolify.

Then copy its connection string into the app as:

```env
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:PORT/DBNAME
```

Do not use the local `docker-compose.yml` Postgres service for Coolify production.

## 5. App environment variables

Set these in the Coolify app:

```env
STORAGE_DIR=/app/storage

UNIT_PLANNER_PROVIDER=notebooklm
SESSION_WRITER_PROVIDER=notebooklm

NOTEBOOKLM_HOME=/data/notebooklm
NOTEBOOKLM_PROFILE=default
NOTEBOOKLM_TIMEOUT_SECONDS=45
NOTEBOOKLM_KEEPALIVE_SECONDS=0
NOTEBOOKLM_NOTEBOOK_PREFIX=Teacher Progress -

OCR_LANG=fra+eng
LOG_LEVEL=INFO
LOG_JSON=true
```

Optional if you still want OpenAI available for fallback/testing:

```env
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o-mini
OPENAI_TIMEOUT_SECONDS=30
```

Optional SMTP:

```env
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=
SMTP_USE_SSL=false
SMTP_USE_STARTTLS=true
```

## 6. First deployment

Deploy the app once before worrying about NotebookLM auth.

After deploy, confirm:

- `https://teacher.ibnbatoutaweb.com/health`
- `https://teacher.ibnbatoutaweb.com/app`

## 7. NotebookLM authentication for production

Do not try to perform the Google login in the production container.

Instead:

1. On your Windows machine:

```powershell
cd C:\Users\user\text\backend
python -m pip install -r requirements.txt
python -m notebooklm login
```

2. Complete the Google / NotebookLM login in the browser.

3. Find the generated file:

```text
%USERPROFILE%\.notebooklm\profiles\default\storage_state.json
```

4. Open the deployed app.

5. Log in as owner.

6. Go to:

- `Owner Panel`
- `NotebookLM Setup`

7. Click:

- `Upload Auth File`

8. Upload your local `storage_state.json`

9. Click:

- `Refresh Status`

Expected result:

- `Package Installed`
- `Ready`

## 8. If NotebookLM expires later

Repeat only the local auth step:

1. Run `python -m notebooklm login` again on your own machine
2. Get a fresh `storage_state.json`
3. Upload it again from the Owner panel

## 9. Production sanity checklist

Before going live, verify:

- login works
- owner panel loads
- roster import works
- class workflow loads
- a unit PDF can be uploaded
- NotebookLM status shows `Ready`
- session confirm generates write-up
- PDF export works

## 10. If you want a safer staged rollout

You can deploy first with:

```env
UNIT_PLANNER_PROVIDER=openai
SESSION_WRITER_PROVIDER=fallback
```

Then switch to NotebookLM after the auth upload is working.
