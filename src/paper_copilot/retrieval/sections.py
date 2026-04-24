from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from paper_copilot.schemas.paper import PaperSkeleton
from paper_copilot.shared.errors import RetrievalError
from paper_copilot.shared.pdf import extract_page_range, get_page_count

__all__ = ["SectionText", "split_by_sections"]


@dataclass(frozen=True, slots=True)
class SectionText:
    title: str
    page_start: int
    page_end: int
    depth: int
    text: str


def split_by_sections(pdf_path: Path, skeleton: PaperSkeleton) -> list[SectionText]:
    sections = skeleton.sections
    if not sections:
        raise RetrievalError("skeleton.sections is empty; nothing to split")

    total_pages = get_page_count(pdf_path)
    out: list[SectionText] = []
    for i, sec in enumerate(sections):
        if sec.page_start > total_pages:
            raise RetrievalError(
                f"section {sec.title!r} page_start={sec.page_start} "
                f"exceeds total_pages={total_pages}"
            )
        # A section whose immediately-following sibling is deeper in the tree is
        # a parent; extract_page_range would sweep across its children's pages
        # and duplicate their content — the child emits the same pages again.
        # Skip parents; leaves carry the actual body text.
        if i + 1 < len(sections) and sections[i + 1].depth > sec.depth:
            continue
        if sec.page_end is not None:
            inferred_end = sec.page_end
        elif i + 1 < len(sections):
            inferred_end = sections[i + 1].page_start
        else:
            inferred_end = total_pages
        text = extract_page_range(pdf_path, sec.page_start, inferred_end)
        out.append(
            SectionText(
                title=sec.title,
                page_start=sec.page_start,
                page_end=inferred_end,
                depth=sec.depth,
                text=text,
            )
        )
    return out
