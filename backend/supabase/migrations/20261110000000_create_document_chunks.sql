create extension if not exists vector with schema extensions;

create table if not exists public.document_chunks (
    id bigint generated always as identity primary key,
    document_id uuid not null,
    chunk_index integer not null check (chunk_index >= 0),
    content text not null,
    embedding extensions.vector(384) not null,
    chapter_number integer,
    page_number integer not null check (page_number > 0),
    paragraph_number integer not null check (paragraph_number > 0),
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    constraint document_chunks_document_chunk_unique unique (document_id, chunk_index)
);

create index if not exists document_chunks_embedding_hnsw_idx
    on public.document_chunks
    using hnsw (embedding extensions.vector_cosine_ops);

create index if not exists document_chunks_document_id_idx
    on public.document_chunks (document_id);

alter table public.document_chunks enable row level security;
