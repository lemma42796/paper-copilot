from __future__ import annotations

from paper_copilot.eval.report import render_html
from paper_copilot.eval.runs import RunRow


def _row(
    run_id: str,
    *,
    coverage: float | None = None,
    claims: int | None = None,
    unsupported: int | None = None,
) -> RunRow:
    return RunRow(
        run_id=run_id,
        suite_name="research",
        git_sha="sha",
        paper_id="research",
        field="research_quality",
        field_passed=unsupported == 0,
        field_n_failures=unsupported or 0,
        cost_cny=0.01,
        latency_s=0.0,
        cache_hit_ratio=0.0,
        budget_passed=True,
        evidence_ref_count=2,
        findings_claim_count=claims,
        findings_inline_ref_count=1,
        claims_without_refs_count=unsupported,
        evidence_coverage_ratio=coverage,
    )


def _retrieval_row(run_id: str, *, query_id: str, recall_5: float, recall_10: float) -> RunRow:
    return RunRow(
        run_id=run_id,
        suite_name="text_embedding_v4_seed_retrieval",
        git_sha="sha",
        paper_id=query_id,
        field="retrieval_recall",
        field_passed=recall_10 == 1.0,
        field_n_failures=0 if recall_10 == 1.0 else 1,
        cost_cny=0.0,
        latency_s=0.0,
        cache_hit_ratio=0.0,
        budget_passed=True,
        retrieval_query="query",
        retrieval_relevant_count=1,
        retrieval_recall_at_5=recall_5,
        retrieval_recall_at_10=recall_10,
        retrieval_missed_at_5=(),
        retrieval_missed_at_10=(),
        retrieval_top_papers=("p1",),
    )


def test_report_renders_research_quality_charts() -> None:
    html = render_html(
        [
            _row("2026-05-18T10-00-00Z", coverage=0.5, claims=4, unsupported=2),
            _row("2026-05-18T11-00-00Z", coverage=1.0, claims=4, unsupported=0),
        ]
    )

    assert "Research quality" in html
    assert "Research evidence coverage" in html
    assert "Research unsupported claim ratio" in html
    assert "evidence coverage 100%" in html
    assert "unsupported claim ratio 0%" in html


def test_report_renders_retrieval_recall_charts() -> None:
    html = render_html(
        [
            _retrieval_row("2026-05-18T10-00-00Z", query_id="q1", recall_5=1.0, recall_10=1.0),
            _retrieval_row("2026-05-18T10-00-00Z", query_id="q2", recall_5=0.5, recall_10=1.0),
            _retrieval_row("2026-05-18T11-00-00Z", query_id="q1", recall_5=1.0, recall_10=1.0),
            _retrieval_row("2026-05-18T11-00-00Z", query_id="q2", recall_5=1.0, recall_10=1.0),
        ]
    )

    assert "Latest retrieval run" in html
    assert "mean recall@5 100.0%" in html
    assert "mean recall@10 100.0%" in html
    assert "Retrieval mean recall" in html
    assert "PASS rate per field" not in html
