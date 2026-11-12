create table if not exists public.conversations (
    id uuid primary key default gen_random_uuid(),
    title text not null default 'New conversation',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.conversation_documents (
    conversation_id uuid not null references public.conversations(id) on delete cascade,
    document_id uuid not null,
    created_at timestamptz not null default now(),
    primary key (conversation_id, document_id)
);

create table if not exists public.messages (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references public.conversations(id) on delete cascade,
    role text not null check (role in ('user', 'assistant')),
    content text not null,
    citations jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists conversations_updated_at_idx
    on public.conversations (updated_at desc);
create index if not exists messages_conversation_created_at_idx
    on public.messages (conversation_id, created_at);
create index if not exists document_chunks_content_fts_idx
    on public.document_chunks
    using gin (to_tsvector('english', content));

alter table public.conversations enable row level security;
alter table public.conversation_documents enable row level security;
alter table public.messages enable row level security;

create or replace function public.search_document_chunks(
    query_embedding extensions.vector(384),
    query_text text,
    document_ids uuid[],
    result_limit integer default 8
)
returns table (
    chunk_id bigint,
    document_id uuid,
    content text,
    page_number integer,
    metadata jsonb,
    similarity double precision,
    rank_score double precision
)
language sql
stable
as $$
    with vector_candidates as (
        select
            chunks.id,
            chunks.document_id,
            chunks.content,
            chunks.page_number,
            chunks.metadata,
            1 - (chunks.embedding <=> query_embedding) as similarity,
            row_number() over (order by chunks.embedding <=> query_embedding) as position
        from public.document_chunks as chunks
        where chunks.document_id = any(document_ids)
        order by chunks.embedding <=> query_embedding
        limit greatest(1, least(result_limit, 100))
    ),
    keyword_candidates as (
        select
            chunks.id,
            chunks.document_id,
            chunks.content,
            chunks.page_number,
            chunks.metadata,
            0::double precision as similarity,
            row_number() over (
                order by ts_rank_cd(
                    to_tsvector('english', chunks.content),
                    websearch_to_tsquery('english', query_text)
                ) desc
            ) as position
        from public.document_chunks as chunks
        where chunks.document_id = any(document_ids)
          and to_tsvector('english', chunks.content)
              @@ websearch_to_tsquery('english', query_text)
        order by ts_rank_cd(
            to_tsvector('english', chunks.content),
            websearch_to_tsquery('english', query_text)
        ) desc
        limit greatest(1, least(result_limit, 100))
    ),
    candidate_scores as (
        select id, document_id, content, page_number, metadata, similarity,
               1.0 / (60 + position) as score
        from vector_candidates
        union all
        select id, document_id, content, page_number, metadata, similarity,
               1.0 / (60 + position) as score
        from keyword_candidates
    )
    select
        candidates.id as chunk_id,
        candidates.document_id,
        candidates.content,
        candidates.page_number,
        candidates.metadata,
        max(candidates.similarity) as similarity,
        sum(candidates.score) as rank_score
    from candidate_scores as candidates
    group by candidates.id, candidates.document_id, candidates.content,
             candidates.page_number, candidates.metadata
    order by rank_score desc, similarity desc
    limit greatest(1, least(result_limit, 100));
$$;
