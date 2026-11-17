create table if not exists public.documents (
    id uuid primary key,
    sha256 text unique,
    filename text not null,
    storage_path text unique,
    status text not null default 'ready'
        check (status in ('processing', 'ready', 'failed')),
    error text,
    page_count integer check (page_count is null or page_count >= 0),
    chunk_count integer check (chunk_count is null or chunk_count >= 0),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.documents enable row level security;

insert into public.documents (
    id,
    sha256,
    filename,
    status,
    page_count,
    chunk_count,
    created_at
)
select
    document_id,
    max(metadata ->> 'sha256'),
    coalesce(max(metadata ->> 'source_file'), 'Unknown document'),
    'ready',
    max(page_number),
    count(*)::integer,
    min(created_at)
from public.document_chunks
group by document_id
on conflict (id) do nothing;

insert into storage.buckets (
    id,
    name,
    public,
    file_size_limit,
    allowed_mime_types
)
values (
    'documents',
    'documents',
    false,
    104857600,
    array['application/pdf']
)
on conflict (id) do update
set
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;
