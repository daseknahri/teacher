# Coolify + NotebookLM Deployment

This app can run on Coolify with NotebookLM enabled, but the important part is that NotebookLM authentication must survive redeploys.

## Recommended approach

Use NotebookLM in production only after the app is already deployed and stable.

Why:
- the app now has fallback behavior if NotebookLM is unavailable
- NotebookLM auth is file-based and must be persisted
- Coolify redeploys are safe only when the auth file lives on persistent storage

## Coolify app setup

Deploy from the repo using the existing Dockerfile:
- build context: repo root
- dockerfile: `backend/Dockerfile`

Expose:
- port `8000`

## Persistent storage

Add these persistent mounts in Coolify:

1. App storage
- mount path: `/app/storage`

2. NotebookLM auth storage
- mount path: `/data/notebooklm`

The second mount is the key requirement for NotebookLM.

## Production environment variables

Set these in Coolify:

```env
DATABASE_URL=postgresql+psycopg://teacher:teacher@postgres:5432/teacher_progress
STORAGE_DIR=/app/storage

UNIT_PLANNER_PROVIDER=notebooklm
SESSION_WRITER_PROVIDER=notebooklm

NOTEBOOKLM_HOME=/data/notebooklm
NOTEBOOKLM_PROFILE=default
NOTEBOOKLM_TIMEOUT_SECONDS=45
NOTEBOOKLM_KEEPALIVE_SECONDS=0
NOTEBOOKLM_NOTEBOOK_PREFIX=Teacher Progress -
```

Optional if you still want OpenAI available as fallback elsewhere:

```env
OPENAI_API_KEY=your_key
OPENAI_MODEL=gpt-4o-mini
```

## First-time NotebookLM authentication

Do not try to perform the Google login inside the server container.

Use this flow instead:

1. On your local machine, install backend requirements.
2. Install the browser dependency NotebookLM uses for login:

```bash
python -m pip install playwright
python -m playwright install chromium
```

3. Run:

```bash
python -m notebooklm login
```

4. Sign in to the Google account that can access NotebookLM.
5. Locate the generated auth file:

Windows:

```text
%USERPROFILE%\.notebooklm\profiles\default\storage_state.json
```

6. Open the deployed app.
7. Log in as owner.
8. Open `Owner Panel` -> `NotebookLM Setup`.
9. Click `Upload Auth File`.
10. Upload the local `storage_state.json`.
11. Click `Refresh Status`.

You want the status card to show:
- `Package Installed`
- `Ready`

## What the status card verifies

The app now checks:
- NotebookLM package installed
- active profile name
- auth file path
- auth file exists
- auth file structure is valid
- whether a NotebookLM context file is present

## Rotation / replacement

If NotebookLM stops working later:
1. authenticate again locally
2. generate a fresh `storage_state.json`
3. upload it again from the Owner panel

You can also use `Clear Auth` in the Owner panel to remove the saved NotebookLM auth file from the deployment.

## Safer rollout option

If you want a staged rollout:

```env
UNIT_PLANNER_PROVIDER=openai
SESSION_WRITER_PROVIDER=fallback
```

Then switch to NotebookLM after the Owner panel reports `Ready`.
