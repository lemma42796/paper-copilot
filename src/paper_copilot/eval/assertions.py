"""Field-level + budget assertions for the eval suite.

Pure functions over JSON-shaped dicts (golden side: parsed from disk;
output side: ``Paper.model_dump(mode='json')``). No Pydantic
revalidation here — the suite owns that step. No LLM-as-judge by
design; assertions are structural and keep on the side of caution
(false positives are worse than false negatives in a regression test).

Assertion strategy per field:

- ``meta``: title / year / arxiv_id exact match; ``len(authors)`` match.
- ``methods``: align by case-insensitive ``name``; every golden method
  must appear in output with the same ``is_novel_to_this_paper`` value.
- ``contributions``: ``len(output) >= len(golden)``, plus per-``type``
  count must not regress. No claim-text match (LLM rewording is normal).
- ``experiments``: align by ``(dataset, metric)`` lowercased; every
  golden experiment must appear.

``limitations`` and ``cross_paper_links`` deliberately have no
assertion — see ``goldens.ALLOWED_FIELDS``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from paper_copilot.shared.errors import EvalError

FailureKind = Literal[
    "missing",
    "value_mismatch",
    "len_short",
    "type_count_short",
    "budget_exceeded",
]


@dataclass(frozen=True, slots=True)
class FieldFailure:
    field: str
    kind: FailureKind
    detail: str


def assert_field(field_name: str, golden_value: Any, output_value: Any) -> list[FieldFailure]:
    match field_name:
        case "meta":
            return assert_meta(golden_value, output_value)
        case "contributions":
            return assert_contributions(golden_value, output_value)
        case "methods":
            return assert_methods(golden_value, output_value)
        case "experiments":
            return assert_experiments(golden_value, output_value)
        case _:
            raise EvalError(f"no assertion registered for field {field_name!r}")


def assert_meta(golden: dict[str, Any], output: dict[str, Any]) -> list[FieldFailure]:
    fails: list[FieldFailure] = []
    for key in ("title", "year", "arxiv_id"):
        if golden.get(key) != output.get(key):
            fails.append(
                FieldFailure(
                    field=f"meta.{key}",
                    kind="value_mismatch",
                    detail=f"golden={golden.get(key)!r}, got={output.get(key)!r}",
                )
            )
    g_authors = len(golden.get("authors") or [])
    o_authors = len(output.get("authors") or [])
    if g_authors != o_authors:
        fails.append(
            FieldFailure(
                field="meta.authors",
                kind="value_mismatch",
                detail=f"golden has {g_authors} author(s), got {o_authors}",
            )
        )
    return fails


def assert_methods(
    golden: list[dict[str, Any]], output: list[dict[str, Any]]
) -> list[FieldFailure]:
    fails: list[FieldFailure] = []
    output_by_key: dict[str, dict[str, Any]] = {}
    for m in output:
        output_by_key.setdefault(_norm(m.get("name", "")), m)

    for gm in golden:
        key = _norm(gm.get("name", ""))
        display = gm.get("name", key) or "(unnamed)"
        if key not in output_by_key:
            fails.append(
                FieldFailure(
                    field=f"methods[{display}]",
                    kind="missing",
                    detail=f"golden method {display!r} absent in output",
                )
            )
            continue
        om = output_by_key[key]
        g_novel = gm.get("is_novel_to_this_paper")
        o_novel = om.get("is_novel_to_this_paper")
        if g_novel != o_novel:
            fails.append(
                FieldFailure(
                    field=f"methods[{display}].is_novel_to_this_paper",
                    kind="value_mismatch",
                    detail=f"golden={g_novel}, got={o_novel}",
                )
            )
    return fails


def assert_contributions(
    golden: list[dict[str, Any]], output: list[dict[str, Any]]
) -> list[FieldFailure]:
    fails: list[FieldFailure] = []
    if len(output) < len(golden):
        fails.append(
            FieldFailure(
                field="contributions",
                kind="len_short",
                detail=f"golden has {len(golden)} contribution(s), got {len(output)}",
            )
        )

    g_counts = Counter(c.get("type") for c in golden)
    o_counts = Counter(c.get("type") for c in output)
    for ctype, g_n in g_counts.items():
        o_n = o_counts.get(ctype, 0)
        if o_n < g_n:
            fails.append(
                FieldFailure(
                    field=f"contributions[type={ctype}]",
                    kind="type_count_short",
                    detail=f"golden has {g_n}, got {o_n}",
                )
            )
    return fails


def assert_experiments(
    golden: list[dict[str, Any]], output: list[dict[str, Any]]
) -> list[FieldFailure]:
    fails: list[FieldFailure] = []
    output_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for e in output:
        key = (_norm(e.get("dataset", "")), _norm(e.get("metric", "")))
        output_by_key.setdefault(key, e)

    for ge in golden:
        key = (_norm(ge.get("dataset", "")), _norm(ge.get("metric", "")))
        display = f"{ge.get('dataset', '?')} / {ge.get('metric', '?')}"
        if key not in output_by_key:
            fails.append(
                FieldFailure(
                    field=f"experiments[{display}]",
                    kind="missing",
                    detail=f"golden experiment {display!r} absent in output",
                )
            )
    return fails


def assert_budget(
    *,
    golden_cost_cny: float,
    output_cost_cny: float,
    golden_latency_s: float,
    output_latency_s: float,
    factor: float = 1.5,
) -> list[FieldFailure]:
    fails: list[FieldFailure] = []
    cost_cap = golden_cost_cny * factor
    if output_cost_cny > cost_cap:
        fails.append(
            FieldFailure(
                field="budget.cost_cny",
                kind="budget_exceeded",
                detail=(
                    f"golden={golden_cost_cny:.4f} cap={cost_cap:.4f} got={output_cost_cny:.4f}"
                ),
            )
        )
    lat_cap = golden_latency_s * factor
    if output_latency_s > lat_cap:
        fails.append(
            FieldFailure(
                field="budget.latency_s",
                kind="budget_exceeded",
                detail=(
                    f"golden={golden_latency_s:.2f} cap={lat_cap:.2f} got={output_latency_s:.2f}"
                ),
            )
        )
    return fails


def _norm(s: str) -> str:
    return s.strip().lower()
