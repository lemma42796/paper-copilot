"""Sliding-window chunker used by the cross-paper index and (later) the
single-paper DeepAgent retrieval.

Lives in ``shared/`` because ``retrieval/`` and ``knowledge/`` are sibling
modules that cannot import each other; both build their own ``Section``
inputs and consume the same chunker.

The chunker is tokenizer-agnostic. Callers inject a ``token_spans``
function — for production the bge-m3 fast tokenizer's ``offset_mapping``;
for tests, a whitespace splitter. Chunks never cross section boundaries:
a section is the smallest semantic unit the ranker has to score.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

__all__ = ["CharSpan", "Chunk", "Section", "TokenSpansFn", "chunk_sections"]


CharSpan = tuple[int, int]
TokenSpansFn = Callable[[str], list[CharSpan]]


@dataclass(frozen=True, slots=True)
class Section:
    title: str
    page_start: int
    page_end: int
    text: str


@dataclass(frozen=True, slots=True)
class Chunk:
    section_title: str
    page_start: int
    page_end: int
    ord: int
    text: str


def chunk_sections(
    sections: list[Section],
    *,
    token_spans: TokenSpansFn,
    max_tokens: int = 512,
    overlap_tokens: int = 64,
) -> list[Chunk]:
    if max_tokens <= 0:
        raise ValueError(f"max_tokens must be positive, got {max_tokens}")
    if not 0 <= overlap_tokens < max_tokens:
        raise ValueError(
            f"overlap_tokens must be in [0, max_tokens); got {overlap_tokens} vs {max_tokens}"
        )

    stride = max_tokens - overlap_tokens
    out: list[Chunk] = []
    ord_ = 0
    for sec in sections:
        if not sec.text.strip():
            continue
        spans = token_spans(sec.text)
        n = len(spans)
        if n == 0:
            continue
        start = 0
        while start < n:
            end = min(start + max_tokens, n)
            char_start, _ = spans[start]
            _, char_end = spans[end - 1]
            text = sec.text[char_start:char_end].strip()
            if text:
                out.append(
                    Chunk(
                        section_title=sec.title,
                        page_start=sec.page_start,
                        page_end=sec.page_end,
                        ord=ord_,
                        text=text,
                    )
                )
                ord_ += 1
            if end == n:
                break
            start += stride
    return out
