from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from paper_copilot.session.paths import default_root
from paper_copilot.session.store import SessionStore
from paper_copilot.session.types import FinalOutput, SessionEntry, SessionHeader


@dataclass(frozen=True, slots=True)
class ChatReportItem:
    id: str
    request: str
    report_markdown: str
    session_path: Path
    report_path: Path
    updated_at: str
    termination_reason: str
    cost_cny: float | None
    events_count: int | None
    paper_budget: dict[str, object]
    composer_plan: dict[str, Any] | None
    proposal_check: dict[str, Any] | None


def list_chat_reports(*, root: Path | None = None, limit: int = 20) -> list[ChatReportItem]:
    home = root if root is not None else default_root()
    papers_dir = home / "papers"
    if not papers_dir.exists():
        return []

    report_paths = sorted(
        papers_dir.glob("*/research-report.md"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return [_read_report(path) for path in report_paths[:limit]]


def _read_report(report_path: Path) -> ChatReportItem:
    session_path = report_path.parent / "session.jsonl"
    entries = SessionStore(session_path, last_id="").read_all()
    header = _first_header(entries)
    final = _last_final_output(entries)
    payload = final.payload
    stat = report_path.stat()

    return ChatReportItem(
        id=report_path.parent.name,
        request=_request_field(payload, default=header.paper_id),
        report_markdown=report_path.read_text(encoding="utf-8"),
        session_path=session_path,
        report_path=report_path,
        updated_at=datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        termination_reason=_string_field(payload, "termination_reason", default="unknown"),
        cost_cny=_cost_field(payload.get("cost")),
        events_count=_events_count_field(payload.get("termination_summary")),
        paper_budget=_object_dict_field(payload.get("paper_budget")),
        composer_plan=_optional_object_dict_field(payload.get("composer_plan")),
        proposal_check=_optional_object_dict_field(payload.get("proposal_check")),
    )


def _first_header(entries: list[SessionEntry]) -> SessionHeader:
    for entry in entries:
        if isinstance(entry, SessionHeader):
            return entry
    raise ValueError("session header not found")


def _last_final_output(entries: list[SessionEntry]) -> FinalOutput:
    for entry in reversed(entries):
        if isinstance(entry, FinalOutput):
            return entry
    raise ValueError("final output not found")


def _string_field(payload: Mapping[str, Any], key: str, *, default: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else default


def _request_field(payload: Mapping[str, Any], *, default: str) -> str:
    return _string_field(
        payload,
        "prompt",
        default=_string_field(payload, "topic", default=default),
    )


def _cost_field(value: object) -> float | None:
    if not isinstance(value, Mapping):
        return None
    cost = value.get("cost_cny")
    return float(cost) if isinstance(cost, int | float) else None


def _events_count_field(value: object) -> int | None:
    if not isinstance(value, Mapping):
        return None
    events_count = value.get("events_count")
    return events_count if isinstance(events_count, int) else None


def _object_dict_field(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _optional_object_dict_field(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return {str(key): item for key, item in value.items()}
