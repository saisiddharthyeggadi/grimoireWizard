# Grimoire Wizard PDF ingestion

This milestone ingests English PDFs into Supabase `pgvector`:

1. PyMuPDF4LLM extracts markdown page by page.
2. Markdown paragraphs are embedded with `sentence-transformers/all-MiniLM-L6-v2`.
3. Adjacent paragraphs are grouped when their cosine similarity meets the configured threshold, with a 300-word default maximum per chunk.
4. Each chunk embedding and its document, chapter, page, and paragraph metadata are upserted into Supabase.

Chapter numbers are detected from headings such as `Chapter IV: ...` or `5. ...`. If a chapter heading is not found, `chapter_number` is `null`. Paragraph numbering is document-wide; each chunk stores its first paragraph number in the dedicated column and its last paragraph number in `metadata.paragraph_end`.

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and use Python 3.11 or newer. Open Git Bash in the project root, then sync the project and test dependencies:

```bash
uv sync --extra dev
```

Run the SQL in [the migration](supabase/migrations/20261110000000_create_document_chunks.sql) in the Supabase SQL editor. It creates the 384-dimensional vector column, indexes, uniqueness constraint, and enables row-level security without adding public access policies.

Create a `.env` file in the project root and set:

```dotenv
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
```

The service-role key bypasses row-level security: keep it private, and never put it in browser or mobile-client code.

## Ingest a PDF

```bash
uv run grimoire-ingest "/c/path/to/document.pdf"
```

Optional controls:

```bash
uv run grimoire-ingest "/c/path/to/document.pdf" --similarity-threshold 0.45 --max-words 300
```

The document ID is deterministic for the PDF's exact bytes, so re-ingesting the same file upserts the same chunks. A changed PDF receives a new ID; the previous version remains in the table and can be removed by its `document_id` when desired. The embedding model may be downloaded the first time ingestion runs.

## Test

Run the test suite without connecting to Supabase:

```bash
uv run pytest -v
```
