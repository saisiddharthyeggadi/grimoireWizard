# grimoireWizard: Decisions and Build Guide

Audience: the project owner (human) and any LLM coding agent working in this repo.
Last updated: 2026-11-16 (revised after reviewing `implemented_summary.md`).

---

## 0. How to read this file (LLM agents: follow this section first)

Every decision carries one status tag:

| Tag | Meaning | What you must do |
|---|---|---|
| **[DECIDED]** | Fixed by the owner. | Treat as a hard constraint. Never change it without being asked. |
| **[IMPLEMENTED]** | Already built and working in the repo. | Do not rebuild it. Extend it only with additive changes. |
| **[PLANNED]** | The owner's stated plan, not yet built. | Build toward it. Raise concerns before deviating. |
| **[RECOMMENDED]** | A default suggested during design review. Not yet confirmed by the owner. | Use it unless the owner says otherwise. Mention it in your summary so it can be confirmed. |
| **[OPEN]** | Not decided. | **Ask the owner before implementing.** Do not pick silently. |

Working rules:
1. Do not invent requirements. If something is not in this file, ask.
2. Make small, reviewable changes. Every change that touches data access needs tests.
3. **Never edit, move, or delete the Streamlit frontend** (see section 6.1). It is the fallback.
4. **Backend API changes must be additive only** (new endpoints, new optional fields). Never rename or remove anything the Streamlit app uses.
5. Never put secrets in code, logs, or the frontend (see section 9).
6. Never log PDF contents or full prompts.
7. Ingestion logic lives in one shared library used by both the CLI and the API. Do not duplicate it.

---

## 1. Product summary

grimoireWizard is a chat app for asking questions about English PDF documents.

- The user starts a conversation and attaches one or more PDFs.
- Attached PDFs stay attached when the conversation is reopened later.
- The user asks questions and gets streamed answers grounded in the PDFs, with citations.
- Target experience (Angular frontend): clicking a page citation opens the PDF in a side panel at the source passage.
- Target auth: Google sign-in.

**Honest status:** a working MVP exists (Python backend + Streamlit frontend). It is suitable for local development, internal testing, and a private pilot. It is **not** suitable for public production or production data until the pre-launch checklist (section 10) is complete. Describe it that way in the README and in any portfolio material.

---

## 2. Current state (what exists today)

Two deployable parts:
- **Backend:** Python, FastAPI, PDF ingestion pipeline plus conversation API. Migrations live in `backend/supabase/migrations/`.
- **Frontend:** Streamlit chat UI (**[IMPLEMENTED]**, kept as fallback).

### Ingestion **[IMPLEMENTED]**
- Accepts a PDF from the `grimoire-ingest` CLI or the API; validates file type and size.
- Extracts markdown page by page (PyMuPDF4LLM); splits into paragraphs and chunks; detects chapter boundaries and paragraph metadata.
- Embeds chunks with `sentence-transformers/all-MiniLM-L6-v2` (384-dim).
- Stores vectors and metadata in Supabase `public.document_chunks` (pgvector).
- Deduplicates deterministically by PDF content hash; removes stale trailing chunks on re-ingest.
- Configurable chunking: similarity threshold, max chunk word count, overlap between adjacent chunks.

### Persistence **[IMPLEMENTED]**
Tables: `documents`, `document_chunks`, `conversations`, `conversation_documents`, `messages` (with citations). The backend uses the Supabase **service-role key**, server-side only. The documents table stores metadata and Storage paths; legacy indexed documents are backfilled without a stored PDF.

### API **[IMPLEMENTED]** (11 endpoints)
`GET /health`, `POST /documents` (upload, store, and ingest), `GET /documents`, `GET /documents/{id}`, `GET /documents/{id}/file`, `POST /conversations`, `GET /conversations` (paginated), `GET /conversations/{id}`, `GET /conversations/{id}/messages`, `POST /conversations/{id}/documents` (attach), and `POST /conversations/{id}/messages` (streams over SSE).

SSE events: `status`, `token`, `citations`, `done`, `error`.

### RAG pipeline **[IMPLEMENTED]** (not yet evaluated)
1. Rewrite the question into a concise search query.
2. Embed the rewritten query.
3. Search only the documents attached to the conversation, using vector similarity plus full-text ranking.
4. Rerank and assemble context from the best chunks.
5. Send excerpts plus the original question to **Gemini via the OpenAI-compatible endpoint**; stream the answer.
6. Citations include document, page, snippet, and a bounding-box field (currently empty until bbox extraction is implemented).

### Streamlit frontend **[IMPLEMENTED]**
Backend URL entry, health check, create/list/reopen conversations, upload a PDF to start a conversation, attach previously indexed documents by UUID, chat, citations in a source expander.

### Not built yet
Authentication and authorization, per-user isolation, production deployment config, monitoring/logging/alerting, hardened secret management, evaluation results, and citation bounding-box extraction/highlighting. The Angular MVP and PDF side-panel shell exist; Angular's performance gate has not been measured.

---

## 3. Decisions

### 3.1 Scope and models

| ID | Decision | Status |
|---|---|---|
| D1 | Documents and questions are **English only**. | **[DECIDED]** |
| D2 | **One fixed embedding model and one fixed LLM.** No per-conversation or per-user model switching. | **[DECIDED]** |
| D3 | Embedding model is `all-MiniLM-L6-v2` (384-dim). Max chunk size must stay under the model's ~256 word-piece input limit, or text is silently truncated (check the current max-word and overlap settings; add a test). | **[IMPLEMENTED]**, limit check **[RECOMMENDED]** |
| D4 | LLM is **Gemini via the OpenAI-compatible endpoint**. Record the exact model name from the backend config in the README. | **[IMPLEMENTED]** |
| D5 | Scanned or image-only PDFs are unsupported in v1. Return an `unsupported_pdf` error with a clear message. OCR is a later feature. | **[RECOMMENDED]** |

### 3.2 Architecture

| ID | Decision | Status |
|---|---|---|
| D6 | Stack: Python backend, Supabase (Postgres + pgvector, Auth, and Storage). | **[IMPLEMENTED]** (Auth **[PLANNED]**) |
| D7 | Backend framework is **FastAPI** with an OpenAPI spec. | **[IMPLEMENTED]** |
| D8 | Answers stream over **SSE**. The Angular client reads it with `fetch` plus a stream reader (not `EventSource`, which cannot send an `Authorization` header or use POST). | **[IMPLEMENTED]** (server), **[RECOMMENDED]** (client approach) |
| D9 | **Two frontends coexist.** Streamlit stays untouched as the fallback. Angular is built in a separate sibling folder. Both use the same backend API. | **[DECIDED]** |
| D10 | Angular is adopted as the primary frontend **only if it does not slow rendering** compared with Streamlit (go/no-go gate in section 6.3). | **[DECIDED]** |
| D11 | Ingestion should become a background task: `POST /documents` returns immediately and the UI polls status. Today it appears to ingest within the request (confirm in code). | **[RECOMMENDED]** |

### 3.3 Auth and security

| ID | Decision | Status |
|---|---|---|
| D12 | Sign-in is **Google**. | **[DECIDED]** |
| D13 | Use **Supabase Auth** with the Google provider. The frontend gets a JWT and sends `Authorization: Bearer`. FastAPI verifies it on every request. | **[CODE IMPLEMENTED; PROVIDER SETUP PENDING]** |
| D14 | Roles: only `user` and `admin`, in a `profiles` table. | **[MIGRATION WRITTEN; APPLICATION PENDING]** |
| D15 | Per-user isolation uses **two layers**: `user_id` columns plus Postgres RLS on every table, and storage policies scoped by user path. | **[IMPLEMENTED IN MIGRATION; STAGING TEST PENDING]** |
| D16 | The backend queries Supabase **as the user** (their JWT) so RLS applies. Vector search is an RPC function that respects RLS. The service-role key is used only for background ingestion. | **[IMPLEMENTED]** |
| D17 | Document uniqueness is per user: unique on `(user_id, sha256)`, with the document ID derived from `user_id + sha256`. (Today the ID comes from the hash alone, which would collide across users and leak that another user has the same file.) Fix **before ingesting real data**. | **[IMPLEMENTED]** |
| D18 | Google OAuth consent screen set to "In production" (basic scopes only: openid, email, profile). | **[RECOMMENDED]** |
| D19 | **Streamlit under auth:** add an `AUTH_MODE=off\|on` flag to the backend. Streamlit works with auth off (local/private pilot). With auth on, Streamlit would need to send a token and is otherwise not supported. Production runs with auth on and serves Angular. | **[RECOMMENDED]** |
| D20 | Launch invite-only (email allowlist) or open to any Google account. | **Open Google sign-up** |

### 3.4 Retrieval and generation

All four steps below are built. The open job is to **measure** them (section 8), not to build them.

| Step | Component | Status |
|---|---|---|
| R0 | Vector retrieval, filtered to the conversation's attached documents. | **[IMPLEMENTED]** |
| R1 | Hybrid search: vector similarity plus full-text ranking. (Confirm the merge method, ideally Reciprocal Rank Fusion in one SQL function.) | **[IMPLEMENTED]** |
| R2 | Reranking before context assembly. **Document in the README what reranker is used** (local cross-encoder or hosted API) and the candidate/keep counts. | **[IMPLEMENTED]**, details **[OPEN]** |
| R3 | Query rewrite into a concise search query. Confirm it uses chat history for follow-ups ("what about the second one?") and is skipped on the first message. | **[IMPLEMENTED]**, history use to confirm |
| R4 | A separate "query understanding" step. Defer; add only if evals show a gain. | **[RECOMMENDED]** (defer) |

Generation rules:
- Prompt = fixed instruction + raw question + reranked chunks with metadata. Do not embed the instruction. Do not pass embeddings to the LLM.
- Answer only from retrieved context, cite pages, and say "not found in the document" instead of guessing. Test this path in the eval.
- Keep the semantic chunker, but keep a simple recursive chunker as a baseline and compare them in the eval.

### 3.5 Citations

- Today citations carry document, page, and snippet **[IMPLEMENTED]**.
- For the Angular side-panel highlight, add `bboxes` (bounding boxes) per chunk at ingestion and in the `citations` payload **[PLANNED]**. Verify what PyMuPDF can provide per chunk. This is an additive field, so Streamlit is unaffected.
- Final citation shape: `{chunk_id, document_id, page, bboxes, snippet}`.
- Chunks ingested before `bboxes` exist will lack them; re-ingest those documents.
- The Angular viewer opens the PDF from a signed URL (`GET /documents/{id}/file`), jumps to `page`, and highlights `bboxes`. Note that PyMuPDF and pdf.js use different coordinate origins; normalize when drawing overlays.

---

## 4. Data model

Exists: `document_chunks`, `conversations`, `conversation_documents`, `messages`.
Needed (**[RECOMMENDED]**): verify against the existing migrations in `backend/supabase/migrations/`, and keep every change additive. Enable RLS on every table when auth lands.

| Table | Key columns |
|---|---|
| `profiles` (new) | `user_id` (FK to auth), `role` (`user` or `admin`) |
| `documents` (implemented) | `id` (currently derived from the PDF hash), `sha256`, `filename`, `storage_path`, `status` (`processing`, `ready`, `failed`), `error`, `page_count`, `chunk_count`, `created_at`. Per-user IDs and uniqueness remain planned with auth. |
| `document_chunks` (exists) | add `user_id`, `bboxes` (jsonb); confirm `page` and the full-text column are present |
| `conversations` (exists) | add `user_id` |
| `conversation_documents` (exists) | as is |
| `messages` (exists) | confirm `status` (`streaming`, `complete`, `error`) so a dropped stream can be recovered |
| `message_feedback` (optional) | `message_id`, `rating` |

Storage: PDFs are stored in a private Supabase Storage bucket at `{document_id}/document.pdf`. User-scoped paths and policies remain planned with auth. PDFs ingested before Storage was introduced have no original file and must be uploaded again for the side-panel viewer.

---

## 5. API specification

Errors use `{ "error": { "code": string, "message": string, "retryable": boolean } }`.
Status column: ✅ implemented, ➕ needed for Angular (build next), ⏭ later.

| Endpoint | Purpose | Status |
|---|---|---|
| `GET /health` | Liveness. | ✅ |
| `POST /documents` | Upload and ingest a PDF. | ✅ (background ingestion ⏭) |
| `GET /documents/{id}` | Status (`processing`, `ready`, `failed`) and metadata. | ✅ |
| `GET /documents` | The document library, for an attach picker (replaces typing UUIDs). | ✅ |
| `GET /documents/{id}/file` | Short-lived signed URL for the PDF viewer. Requires PDF storage. | ✅ |
| `DELETE /documents/{id}` | Delete file and chunks. | ⏭ |
| `GET /documents/{id}/events` | SSE ingestion progress (replaces polling). | ⏭ |
| `POST /conversations` | Create (optional `document_ids`). | ✅ |
| `GET /conversations` | Sidebar history, paginated. | ✅ |
| `GET /conversations/{id}` | Details plus attached documents. | ✅ |
| `GET /conversations/{id}/messages` | Messages with citations. | ✅ |
| `POST /conversations/{id}/documents` | Attach `{document_id}`. | ✅ |
| `POST /conversations/{id}/messages` | Send `{content}`; stream the answer over SSE. | ✅ |
| `PATCH /conversations/{id}` | Rename. | ⏭ |
| `DELETE /conversations/{id}` | Delete. | ⏭ |
| `DELETE /conversations/{id}/documents/{document_id}` | Detach. | ⏭ |
| `GET /messages/{id}` | Re-fetch a final message if the stream dropped. | ⏭ |
| `POST /messages/{id}/regenerate` | Retry. | ⏭ |
| `POST /messages/{id}/feedback` | Thumbs up/down (feeds evals). | ⏭ |

### SSE events for `POST /conversations/{id}/messages`
| Event | Payload |
|---|---|
| `status` | `rewriting`, `retrieving`, `reranking`, `generating` (drives UI loading states) |
| `token` | answer text delta |
| `citations` | `[{chunk_id, document_id, page, bboxes, snippet}]` (`bboxes` added later) |
| `done` | `{message_id, timings}` (timings let you measure latency, see section 6.3) |
| `error` | `{code, message, retryable}` |

Cancelling = the client aborts the request.

### Error codes
`document_not_ready`, `unsupported_pdf`, `llm_unavailable`, `rate_limited`, `unauthorized`, `not_found`, `quota_exceeded`.

---

## 6. Frontend: Angular alongside Streamlit

### 6.1 Folder layout and coexistence rules **[DECIDED]**

```text
repo/
├── backend/                  # FastAPI + ingestion (shared by both frontends)
├── <streamlit-folder>/       # existing Streamlit app: DO NOT TOUCH
└── frontend-angular/         # new Angular app (proposed name)
```

- Angular lives in its own top-level folder next to the Streamlit one. The proposed name is `frontend-angular/` **[RECOMMENDED]**; the actual Streamlit folder name must be confirmed **[OPEN]**.
- Do not edit, move, rename, or delete the Streamlit folder, its dependencies, or its run command.
- Separate dependency management (`package.json`), separate README, and separate Docker/deploy target for Angular.
- Both frontends call the same backend API. API changes are additive only (rule 4 in section 0).
- Add a root README section: "How to run either frontend."
- Add a contract test that calls the endpoints Streamlit uses, so any backend change that would break Streamlit fails CI.
- **Reverting = stop serving the Angular app.** Nothing else changes.
- Use the current stable Angular version, standalone components, and TypeScript strict mode.

### 6.2 Angular requirements

1. Streamed responses with live status text (the `status` events).
2. ~~Per-conversation model switching~~ **dropped** (D2).
3. Claude-like flow: attach a PDF to a conversation; it stays attached when reopened.
4. Clickable page citations that open the PDF in a side panel at the source chunk (highlighted by `bboxes`).
5. Chat history, loading states, error handling (retry control, a clear "document still processing" state).
6. A document picker (from `GET /documents`) instead of typing UUIDs.
7. Configurable API base URL via environment config.

### 6.3 Performance guardrails and the go/no-go gate **[DECIDED]**

Angular must not slow down any rendering. Build it with these rules from day one.

**Rendering rules**
- Standalone components, `ChangeDetectionStrategy.OnPush`, and signals for state. Use `@for` with `track`. No function calls in templates.
- **Streaming:** buffer incoming tokens and flush to the UI at most once per animation frame (`requestAnimationFrame`). Update only the in-flight message component, never the whole list. Parse the stream outside the Angular zone and re-enter only on flush (or go zoneless if the chosen Angular version supports it).
- **Markdown:** use a lightweight parser, throttle re-rendering of the in-flight message, and **always sanitize** output (for example `marked` + `DOMPurify`). Never bind unsanitized HTML.
- **Long histories:** messages are already paginated by the API. Use CDK virtual scrolling if conversations grow beyond a few dozen messages.
- **PDF viewer:** load `pdf.js` and its worker in a lazy chunk, only for the side panel. Prefetch it when the first `citations` event arrives (idle time) so the first citation click is fast. Render only the visible page and its neighbors; cache the loaded PDF per document.
- **Routes:** lazy-load by route.

**Build rules**
- AOT production build, gzip or brotli compression, hashed assets with long cache lifetimes.
- Set bundle budgets in `angular.json` (initial bundle and component styles), starting tighter than Angular's defaults. Pick the numbers after the first build. CI fails on regression.

**Go/no-go gate.** Measure both frontends on the same machine, same backend, and same document. Angular becomes the default frontend only if it passes. Until then Streamlit stays the default.

| Metric | Gate (initial targets, tune after the first measurement) |
|---|---|
| Open a conversation with a long history | Not slower than Streamlit |
| Send → first token visible | Not slower than Streamlit; first token appears within about 100 ms of the backend emitting it |
| Streaming smoothness | No long tasks (over 50 ms) from rendering during streaming (Chrome Performance panel); steady frame rate |
| Citation click → PDF page visible | About 1 s or less on a typical PDF once the viewer chunk is cached |
| Lighthouse performance (production build, desktop) | 90 or higher |

If the gate fails, fix the cause and re-measure. Do not remove or modify Streamlit to "make room."

### 6.4 Backend additions required for Angular (all additive)

| ID | Change |
|---|---|
| B1 | **CORS** allowlist via `API_CORS_ORIGINS`. **[IMPLEMENTED]** |
| B2 | `GET /documents/{id}` (status and metadata). **[IMPLEMENTED]** |
| B3 | `GET /documents` (library list). **[IMPLEMENTED]** |
| B4 | Store the original PDF in Supabase Storage on upload, and add `GET /documents/{id}/file` (signed URL). **[IMPLEMENTED]** Earlier indexed PDFs have no stored file; re-upload them. |
| B5 | Capture `bboxes` per chunk at ingestion and include them in the `citations` payload. Re-ingest older documents. |
| B6 | A `documents` table (section 4). **[IMPLEMENTED]** |

---

## 7. Build order and acceptance criteria

**Done:** backend MVP (no auth), RAG pipeline R0-R3, Streamlit UI.

**M3: Evaluation first**
- Build the eval set and harness (section 8) and measure R0-R3, which are built but unmeasured.
- Done when the README has a table comparing configurations.

**M4: Backend additions for Angular (B1-B6)**
- Additive changes only, plus the Streamlit contract test.
- Done when Streamlit still works unchanged, and a `curl` call can fetch a document's status, list documents, get a signed PDF URL, and see `bboxes` in citations.

**M5: Angular MVP in `frontend-angular/`**
- Spike the two riskiest pieces first and measure them: the streaming message component, and the PDF side panel with highlight.
- Then build the rest (conversation list, upload, picker, chat, history, error and loading states).
- Done when the go/no-go gate (section 6.3) passes against Streamlit.

**M6: Auth and isolation**
- Supabase Auth with Google, JWT verification in FastAPI, `AUTH_MODE` flag (D19), RLS, `user_id` columns, per-user document IDs (D17), Angular sign-in.
- Done when user A can complete the full flow and **user B cannot see any of it**, proven by an automated test.

**M7: Hardening and deploy**
- Pre-launch checklist (section 10), staging and production environments, CI/CD, then the launch decision (D20).

---

## 8. Evaluation plan (now the top priority)

R0-R3 are built, but nothing has measured whether each step helps.

- Build 15-20 question/answer pairs over a few real PDFs, including questions whose answer is **not** in the document.
- Metrics: retrieval recall@k, answer faithfulness (grounded in retrieved context), correct "not found" behavior, citation page accuracy, and latency (retrieval, rerank, time-to-first-token).
- Compare: vector-only vs hybrid vs hybrid + rerank; with and without query rewrite; semantic vs recursive chunking.
- Run it as a separate offline harness, not per request. Re-run before releases.
- Report results honestly in the README, including what did not help.

---

## 9. Security and secrets rules

- The Supabase **service-role key and the Gemini API key exist only on the backend**. The Angular app gets only the public Supabase URL and anon key (once auth is added).
- `.env` stays gitignored. Use separate keys for staging and production. Use managed platform secrets (Cloud Run + Secret Manager, Fly secrets, or Render env vars); Vault is not needed.
- Every table has RLS once auth lands. Every new query path gets an isolation test.
- Sanitize all model output before rendering it (see section 6.3).
- Quotas in the API: max PDF size and page count, documents per user, messages per day, concurrent ingestions, request timeouts. Set a spend cap or budget alert at the LLM provider.
- Rate limiting per user (for example slowapi or fastapi-limiter), optionally an edge layer in front.
- CORS: allow only the known frontend origins, never `*` in production.

---

## 10. Pre-launch checklist

Before any public or production use:

- [ ] Auth plus roles (`user`, `admin`)
- [ ] Per-user isolation: RLS, storage policies, per-user document IDs (D17)
- [ ] Secret management via platform secrets; keys rotated and separated per environment
- [ ] Rate limiting, quotas, and abuse protection; LLM spend cap
- [ ] Logging, metrics, and alerting: structured JSON logs with request IDs; per-stage latency and token cost; error tracking (Sentry or similar); uptime check; alerts on error rate, p95 latency, daily spend
- [ ] Staging and production deployment config: two Supabase projects, two backend deployments, one Docker image promoted from staging to prod, migrations applied by the Supabase CLI in CI, separate Google OAuth redirect URIs per environment, Angular on a static host with per-environment config
- [ ] End-to-end integration tests against real infrastructure (see below)

Testing approach:
- Real Postgres + pgvector in CI (`supabase start` or a staging project).
- Google login is hard to automate: create test users through the Supabase admin API and mint their sessions instead.
- Mock the LLM in most tests; keep a few real-call smoke tests.
- Playwright for the Angular browser flow.
- **Mandatory test:** user A cannot read user B's documents, chunks, messages, or PDF files.
- The Streamlit contract test (section 6.1) stays in CI.
- Run the eval set as a regression check.

Priority order: auth and isolation, then secrets and staging, then quotas and rate limits, then logging, then full end-to-end tests.

---

## 11. Recorded owner decisions

- Keep Streamlit in `frontend/` and Angular in `frontend-angular/`.
- Use Firebase Hosting, Cloud Run, and Supabase Auth with Google.
- Launch with open Google sign-up; Streamlit is local/private-pilot only once auth is enabled.
- Use `cross-encoder/ms-marco-MiniLM-L-6-v2`, retrieve 25 candidates, and keep the top 3.
- Enforce a 100 MB PDF limit and a 1,000-page limit.
- Use Gemini model `gemini-4-hydrogen`, Langfuse, and UptimeRobot.
- The owner is learning Angular; retain the go/no-go gate before making it the default.

Remaining account provisioning, secrets, OAuth setup, and staging/production
verification are tracked in `OWNER_ACTION_CHECKLIST.md`.

---

## 12. Guidance for the owner: what to do next

1. **Complete the owner actions in `OWNER_ACTION_CHECKLIST.md`.** Never put credentials in the repository or chat.
2. **Run the evaluation first (M3).** You built hybrid search, reranking, and query rewrite; the eval is how you learn which ones earn their latency, and it is your best portfolio evidence.
3. **Do the additive backend changes (M4)** before touching Angular, and add the Streamlit contract test in the same step so you can always revert safely.
4. **Scaffold Angular in the sibling folder with performance budgets from day one.** Prototype the streaming message component and the PDF side panel first, and measure them against Streamlit before building the rest. These are the two places a slowdown would show up.
5. **Do not touch the Streamlit folder.** If something there needs to change, ask first.
6. **Fix the per-user document ID (D17) before ingesting real data.** Changing it later means migrating IDs.
7. **Check the chunk size against the embedding model's input limit** now, while it is a one-line fix.
8. **Treat the isolation test as non-negotiable** when auth lands.
9. **Write the README as you go:** architecture diagram, eval results, performance gate results (Streamlit vs Angular), and an honest status line (see section 1).
