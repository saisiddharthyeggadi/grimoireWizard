# Grimoire Wizard PDF ingestion

This milestone ingests English PDFs into Supabase `pgvector`:

1. PyMuPDF4LLM extracts markdown page by page.
2. Markdown paragraphs are embedded with `sentence-transformers/all-MiniLM-L6-v2`.
3. Adjacent paragraphs are grouped when their cosine similarity meets the configured threshold, with a 300-word default maximum per chunk, configurable word overlap, and a hard token limit from the loaded embedding model's tokenizer and maximum sequence length.
4. Each chunk embedding and its document, chapter, page, and paragraph metadata are upserted into Supabase.

Chapter numbers are detected from headings such as `Chapter IV: ...` or `5. ...`. If a chapter heading is not found, `chapter_number` is `null`. Paragraph numbering is document-wide; each chunk stores its first paragraph number in the dedicated column and its last paragraph number in `metadata.paragraph_end`.

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and use Python 3.11 or newer. From the `backend/` directory, sync the project and test dependencies:

```bash
uv sync --extra dev
```

Run all SQL migrations in `supabase/migrations/` in order in the Supabase SQL editor. They create the vector, conversation, and document tables and a private `documents` Storage bucket. The new documents migration backfills metadata for already-indexed PDFs; their original files are not recoverable, so upload those PDFs again to enable previews. The auth migration adds per-user ownership, Auth profiles, Postgres RLS, and Storage policies. Existing rows remain ownerless and are intentionally not visible to signed-in users; upload those PDFs again after auth is enabled.

Copy `.env.example` to `.env` in the `backend/` directory and set:

```dotenv
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-public-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
GEMINI_API_KEY=your-gemini-api-key
LLM_MODEL=gemini-4-hydrogen
ENV=development
AUTH_MODE=off
```

The backend uses Gemini's OpenAI-compatible API endpoint and defaults to
`gemini-4-hydrogen`. `LLM_MODEL` can select another Gemini model available to
your API key. `GEMINI_API_KEY` is required; local and other LLM providers are
not configured or supported.

`SUPABASE_SERVICE_ROLE_KEY` bypasses row-level security and is used by the
backend only for PDF ingestion. Keep it private and never put it in browser
configuration. The public `SUPABASE_ANON_KEY` is used by the Angular client
and by the backend to validate sessions and make user-scoped database
requests.

## Ingest a PDF

```bash
uv run grimoire-ingest "/c/path/to/document.pdf"
```

Optional controls:

```bash
uv run grimoire-ingest "/c/path/to/document.pdf" --similarity-threshold 0.45 --max-words 300 --overlap-words 40
```

`--overlap-words` repeats the end of one chunk at the start of the next. The repeated words count toward both `--max-words` and the embedding model's token limit; the default overlap is `0`, preserving non-overlapping chunks. The overlap must be smaller than the maximum chunk size.

The CLI is a local/admin ingestion tool: it derives a deterministic ID from the
PDF bytes and leaves `user_id` unset. Such rows are intentionally invisible to
authenticated users. The authenticated API derives the document ID from the
user ID and PDF SHA-256, so identical PDFs belonging to different users do not
collide. The embedding model may be downloaded the first time ingestion runs.

## Troubleshooting Supabase

If ingestion ends with `PGRST205` and says it cannot find
`public.document_chunks` in the schema cache, the configured Supabase project
does not currently expose that table to the API. In the SQL editor for the
project whose URL is in `.env`, run the SQL in
[the migration](supabase/migrations/20261110000000_create_document_chunks.sql).
Verify that it exists with:

```sql
select to_regclass('public.document_chunks');
```

The result should be `public.document_chunks`, not `NULL`. If it exists but the
API still reports `PGRST205`, reload the PostgREST schema cache in the SQL
editor with `NOTIFY pgrst, 'reload schema';` and confirm that `.env` points to
that same project. Do not share or paste the service-role key.

The Hugging Face symlink warning on Windows is unrelated to ingestion failure:
the cache still works but may use more disk space. Enabling Windows Developer
Mode or running Python as administrator allows symlinks; otherwise the warning
can be ignored. Model and tokenizer downloads are expected on the first run.

## Conversation API

The FastAPI application implements the conversation and PDF upload endpoints
in `../project_decisions/backend_endpoints.md`. Apply all SQL migrations in
`supabase/migrations/` to the same Supabase project used for ingestion. For
local development, set `ENV=development` and `AUTH_MODE=off`. The API assigns
the fixed local identity in `AUTH_DEV_USER_ID`; it refuses to start with auth
disabled when `ENV=production`.

For an authenticated deployment set `ENV=production`, `AUTH_MODE=on`,
`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, and
`GEMINI_API_KEY`:

```bash
uv sync --extra dev
uv run grimoire-api
```

The API listens on `http://127.0.0.1:8000`; `/docs` provides the interactive
OpenAPI schema. The backend connects only to Google's OpenAI-compatible Gemini
endpoint; `LLM_MODEL` selects the Gemini model. Set `API_CORS_ORIGINS` to a
comma-separated list when the frontend runs on a different origin.

`POST /documents` accepts a PDF multipart upload, stores it in the private
Supabase Storage bucket under the signed-in user's ID, runs the existing ingestion pipeline, and returns its
deterministic `document_id`, filename, and chunk counts. `GET /documents`
returns the paginated document library, `GET /documents/{id}` returns document
metadata and status, and `GET /documents/{id}/file` returns a five-minute
signed URL for stored PDFs. Documents ingested before Storage was added remain
listable, but need to be uploaded again for PDF previews. `POST /conversations`
accepts an optional `title`.
Attach an already-ingested document with
`POST /conversations/{id}/documents` and a JSON `document_id`.
`POST /conversations/{id}/messages` accepts `{ "content": "..." }` and streams
Server-Sent Events (`status`, `token`, `citations`, `done`, or `error`). The
conversation and message tables persist chat history; retrieval is restricted
to documents attached to that conversation and combines pgvector similarity
with PostgreSQL full-text ranking.

In `AUTH_MODE=on`, every request other than `GET /health` requires a Supabase
access token in `Authorization: Bearer <access-token>`. The backend validates
the token with Supabase Auth and uses that same token for user-scoped database
and Storage operations so RLS applies. The service-role key is used only for
the ingestion writes. The Angular app signs in with Google using the public
Supabase URL and anon key in `src/environments/environment.ts` (local) and
`environment.prod.ts` (production); never put the service-role key there.

Before deploying, enable Google in Supabase Auth, configure the OAuth redirect
URLs, and apply all migrations. In particular, the per-user RLS migration must
be active before real documents are uploaded. An automated RLS check against
the staging project is still required before launch.
SSE errors use `document_not_ready`, `llm_unavailable`, `rate_limited`, or
`internal_error` when a backend dependency fails.

## Test

Run the test suite without connecting to Supabase:

```bash
uv run pytest -v
```
