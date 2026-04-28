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
from paper_copilot.eval.suite import SuiteResult
from paper_copilot.shared.errors import EvalError


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

    def to_json(self) -> dict[str, Any]:
        return {
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
                )
            )

    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row.to_json(), ensure_ascii=False))
            f.write("\n")
    return path


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
