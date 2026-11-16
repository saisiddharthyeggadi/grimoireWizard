# Grimoire Wizard: implemented project summary

## Overview

Grimoire Wizard is a document Q&A MVP built around a Python backend and a Streamlit frontend. The project ingests PDFs, stores chunk embeddings in Supabase with pgvector, and answers questions using retrieval-augmented generation (RAG) over the documents attached to a conversation.

The implementation is split into two deployable parts:

- Backend: PDF ingestion pipeline and conversation API
- Frontend: Streamlit chat UI for asking questions and viewing citations

## Implemented components

### 1. PDF ingestion pipeline

The backend includes a PDF ingestion flow that:

- accepts a PDF file from the CLI or API
- validates the file type and size
- extracts markdown content page by page using PyMuPDF4LLM
- splits content into paragraph-level and chunk-level segments
- detects chapter boundaries and paragraph metadata
- embeds chunks using `sentence-transformers/all-MiniLM-L6-v2`
- stores chunk vectors and metadata in Supabase `public.document_chunks`
- deduplicates documents deterministically by PDF content hash
- removes stale trailing chunks when a document is re-ingested

The ingestion logic supports configurable chunking behavior, including:

- similarity threshold for semantic grouping
- max chunk word count
- overlap between adjacent chunks

This is implemented in the backend ingestion code and exposed through the `grimoire-ingest` CLI.

### 2. Supabase-backed storage

The project includes persistence for:

- document chunks with embeddings and metadata
- conversations
- conversation-to-document attachments
- chat messages with citations

The database usage is designed around:

- `document_chunks` for vector search and document metadata
- `conversations` for chat threads
- `conversation_documents` for document attachment relationships
- `messages` for stored user and assistant replies

The backend uses a Supabase service-role key on the server side and relies on configured database migrations under `backend/supabase/migrations/`.

### 3. Conversation API

The backend exposes a FastAPI app with the following implemented endpoints:

- `GET /health` for liveness checks
- `POST /documents` to upload and ingest a PDF
- `POST /conversations` to create a conversation
- `GET /conversations` to list conversations with pagination
- `GET /conversations/{id}` to fetch conversation details and attached documents
- `GET /conversations/{id}/messages` to retrieve messages
- `POST /conversations/{id}/documents` to attach a previously ingested document
- `POST /conversations/{id}/messages` to send a user message and stream an answer over SSE

The messaging flow streams server-sent events with:

- `status` updates
- `token` deltas for incremental answer text
- `citations` payloads
- `done` completion signal
- `error` events for backend failures

### 4. RAG retrieval and answer generation

The project implements a retrieval pipeline that:

- rewrites the user's question into a concise search query
- encodes the rewritten query into a vector
- searches only within the documents attached to the conversation
- uses vector similarity plus full-text ranking to retrieve relevant chunks
- reranks and constructs context from the best chunks
- sends the document excerpts and the original question to Gemini via the OpenAI-compatible endpoint
- streams the generated answer back to the client

Each assistant response includes citations to the relevant source chunks, including document, page, and snippet information.

### 5. Frontend UI

The frontend is a Streamlit application that supports:

- entering a backend API URL
- checking backend health
- creating conversations
- listing and reopening conversations
- uploading a PDF to start a conversation
- attaching previously indexed documents by UUID
- chatting with the attached document set
- viewing citations in the assistant response

The chat UI renders messages and a source expander showing references for cited passages.

## Data flow summary

```text
PDF upload -> ingestion -> embeddings -> Supabase
        \n
Conversation creation -> attach document -> send question -> retrieve chunks -> LLM -> stream answer + citations
```

## Current project status

This repo is a working MVP for a private, single-service document Q&A workflow. It successfully demonstrates the core flow from PDF upload to retrieval and answer generation.

It is not yet a production-ready multi-user system because it does not include:

- user authentication / authorization
- per-user isolation for conversations and documents
- deployment configuration for production
- production-grade monitoring, logging, and alerting
- hardened secret management and network controls

## Operational assumptions

The implementation expects:

- a configured Supabase project with the SQL migrations applied
- a valid Gemini API key
- a backend environment with `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and `GEMINI_API_KEY`
- a trusted server-side deployment model, since the service-role key is intentionally server-only

## In short

The project implements a functional document ingestion + RAG chat system for a local or internal MVP environment, with a backend API, Supabase vector store, and a Streamlit client. It is well suited to prototype and pilot use, but it still requires additional security and operational work before production deployment.
