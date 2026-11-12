## PDF Ingestion Architecture

```text
PDF file + CLI options
        │
        ▼
grimoire-ingest CLI
  ├─ Validate PDF and chunking options
  ├─ Load Supabase URL and service-role key
  └─ Create Supabase client
        │
        ▼
Parse PDF pages (PyMuPDF4LLM)
        │
        ▼
Parse page markdown into paragraphs
  └─ Track page, paragraph, and chapter numbers
        │
        ▼
Load sentence-transformers/all-MiniLM-L6-v2
        │
        ▼
Build semantic chunks, page by page
  ├─ Embed paragraph units to compare adjacent paragraphs
  ├─ Split at semantic/chapter boundaries and max-word limit
  └─ Embed each final chunk (384-dimensional vector)
        │
        ▼
Build chunk records
  ├─ Deterministic document ID from the PDF's SHA-256
  ├─ Content, embedding, location, and source metadata
  └─ Validate embedding dimensions and finite values
        │
        ▼
Supabase public.document_chunks (pgvector)
  ├─ Upsert in batches of 100 by document_id + chunk_index
  └─ Delete stale trailing chunks for this document
```

The CLI reports ingestion complete only after parsing, embedding, and the
Supabase writes finish successfully. The embedding model may be downloaded the
first time it is loaded.

## Query / Retrieval Flow

        ┌───────────────┐
        │ User Question │
        └───────┬───────┘
                ↓
        Query Understanding
                ↓
        Query Rewrite / Expansion
                ↓
        ┌──────────┴──────────┐
        ↓                     ↓
Vector Search          Keyword Search
        ↓                     ↓
        └──────────┬──────────┘
                ↓
        Candidate Chunks
                ↓
            Reranker
                ↓
        Top relevant chunks
                ↓
        Context Assembly
                ↓
                LLM
                ↓
            Final Answer