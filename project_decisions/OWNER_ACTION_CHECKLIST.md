# Grimoire Wizard: owner action checklist

This list contains the project decisions, access, source material, and real-world
checks that only the owner can provide or perform. Implementation work can
continue after the relevant items are answered; do not share secrets in this
file or in chat.

## 1. Owner decisions received

- [x] **Frontend folders:** Keep Streamlit in `frontend/`; use sibling
  `frontend-angular/` for Angular.
- [x] **Launch access (D20):** Open Google sign-up.
- [x] **Reranking (R2):** Use
  `cross-encoder/ms-marco-MiniLM-L-6-v2`; retrieve 25 candidates and keep the
  top 3.
- [x] **Hosting:** Cloud Run for the backend and Firebase Hosting for Angular.
- [x] **Streamlit with auth (D19):** Streamlit may be limited to local
  development/private pilots once auth is enabled.
- [x] **Angular experience:** Owner is learning Angular for this project.
- [x] **PDF limits:** Backend enforces a maximum 100 MB and 1,000 pages.
- [x] **Gemini model (D4):** Confirmed as `gemini-4-hydrogen`.

## 2. Provide evaluation material (M3, first priority)

- [X] Identify the approved PDF filename(s) and provide page and passage
  numbers for answerable evaluation examples. From those passages, create and
  review 15–20 questions with expected answers and source references; include
  questions whose answers are absent from the documents and mark them
  unanswerable.
- [X] Keep the PDFs available for later repeat runs. Evaluation results should
  be reproducible and reported without exposing private document contents.
- [X] Review the evaluation results and decide whether any retrieval or
  generation change is worth its added latency. Results and configurations
  should be recorded in the root README.

## 3. Prepare the environments and source documents

- [ ] Keep Supabase and Gemini credentials in local ignored environment files
  or a managed secret store. Do not send keys in chat, add them to source
  control, or put them in frontend configuration.
- [ ] Identify which Supabase project is for local/development and confirm the
  current migrations have been applied there before database-backed checks.
- [ ] Retain the original PDFs for any documents that will need to be uploaded
  again after PDF Storage and bounding-box support are implemented; previously
  ingested PDFs are not stored by the current backend.

## 4. Review the Angular go/no-go measurements (M5)

After the Angular MVP exists:

- [ ] Use the same computer, backend, and representative document to compare
  Angular with Streamlit.
- [ ] Run the production Angular build and browser measurements for long
  conversation opening, send-to-first-token delay, streaming responsiveness,
  citation-to-page display, and Lighthouse performance.
- [ ] Review the measurements against section 6.3 of `DECISIONS.md`. Keep
  Streamlit as the default unless every go/no-go requirement is met.

## 5. Configure and verify authentication/isolation (M6)

The auth code and SQL migration are prepared. Do not mark this section complete
until the migration is applied to staging and the two-user isolation test has
passed.

- [ ] Enable Google as the Supabase Auth provider and configure the required
  OAuth consent screen and redirect URLs for each environment. Use only the
  basic scopes listed in `DECISIONS.md`.
- [ ] Decide which trusted email addresses, if any, belong on the launch
  allowlist.
- [ ] Help provision two test users (A and B) or an equivalent test setup.
  Verify with the automated test that user B cannot access user A's
  documents, chunks, conversations, messages, or stored PDF files.
- [ ] Confirm the agreed Streamlit behavior when `AUTH_MODE` is enabled.

## 6. Complete hardening and launch preparation (M7)

Before any public or production use:

- [ ] Select and provision separate staging and production Supabase projects
  and backend deployments, plus the Angular static host.
- [ ] Configure platform-managed secrets separately for each environment;
  rotate any keys that may have been exposed and never reuse development keys
  in production.
- [ ] Set and verify PDF/page, document, message, concurrency, and timeout
  quotas; configure per-user rate limits and an LLM spend cap or budget alert.
- [ ] Choose/enable operational monitoring: structured logs and request IDs,
  per-stage latency and token cost, error tracking, uptime checks, and alerts
  for error rate, p95 latency, and spend.
- [ ] Approve the staging-to-production release process, migration process,
  OAuth redirect URLs, and per-environment frontend configuration.
- [ ] Ensure real-Postgres/pgvector integration tests, the Streamlit API
  contract test, the two-user isolation test, Angular browser tests, and the
  evaluation regression run are passing before launch.
- [ ] Re-review every item in section 10 of `DECISIONS.md` and make the final
  invite-only/open launch decision before production access is enabled.

## Repository facts already checked

- The existing Streamlit app is in `frontend/`; it must remain untouched.
- The backend currently sets the maximum PDF upload size to 50 MB; no page
  limit was found.
- The backend's configured default Gemini model is `gemini-4-hydrogen`.
- The current vector/keyword search function combines rankings, but the
  request path does not apply a separate reranker.
- Query rewriting currently receives only the current question; conversation
  history is not supplied and the rewrite is not skipped for a first message.
- Chunk creation now uses the loaded embedding model's tokenizer and maximum
  sequence length, including overlap, to prevent silent token truncation.
