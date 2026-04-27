"""Suite parsing + execution.

YAML schema:

    name: smoke
    papers:
      - paper_id: a639448e61be
        pdf: /abs/path/to/transformer.pdf
        fields: [methods, contributions]
    budget_per_paper:           # optional, absolute caps
      cost_cny: 0.20
      latency_s: 90

For each paper the runner:
1. verifies ``compute_paper_id(pdf) == paper_id`` (catches stale paths),
2. runs ``MainAgent.run`` with ``PAPER_COPILOT_HOME`` set to a fresh
   tmpdir and no embedder/stores — so RelatedAgent short-circuits and
   the user's real index is untouched (suites must be repeatable),
3. compares each requested field against its golden via
   ``assertions.assert_field``, plus the absolute budget caps.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from paper_copilot.agents.llm_client import LLMClient
from paper_copilot.agents.main import MainAgent
from paper_copilot.eval import goldens
from paper_copilot.eval.assertions import FieldFailure, assert_field
from paper_copilot.session.paths import compute_paper_id
from paper_copilot.shared.cost import CostSnapshot
from paper_copilot.shared.errors import EvalError

SuiteFieldName = Literal["meta", "contributions", "methods", "experiments"]


class PaperSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paper_id: str = Field(min_length=1)
    pdf: Path
    fields: list[SuiteFieldName] = Field(min_length=1)


class BudgetPerPaper(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cost_cny: float | None = Field(default=None, ge=0)
    latency_s: float | None = Field(default=None, ge=0)


class Suite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    papers: list[PaperSpec] = Field(min_length=1)
    budget_per_paper: BudgetPerPaper | None = None


@dataclass(frozen=True, slots=True)
class FieldResult:
    paper_id: str
    field: str
    failures: tuple[FieldFailure, ...]


@dataclass(frozen=True, slots=True)
class PaperResult:
    paper_id: str
    pdf: Path
    cost: CostSnapshot
    latency_s: float
    fields: tuple[FieldResult, ...]
    budget_failures: tuple[FieldFailure, ...]

    @property
    def passed(self) -> bool:
        if self.budget_failures:
            return False
        return all(not fr.failures for fr in self.fields)


@dataclass(frozen=True, slots=True)
class SuiteResult:
    suite_name: str
    papers: tuple[PaperResult, ...]

    @property
    def passed(self) -> bool:
        return all(p.passed for p in self.papers)


def load_suite(path: Path) -> Suite:
    if not path.exists():
        raise EvalError(f"suite file not found: {path}")
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise EvalError(f"suite file must be a YAML mapping at top level: {path}")
    return Suite.model_validate(raw)


async def run_suite(
    suite: Suite,
    *,
    goldens_dir: Path | None = None,
) -> SuiteResult:
    paper_results: list[PaperResult] = []
    for spec in suite.papers:
        paper_results.append(await _run_paper(spec, suite.budget_per_paper, goldens_dir))
    return SuiteResult(suite_name=suite.name, papers=tuple(paper_results))


async def _run_paper(
    spec: PaperSpec,
    budget: BudgetPerPaper | None,
    goldens_dir: Path | None,
) -> PaperResult:
    pdf_path = spec.pdf.expanduser()
    if not pdf_path.exists():
        raise EvalError(f"PDF not found: {pdf_path}")

    actual_id = compute_paper_id(pdf_path)
    if actual_id != spec.paper_id:
        raise EvalError(
            f"paper_id mismatch for {pdf_path}: "
            f"suite says {spec.paper_id!r}, PDF computes {actual_id!r}"
        )

    # Pre-load goldens before the LLM run so we fail fast on a missing
    # golden — no point burning ~¥0.05 to discover the user forgot to
    # `eval mark` a field.
    field_goldens: dict[str, Any] = {}
    for field in spec.fields:
        record = goldens.read(spec.paper_id, field, dir_=goldens_dir)
        field_goldens[field] = record.value

    with tempfile.TemporaryDirectory(prefix="paper-copilot-eval-") as td:
        tmproot = Path(td)
        prior_home = os.environ.get("PAPER_COPILOT_HOME")
        os.environ["PAPER_COPILOT_HOME"] = str(tmproot)
        try:
            agent = MainAgent(LLMClient(), root=tmproot)
            t0 = time.perf_counter()
            run = await agent.run(pdf_path)
            elapsed = time.perf_counter() - t0
        finally:
            if prior_home is None:
                os.environ.pop("PAPER_COPILOT_HOME", None)
            else:
                os.environ["PAPER_COPILOT_HOME"] = prior_home

    paper_dump = run.paper.model_dump(mode="json")

    field_results: list[FieldResult] = []
    for field in spec.fields:
        fails = assert_field(field, field_goldens[field], paper_dump.get(field))
        field_results.append(
            FieldResult(
                paper_id=spec.paper_id,
                field=field,
                failures=tuple(fails),
            )
        )

    budget_fails: list[FieldFailure] = []
    if budget is not None:
        if budget.cost_cny is not None and run.cost.cost_cny > budget.cost_cny:
            budget_fails.append(
                FieldFailure(
                    field="budget.cost_cny",
                    kind="budget_exceeded",
                    detail=f"cap={budget.cost_cny:.4f} got={run.cost.cost_cny:.4f}",
                )
            )
        if budget.latency_s is not None and elapsed > budget.latency_s:
            budget_fails.append(
                FieldFailure(
                    field="budget.latency_s",
                    kind="budget_exceeded",
                    detail=f"cap={budget.latency_s:.2f} got={elapsed:.2f}",
                )
            )

    return PaperResult(
        paper_id=spec.paper_id,
        pdf=pdf_path,
        cost=run.cost,
        latency_s=elapsed,
        fields=tuple(field_results),
        budget_failures=tuple(budget_fails),
    )


def run_suite_sync(suite: Suite, *, goldens_dir: Path | None = None) -> SuiteResult:
    return asyncio.run(run_suite(suite, goldens_dir=goldens_dir))
