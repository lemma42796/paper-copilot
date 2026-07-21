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


def build_multi_compare_payload(
    rows: list[PaperRow],
    aspects: list[str],
    *,
    max_items: int = 8,
) -> dict[str, Any]:
    comparison = [
        {
            "paper_id": row.paper_id,
            "meta": row.data.get("meta", {}),
            **{
                aspect: _bounded_items(row.data.get(aspect, []), max_items=max_items)
                for aspect in aspects
            },
        }
        for row in rows
    ]
    shared: dict[str, list[str]] = {}
    if "contributions" in aspects:
        shared["contribution_claims"] = _shared_values(
            rows,
            collection="contributions",
            field="claim",
            max_items=max_items,
        )
    if "methods" in aspects:
        shared["method_names"] = _shared_values(
            rows,
            collection="methods",
            field="name",
            max_items=max_items,
        )
    if "experiments" in aspects:
        shared["datasets"] = _shared_values(
            rows,
            collection="experiments",
            field="dataset",
            max_items=max_items,
        )
        shared["comparison_baselines"] = _shared_values(
            rows,
            collection="experiments",
            field="comparison_baseline",
            max_items=max_items,
        )
    if "limitations" in aspects:
        shared["limitation_descriptions"] = _shared_values(
            rows,
            collection="limitations",
            field="description",
            max_items=max_items,
        )

    payload: dict[str, Any] = {
        "papers": [
            {"paper_id": row.paper_id, "meta": row.data.get("meta", {})}
            for row in rows
        ],
        "aspects": aspects,
        "comparison": comparison,
        "shared_exact_matches": shared,
        "cross_paper_links": _multi_link_records(rows),
    }
    if len(rows) == 2:
        pairwise = build_compare_payload(rows[0], rows[1])
        payload["pairwise_alignment"] = {
            "methods_aligned": (
                pairwise["methods_aligned"][:max_items] if "methods" in aspects else []
            ),
            "experiments_aligned": (
                pairwise["experiments_aligned"][:max_items]
                if "experiments" in aspects
                else []
            ),
            "cross_paper_links": pairwise["cross_paper_links"],
        }
    return payload


def _shared_values(
    rows: list[PaperRow],
    *,
    collection: str,
    field: str,
    max_items: int,
) -> list[str]:
    values_by_paper: list[dict[str, str]] = []
    for row in rows:
        normalized: dict[str, str] = {}
        items = row.data.get(collection, [])
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                value = item.get(field)
                if isinstance(value, str) and value.strip():
                    normalized.setdefault(_norm(value), value)
        values_by_paper.append(normalized)
    if not values_by_paper:
        return []
    shared_keys = set(values_by_paper[0])
    for values in values_by_paper[1:]:
        shared_keys.intersection_update(values)
    return [values_by_paper[0][key] for key in sorted(shared_keys)[:max_items]]


def _bounded_items(value: Any, *, max_items: int) -> Any:
    return value[:max_items] if isinstance(value, list) else value


def _multi_link_records(rows: list[PaperRow]) -> list[dict[str, Any]]:
    paper_ids = {row.paper_id for row in rows}
    links: list[dict[str, Any]] = []
    for row in rows:
        for link in row.data.get("cross_paper_links", []) or []:
            if link.get("related_paper_id") in paper_ids:
                links.append({"source_paper_id": row.paper_id, **link})
    return links


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
