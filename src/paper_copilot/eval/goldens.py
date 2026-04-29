"""Golden record I/O. One JSON file per (paper_id, field).

Layout: ``eval/goldens/<paper_id>_<field>.json`` at repo root. Goldens
are project artifacts (committed to git), distinct from the user's
``~/.paper-copilot/`` runtime data.

A golden captures one top-level Paper field at the moment a human
judged the output good. Suite runs later compare new pipeline output
against these to detect regressions.

``limitations`` and ``cross_paper_links`` are deliberately excluded
from ``ALLOWED_FIELDS``: limitations have no stable structural key for
alignment, and cross_paper_links are skipped per the M14 plan because
suite runs use an isolated tmpdir where the candidate library is
empty.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from paper_copilot.eval._paths import default_goldens_dir
from paper_copilot.session import SessionStore
from paper_copilot.shared.errors import EvalError

ALLOWED_FIELDS: tuple[str, ...] = ("meta", "contributions", "methods", "experiments")


@dataclass(frozen=True, slots=True)
class GoldenRecord:
    paper_id: str
    field: str
    marked_at: str
    value: Any  # JSON-shaped: dict for `meta`, list for the others.

    def to_json(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "field": self.field,
            "marked_at": self.marked_at,
            "value": self.value,
        }


def file_path(paper_id: str, field: str, *, dir_: Path | None = None) -> Path:
    base = dir_ if dir_ is not None else default_goldens_dir()
    return base / f"{paper_id}_{field}.json"


def write(record: GoldenRecord, *, dir_: Path | None = None) -> Path:
    if record.field not in ALLOWED_FIELDS:
        raise EvalError(f"unsupported field {record.field!r}; allowed: {', '.join(ALLOWED_FIELDS)}")
    path = file_path(record.paper_id, record.field, dir_=dir_)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record.to_json(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def read(paper_id: str, field: str, *, dir_: Path | None = None) -> GoldenRecord:
    path = file_path(paper_id, field, dir_=dir_)
    if not path.exists():
        raise EvalError(f"no golden at {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return GoldenRecord(
        paper_id=raw["paper_id"],
        field=raw["field"],
        marked_at=raw["marked_at"],
        value=raw["value"],
    )


def mark_from_session(
    paper_id: str,
    fields: tuple[str, ...] | list[str],
    *,
    root: Path | None = None,
    dir_: Path | None = None,
) -> list[GoldenRecord]:
    """Snapshot the latest ``final_output`` from a paper's session.jsonl
    into one golden file per requested field. Overwrites prior goldens.
    """
    invalid = [f for f in fields if f not in ALLOWED_FIELDS]
    if invalid:
        raise EvalError(f"unsupported field(s) {invalid}; allowed: {', '.join(ALLOWED_FIELDS)}")

    store = SessionStore.load(paper_id, root=root)
    final = store.last_final_output()
    if final is None:
        raise EvalError(
            f"no final_output in session for {paper_id}; run `paper-copilot read` first"
        )

    marked_at = datetime.now(UTC).isoformat()

    records: list[GoldenRecord] = []
    for field in fields:
        if field not in final.payload:
            raise EvalError(f"field {field!r} not present in session final_output")
        record = GoldenRecord(
            paper_id=paper_id,
            field=field,
            marked_at=marked_at,
            value=final.payload[field],
        )
        write(record, dir_=dir_)
        records.append(record)
    return records
