"""Append-only cross-paper edge log at ``<root>/graph/cross-paper-links.jsonl``.

One line per directed edge emitted by RelatedAgent. The log is the source of
truth for cross-paper relations; Paper.cross_paper_links in session.jsonl is a
denormalised copy. Kept flat + append-only because MVP has no "update" or
"delete" use case — a stale link survives until the related paper is fully
re-read, at which point a new line shadows it (readers pick the latest).

Reverse lookups (who points at paper X) scan the whole file; at Phase 2 scale
that is O(N_papers * avg_links_per_paper) < 50 rows and plenty fast.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from paper_copilot.schemas.paper import CrossPaperLink
from paper_copilot.session.paths import default_root

_REL_PATH = Path("graph") / "cross-paper-links.jsonl"


def graph_path(root: Path | None = None) -> Path:
    base = root if root is not None else default_root()
    return base / _REL_PATH


def append_links(
    paper_id: str,
    links: list[CrossPaperLink],
    *,
    root: Path | None = None,
    clock: Callable[[], str] = lambda: datetime.now(UTC).isoformat(),
) -> None:
    if not links:
        return
    path = graph_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = clock()
    with path.open("a", encoding="utf-8") as f:
        for link in links:
            row = {
                "paper_id": paper_id,
                "related_paper_id": link.related_paper_id,
                "related_title": link.related_title,
                "relation_type": link.relation_type,
                "explanation": link.explanation,
                "indexed_at": ts,
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
