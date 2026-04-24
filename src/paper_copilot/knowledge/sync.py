"""Sync a validated ``Paper`` into the fields index.

The caller owns loading: online from ``MainAgent.run`` passes a fresh
``Paper`` object, batch reindex (see ``cli/commands/reindex.py``) passes
the raw JSON payload read from ``session.jsonl``. Both converge here so
the store stays ignorant of pydantic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from paper_copilot.schemas import Paper

from .fields_store import FieldsStore


def index_paper(
    paper: Paper | dict[str, Any],
    paper_id: str,
    store: FieldsStore,
    *,
    indexed_at: str | None = None,
) -> None:
    payload = paper.model_dump(mode="json") if isinstance(paper, Paper) else paper
    ts = indexed_at if indexed_at is not None else datetime.now(UTC).isoformat()
    store.upsert(paper_id, payload, ts)
