from __future__ import annotations

from typing import Any

from paper_copilot.knowledge.fields_store import PaperRow


def build_compare_payload(row_a: PaperRow, row_b: PaperRow) -> dict[str, Any]:
    a, b = row_a.data, row_b.data
    return {
        "a": {"paper_id": row_a.paper_id, "meta": a.get("meta", {})},
        "b": {"paper_id": row_b.paper_id, "meta": b.get("meta", {})},
        "contributions": {
            "a": a.get("contributions", []),
            "b": b.get("contributions", []),
        },
        "methods_aligned": [
            {
                "key": key,
                "a": a_item,
                "b": b_item,
            }
            for key, a_item, b_item in _align(
                a.get("methods", []),
                b.get("methods", []),
                lambda method: _norm(method.get("name", "")),
            )
        ],
        "experiments_aligned": [
            {
                "key": list(key),
                "a": a_item,
                "b": b_item,
            }
            for key, a_item, b_item in _align(
                a.get("experiments", []),
                b.get("experiments", []),
                lambda experiment: (
                    _norm(experiment.get("dataset", "")),
                    _norm(experiment.get("metric", "")),
                ),
            )
        ],
        "limitations": {
            "a": a.get("limitations", []),
            "b": b.get("limitations", []),
        },
        "cross_paper_links": _link_records(row_a, row_b),
    }


def _link_records(row_a: PaperRow, row_b: PaperRow) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for src, dst, direction in [(row_a, row_b, "a_to_b"), (row_b, row_a, "b_to_a")]:
        for link in src.data.get("cross_paper_links", []) or []:
            if link.get("related_paper_id") == dst.paper_id:
                out.append({"direction": direction, **link})
    return out


def _align(
    a_items: list[dict[str, Any]],
    b_items: list[dict[str, Any]],
    key_fn: Any,
) -> list[tuple[Any, dict[str, Any] | None, dict[str, Any] | None]]:
    a_by_key: dict[Any, dict[str, Any]] = {}
    for item in a_items:
        a_by_key.setdefault(key_fn(item), item)
    b_by_key: dict[Any, dict[str, Any]] = {}
    for item in b_items:
        b_by_key.setdefault(key_fn(item), item)

    rows: list[tuple[Any, dict[str, Any] | None, dict[str, Any] | None]] = []
    for key, a_item in a_by_key.items():
        if key in b_by_key:
            rows.append((key, a_item, b_by_key[key]))
    for key, a_item in a_by_key.items():
        if key not in b_by_key:
            rows.append((key, a_item, None))
    for key, b_item in b_by_key.items():
        if key not in a_by_key:
            rows.append((key, None, b_item))
    return rows


def _norm(value: str) -> str:
    return value.strip().lower()
