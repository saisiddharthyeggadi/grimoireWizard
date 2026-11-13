from __future__ import annotations

import json
import logging
import math
import shutil
import tempfile
import time
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openai import OpenAI, OpenAIError, RateLimitError
from postgrest.exceptions import APIError
from pydantic import BaseModel, Field
from supabase import create_client

from grimoire_ingest.pipeline import ingest_pdf

from .config import Settings
from .store import SupabaseConversationStore

logger = logging.getLogger(__name__)
EMBEDDING_DIMENSIONS = 384
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
MAX_PDF_UPLOAD_BYTES = 50 * 1024 * 1024


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)


class DocumentAttach(BaseModel):
    document_id: UUID


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)


@lru_cache(maxsize=1)
def load_encoder() -> Any:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL)


def _client_store(settings: Settings) -> SupabaseConversationStore:
    settings.validate_supabase()
    client = create_client(
        settings.supabase_url or "",
        settings.supabase_service_role_key or "",
    )
    return SupabaseConversationStore(client)


def _get_store(request: Request) -> SupabaseConversationStore:
    store = request.app.state.store
    if store is None:
        store = _client_store(request.app.state.settings)
        request.app.state.store = store
    return store


def _get_encoder(request: Request) -> Any:
    return request.app.state.encoder or load_encoder()


def _get_llm_client(request: Request) -> OpenAI:
    existing = request.app.state.llm_client
    if existing is not None:
        return existing
    settings: Settings = request.app.state.settings
    if not settings.gemini_api_key:
        raise RuntimeError("Set GEMINI_API_KEY to enable conversation responses.")
    client = OpenAI(
        api_key=settings.gemini_api_key,
        base_url=GEMINI_BASE_URL,
    )
    request.app.state.llm_client = client
    return client


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _error_event(code: str, message: str, retryable: bool) -> str:
    return _sse(
        "error",
        {"code": code, "message": message, "retryable": retryable},
    )


def _query_vector(encoder: Any, question: str) -> list[float]:
    result = encoder.encode([question], normalize_embeddings=True)
    if hasattr(result, "tolist"):
        result = result.tolist()
    if not result:
        raise ValueError("The query encoder returned no vector.")
    vector = result[0]
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    values = [float(value) for value in vector]
    if len(values) != EMBEDDING_DIMENSIONS or not all(map(math.isfinite, values)):
        raise ValueError("The query encoder returned an invalid 384-dimensional vector.")
    return values


def _rewrite_query(llm_client: OpenAI, model: str, question: str) -> str:
    response = llm_client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "Rewrite the user's question as a concise document-search query. "
                    "Preserve named entities and important terms. Return only the query."
                ),
            },
            {"role": "user", "content": question},
        ],
    )
    rewritten = response.choices[0].message.content
    if not rewritten or not rewritten.strip():
        raise ValueError("The query rewriting model returned an empty query.")
    return rewritten.strip()


def _make_citations(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations = []
    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        citations.append(
            {
                "chunk_id": chunk.get("chunk_id", chunk.get("id")),
                "document_id": chunk["document_id"],
                "page": chunk["page_number"],
                "bboxes": metadata.get("bboxes", []),
                "snippet": chunk["content"][:500],
            }
        )
    return citations


def _answer_stream(
    store: SupabaseConversationStore,
    llm_client: OpenAI,
    settings: Settings,
    conversation_id: UUID,
    question: str,
    document_ids: list[UUID],
    encoder: Any,
) -> Iterator[str]:
    started = time.monotonic()
    yield _sse("status", {"status": "rewriting"})
    try:
        rewritten_question = _rewrite_query(llm_client, settings.llm_model, question)
    except RateLimitError:
        logger.exception("The configured LLM rate limit was reached during query rewriting.")
        yield _error_event(
            "rate_limited", "The answer service is rate limited.", True
        )
        return
    except OpenAIError:
        logger.exception("The configured LLM could not rewrite the chat query.")
        yield _error_event(
            "llm_unavailable", "The answer service is unavailable.", True
        )
        return
    except (IndexError, TypeError, ValueError):
        logger.exception("The configured LLM returned an invalid rewritten query.")
        yield _error_event(
            "internal_error", "The query could not be processed.", False
        )
        return
    try:
        query_embedding = _query_vector(encoder, rewritten_question)
    except (RuntimeError, TypeError, ValueError):
        logger.exception("Could not encode a chat query.")
        yield _error_event(
            "internal_error", "The query could not be processed.", False
        )
        return

    yield _sse("status", {"status": "retrieving"})
    try:
        chunks = store.search_chunks(query_embedding, rewritten_question, document_ids)
    except APIError:
        logger.exception("Document retrieval failed.")
        yield _error_event("internal_error", "Document retrieval failed.", True)
        return
    if not chunks:
        yield _error_event(
            "document_not_ready",
            "No indexed content was found in the attached documents.",
            False,
        )
        return

    yield _sse("status", {"status": "reranking"})
    citations = _make_citations(chunks)
    context = "\n\n".join(
        f"[{index + 1}] {chunk['content']}" for index, chunk in enumerate(chunks)
    )
    yield _sse("status", {"status": "generating"})
    answer_parts: list[str] = []
    try:
        completion = llm_client.chat.completions.create(
            model=settings.llm_model,
            temperature=0.2,
            stream=True,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Answer the user using the supplied document excerpts. "
                        "If they do not contain the answer, say so. Cite sources "
                        "with bracketed excerpt numbers such as [1].\n\n"
                        f"Document excerpts:\n{context}"
                    ),
                },
                {"role": "user", "content": question},
            ],
        )
        for part in completion:
            delta = part.choices[0].delta.content
            if delta:
                answer_parts.append(delta)
                yield _sse("token", {"text": delta})
    except RateLimitError:
        logger.exception("The configured LLM rate limit was reached.")
        yield _error_event("rate_limited", "The answer service is rate limited.", True)
        return
    except OpenAIError:
        logger.exception("The configured LLM could not generate an answer.")
        yield _error_event("llm_unavailable", "The answer service is unavailable.", True)
        return

    answer = "".join(answer_parts)
    if not answer:
        yield _error_event(
            "llm_unavailable", "The answer service returned no answer.", True
        )
        return
    try:
        message = store.save_message(conversation_id, "assistant", answer, citations)
    except APIError:
        logger.exception("Could not persist the generated assistant message.")
        yield _error_event("internal_error", "The answer could not be saved.", True)
        return
    yield _sse("citations", {"citations": citations})
    yield _sse(
        "done",
        {
            "message_id": message["id"],
            "timings_ms": {"total": round((time.monotonic() - started) * 1000)},
        },
    )


def create_app(
    *,
    store: SupabaseConversationStore | None = None,
    encoder: Any | None = None,
    llm_client: OpenAI | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    app = FastAPI(title="Grimoire Wizard API", version="0.1.0")
    app.state.settings = settings or Settings.from_environment()
    app.state.store = store
    app.state.encoder = encoder
    app.state.llm_client = llm_client
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(app.state.settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Accept", "Content-Type"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/documents", status_code=status.HTTP_201_CREATED)
    def upload_document(
        request: Request, file: UploadFile = File(...)
    ) -> dict[str, Any]:
        filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        if not filename or Path(filename).suffix.lower() != ".pdf":
            raise HTTPException(status_code=415, detail="Upload a PDF file.")

        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)
        if file_size > MAX_PDF_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"PDF exceeds the {MAX_PDF_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.",
            )
        if b"%PDF-" not in file.file.read(1024):
            raise HTTPException(status_code=415, detail="The uploaded file is not a PDF.")
        file.file.seek(0)

        with tempfile.TemporaryDirectory(prefix="grimoire-upload-") as directory:
            pdf_path = Path(directory) / filename
            with pdf_path.open("wb") as destination:
                shutil.copyfileobj(file.file, destination)
            try:
                result = ingest_pdf(pdf_path, _get_store(request).client)
            except APIError as error:
                logger.exception("Supabase failed to store uploaded PDF chunks.")
                raise HTTPException(
                    status_code=502,
                    detail="Supabase could not store the PDF. Check the backend log.",
                ) from error
            except (OSError, TypeError, ValueError) as error:
                logger.exception("The uploaded PDF could not be ingested.")
                raise HTTPException(
                    status_code=422,
                    detail=f"Could not process this PDF: {error}",
                ) from error
            finally:
                file.file.close()

        return {
            **result,
            "filename": filename,
            "status": "ready",
        }

    @app.post("/conversations", status_code=status.HTTP_201_CREATED)
    def create_conversation(
        request: Request, body: ConversationCreate | None = None
    ) -> dict[str, Any]:
        return _get_store(request).create_conversation(body.title if body else None)

    @app.get("/conversations")
    def list_conversations(
        request: Request,
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        rows = _get_store(request).list_conversations(limit, offset)
        return {
            "items": rows[:limit],
            "limit": limit,
            "offset": offset,
            "has_more": len(rows) > limit,
        }

    @app.get("/conversations/{conversation_id}")
    def get_conversation(conversation_id: UUID, request: Request) -> dict[str, Any]:
        conversation = _get_store(request).get_conversation(conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        return conversation

    @app.get("/conversations/{conversation_id}/messages")
    def get_messages(conversation_id: UUID, request: Request) -> list[dict[str, Any]]:
        store = _get_store(request)
        if store.get_conversation(conversation_id) is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        return store.get_messages(conversation_id)

    @app.post(
        "/conversations/{conversation_id}/documents",
        status_code=status.HTTP_201_CREATED,
    )
    def attach_document(
        conversation_id: UUID, body: DocumentAttach, request: Request
    ) -> dict[str, Any]:
        store = _get_store(request)
        if store.get_conversation(conversation_id) is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        document = store.get_document(body.document_id)
        if document is None:
            raise HTTPException(
                status_code=404, detail="Document is not indexed or is not ready."
            )
        store.attach_document(conversation_id, body.document_id)
        return document

    @app.post("/conversations/{conversation_id}/messages")
    def send_message(
        conversation_id: UUID, body: MessageCreate, request: Request
    ) -> StreamingResponse:
        question = body.content.strip()
        if not question:
            raise HTTPException(status_code=422, detail="Message content cannot be blank.")
        store = _get_store(request)
        conversation = store.get_conversation(conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        documents = conversation.get("documents", [])
        if not documents:
            raise HTTPException(
                status_code=409, detail="Attach a ready document before asking a question."
            )
        store.save_message(conversation_id, "user", question)
        settings: Settings = request.app.state.settings
        try:
            llm_client = _get_llm_client(request)
        except RuntimeError as error:
            llm_client = None
            configuration_error = str(error)
        else:
            configuration_error = ""

        def events() -> Iterator[str]:
            if llm_client is None:
                yield _error_event("llm_unavailable", configuration_error, True)
                return
            try:
                encoder = _get_encoder(request)
            except (ImportError, OSError, RuntimeError):
                logger.exception("Could not load the query embedding model.")
                yield _error_event(
                    "internal_error",
                    "The query embedding model is unavailable.",
                    True,
                )
                return
            yield from _answer_stream(
                store,
                llm_client,
                settings,
                conversation_id,
                question,
                [UUID(document["id"]) for document in documents],
                encoder,
            )

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run(
        "grimoire_api.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
