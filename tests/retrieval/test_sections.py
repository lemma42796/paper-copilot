from collections.abc import Callable
from pathlib import Path

import pytest

from paper_copilot.retrieval import SectionText, split_by_sections
from paper_copilot.schemas.paper import PaperSkeleton, SectionMarker
from paper_copilot.shared.errors import RetrievalError


def _sm(title: str, page_start: int, page_end: int | None, depth: int = 1) -> SectionMarker:
    return SectionMarker(title=title, page_start=page_start, page_end=page_end, depth=depth)


def test_split_by_sections_simple(make_pdf: Callable[[list[str]], Path]) -> None:
    pdf = make_pdf(["PAGE_ONE_MARK", "PAGE_TWO_MARK", "PAGE_THREE_MARK"])
    skeleton = PaperSkeleton(
        sections=[
            _sm("Intro", 1, 1, depth=1),
            _sm("Body", 2, 3, depth=1),
        ]
    )
    out = split_by_sections(pdf, skeleton)
    assert len(out) == 2
    assert all(isinstance(s, SectionText) for s in out)
    assert out[0].title == "Intro"
    assert "PAGE_ONE_MARK" in out[0].text
    assert "PAGE_TWO_MARK" not in out[0].text
    assert out[1].title == "Body"
    assert "PAGE_TWO_MARK" in out[1].text
    assert "PAGE_THREE_MARK" in out[1].text
    assert out[1].page_start == 2
    assert out[1].page_end == 3


def test_split_by_sections_page_end_none_uses_next(
    make_pdf: Callable[[list[str]], Path],
) -> None:
    pdf = make_pdf(["P1", "P2", "P3"])
    skeleton = PaperSkeleton(
        sections=[
            _sm("A", 1, None, depth=1),
            _sm("B", 3, 3, depth=1),
        ]
    )
    out = split_by_sections(pdf, skeleton)
    assert out[0].page_end == 3
    assert "P1" in out[0].text
    assert "P2" in out[0].text
    assert "P3" in out[0].text


def test_split_by_sections_last_page_end_none_uses_total_pages(
    make_pdf: Callable[[list[str]], Path],
) -> None:
    pdf = make_pdf(["P1", "P2", "P3", "P4"])
    skeleton = PaperSkeleton(
        sections=[
            _sm("Only", 2, None, depth=1),
        ]
    )
    out = split_by_sections(pdf, skeleton)
    assert out[0].page_end == 4
    assert "P2" in out[0].text
    assert "P4" in out[0].text


def test_split_by_sections_skips_parent_to_avoid_child_duplication(
    make_pdf: Callable[[list[str]], Path],
) -> None:
    pdf = make_pdf(["P1", "P2", "P3"])
    skeleton = PaperSkeleton(
        sections=[
            _sm("Parent", 1, 3, depth=1),
            _sm("Child", 2, 3, depth=2),
        ]
    )
    out = split_by_sections(pdf, skeleton)
    assert len(out) == 1
    assert out[0].title == "Child"
    assert out[0].depth == 2


def test_split_by_sections_emits_sibling_at_same_depth(
    make_pdf: Callable[[list[str]], Path],
) -> None:
    pdf = make_pdf(["P1", "P2", "P3", "P4"])
    skeleton = PaperSkeleton(
        sections=[
            _sm("A", 1, 2, depth=1),
            _sm("B", 3, 4, depth=1),
        ]
    )
    out = split_by_sections(pdf, skeleton)
    assert [s.title for s in out] == ["A", "B"]


def test_split_by_sections_parent_skipped_even_without_page_end(
    make_pdf: Callable[[list[str]], Path],
) -> None:
    pdf = make_pdf(["P1", "P2", "P3"])
    skeleton = PaperSkeleton(
        sections=[
            _sm("Parent", 1, None, depth=1),
            _sm("Child", 2, None, depth=2),
            _sm("Next", 3, 3, depth=1),
        ]
    )
    out = split_by_sections(pdf, skeleton)
    assert [s.title for s in out] == ["Child", "Next"]


def test_split_by_sections_empty_skeleton(
    make_pdf: Callable[[list[str]], Path],
) -> None:
    pdf = make_pdf(["P1"])
    skeleton = PaperSkeleton(sections=[])
    with pytest.raises(RetrievalError):
        split_by_sections(pdf, skeleton)


def test_split_by_sections_page_out_of_range(
    make_pdf: Callable[[list[str]], Path],
) -> None:
    pdf = make_pdf(["P1", "P2"])
    skeleton = PaperSkeleton(
        sections=[
            _sm("Ghost", 5, 5, depth=1),
        ]
    )
    with pytest.raises(RetrievalError):
        split_by_sections(pdf, skeleton)
