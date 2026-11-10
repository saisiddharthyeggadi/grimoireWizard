from grimoire_ingest.semantic import (
    Paragraph,
    build_semantic_chunks,
    chapter_number_from_heading,
    parse_markdown_pages,
)


class KeywordEncoder:
    def encode(self, texts, normalize_embeddings=True):
        vectors = []
        for text in texts:
            if "unrelated" in text.lower():
                vectors.append([-1.0, 0.0])
            else:
                vectors.append([1.0, 0.0])
        return vectors


def test_splits_when_adjacent_paragraphs_are_semantically_distant():
    paragraphs = [
        Paragraph("Related text.", 1, 1, 1),
        Paragraph("Unrelated text.", 1, 2, 1),
    ]

    chunks = build_semantic_chunks(paragraphs, KeywordEncoder().encode)

    assert [chunk.text for chunk in chunks] == ["Related text.", "Unrelated text."]
    assert [chunk.paragraph_number for chunk in chunks] == [1, 2]


def test_respects_page_chapter_and_maximum_word_boundaries():
    paragraphs = [
        Paragraph("one two three four five", 2, 4, 2),
        Paragraph("six seven", 2, 5, 2),
    ]

    chunks = build_semantic_chunks(
        paragraphs,
        KeywordEncoder().encode,
        similarity_threshold=-1.0,
        max_words=5,
    )

    assert [len(chunk.text.split()) for chunk in chunks] == [5, 2]
    assert all(chunk.page_number == 2 and chunk.chapter_number == 2 for chunk in chunks)


def test_tracks_chapter_and_document_wide_paragraph_numbers_across_pages():
    pages = [
        "# Chapter IV: Beginnings\n\nFirst paragraph.",
        "Second paragraph.\n\n# 5. Next chapter\n\nThird paragraph.",
    ]

    parsed = parse_markdown_pages(pages)

    assert [(p.page_number, p.paragraph_number, p.chapter_number) for p in parsed[0]] == [
        (1, 1, 4),
        (1, 2, 4),
    ]
    assert [(p.page_number, p.paragraph_number, p.chapter_number) for p in parsed[1]] == [
        (2, 3, 4),
        (2, 4, 5),
        (2, 5, 5),
    ]


def test_chapter_heading_parser_ignores_regular_prose():
    assert chapter_number_from_heading("Chapter 12: The End") == 12
    assert chapter_number_from_heading("A paragraph beginning with words") is None
