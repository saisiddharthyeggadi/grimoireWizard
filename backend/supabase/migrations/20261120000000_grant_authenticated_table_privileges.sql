-- RLS policies only filter rows; the role still needs table-level privileges.
grant usage on schema public to authenticated;

grant select, insert, update, delete on table
    public.documents,
    public.document_chunks,
    public.conversations,
    public.conversation_documents,
    public.messages
to authenticated;

grant select on table public.profiles to authenticated;
