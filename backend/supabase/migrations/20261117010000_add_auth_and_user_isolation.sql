create table if not exists public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    role text not null default 'user' check (role in ('user', 'admin')),
    created_at timestamptz not null default now()
);

alter table public.documents
    add column if not exists user_id uuid;
alter table public.document_chunks
    add column if not exists user_id uuid;
alter table public.conversations
    add column if not exists user_id uuid;
alter table public.conversation_documents
    add column if not exists user_id uuid;
alter table public.messages
    add column if not exists user_id uuid;

alter table public.documents drop constraint if exists documents_sha256_key;
create unique index if not exists documents_user_sha256_unique
    on public.documents (user_id, sha256)
    where user_id is not null;

create index if not exists documents_user_id_idx on public.documents (user_id);
create index if not exists document_chunks_user_id_idx
    on public.document_chunks (user_id);
create index if not exists conversations_user_updated_idx
    on public.conversations (user_id, updated_at desc);
create index if not exists conversation_documents_user_id_idx
    on public.conversation_documents (user_id);
create index if not exists messages_user_conversation_created_idx
    on public.messages (user_id, conversation_id, created_at);

alter function public.search_document_chunks(
    extensions.vector, text, uuid[], integer
) security invoker;

create or replace function public.create_profile_for_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into public.profiles (id) values (new.id)
    on conflict (id) do nothing;
    return new;
end;
$$;

drop trigger if exists create_profile_after_signup on auth.users;
create trigger create_profile_after_signup
    after insert on auth.users
    for each row execute function public.create_profile_for_new_user();

alter table public.profiles enable row level security;

drop policy if exists "Users read their own profile" on public.profiles;
create policy "Users read their own profile"
    on public.profiles for select to authenticated
    using (id = (select auth.uid()));

drop policy if exists "Users access their own documents" on public.documents;
create policy "Users access their own documents"
    on public.documents for all to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

drop policy if exists "Users access their own chunks" on public.document_chunks;
create policy "Users access their own chunks"
    on public.document_chunks for all to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

drop policy if exists "Users access their own conversations" on public.conversations;
create policy "Users access their own conversations"
    on public.conversations for all to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

drop policy if exists "Users access their own conversation documents"
    on public.conversation_documents;
create policy "Users access their own conversation documents"
    on public.conversation_documents for all to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

drop policy if exists "Users access their own messages" on public.messages;
create policy "Users access their own messages"
    on public.messages for all to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

drop policy if exists "Users access their own stored PDFs" on storage.objects;
create policy "Users access their own stored PDFs"
    on storage.objects for all to authenticated
    using (
        bucket_id = 'documents'
        and (storage.foldername(name))[1] = (select auth.uid())::text
    )
    with check (
        bucket_id = 'documents'
        and (storage.foldername(name))[1] = (select auth.uid())::text
    );
