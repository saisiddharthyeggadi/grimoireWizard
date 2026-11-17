from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

from grimoire_api.store import SupabaseConversationStore


class InsertQuery:
    def __init__(self):
        self.row = None
        self.selections = []

    def insert(self, row):
        self.row = row
        return self

    def update(self, _row):
        return self

    def eq(self, *_args):
        return self

    def select(self, columns):
        self.selections.append(columns)
        return self

    def execute(self):
        return SimpleNamespace(data=[self.row])


class FakeClient:
    def __init__(self):
        self.query = InsertQuery()

    def table(self, _name):
        return self.query


class DocumentQuery:
    def __init__(self, client):
        self.client = client
        self.filter = None
        self.page_range = None
        self.inserted = None
        self.count_requested = False

    def select(self, _columns, count=None):
        self.count_requested = count == "exact"
        return self

    def upsert(self, row, on_conflict):
        assert on_conflict == "id"
        self.inserted = row
        self.client.documents = [
            existing
            for existing in self.client.documents
            if existing["id"] != row["id"]
        ]
        self.client.documents.append(row)
        return self

    def eq(self, column, value):
        self.filter = (column, value)
        return self

    def limit(self, _limit):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def range(self, start, end):
        self.page_range = (start, end + 1)
        return self

    def execute(self):
        rows = list(self.client.documents)
        if self.filter:
            column, value = self.filter
            rows = [row for row in rows if row[column] == value]
        total = len(rows)
        if self.page_range:
            rows = rows[slice(*self.page_range)]
        if self.inserted:
            rows = [self.inserted]
        return SimpleNamespace(data=rows, count=total if self.count_requested else None)


class FakeBucket:
    def __init__(self):
        self.uploads = []
        self.signed_urls = []

    def upload(self, path, content, options):
        self.uploads.append((path, content, options))

    def create_signed_url(self, path, expires_in):
        self.signed_urls.append((path, expires_in))
        return {"signedURL": "https://example.supabase.co/signed.pdf"}


class DocumentClient:
    def __init__(self, documents):
        self.documents = documents
        self.bucket = FakeBucket()
        self.storage = self

    def table(self, _name):
        return DocumentQuery(self)

    def from_(self, bucket_name):
        assert bucket_name == "documents"
        return self.bucket


def test_insert_operations_request_rows_for_persistence_responses():
    client = FakeClient()
    user_id = str(uuid4())
    store = SupabaseConversationStore(client, user_id)

    conversation = store.create_conversation("Notes")
    message = store.save_message(
        uuid4(),
        "user",
        "Question",
    )

    assert conversation["title"] == "Notes"
    assert message["content"] == "Question"
    assert client.query.row["user_id"] == user_id
    assert client.query.selections == [
        "id,title,created_at,updated_at",
        "id,role,content,citations,created_at",
    ]


def test_document_store_persists_pdf_and_returns_signed_url():
    client = DocumentClient([])
    user_id = str(uuid4())
    store = SupabaseConversationStore(client, user_id)
    document_id = str(uuid4())

    document = store.save_document(
        document_id,
        "guide.pdf",
        b"%PDF-1.7 content",
        page_count=3,
        chunk_count=5,
        user_id=user_id,
    )
    signed_url = store.get_document_file_url(UUID(document_id))
    library = store.list_documents(limit=10, offset=0)

    assert document == {
        "id": document_id,
        "filename": "guide.pdf",
        "status": "ready",
        "pages": 3,
        "chunks": 5,
        "created_at": None,
    }
    assert client.documents[0]["user_id"] == user_id
    assert client.documents[0]["storage_path"] == f"{user_id}/{document_id}/document.pdf"
    assert client.bucket.uploads[0] == (
        f"{user_id}/{document_id}/document.pdf",
        b"%PDF-1.7 content",
        {"content-type": "application/pdf", "upsert": "true"},
    )
    assert signed_url == "https://example.supabase.co/signed.pdf"
    assert client.bucket.signed_urls == [(f"{user_id}/{document_id}/document.pdf", 300)]
    assert library["items"] == [document]
    assert library["has_more"] is False
