from pathlib import Path

import pytest

from grimoire_ingest.pipeline import (
    EMBEDDING_DIMENSIONS,
    build_chunk_records,
    ingest_pdf,
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
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name

    def upsert(self, records, on_conflict, **options):
        expected_conflict = (
            "document_id,chunk_index"
            if self.table_name == "document_chunks"
            else "id"
        )
        assert on_conflict == expected_conflict
        if self.table_name == "documents":
            assert options == {"ignore_duplicates": True}
        return Query(self.client, "upsert", records)

    def delete(self):
        return Query(self.client, "delete")


class FakeClient:
    def __init__(self):
        self.calls = []

    def table(self, table_name):
        return Table(self, table_name)


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
    assert records[0]["user_id"] is None


def test_document_ids_are_scoped_to_user_for_identical_pdf_bytes(tmp_path):
    pdf_path = tmp_path / "guide.pdf"
    pdf_path.write_bytes(b"same pdf bytes")

    first_id, first_records, _ = build_chunk_records(
        pdf_path,
        ["A useful paragraph."],
        FixedEncoder(),
        user_id="00000000-0000-4000-8000-000000000001",
    )
    second_id, second_records, _ = build_chunk_records(
        pdf_path,
        ["A useful paragraph."],
        FixedEncoder(),
        user_id="00000000-0000-4000-8000-000000000002",
    )

    assert first_id != second_id
    assert first_records[0]["user_id"] == "00000000-0000-4000-8000-000000000001"
    assert second_records[0]["user_id"] == "00000000-0000-4000-8000-000000000002"


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


def test_build_chunk_records_respects_encoder_tokenizer_limit(tmp_path):
    class LimitedEncoder(FixedEncoder):
        max_seq_length = 6

        class Tokenizer:
            def encode(self, text, add_special_tokens=True):
                return [0, *text.split(), 1] if add_special_tokens else text.split()

        tokenizer = Tokenizer()

    pdf_path = tmp_path / "guide.pdf"
    pdf_path.write_bytes(b"pdf bytes")

    _, records, _ = build_chunk_records(
        pdf_path,
        ["one two three four five six seven eight"],
        LimitedEncoder(),
        overlap_words=1,
    )

    assert all(
        len(LimitedEncoder.tokenizer.encode(record["content"])) <= 6
        for record in records
    )


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


def test_ingestion_records_document_metadata(tmp_path, monkeypatch):
    pdf_path = tmp_path / "guide.pdf"
    pdf_path.write_bytes(b"pdf bytes")
    client = FakeClient()
    monkeypatch.setattr("grimoire_ingest.pipeline._pdf_page_count", lambda _path: 1)

    result = ingest_pdf(
        pdf_path,
        client,
        parser=lambda _path: ["A useful paragraph."],
        encoder=FixedEncoder(),
    )

    assert result["pages"] == 1
    metadata = client.calls[-1][1]
    assert metadata["id"] == result["document_id"]
    assert metadata["filename"] == "guide.pdf"
    assert metadata["status"] == "ready"
    assert metadata["page_count"] == 1
    assert metadata["chunk_count"] == result["chunks"]
    assert metadata["storage_path"] is None


def test_rejects_vectors_with_wrong_dimension(tmp_path):
    pdf_path = tmp_path / "guide.pdf"
    pdf_path.write_bytes(b"pdf bytes")

    class WrongDimensionEncoder:
        def encode(self, texts, normalize_embeddings=True):
            return [[0.1, 0.2] for _ in texts]

    with pytest.raises(ValueError, match="expected 384"):
        build_chunk_records(pdf_path, ["A useful paragraph."], WrongDimensionEncoder())


def test_ingestion_rejects_pdf_over_page_limit(tmp_path, monkeypatch):
    pdf_path = tmp_path / "guide.pdf"
    pdf_path.write_bytes(b"pdf bytes")
    parser_called = False

    def parser(_path):
        nonlocal parser_called
        parser_called = True
        return ["A useful paragraph."]

    monkeypatch.setattr("grimoire_ingest.pipeline._pdf_page_count", lambda _path: 1001)

    with pytest.raises(ValueError, match="1,000-page maximum"):
        ingest_pdf(pdf_path, object(), parser=parser, encoder=FixedEncoder())

    assert not parser_called


def test_ingestion_rejects_pdf_over_file_size_limit(tmp_path, monkeypatch):
    pdf_path = tmp_path / "guide.pdf"
    pdf_path.write_bytes(b"pdf bytes")
    monkeypatch.setattr("grimoire_ingest.pipeline.MAX_PDF_UPLOAD_BYTES", 4)

    with pytest.raises(ValueError, match="configured maximum file size"):
        ingest_pdf(pdf_path, object(), encoder=FixedEncoder())
