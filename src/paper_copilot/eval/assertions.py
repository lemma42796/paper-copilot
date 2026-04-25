"""Field-level + budget assertions for the eval suite.

Pure functions over JSON-shaped dicts (golden side: parsed from disk;
output side: ``Paper.model_dump(mode='json')``). No Pydantic
revalidation here — the suite owns that step. No LLM-as-judge by
design; assertions are structural and tuned to the LLM-noise floor
observed empirically — see M14 v1 实测 in TASKS.md.

Assertion strategy per field:

- ``meta``: title / year / arxiv_id exact match; ``len(authors)`` match.
  These are extracted verbatim from the paper's first page and stay
  stable across reruns.
- ``methods``: catastrophic length drop (output < 50% of golden).
  Both name-keyed alignment AND ``is_novel_to_this_paper`` checks were
  pulled — the LLM rephrases method names AND flips the novelty enum
  stochastically across no-op reruns of the same prompt/model. M15 to
  revisit with multi-run majority-vote goldens.
- ``contributions``: catastrophic length drop only. ``type`` is an
  LLM-picked enum that varies even at zero temperature, so per-type
  count enforcement triggers at the noise floor.
- ``experiments``: align by ``(dataset, metric)`` lowercased; every
  golden experiment must appear (these names are stable — they come
  from the paper's tables, not LLM phrasing).

``limitations`` and ``cross_paper_links`` deliberately have no
assertion — see ``goldens.ALLOWED_FIELDS``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from paper_copilot.shared.errors import EvalError

FailureKind = Literal[
    "missing",
    "value_mismatch",
    "len_short",
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


_HALVING_THRESHOLD = 0.5


def assert_methods(
    golden: list[dict[str, Any]], output: list[dict[str, Any]]
) -> list[FieldFailure]:
    """Catastrophic length drop only. Two M14 v1 lessons baked in:

    - Method *names* drift across reruns ('Residual Learning Framework'
      vs 'Residual Block') — silently accepted, not a regression.
    - ``is_novel_to_this_paper`` *also* flips stochastically at the
      noise floor (observed True↔False on identity shortcuts / dropout
      under the same prompt + model), because it's a semantic judgment
      with no stable LLM commitment. Per-method enum checks fired even
      on no-op reruns. Pulled out of v1; M15 to revisit with multi-run
      majority-vote goldens or a confidence-aware schema field.
    """
    fails: list[FieldFailure] = []
    if golden and len(output) < len(golden) * _HALVING_THRESHOLD:
        fails.append(
            FieldFailure(
                field="methods",
                kind="len_short",
                detail=(
                    f"golden has {len(golden)} method(s), got {len(output)} (below 50% threshold)"
                ),
            )
        )
    return fails


def assert_contributions(
    golden: list[dict[str, Any]], output: list[dict[str, Any]]
) -> list[FieldFailure]:
    """Only fail on catastrophic length drop. ``type`` is an LLM-picked
    enum that varies across reruns (e.g. ``novel_method`` vs
    ``analysis`` for the same claim), so per-type count enforcement
    produces false positives at the noise floor — see M14 v1 lesson in
    TASKS.md.
    """
    fails: list[FieldFailure] = []
    if golden and len(output) < len(golden) * _HALVING_THRESHOLD:
        fails.append(
            FieldFailure(
                field="contributions",
                kind="len_short",
                detail=(
                    f"golden has {len(golden)} contribution(s), got {len(output)} "
                    f"(below 50% threshold)"
                ),
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
