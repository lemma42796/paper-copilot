from __future__ import annotations

import re

import pytest

from paper_copilot.shared.chunking import CharSpan, Section, chunk_sections


def word_spans(text: str) -> list[CharSpan]:
    """Mock tokenizer: each whitespace-delimited word is one 'token'."""
    return [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]


def _section(title: str, text: str, ps: int = 1, pe: int = 1) -> Section:
    return Section(title=title, page_start=ps, page_end=pe, text=text)


def test_empty_sections_yields_no_chunks() -> None:
    assert chunk_sections([], token_spans=word_spans) == []


def test_blank_section_skipped() -> None:
    assert chunk_sections([_section("S", "   \n  ")], token_spans=word_spans) == []


def test_short_section_emits_single_chunk() -> None:
    sec = _section("Intro", "one two three four", ps=2, pe=2)
    chunks = chunk_sections([sec], token_spans=word_spans, max_tokens=10, overlap_tokens=2)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.section_title == "Intro"
    assert c.page_start == 2
    assert c.page_end == 2
    assert c.text == "one two three four"
    assert c.ord == 0


def test_long_section_splits_with_overlap() -> None:
    text = " ".join(f"w{i}" for i in range(10))
    chunks = chunk_sections(
        [_section("Method", text)],
        token_spans=word_spans,
        max_tokens=4,
        overlap_tokens=1,
    )
    # stride=3, n=10: windows start at 0, 3, 6; the 6→10 window ends at n and stops.
    assert [c.text for c in chunks] == [
        "w0 w1 w2 w3",
        "w3 w4 w5 w6",
        "w6 w7 w8 w9",
    ]
    assert [c.ord for c in chunks] == [0, 1, 2]


def test_ord_continues_across_sections() -> None:
    a = _section("A", "a1 a2 a3", ps=1, pe=1)
    b = _section("B", "b1 b2 b3", ps=2, pe=2)
    chunks = chunk_sections([a, b], token_spans=word_spans, max_tokens=10, overlap_tokens=2)
    assert [c.section_title for c in chunks] == ["A", "B"]
    assert [c.ord for c in chunks] == [0, 1]
    assert chunks[1].page_start == 2


def test_chunks_do_not_cross_section_boundary() -> None:
    a = _section("A", "a1 a2 a3", ps=1, pe=1)
    b = _section("B", "b1 b2 b3", ps=2, pe=2)
    # max_tokens large enough to swallow both, but chunker must still split.
    chunks = chunk_sections([a, b], token_spans=word_spans, max_tokens=100, overlap_tokens=8)
    assert len(chunks) == 2
    assert chunks[0].text == "a1 a2 a3"
    assert chunks[1].text == "b1 b2 b3"


def test_invalid_overlap_raises() -> None:
    with pytest.raises(ValueError):
        chunk_sections([], token_spans=word_spans, max_tokens=10, overlap_tokens=10)
    with pytest.raises(ValueError):
        chunk_sections([], token_spans=word_spans, max_tokens=0)
