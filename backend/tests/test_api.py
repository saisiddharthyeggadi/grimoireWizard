from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from grimoire_api.config import Settings
from grimoire_api.main import create_app


class FakeStore:
    def __init__(self):
        self.conversation_id = uuid4()
        self.document_id = uuid4()
        self.client = object()
        self.messages = []
        self.attached = []

    def create_conversation(self, title):
        return {"id": str(self.conversation_id), "title": title or "New conversation"}

    def list_conversations(self, limit, offset):
        rows = [{"id": str(self.conversation_id)}, {"id": str(uuid4())}]
        return rows[offset : offset + limit + 1]

    def get_conversation(self, conversation_id):
        if conversation_id != self.conversation_id:
            return None
        return {
            "id": str(self.conversation_id),
            "title": "Notes",
            "documents": list(self.attached),
        }

    def get_document(self, document_id):
        if document_id != self.document_id:
            return None
        return {"id": str(document_id), "filename": "guide.pdf", "status": "ready"}

    def attach_document(self, conversation_id, document_id):
        self.attached.append(self.get_document(document_id))

    def get_messages(self, _conversation_id):
        return self.messages

    def save_message(self, _conversation_id, role, content, citations=None):
        message = {
            "id": str(uuid4()),
            "role": role,
            "content": content,
            "citations": citations or [],
        }
        self.messages.append(message)
        return message

    def search_chunks(self, _embedding, _question, _document_ids):
        return [
            {
                "chunk_id": 7,
                "document_id": str(self.document_id),
                "content": "The guide says to follow the example.",
                "page_number": 2,
                "metadata": {},
            }
        ]


class FakeEncoder:
    def encode(self, _questions, normalize_embeddings=True):
        assert normalize_embeddings
        return [[1.0] + [0.0] * 383]


class FakeCompletions:
    def create(self, **kwargs):
        if not kwargs.get("stream"):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="guide example steps")
                    )
                ]
            )
        return [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="Follow the example [1].")
                    )
                ]
            )
        ]


def _client(store=None, **options):
    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="server-secret-placeholder",
        gemini_api_key="test-key",
        llm_model="test-model",
    )
    return TestClient(
        create_app(
            store=store or FakeStore(),
            settings=settings,
            **options,
        )
    )


def test_health_and_conversation_creation():
    client = _client()
    assert client.get("/health").json() == {"status": "ok"}

    response = client.post("/conversations", json={"title": "Research"})
    empty_response = client.post("/conversations")

    assert response.status_code == 201
    assert response.json()["title"] == "Research"
    assert empty_response.status_code == 201
    assert empty_response.json()["title"] == "New conversation"


def test_settings_load_gemini_key_and_default_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("LLM_API_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("LLM_BASE_URL", "https://legacy.example/v1")
    monkeypatch.delenv("LLM_MODEL", raising=False)

    settings = Settings.from_environment()

    assert settings.gemini_api_key == "gemini-test-key"
    assert settings.llm_model == "gemini-4-hydrogen"


def test_gemini_client_ignores_local_llm_url(monkeypatch):
    observed = {}
    store = FakeStore()
    store.attach_document(store.conversation_id, store.document_id)
    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="server-secret-placeholder",
        gemini_api_key="gemini-test-key",
        llm_model="test-model",
    )
    llm_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )

    def fake_openai(*, api_key, base_url):
        observed["api_key"] = api_key
        observed["base_url"] = base_url
        return llm_client

    monkeypatch.setattr("grimoire_api.main.OpenAI", fake_openai)
    client = TestClient(create_app(store=store, encoder=FakeEncoder(), settings=settings))

    response = client.post(
        f"/conversations/{store.conversation_id}/messages",
        json={"content": "Question"},
    )

    assert response.status_code == 200
    assert "event: done" in response.text
    assert observed == {
        "api_key": "gemini-test-key",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
    }


def test_upload_pdf_ingests_and_returns_document_details(monkeypatch):
    observed = {}

    def fake_ingest(pdf_path, client):
        observed["filename"] = pdf_path.name
        observed["content"] = pdf_path.read_bytes()
        observed["client"] = client
        return {
            "document_id": "doc-id",
            "pages": 2,
            "paragraphs": 4,
            "chunks": 3,
        }

    monkeypatch.setattr("grimoire_api.main.ingest_pdf", fake_ingest)
    store = FakeStore()
    response = _client(store).post(
        "/documents",
        files={"file": ("guide.pdf", b"%PDF-1.7 test content", "application/pdf")},
    )

    assert response.status_code == 201
    assert response.json() == {
        "document_id": "doc-id",
        "pages": 2,
        "paragraphs": 4,
        "chunks": 3,
        "filename": "guide.pdf",
        "status": "ready",
    }
    assert observed["filename"] == "guide.pdf"
    assert observed["content"] == b"%PDF-1.7 test content"
    assert observed["client"] is store.client


def test_upload_pdf_rejects_non_pdf_files():
    response = _client().post(
        "/documents",
        files={"file": ("guide.txt", b"not a pdf", "text/plain")},
    )

    assert response.status_code == 415


def test_upload_pdf_rejects_invalid_pdf_content():
    response = _client().post(
        "/documents",
        files={"file": ("guide.pdf", b"not a pdf", "application/pdf")},
    )

    assert response.status_code == 415


def test_conversation_list_is_paginated():
    response = _client().get("/conversations?limit=1&offset=0")

    assert response.status_code == 200
    assert response.json()["limit"] == 1
    assert len(response.json()["items"]) == 1
    assert response.json()["has_more"]


def test_attach_document_requires_indexed_document():
    store = FakeStore()
    client = _client(store)
    conversation_id = store.conversation_id
    missing_document = uuid4()

    missing = client.post(
        f"/conversations/{conversation_id}/documents",
        json={"document_id": str(missing_document)},
    )
    ready = client.post(
        f"/conversations/{conversation_id}/documents",
        json={"document_id": str(store.document_id)},
    )

    assert missing.status_code == 404
    assert ready.status_code == 201
    assert ready.json()["filename"] == "guide.pdf"
    assert client.get(f"/conversations/{conversation_id}").json()["documents"]


def test_message_endpoint_streams_and_persists_answer_and_citations():
    store = FakeStore()
    llm_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    client = _client(store, encoder=FakeEncoder(), llm_client=llm_client)
    conversation_id = store.conversation_id
    store.attach_document(conversation_id, store.document_id)

    response = client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "  What does the guide say?  "},
    )

    assert response.status_code == 200
    assert "event: status" in response.text
    assert "event: token" in response.text
    assert "event: citations" in response.text
    assert "event: done" in response.text
    assert [message["role"] for message in store.messages] == ["user", "assistant"]
    assert store.messages[-1]["citations"][0]["page"] == 2
    assert len(client.get(f"/conversations/{conversation_id}/messages").json()) == 2


def test_message_requires_an_attached_document():
    store = FakeStore()
    response = _client(store).post(
        f"/conversations/{store.conversation_id}/messages",
        json={"content": "Question"},
    )

    assert response.status_code == 409


def test_message_stream_reports_missing_llm_configuration():
    store = FakeStore()
    store.attach_document(store.conversation_id, store.document_id)
    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="server-secret-placeholder",
        gemini_api_key=None,
        llm_model="test-model",
    )
    client = TestClient(create_app(store=store, settings=settings))

    response = client.post(
        f"/conversations/{store.conversation_id}/messages",
        json={"content": "Question"},
    )

    assert response.status_code == 200
    assert '"code": "llm_unavailable"' in response.text
    assert '"retryable": true' in response.text


def test_invalid_conversation_id_is_rejected():
    response = _client().get("/conversations/not-a-uuid")

    assert response.status_code == 422
