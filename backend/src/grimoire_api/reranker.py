from __future__ import annotations

import math
from collections.abc import Sequence
from functools import lru_cache
from typing import Any

RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANKER_CANDIDATE_COUNT = 25
RERANKER_KEEP_COUNT = 3


@lru_cache(maxsize=1)
def _load_reranker() -> Any:
    from sentence_transformers import CrossEncoder

    return CrossEncoder(RERANKER_MODEL)


def rerank_chunks(
    question: str,
    chunks: Sequence[dict[str, Any]],
    *,
    model: Any | None = None,
    keep_count: int = RERANKER_KEEP_COUNT,
) -> list[dict[str, Any]]:
    if keep_count < 1:
        raise ValueError("keep_count must be at least 1.")
    if not chunks:
        return []

    active_model = model if model is not None else _load_reranker()
    pairs = [[question, chunk["content"]] for chunk in chunks]
    raw_scores = active_model.predict(pairs)
    if hasattr(raw_scores, "tolist"):
        raw_scores = raw_scores.tolist()
    scores = [float(score) for score in raw_scores]
    if len(scores) != len(chunks):
        raise ValueError("The reranker returned a different number of scores than chunks.")
    if not all(math.isfinite(score) for score in scores):
        raise ValueError("The reranker returned a non-finite score.")

    ranked = sorted(
        enumerate(chunks),
        key=lambda item: (-scores[item[0]], item[0]),
    )
    return [chunk for _, chunk in ranked[:keep_count]]
