"""Run history persistence for eval suites.

Each ``write_run(SuiteResult)`` call writes one ``eval/runs/<run_id>.jsonl``
file with a flat record per (paper_id, field). Run history feeds the
HTML trend report (``eval/report.py``); single-run pass/fail is a noisy
signal at the LLM noise floor (M14 v1 lesson) so the trend over ≥3
runs is the actual regression detector.

Layout: ``eval/runs/<run_id>.jsonl`` at repo root. ``run_id`` is a
filename-safe ISO-8601-ish UTC timestamp (``2026-04-27T15-30-45Z``);
chronological sort = lexicographic sort.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from paper_copilot.eval._paths import default_runs_dir, find_project_root
from paper_copilot.eval.retrieval import RetrievalEvalResult
from paper_copilot.eval.suite import SuiteResult
from paper_copilot.session import FinalOutput, LLMCall, SessionHeader, SessionStore
from paper_copilot.shared.errors import EvalError
from paper_copilot.shared.prompt_fingerprint import compute_prompt_bundle_sha256


@dataclass(frozen=True, slots=True)
class RunRow:
    run_id: str
    suite_name: str
    git_sha: str
    paper_id: str
    field: str
    field_passed: bool
    field_n_failures: int
    cost_cny: float
    latency_s: float
    cache_hit_ratio: float
    budget_passed: bool
    model: str | None = None
    prompt_bundle_sha256: str | None = None
    evidence_ref_count: int | None = None
    findings_claim_count: int | None = None
    findings_inline_ref_count: int | None = None
    claims_without_refs_count: int | None = None
    evidence_coverage_ratio: float | None = None
    proposal_check_passed: bool | None = None
    proposal_repair_attempted: bool | None = None
    retrieval_query: str | None = None
    retrieval_relevant_count: int | None = None
    retrieval_recall_at_5: float | None = None
    retrieval_recall_at_10: float | None = None
    retrieval_precision_at_5: float | None = None
    retrieval_precision_at_10: float | None = None
    retrieval_missed_at_5: tuple[str, ...] | None = None
    retrieval_missed_at_10: tuple[str, ...] | None = None
    retrieval_top_papers: tuple[str, ...] | None = None
    retrieval_evidence_anchor_count: int | None = None
    retrieval_evidence_recall_at_5: float | None = None
    retrieval_evidence_recall_at_10: float | None = None
    retrieval_evidence_anchor_precision_at_5: float | None = None
    retrieval_evidence_anchor_precision_at_10: float | None = None
    retrieval_missed_evidence_at_5: tuple[str, ...] | None = None
    retrieval_missed_evidence_at_10: tuple[str, ...] | None = None

    def to_json(self) -> dict[str, Any]:
        raw: dict[str, Any] = {
            "run_id": self.run_id,
            "suite_name": self.suite_name,
            "git_sha": self.git_sha,
            "paper_id": self.paper_id,
            "field": self.field,
            "field_passed": self.field_passed,
            "field_n_failures": self.field_n_failures,
            "cost_cny": self.cost_cny,
            "latency_s": self.latency_s,
            "cache_hit_ratio": self.cache_hit_ratio,
            "budget_passed": self.budget_passed,
        }
        identity = {
            "model": self.model,
            "prompt_bundle_sha256": self.prompt_bundle_sha256,
        }
        raw.update({key: value for key, value in identity.items() if value is not None})
        quality = {
            "evidence_ref_count": self.evidence_ref_count,
            "findings_claim_count": self.findings_claim_count,
            "findings_inline_ref_count": self.findings_inline_ref_count,
            "claims_without_refs_count": self.claims_without_refs_count,
            "evidence_coverage_ratio": self.evidence_coverage_ratio,
            "proposal_check_passed": self.proposal_check_passed,
            "proposal_repair_attempted": self.proposal_repair_attempted,
        }
        raw.update({key: value for key, value in quality.items() if value is not None})
        retrieval = {
            "retrieval_query": self.retrieval_query,
            "retrieval_relevant_count": self.retrieval_relevant_count,
            "retrieval_recall_at_5": self.retrieval_recall_at_5,
            "retrieval_recall_at_10": self.retrieval_recall_at_10,
            "retrieval_precision_at_5": self.retrieval_precision_at_5,
            "retrieval_precision_at_10": self.retrieval_precision_at_10,
            "retrieval_missed_at_5": _list_or_none(self.retrieval_missed_at_5),
            "retrieval_missed_at_10": _list_or_none(self.retrieval_missed_at_10),
            "retrieval_top_papers": _list_or_none(self.retrieval_top_papers),
            "retrieval_evidence_anchor_count": self.retrieval_evidence_anchor_count,
            "retrieval_evidence_recall_at_5": self.retrieval_evidence_recall_at_5,
            "retrieval_evidence_recall_at_10": self.retrieval_evidence_recall_at_10,
            "retrieval_evidence_anchor_precision_at_5": (
                self.retrieval_evidence_anchor_precision_at_5
            ),
            "retrieval_evidence_anchor_precision_at_10": (
                self.retrieval_evidence_anchor_precision_at_10
            ),
            "retrieval_missed_evidence_at_5": _list_or_none(
                self.retrieval_missed_evidence_at_5
            ),
            "retrieval_missed_evidence_at_10": _list_or_none(
                self.retrieval_missed_evidence_at_10
            ),
        }
        raw.update({key: value for key, value in retrieval.items() if value is not None})
        return raw

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> RunRow:
        return cls(
            run_id=raw["run_id"],
            suite_name=raw["suite_name"],
            git_sha=raw["git_sha"],
            paper_id=raw["paper_id"],
            field=raw["field"],
            field_passed=raw["field_passed"],
            field_n_failures=raw["field_n_failures"],
            cost_cny=raw["cost_cny"],
            latency_s=raw["latency_s"],
            cache_hit_ratio=raw["cache_hit_ratio"],
            budget_passed=raw["budget_passed"],
            model=raw.get("model"),
            prompt_bundle_sha256=raw.get("prompt_bundle_sha256"),
            evidence_ref_count=raw.get("evidence_ref_count"),
            findings_claim_count=raw.get("findings_claim_count"),
            findings_inline_ref_count=raw.get("findings_inline_ref_count"),
            claims_without_refs_count=raw.get("claims_without_refs_count"),
            evidence_coverage_ratio=raw.get("evidence_coverage_ratio"),
            proposal_check_passed=raw.get("proposal_check_passed"),
            proposal_repair_attempted=raw.get("proposal_repair_attempted"),
            retrieval_query=raw.get("retrieval_query"),
            retrieval_relevant_count=raw.get("retrieval_relevant_count"),
            retrieval_recall_at_5=raw.get("retrieval_recall_at_5"),
            retrieval_recall_at_10=raw.get("retrieval_recall_at_10"),
            retrieval_precision_at_5=raw.get(
                "retrieval_precision_at_5",
                _legacy_retrieval_precision(raw, k=5),
            ),
            retrieval_precision_at_10=raw.get(
                "retrieval_precision_at_10",
                _legacy_retrieval_precision(raw, k=10),
            ),
            retrieval_missed_at_5=_tuple_or_none(raw.get("retrieval_missed_at_5")),
            retrieval_missed_at_10=_tuple_or_none(raw.get("retrieval_missed_at_10")),
            retrieval_top_papers=_tuple_or_none(raw.get("retrieval_top_papers")),
            retrieval_evidence_anchor_count=raw.get("retrieval_evidence_anchor_count"),
            retrieval_evidence_recall_at_5=raw.get("retrieval_evidence_recall_at_5"),
            retrieval_evidence_recall_at_10=raw.get("retrieval_evidence_recall_at_10"),
            retrieval_evidence_anchor_precision_at_5=raw.get(
                "retrieval_evidence_anchor_precision_at_5"
            ),
            retrieval_evidence_anchor_precision_at_10=raw.get(
                "retrieval_evidence_anchor_precision_at_10"
            ),
            retrieval_missed_evidence_at_5=_tuple_or_none(
                raw.get("retrieval_missed_evidence_at_5")
            ),
            retrieval_missed_evidence_at_10=_tuple_or_none(
                raw.get("retrieval_missed_evidence_at_10")
            ),
        )


def make_run_id(now: datetime | None = None) -> str:
    ts = now if now is not None else datetime.now(UTC)
    # ``2026-04-27T15-30-45Z`` — colons stripped so the filename is portable.
    return ts.strftime("%Y-%m-%dT%H-%M-%SZ")


def _git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=find_project_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip() or "unknown"


def _cache_hit_ratio(input_tokens: int, cache_read: int, cache_create: int) -> float:
    # Disjoint accounting: Dashscope reports cached and non-cached
    # input tokens separately (see shared/cost.py). Total billed prompt
    # volume is the sum; ratio is the share that hit cache.
    total = input_tokens + cache_read + cache_create
    if total == 0:
        return 0.0
    return cache_read / total


def write_run(
    result: SuiteResult,
    *,
    runs_dir: Path | None = None,
    run_id: str | None = None,
    git_sha: str | None = None,
) -> Path:
    rid = run_id if run_id is not None else make_run_id()
    sha = git_sha if git_sha is not None else _git_sha()
    base = runs_dir if runs_dir is not None else default_runs_dir()
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{rid}.jsonl"
    if path.exists():
        raise EvalError(f"run file already exists: {path}")

    rows: list[RunRow] = []
    for paper in result.papers:
        cost = paper.cost
        ratio = _cache_hit_ratio(
            cost.input_tokens, cost.cache_read_tokens, cost.cache_creation_tokens
        )
        budget_passed = not paper.budget_failures
        for fr in paper.fields:
            rows.append(
                RunRow(
                    run_id=rid,
                    suite_name=result.suite_name,
                    git_sha=sha,
                    paper_id=paper.paper_id,
                    field=fr.field,
                    field_passed=not fr.failures,
                    field_n_failures=len(fr.failures),
                    cost_cny=cost.cost_cny,
                    latency_s=paper.latency_s,
                    cache_hit_ratio=ratio,
                    budget_passed=budget_passed,
                    model=paper.model,
                    prompt_bundle_sha256=paper.prompt_bundle_sha256,
                )
            )

    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row.to_json(), ensure_ascii=False))
            f.write("\n")
    return path


def write_research_quality_run(
    session_path: Path,
    *,
    runs_dir: Path | None = None,
    run_id: str | None = None,
    git_sha: str | None = None,
    suite_name: str = "research",
) -> Path:
    rid = run_id if run_id is not None else make_run_id()
    sha = git_sha if git_sha is not None else _git_sha()
    base = runs_dir if runs_dir is not None else default_runs_dir()
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{rid}.jsonl"
    if path.exists():
        raise EvalError(f"run file already exists: {path}")

    header, final, prompt_bundle_sha256 = _read_research_final(session_path)
    quality = _quality_payload(final)
    cost = _cost_payload(final)
    unsupported_count = _int_quality(quality, "claims_without_refs_count")
    proposal_failure_count = _proposal_failure_count(final)
    failure_count = unsupported_count + proposal_failure_count
    row = RunRow(
        run_id=rid,
        suite_name=suite_name,
        git_sha=sha,
        paper_id=suite_name,
        field="research_quality",
        field_passed=failure_count == 0,
        field_n_failures=failure_count,
        cost_cny=_float_cost(cost, "cost_cny"),
        latency_s=0.0,
        cache_hit_ratio=_cache_hit_ratio(
            _int_cost(cost, "input_tokens"),
            _int_cost(cost, "cache_read_tokens"),
            _int_cost(cost, "cache_creation_tokens"),
        ),
        budget_passed=True,
        model=header.model,
        prompt_bundle_sha256=prompt_bundle_sha256,
        evidence_ref_count=_int_quality(quality, "evidence_ref_count"),
        findings_claim_count=_int_quality(quality, "findings_claim_count"),
        findings_inline_ref_count=_int_quality(quality, "findings_inline_ref_count"),
        claims_without_refs_count=unsupported_count,
        evidence_coverage_ratio=_float_quality(quality, "evidence_coverage_ratio"),
        proposal_check_passed=_optional_nested_bool(
            final,
            parent="proposal_check",
            key="passed",
        ),
        proposal_repair_attempted=_optional_nested_bool(
            final,
            parent="proposal_repair",
            key="attempted",
        ),
    )

    path.write_text(
        json.dumps(row.to_json(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def write_retrieval_run(
    result: RetrievalEvalResult,
    *,
    runs_dir: Path | None = None,
    run_id: str | None = None,
    git_sha: str | None = None,
) -> Path:
    rid = run_id if run_id is not None else make_run_id()
    sha = git_sha if git_sha is not None else _git_sha()
    base = runs_dir if runs_dir is not None else default_runs_dir()
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{rid}.jsonl"
    if path.exists():
        raise EvalError(f"run file already exists: {path}")

    with path.open("w", encoding="utf-8") as f:
        for query in result.queries:
            missed_evidence = query.missed_evidence_at_10
            row = RunRow(
                run_id=rid,
                suite_name=result.suite_name,
                git_sha=sha,
                paper_id=query.query_id,
                field="retrieval_recall",
                field_passed=not query.missed_at_10 and not missed_evidence,
                field_n_failures=len(query.missed_at_10) + len(missed_evidence),
                cost_cny=0.0,
                latency_s=0.0,
                cache_hit_ratio=0.0,
                budget_passed=True,
                retrieval_query=query.query,
                retrieval_relevant_count=len(query.relevant_papers),
                retrieval_recall_at_5=query.recall_at_5,
                retrieval_recall_at_10=query.recall_at_10,
                retrieval_precision_at_5=query.precision_at_5,
                retrieval_precision_at_10=query.precision_at_10,
                retrieval_missed_at_5=query.missed_at_5,
                retrieval_missed_at_10=query.missed_at_10,
                retrieval_top_papers=tuple(hit.paper_id for hit in query.hits),
                retrieval_evidence_anchor_count=query.evidence_anchor_count,
                retrieval_evidence_recall_at_5=query.evidence_recall_at_5,
                retrieval_evidence_recall_at_10=query.evidence_recall_at_10,
                retrieval_evidence_anchor_precision_at_5=(
                    query.evidence_anchor_precision_at_5
                ),
                retrieval_evidence_anchor_precision_at_10=(
                    query.evidence_anchor_precision_at_10
                ),
                retrieval_missed_evidence_at_5=query.missed_evidence_at_5,
                retrieval_missed_evidence_at_10=query.missed_evidence_at_10,
            )
            f.write(json.dumps(row.to_json(), ensure_ascii=False))
            f.write("\n")
    return path


def _read_research_final(
    session_path: Path,
) -> tuple[SessionHeader, FinalOutput, str | None]:
    if not session_path.exists():
        raise EvalError(f"session file not found: {session_path}")
    entries = SessionStore(session_path, last_id="").read_all()
    header = next((e for e in entries if isinstance(e, SessionHeader)), None)
    if header is None:
        raise EvalError(f"session header not found: {session_path}")
    final = next((e for e in reversed(entries) if isinstance(e, FinalOutput)), None)
    if final is None:
        raise EvalError(f"final_output not found: {session_path}")
    prompt_bundle_sha256 = compute_prompt_bundle_sha256(
        (entry.agent, entry.prompt_sha256)
        for entry in entries
        if isinstance(entry, LLMCall) and entry.prompt_sha256 is not None
    )
    return header, final, prompt_bundle_sha256


def _quality_payload(final: FinalOutput) -> dict[str, Any]:
    quality = final.payload.get("quality")
    if not isinstance(quality, dict):
        raise EvalError("final_output.quality missing; rerun research with M17 quality payload")
    return quality


def _cost_payload(final: FinalOutput) -> dict[str, Any]:
    cost = final.payload.get("cost")
    return cost if isinstance(cost, dict) else {}


def _proposal_failure_count(final: FinalOutput) -> int:
    proposal_check = final.payload.get("proposal_check")
    if not isinstance(proposal_check, dict) or proposal_check.get("passed") is not False:
        return 0
    issues = proposal_check.get("issues")
    if not isinstance(issues, list):
        return 1
    error_count = 0
    for issue in issues:
        if isinstance(issue, dict) and issue.get("severity") == "error":
            error_count += 1
    return max(error_count, 1)


def _optional_nested_bool(
    final: FinalOutput,
    *,
    parent: str,
    key: str,
) -> bool | None:
    payload = final.payload.get(parent)
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    return value if isinstance(value, bool) else None


def _int_quality(quality: dict[str, Any], key: str) -> int:
    value = quality.get(key)
    if not isinstance(value, int):
        raise EvalError(f"final_output.quality.{key} missing or not an int")
    return value


def _float_quality(quality: dict[str, Any], key: str) -> float:
    value = quality.get(key)
    if not isinstance(value, int | float):
        raise EvalError(f"final_output.quality.{key} missing or not a number")
    return float(value)


def _int_cost(cost: dict[str, Any], key: str) -> int:
    value = cost.get(key, 0)
    return value if isinstance(value, int) else 0


def _float_cost(cost: dict[str, Any], key: str) -> float:
    value = cost.get(key, 0.0)
    return float(value) if isinstance(value, int | float) else 0.0


def _tuple_or_none(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value)
    return None


def _list_or_none(value: tuple[str, ...] | None) -> list[str] | None:
    if value is None:
        return None
    return list(value)


def _legacy_retrieval_precision(raw: dict[str, Any], *, k: int) -> float | None:
    relevant_count = raw.get("retrieval_relevant_count")
    missed = raw.get(f"retrieval_missed_at_{k}")
    top_papers = raw.get("retrieval_top_papers")
    if not isinstance(relevant_count, int) or not isinstance(missed, list | tuple):
        return None
    if not isinstance(top_papers, list | tuple):
        return None
    denominator = min(k, len(top_papers))
    if denominator == 0:
        return 0.0
    return (relevant_count - len(missed)) / denominator


def load_history(
    *,
    runs_dir: Path | None = None,
    suite_name: str | None = None,
    last: int | None = None,
) -> list[RunRow]:
    base = runs_dir if runs_dir is not None else default_runs_dir()
    if not base.exists():
        return []
    files = sorted(p for p in base.iterdir() if p.suffix == ".jsonl")
    if last is not None:
        # Filter by suite first when filtering, then truncate — otherwise
        # ``last=5`` could return zero rows if the most recent 5 files
        # belong to a different suite.
        if suite_name is not None:
            files = [
                f
                for f in files
                if _peek_suite_name(f) == suite_name
            ]
        files = files[-last:]
    rows: list[RunRow] = []
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = RunRow.from_json(json.loads(line))
            if suite_name is not None and row.suite_name != suite_name:
                continue
            rows.append(row)
    return rows


def _peek_suite_name(path: Path) -> str | None:
    with path.open("r", encoding="utf-8") as f:
        line = f.readline().strip()
    if not line:
        return None
    value = json.loads(line).get("suite_name")
    return value if isinstance(value, str) else None
