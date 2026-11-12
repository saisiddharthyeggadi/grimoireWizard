from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

Encode = Callable[..., object]


@dataclass(frozen=True)
class Paragraph:
    text: str
    page_number: int
    paragraph_number: int
    chapter_number: int | None


@dataclass(frozen=True)
class SemanticChunk:
    text: str
    page_number: int
    paragraph_number: int
    paragraph_end: int
    chapter_number: int | None
    embedding: list[float]


_CHAPTER_HEADING = re.compile(
    r"^\s{0,3}(?:#{1,6}\s*)?(?:chapter\s+)?"
    r"(?P<number>\d+|[IVXLCDM]+)(?:[.:\-]\s+|\s+|$)",
    re.IGNORECASE,
)


def _roman_to_int(value: str) -> int:
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    previous = 0
    for character in reversed(value.upper()):
        current = values[character]
        total += -current if current < previous else current
        previous = current
    return total


def chapter_number_from_heading(text: str) -> int | None:
    match = _CHAPTER_HEADING.match(text)
    if match is None:
        return None
    value = match.group("number")
    return int(value) if value.isdigit() else _roman_to_int(value)


def parse_markdown_pages(pages: Sequence[str]) -> list[list[Paragraph]]:
    """Split parsed page markdown into paragraphs and carry chapter state across pages."""
    parsed_pages: list[list[Paragraph]] = []
    current_chapter: int | None = None
    paragraph_number = 0

    for page_number, markdown in enumerate(pages, start=1):
        page_paragraphs: list[Paragraph] = []
        for raw_paragraph in re.split(r"\n\s*\n", markdown):
            text = raw_paragraph.strip()
            if not text:
                continue
            detected_chapter = chapter_number_from_heading(text)
            if detected_chapter is not None:
                current_chapter = detected_chapter
            paragraph_number += 1
            page_paragraphs.append(
                Paragraph(
                    text=text,
                    page_number=page_number,
                    paragraph_number=paragraph_number,
                    chapter_number=current_chapter,
                )
            )
        parsed_pages.append(page_paragraphs)
    return parsed_pages


def _vectors(encode: Encode, texts: Sequence[str]) -> list[list[float]]:
    result = encode(list(texts), normalize_embeddings=True)
    if hasattr(result, "tolist"):
        result = result.tolist()
    if not isinstance(result, Sequence) or isinstance(result, (str, bytes)):
        raise TypeError("The embedding model must return one vector per text.")
    vectors: list[list[float]] = []
    for row in result:
        if hasattr(row, "tolist"):
            row = row.tolist()
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)):
            raise TypeError("The embedding model returned an invalid vector.")
        vectors.append([float(value) for value in row])
    if len(vectors) != len(texts):
        raise ValueError("The embedding model returned a different number of vectors than texts.")
    return vectors


def _word_count(text: str) -> int:
    return len(text.split())


def _split_long_paragraph(paragraph: Paragraph, max_words: int) -> list[Paragraph]:
    words = paragraph.text.split()
    if len(words) <= max_words:
        return [paragraph]
    return [
        Paragraph(
            text=" ".join(words[index : index + max_words]),
            page_number=paragraph.page_number,
            paragraph_number=paragraph.paragraph_number,
            chapter_number=paragraph.chapter_number,
        )
        for index in range(0, len(words), max_words)
    ]


def _suffix_units(paragraphs: Sequence[Paragraph], word_count: int) -> list[Paragraph]:
    suffix: list[Paragraph] = []
    remaining = word_count
    for paragraph in reversed(paragraphs):
        words = paragraph.text.split()
        take = min(remaining, len(words))
        if take:
            suffix.append(
                Paragraph(
                    text=" ".join(words[-take:]),
                    page_number=paragraph.page_number,
                    paragraph_number=paragraph.paragraph_number,
                    chapter_number=paragraph.chapter_number,
                )
            )
            remaining -= take
        if remaining == 0:
            break
    suffix.reverse()
    return suffix


def build_semantic_chunks(
    paragraphs: Sequence[Paragraph],
    encode: Encode,
    *,
    similarity_threshold: float = 0.45,
    max_words: int = 300,
    overlap_words: int = 0,
) -> list[SemanticChunk]:
    """Group adjacent paragraphs by similarity, with bounded word overlap."""
    if not -1.0 <= similarity_threshold <= 1.0:
        raise ValueError("similarity_threshold must be between -1 and 1.")
    if max_words < 1:
        raise ValueError("max_words must be at least 1.")
    if not 0 <= overlap_words < max_words:
        raise ValueError("overlap_words must be between 0 and max_words - 1.")
    if not paragraphs:
        return []

    units = [
        unit
        for paragraph in paragraphs
        for unit in _split_long_paragraph(paragraph, max_words)
    ]
    unit_vectors = _vectors(encode, [unit.text for unit in units])

    groups: list[list[Paragraph]] = []
    current_group: list[Paragraph] = []
    current_words = 0
    current_new_words = 0

    def finish_group() -> None:
        nonlocal current_group, current_words, current_new_words
        if current_new_words == 0:
            return
        groups.append(current_group)
        current_group = _suffix_units(current_group, overlap_words)
        current_words = sum(_word_count(unit.text) for unit in current_group)
        current_new_words = 0

    for index, unit in enumerate(units):
        split_for_semantics = False
        if current_new_words:
            previous_vector = unit_vectors[index - 1]
            current_vector = unit_vectors[index]
            similarity = sum(a * b for a, b in zip(previous_vector, current_vector))
            split_for_semantics = (
                similarity < similarity_threshold
                or current_group[-1].chapter_number != unit.chapter_number
            )
        if split_for_semantics:
            finish_group()

        words = unit.text.split()
        if current_new_words and current_words + len(words) > max_words:
            finish_group()

        offset = 0
        while offset < len(words):
            available_words = max_words - current_words
            if available_words == 0:
                finish_group()
                available_words = max_words - current_words
            take = min(available_words, len(words) - offset)
            current_group.append(
                Paragraph(
                    text=" ".join(words[offset : offset + take]),
                    page_number=unit.page_number,
                    paragraph_number=unit.paragraph_number,
                    chapter_number=unit.chapter_number,
                )
            )
            current_words += take
            current_new_words += take
            offset += take
            if offset < len(words):
                finish_group()
    if current_new_words:
        groups.append(current_group)

    chunk_texts = ["\n\n".join(unit.text for unit in group) for group in groups]
    chunk_vectors = _vectors(encode, chunk_texts)
    return [
        SemanticChunk(
            text=text,
            page_number=group[0].page_number,
            paragraph_number=group[0].paragraph_number,
            paragraph_end=group[-1].paragraph_number,
            chapter_number=group[0].chapter_number,
            embedding=vector,
        )
        for group, text, vector in zip(groups, chunk_texts, chunk_vectors)
    ]
