from __future__ import annotations

import hashlib
import math
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from .semantic import build_semantic_chunks, parse_markdown_pages

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384
TABLE_NAME = "document_chunks"
UPLOAD_BATCH_SIZE = 100
MAX_PDF_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_PDF_PAGES = 1000


def _pdf_page_count(pdf_path: Path) -> int:
    import pymupdf

    with pymupdf.open(pdf_path) as document:
        return document.page_count


def parse_pdf_pages(pdf_path: Path) -> list[str]:
    import pymupdf4llm

    page_chunks = pymupdf4llm.to_markdown(str(pdf_path), page_chunks=True)
    pages: list[str] = []
    for page_number, page in enumerate(page_chunks, start=1):
        if not isinstance(page, Mapping):
            raise TypeError(f"PDF parser returned invalid data for page {page_number}.")
        text = page.get("text", page.get("markdown", ""))
        if not isinstance(text, str):
            raise TypeError(f"PDF parser returned non-text content for page {page_number}.")
        pages.append(text)
    return pages


def load_encoder() -> Any:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def _content_id(pdf_path: Path) -> tuple[str, str]:
    digest = hashlib.sha256()
    with pdf_path.open("rb") as pdf_file:
        for block in iter(lambda: pdf_file.read(1024 * 1024), b""):
            digest.update(block)
    checksum = digest.hexdigest()
    document_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"sha256:{checksum}"))
    return document_id, checksum


def _validate_embedding(embedding: Sequence[float], chunk_index: int) -> list[float]:
    vector = [float(value) for value in embedding]
    if len(vector) != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Chunk {chunk_index} has {len(vector)} embedding dimensions; "
            f"expected {EMBEDDING_DIMENSIONS}."
        )
    if not all(math.isfinite(value) for value in vector):
        raise ValueError(f"Chunk {chunk_index} has a non-finite embedding value.")
    return vector


def build_chunk_records(
    pdf_path: Path,
    pages: Sequence[str],
    encoder: Any,
    *,
    similarity_threshold: float = 0.45,
    max_words: int = 300,
    overlap_words: int = 0,
    user_id: str | None = None,
) -> tuple[str, list[dict[str, Any]], int]:
    document_id, checksum = _content_id(pdf_path)
    if user_id is not None:
        document_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"user:{UUID(user_id)}:sha256:{checksum}")
        )
    parsed_pages = parse_markdown_pages(pages)
    records: list[dict[str, Any]] = []
    tokenizer = getattr(encoder, "tokenizer", None)
    max_tokens = getattr(encoder, "max_seq_length", None)
    if (tokenizer is None) != (max_tokens is None):
        raise TypeError(
            "The embedding encoder must expose both tokenizer and max_seq_length."
        )
    token_count = (
        lambda text: len(tokenizer.encode(text, add_special_tokens=True))
        if tokenizer is not None
        else None
    )

    for page_paragraphs in parsed_pages:
        chunks = build_semantic_chunks(
            page_paragraphs,
            encoder.encode,
            similarity_threshold=similarity_threshold,
            max_words=max_words,
            overlap_words=overlap_words,
            max_tokens=max_tokens,
            token_count=token_count if tokenizer is not None else None,
        )
        for chunk in chunks:
            chunk_index = len(records)
            records.append(
                {
                    "document_id": document_id,
                    "user_id": user_id,
                    "chunk_index": chunk_index,
                    "content": chunk.text,
                    "embedding": _validate_embedding(chunk.embedding, chunk_index),
                    "chapter_number": chunk.chapter_number,
                    "page_number": chunk.page_number,
                    "paragraph_number": chunk.paragraph_number,
                    "metadata": {
                        "source_file": pdf_path.name,
                        "sha256": checksum,
                        "paragraph_end": chunk.paragraph_end,
                        "embedding_model": MODEL_NAME,
                    },
                }
            )
    if not records:
        raise ValueError(f"No extractable text was found in {pdf_path.name}.")
    return document_id, records, sum(len(page) for page in parsed_pages)


def upload_chunk_records(
    client: Any,
    records: Sequence[dict[str, Any]],
    *,
    batch_size: int = UPLOAD_BATCH_SIZE,
) -> None:
    if not records:
        raise ValueError("Cannot upload an empty document.")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")

    document_id = records[0]["document_id"]
    if any(record["document_id"] != document_id for record in records):
        raise ValueError("All records in one upload must have the same document_id.")

    for start in range(0, len(records), batch_size):
        batch = list(records[start : start + batch_size])
        client.table(TABLE_NAME).upsert(
            batch,
            on_conflict="document_id,chunk_index",
        ).execute()

    client.table(TABLE_NAME).delete().eq("document_id", document_id).gte(
        "chunk_index", len(records)
    ).execute()


def ingest_pdf(
    pdf_path: Path,
    client: Any,
    *,
    encoder: Any | None = None,
    parser: Callable[[Path], list[str]] = parse_pdf_pages,
    similarity_threshold: float = 0.45,
    max_words: int = 300,
    overlap_words: int = 0,
    user_id: str | None = None,
) -> dict[str, int | str]:
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a .pdf file: {pdf_path}")
    if pdf_path.stat().st_size > MAX_PDF_UPLOAD_BYTES:
        raise ValueError("PDF exceeds the configured maximum file size.")
    page_count = _pdf_page_count(pdf_path)
    if page_count > MAX_PDF_PAGES:
        raise ValueError("PDF exceeds the 1,000-page maximum.")

    pages = parser(pdf_path)
    active_encoder = encoder if encoder is not None else load_encoder()
    document_id, records, paragraph_count = build_chunk_records(
        pdf_path,
        pages,
        active_encoder,
        similarity_threshold=similarity_threshold,
        max_words=max_words,
        overlap_words=overlap_words,
        user_id=user_id,
    )
    upload_chunk_records(client, records)
    client.table("documents").upsert(
        {
            "id": document_id,
            "user_id": user_id,
            "sha256": records[0]["metadata"]["sha256"],
            "filename": pdf_path.name,
            "storage_path": None,
            "status": "ready",
            "page_count": len(pages),
            "chunk_count": len(records),
            "error": None,
        },
        on_conflict="id",
        ignore_duplicates=True,
    ).execute()
    return {
        "document_id": document_id,
        "pages": len(pages),
        "paragraphs": paragraph_count,
        "chunks": len(records),
    }
