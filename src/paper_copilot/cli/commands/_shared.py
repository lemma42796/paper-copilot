"""Shared CLI argument helpers."""

from __future__ import annotations

from pathlib import Path

from paper_copilot.session.paths import compute_paper_id


def resolve_paper_arg(arg: str) -> str:
    """Accept either a 12-char paper_id or a path to a PDF; return the paper_id."""
    p = Path(arg)
    if p.is_file():
        return compute_paper_id(p)
    return arg
