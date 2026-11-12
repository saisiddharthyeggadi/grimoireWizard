from pathlib import Path

import pytest

from grimoire_ingest.pipeline import (
    EMBEDDING_DIMENSIONS,
    build_chunk_records,
    upload_chunk_records,
)


class FixedEncoder:
    def encode(self, texts, normalize_embeddings=True):
        return [[1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1) for _ in texts]


class Query:
    def __init__(self, client, operation, records=None):
        self.client = client
        self.operation = operation
        self.records = records

    def execute(self):
        self.client.calls.append((self.operation, self.records))
        return None

    def eq(self, *_args):
        return self

    def gte(self, *_args):
        return self


class Table:
    def __init__(self, client):
        self.client = client

    def upsert(self, records, on_conflict):
        assert on_conflict == "document_id,chunk_index"
        return Query(self.client, "upsert", records)

    def delete(self):
        return Query(self.client, "delete")


class FakeClient:
    def __init__(self):
        self.calls = []

    def table(self, _table_name):
        return Table(self)


def test_chunk_records_include_required_metadata_and_384d_vectors(tmp_path):
    pdf_path = tmp_path / "guide.pdf"
    pdf_path.write_bytes(b"pdf bytes")

    document_id, records, paragraph_count = build_chunk_records(
        pdf_path,
        ["# Chapter 1: Start\n\nA useful paragraph."],
        FixedEncoder(),
    )

    assert paragraph_count == 2
    assert len(records) == 1
    assert records[0]["document_id"] == document_id
    assert records[0]["chapter_number"] == 1
    assert records[0]["page_number"] == 1
    assert records[0]["paragraph_number"] == 1
    assert records[0]["metadata"]["source_file"] == "guide.pdf"
    assert records[0]["metadata"]["paragraph_end"] == 2
    assert len(records[0]["embedding"]) == EMBEDDING_DIMENSIONS


def test_build_chunk_records_passes_overlap_words_to_chunker(tmp_path):
    pdf_path = tmp_path / "guide.pdf"
    pdf_path.write_bytes(b"pdf bytes")

    _, records, _ = build_chunk_records(
        pdf_path,
        ["one two three four five six seven eight nine ten"],
        FixedEncoder(),
        max_words=5,
        overlap_words=2,
    )

    assert [record["content"].split() for record in records] == [
        ["one", "two", "three", "four", "five"],
        ["four", "five", "six", "seven", "eight"],
        ["seven", "eight", "nine", "ten"],
    ]


def test_upload_batches_records_and_removes_stale_trailing_chunks():
    client = FakeClient()
    records = [
        {"document_id": "doc", "chunk_index": index}
        for index in range(3)
    ]

    upload_chunk_records(client, records, batch_size=2)

    assert [call[0] for call in client.calls] == ["upsert", "upsert", "delete"]
    assert len(client.calls[0][1]) == 2
    assert len(client.calls[1][1]) == 1


def test_rejects_vectors_with_wrong_dimension(tmp_path):
    pdf_path = tmp_path / "guide.pdf"
    pdf_path.write_bytes(b"pdf bytes")

    class WrongDimensionEncoder:
        def encode(self, texts, normalize_embeddings=True):
            return [[0.1, 0.2] for _ in texts]

    with pytest.raises(ValueError, match="expected 384"):
        build_chunk_records(pdf_path, ["A useful paragraph."], WrongDimensionEncoder())
