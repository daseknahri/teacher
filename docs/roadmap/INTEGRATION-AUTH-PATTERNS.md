# Integration Auth Patterns

Last updated: 2026-05-17

This note preserves the integration strategy we worked out while connecting NotebookLM to the Teacher Progress app. It is meant to be reused in future projects when we need to connect to AI tools, social tools, content platforms, or browser-only services.

The core question is not just "can we connect to the platform?" It is:

- How stable is the connection method?
- How much of the user experience can we hide cleanly?
- Where should secrets and session state live?
- What happens when auth expires?
- How do we keep cost and operational risk under control?

## Four Integration Modes

### 1. Official API mode

Use this when the provider offers a real API with documented authentication.

Examples:
- Gemini API
- OpenAI API
- Meta Graph API
- Stripe API

Typical auth:
- API key
- OAuth access token + refresh token
- service account / cloud auth

Recommended architecture:
- frontend collects the user input
- backend stores the secrets
- backend calls the provider
- backend handles retries, rate limiting, logging, cost control

Why this is the best mode:
- stable
- scalable
- easier to monitor
- easier to automate
- safer than browser-session reuse

Use this by default whenever it exists.

### 2. OAuth mode

Use this when the platform supports user authorization but the token must be tied to a real user account.

Examples:
- Google Workspace APIs
- Microsoft Graph
- many social/media APIs

Typical auth:
- user grants consent
- backend stores refresh token securely
- backend refreshes access token automatically

Recommended architecture:
- frontend starts the consent flow
- backend receives callback
- backend stores refresh token
- backend refreshes access token server-side

Why this is good:
- near-automatic after first setup
- real user consent
- no need to re-login frequently if refresh token stays valid

### 3. Restored-session mode

Use this when the platform does not give a proper developer auth flow, but a browser login can be saved and replayed.

Examples:
- NotebookLM consumer workflow with `storage_state.json`
- internal browser-only tools without a public API

Typical auth:
- local browser login
- save browser session state
- upload session state to backend
- backend uses that state until it expires

Recommended architecture:
- local helper handles the browser login
- backend stores the uploaded auth state in persistent storage
- backend monitors whether auth is still healthy
- app shows `refresh required` when needed

Why this is acceptable:
- workable for internal tools
- can feel smooth if the refresh flow is reduced to one click

Main weakness:
- cookies expire
- not as reliable as real OAuth or official APIs

### 4. Browser-automation mode

Use this only when there is no official API and no durable auth pattern that can be reused safely.

Examples:
- automating a consumer website with Playwright
- internal dashboard scraping

Typical auth:
- browser automation
- DOM actions
- fragile selectors

Recommended architecture:
- keep it isolated
- treat it as a last resort
- build strong observability and failure handling

Main weakness:
- high maintenance
- changes in UI can break everything
- usually not a good foundation for production growth

## Decision Order

When evaluating any new integration, follow this order:

1. If there is an official API, use it.
2. If there is no simple API but there is OAuth, use backend OAuth.
3. If there is no real API but restored browser session is possible, use restored-session mode.
4. If the only path is website automation, treat it as a last resort.

This order avoids building fragile systems when a cleaner option exists.

## Frontend vs Backend Responsibilities

### Frontend should do

- collect prompts, files, and settings
- show status
- show previews
- show failures in a clean way
- trigger local helper download or consent flow

### Backend should do

- store secrets or session state
- call providers
- handle retries
- handle rate limiting
- track errors
- track quota / cost
- decide whether auth needs refresh

Why:
- frontend improves UX
- backend improves reliability

Frontend should not be trusted with long-lived secrets.

## NotebookLM Pattern We Used

NotebookLM consumer access does not behave like a normal developer API. So we used restored-session mode.

### Current shape

1. Owner authenticates NotebookLM locally.
2. Local session is stored in `storage_state.json`.
3. App uploads the auth file to persistent server storage.
4. Backend uses that auth file for NotebookLM requests.
5. Owner panel runs smoke tests and shows auth health.
6. When auth becomes stale, owner refreshes it with a helper.

### Why this is the right compromise

- no fake silent browser login on the server
- no repeated manual upload required once the helper exists
- operationally understandable
- good enough for internal app usage

## "Can the app open cmd itself?"

In normal browser security, not cleanly.

A web app should not directly start local terminal commands on the user's machine without a local installed helper or protocol handler. The clean alternative is:

1. app prepares a local helper
2. user downloads it
3. user double-clicks it
4. helper runs login and upload flow

This is why the current approach uses a downloadable Windows helper script.

## Near One-Click Pattern

If the provider requires local browser login, the clean UX is:

1. user clicks `Prepare Refresh` or `Download Refresh Helper`
2. app creates a short-lived token
3. user downloads and runs the helper locally
4. helper opens the browser login
5. helper uploads auth back to the app
6. helper runs smoke test
7. app shows healthy status

This keeps the technical work mostly hidden while staying within browser security boundaries.

## Cost and Quota Strategy

Do not build around multiple personal accounts to expand quota or bypass product limits.

Why this is a bad base:
- fragile
- hard to monitor
- hard to audit
- often against platform rules
- difficult to scale cleanly

Better options:
- use official paid API
- support multiple providers
- cache outputs
- queue long-running jobs
- let advanced users bring their own API key
- reduce unnecessary generation through templates and reuse

## Provider-Specific Notes

### Gemini for image generation

Preferred mode:
- official API mode

Why:
- much cleaner than restored browser auth
- natural backend integration
- easier to generate blog images on demand without copy-pasting prompts

Recommended shape:
- frontend sends prompt
- backend calls Gemini or image API
- backend stores or returns generated image
- optionally cache results by prompt/template

### NotebookLM

Preferred mode:
- restored-session mode for consumer NotebookLM
- official API mode if NotebookLM Enterprise / official Google API is the target later

Why:
- consumer NotebookLM does not currently fit the normal API-key model we want

### Facebook groups or other social posting

Preferred mode:
- official API / OAuth if the exact publishing flow is allowed

Avoid:
- trying to bypass missing permissions with browser-session hacks unless it is an internal supervised tool and risk is accepted

Social platforms change rules often. A browser-session shortcut can become brittle quickly.

## What We Win From Backend-Centered Integrations

- less user friction after first setup
- better reliability
- easier monitoring
- stronger cost control
- cleaner retry logic
- safer secrets handling

The frontend still matters a lot, but mainly for:
- usability
- visibility
- reducing anxiety
- guiding the user through setup

## What Makes an Integration Feel "Clean"

An integration feels clean when:

- setup is guided
- auth state is visible
- failures are explained
- refresh can be done quickly
- user does not need to repeat technical steps
- the system does not silently degrade without warning

That is why the app now has:
- smoke test
- auth health
- refresh-required warning
- downloadable refresh helper

## Reusable Checklist For New Integrations

Before building a new integration, answer these:

1. Is there an official API?
2. Is there OAuth with refresh tokens?
3. If not, can browser session state be reused safely?
4. Where will auth live?
5. How will expired auth be detected?
6. What is the refresh UX?
7. What is the cost model?
8. What is the rate limit model?
9. Can the system fail safely?
10. How much of the technical flow can be hidden without becoming opaque?

## Recommended Default Choices

For future projects:

- Prefer official API mode.
- Use OAuth mode when user consent is required.
- Use restored-session mode only when the platform does not give a better path.
- Use browser automation only as a last resort.

For internal admin UX:

- always include a health check
- always show last success / last failure
- always provide a refresh path
- never hide failures completely

That balance gives the best mix of usability and reliability.
