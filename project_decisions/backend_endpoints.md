Documents

Endpoint	Purpose
★ POST /documents	Upload a PDF. Dedupes by SHA-256, stores the file, returns the ID
★ GET /documents/{id}	Status (poll for the MVP)
★ GET /documents/{id}/file	Signed URL for the side-panel viewer
GET /documents	Document library
DELETE /documents/{id}	Delete the file and chunks
GET /documents/{id}/events	SSE ingestion progress (replaces polling later)

Conversations

Endpoint	Purpose
★ POST /conversations	Create
★ GET /conversations	Sidebar history (paginated)
★ GET /conversations/{id}	Details plus attached documents
★ GET /conversations/{id}/messages	Messages with citations. This makes reopening a chat work
★ POST /conversations/{id}/documents	Attach {document_id}, persisted
PATCH /conversations/{id}	Rename
DELETE /conversations/{id}	Delete
DELETE /conversations/{id}/documents/{document_id}	Detach

Chat

Endpoint	Purpose
★ POST /conversations/{id}/messages	Send a question, stream the answer over SSE
GET /messages/{id}	Re-fetch a final message if the stream dropped
POST /messages/{id}/regenerate	Retry
POST /messages/{id}/feedback	Thumbs up/down for evals

Ops

Endpoint	Purpose
★ GET /health	Liveness

SSE events (unchanged)

status: rewriting, retrieving, reranking, generating
token: answer delta
citations: [{chunk_id, document_id, page, bboxes, snippet}]
done: message ID and timings
error: {code, message, retryable}

Error codes: document_not_ready, unsupported_pdf, llm_unavailable, rate_limited. Drop index_missing_for_model.


MVP
POST /documents	Upload a PDF. Dedupes by SHA-256, stores the file, returns the ID
GET /documents/{id}	Status (poll for the MVP)
GET /documents/{id}/file	Signed URL for the side-panel viewer

POST /conversations	Create
GET /conversations	Sidebar history (paginated)
GET /conversations/{id}	Details plus attached documents
GET /conversations/{id}/messages	Messages with citations. This makes reopening a chat work
POST /conversations/{id}/documents	Attach {document_id}, persisted
POST /conversations/{id}/messages	Send a question, stream the answer over SSE
GET /health	Liveness

## MVP implementation contract

- `POST /conversations` accepts an optional JSON `title`; an empty body creates
  a conversation titled `New conversation`.
- `POST /documents` accepts a PDF multipart upload (maximum 50 MB), processes
  it with the existing ingestion pipeline, and returns its deterministic
  document ID and ingestion counts.
- `GET /conversations?limit=20&offset=0` returns `items`, `limit`, `offset`,
  and `has_more`.
- Conversation details include attached `documents` with `id`, `filename`,
  and `status`. A document is attachable once its ingestion chunks exist.
- `POST /conversations/{id}/documents` accepts
  `{ "document_id": "<uuid>" }`.
- `GET /conversations/{id}/messages` returns persisted messages including
  their citations.
- `POST /conversations/{id}/messages` accepts `{ "content": "..." }`. Its SSE
  data payloads are JSON: `status` has a `status` field; `token` has `text`;
  `citations` has citation objects; `done` has `message_id` and `timings_ms`;
  `error` has `code`, `message`, and `retryable`.
- Retrieval is scoped to the conversation's attached documents and combines
  vector similarity with full-text ranking. The upload endpoint returns
  document IDs from the existing PDF ingestion pipeline.
- Apply both SQL migrations under `backend/supabase/migrations/` before running
  the API. Configure Supabase and LLM credentials in the backend environment.
