# Grimoire Wizard Angular frontend

The Angular application is a separate frontend beside the Streamlit fallback.
It uses the FastAPI backend and does not change or replace the Streamlit app.

## Requirements

- Node.js and npm
- The backend running at `http://127.0.0.1:8000`
- Supabase migrations applied and backend credentials configured for the API

The development server uses port `5173`, which is in the backend's default CORS
allowlist.

## Run locally

From `frontend-angular/`:

```powershell
npm ci
npm start
```

Open `http://localhost:5173`. The initial API URL is configured in
`src/environments/environment.ts`. You can also change the API URL in
**API connection** in the app; that override is saved only in the current
browser.

## Features

- Conversation history and reopenable conversations
- PDF upload to start or add to a conversation
- Conversation-attached sources and an attach-from-library picker
- Fetch-based SSE streaming with status updates, animation-frame token
  batching, cancel, and retry controls
- Sanitized Markdown rendering
- Clickable page citations and a lazily loaded PDF.js side panel that draws
  available citation bounding boxes
- Responsive layout, standalone OnPush components, and a lazy workspace route

## Backend support and remaining work

The backend now provides `GET /documents`, `GET /documents/{id}`, and
`GET /documents/{id}/file`. New uploads are stored in the private Supabase
Storage bucket; the file endpoint returns a short-lived signed URL. Apply the
new documents-and-storage migration before using these features. Documents
indexed before Storage was added remain in the library but need to be uploaded
again to enable PDF previews.

The backend does not yet persist citation bounding boxes. The viewer can open
stored PDFs and navigate to cited pages, but passage highlighting requires the
planned bounding-box ingestion and citation changes.

## Production build and Firebase Hosting

Set the production API URL in `src/environments/environment.prod.ts`, then
build:

```powershell
npm run build
```

The Firebase Hosting configuration serves `dist/frontend-angular/browser`,
uses SPA route fallback, avoids caching `index.html`, and caches hashed assets
for one year. Firebase Hosting serves compressed static assets automatically.
Deploy from this directory after selecting the Firebase project:

```powershell
firebase deploy --only hosting
```

The production backend's `API_CORS_ORIGINS` must include the Firebase Hosting
origin. The app does not yet include sign-in; keep it on a trusted network
until backend authentication and per-user isolation are implemented. Streamlit
remains the default until the performance go/no-go measurements in
[`DECISIONS.md`](../project_decisions/DECISIONS.md) pass.

## Checks

```powershell
npm test -- --watch=false
npm run build
```
