# Grimoire Wizard PDF ingestion

This milestone ingests English PDFs into Supabase `pgvector`:

1. PyMuPDF4LLM extracts markdown page by page.
2. Markdown paragraphs are embedded with `sentence-transformers/all-MiniLM-L6-v2`.
3. Adjacent paragraphs are grouped when their cosine similarity meets the configured threshold, with a 300-word default maximum per chunk and configurable word overlap.
4. Each chunk embedding and its document, chapter, page, and paragraph metadata are upserted into Supabase.

Chapter numbers are detected from headings such as `Chapter IV: ...` or `5. ...`. If a chapter heading is not found, `chapter_number` is `null`. Paragraph numbering is document-wide; each chunk stores its first paragraph number in the dedicated column and its last paragraph number in `metadata.paragraph_end`.

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and use Python 3.11 or newer. From the `backend/` directory, sync the project and test dependencies:

```bash
uv sync --extra dev
```

Run the SQL in [the migration](supabase/migrations/20261110000000_create_document_chunks.sql) in the Supabase SQL editor. It creates the 384-dimensional vector column, indexes, uniqueness constraint, and enables row-level security without adding public access policies.

Copy `.env.example` to `.env` in the `backend/` directory and set:

```dotenv
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
GEMINI_API_KEY=your-gemini-api-key
LLM_MODEL=gemini-4-hydrogen
```

The backend uses Gemini's OpenAI-compatible API endpoint and defaults to
`gemini-4-hydrogen`. `LLM_MODEL` can select another Gemini model available to
your API key. `GEMINI_API_KEY` is required; local and other LLM providers are
not configured or supported.

The service-role key bypasses row-level security: keep it private, and never put it in browser or mobile-client code.

## Ingest a PDF

```bash
uv run grimoire-ingest "/c/path/to/document.pdf"
```

Optional controls:

```bash
uv run grimoire-ingest "/c/path/to/document.pdf" --similarity-threshold 0.45 --max-words 300 --overlap-words 40
```

`--overlap-words` repeats the end of one chunk at the start of the next. The repeated words count toward `--max-words`; the default overlap is `0`, preserving non-overlapping chunks. The overlap must be smaller than the maximum chunk size.

The document ID is deterministic for the PDF's exact bytes, so re-ingesting the same file upserts the same chunks. A changed PDF receives a new ID; the previous version remains in the table and can be removed by its `document_id` when desired. The embedding model may be downloaded the first time ingestion runs.

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
in `../project_decisions/backend_endpoints.md`. Apply both SQL migrations in
`supabase/migrations/` to the same Supabase project used for ingestion. Start
the API from this directory after setting `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY`, and `GEMINI_API_KEY`:

```bash
uv sync --extra dev
uv run grimoire-api
```

The API listens on `http://127.0.0.1:8000`; `/docs` provides the interactive
OpenAPI schema. The backend connects only to Google's OpenAI-compatible Gemini
endpoint; `LLM_MODEL` selects the Gemini model. Set `API_CORS_ORIGINS` to a
comma-separated list when the frontend runs on a different origin.

`POST /documents` accepts a PDF multipart upload (maximum 50 MB), runs the
existing ingestion pipeline, and returns its deterministic `document_id`,
filename, and chunk counts. `POST /conversations` accepts an optional `title`.
Attach an already-ingested document with
`POST /conversations/{id}/documents` and a JSON `document_id`.
`POST /conversations/{id}/messages` accepts `{ "content": "..." }` and streams
Server-Sent Events (`status`, `token`, `citations`, `done`, or `error`). The
conversation and message tables persist chat history; retrieval is restricted
to documents attached to that conversation and combines pgvector similarity
with PostgreSQL full-text ranking.

The API uses the Supabase service-role key exclusively on the server. This MVP
does not implement user authentication or per-user conversation isolation;
keep it on a trusted network until an authentication model is added.
SSE errors use `document_not_ready`, `llm_unavailable`, `rate_limited`, or
`internal_error` when a backend dependency fails.

## Test

Run the test suite without connecting to Supabase:

```bash
uv run pytest -v
```
