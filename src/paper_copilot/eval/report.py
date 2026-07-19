"""Static HTML trend report from eval run history.

Hand-rolled SVG line charts (no JS / chart-lib deps) over the last N
runs:

1. Per-field PASS rate — answers M14's noise-floor question:
   single-run PASS/FAIL is binary noise, but the line over ≥3 runs
   shows whether a field is truly degrading or just flickering.
2. Per-paper cost (CNY) — catches model/prompt cost regressions.
3. Per-paper cache-hit ratio — catches M9 cache regressions
   (cache_read / total billed prompt tokens).
4. Optional Paper Copilot evidence quality — catches unsupported-claim
   drift when rows include M17 quality payload fields.
5. Optional retrieval recall — catches paper/evidence index search regressions
   when rows include M18 retrieval eval payload fields.

Top-of-page markdown summary diffs the most recent run against the
prior one for the same suite, highlighting fields whose PASS state
flipped and per-paper cost/cache deltas > ±10%.
"""

from __future__ import annotations

import html
import itertools
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from paper_copilot.eval.runs import RunRow

_W, _H = 820, 280
_M_L, _M_R, _M_T, _M_B = 70, 20, 24, 56
_PLOT_W = _W - _M_L - _M_R
_PLOT_H = _H - _M_T - _M_B

# matplotlib tab10
_PALETTE = (
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
)


@dataclass(frozen=True, slots=True)
class _RunGroup:
    run_id: str
    suite_name: str
    git_sha: str
    rows: tuple[RunRow, ...]


def render_html(rows: list[RunRow], *, title: str = "paper-copilot eval report") -> str:
    if not rows:
        return _empty_page(title)

    groups = _group_runs(rows)
    summary = _summary_md(groups)
    non_retrieval_groups = _filter_group_rows(groups, lambda row: not _is_retrieval(row))
    quality_sections = _quality_sections(groups)
    retrieval_sections = _retrieval_sections(groups)

    chart_sections: list[str] = []
    if non_retrieval_groups:
        chart_sections.extend(
            [
                "<section class='chart'><h2>PASS rate per field</h2>",
                _chart_pass_rate(non_retrieval_groups),
                "</section>",
                "<section class='chart'><h2>Per-paper cost (¥)</h2>",
                _chart_paper_metric(
                    non_retrieval_groups,
                    value_fn=lambda r: r.cost_cny,
                    y_format="{:.4f}",
                ),
                "</section>",
                "<section class='chart'><h2>Per-paper cache-hit ratio</h2>",
                _chart_paper_metric(
                    non_retrieval_groups,
                    value_fn=lambda r: r.cache_hit_ratio,
                    y_format="{:.2%}",
                    y_max=1.0,
                ),
                "</section>",
            ]
        )

    body = "\n".join(
        [
            f"<h1>{html.escape(title)}</h1>",
            f"<p class='meta'>{len(groups)} run(s) · "
            f"suite={html.escape(groups[-1].suite_name)} · "
            f"latest={html.escape(groups[-1].run_id)} ({html.escape(groups[-1].git_sha)})</p>",
            "<section class='summary'>",
            summary,
            "</section>",
            *chart_sections,
            quality_sections,
            retrieval_sections,
        ]
    )
    return _PAGE_TMPL.format(title=html.escape(title), body=body)


def write_report(rows: list[RunRow], out_path: Path, *, title: str | None = None) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page_title = title or "paper-copilot eval report"
    out_path.write_text(render_html(rows, title=page_title), encoding="utf-8")
    return out_path


def _group_runs(rows: list[RunRow]) -> list[_RunGroup]:
    groups: list[_RunGroup] = []
    for run_id, items in itertools.groupby(rows, key=lambda r: r.run_id):
        bucket = tuple(items)
        groups.append(
            _RunGroup(
                run_id=run_id,
                suite_name=bucket[0].suite_name,
                git_sha=bucket[0].git_sha,
                rows=bucket,
            )
        )
    return groups


def _filter_group_rows(
    groups: list[_RunGroup], predicate: Callable[[RunRow], bool]
) -> list[_RunGroup]:
    filtered: list[_RunGroup] = []
    for group in groups:
        rows = tuple(row for row in group.rows if predicate(row))
        if not rows:
            continue
        filtered.append(
            _RunGroup(
                run_id=group.run_id,
                suite_name=group.suite_name,
                git_sha=group.git_sha,
                rows=rows,
            )
        )
    return filtered


def _summary_md(groups: list[_RunGroup]) -> str:
    latest = groups[-1]
    if _all_retrieval(latest.rows):
        return _retrieval_summary_md(groups)

    fields = sorted({r.field for r in latest.rows})
    papers = sorted({r.paper_id for r in latest.rows})

    lines: list[str] = []
    lines.append(
        f"<p><b>Latest run</b>: {len(papers)} paper(s) · "
        f"{len(fields)} field(s) · "
        f"PASS rate { _pass_rate(latest.rows):.0%}</p>"
    )
    quality = _run_quality(latest)
    if quality is not None:
        coverage, unsupported = quality
        lines.append(
            f"<p><b>Research quality</b>: evidence coverage {coverage:.0%} · "
            f"unsupported claim ratio {unsupported:.0%}</p>"
        )

    if len(groups) < 2:
        lines.append("<p class='hint'>Need ≥2 runs to show a trend diff.</p>")
        return "\n".join(lines)

    prior = groups[-2]
    lines.append(
        f"<p><b>vs prior</b> ({html.escape(prior.run_id)}, "
        f"{html.escape(prior.git_sha)})</p>"
    )

    flips = _pass_flips(prior, latest)
    if flips:
        lines.append("<ul class='diff'>")
        for paper_id, field, was, now in flips:
            arrow = "↗" if now else "↘"
            cls = "up" if now else "down"
            lines.append(
                f"<li class='{cls}'>{arrow} {html.escape(paper_id)} / "
                f"{html.escape(field)}: {_pf(was)} → {_pf(now)}</li>"
            )
        lines.append("</ul>")
    else:
        lines.append("<p class='hint'>No PASS state flips since prior run.</p>")

    cost_drifts = _paper_drifts(prior, latest, lambda r: r.cost_cny, threshold=0.10)
    if cost_drifts:
        lines.append("<p><b>Cost drift &gt; ±10%</b></p><ul class='diff'>")
        for paper_id, before, after, pct in cost_drifts:
            arrow = "↗" if after > before else "↘"
            cls = "down" if after > before else "up"
            lines.append(
                f"<li class='{cls}'>{arrow} {html.escape(paper_id)}: "
                f"¥{before:.4f} → ¥{after:.4f} ({pct:+.0%})</li>"
            )
        lines.append("</ul>")

    cache_drifts = _paper_drifts(prior, latest, lambda r: r.cache_hit_ratio, threshold=0.10)
    if cache_drifts:
        lines.append("<p><b>Cache-hit drift &gt; ±10%</b></p><ul class='diff'>")
        for paper_id, before, after, pct in cache_drifts:
            arrow = "↗" if after > before else "↘"
            cls = "up" if after > before else "down"
            lines.append(
                f"<li class='{cls}'>{arrow} {html.escape(paper_id)}: "
                f"{before:.1%} → {after:.1%} ({pct:+.0%})</li>"
            )
        lines.append("</ul>")

    return "\n".join(lines)


def _retrieval_summary_md(groups: list[_RunGroup]) -> str:
    latest = groups[-1]
    latest_stats = _run_retrieval(latest)
    if latest_stats is None:
        return "<p class='hint'>No retrieval rows found in latest run.</p>"

    (
        query_count,
        recall_at_5,
        recall_at_10,
        precision_at_5,
        precision_at_10,
        evidence_query_count,
        evidence_at_5,
        evidence_at_10,
        evidence_precision_at_5,
        evidence_precision_at_10,
    ) = latest_stats
    lines = [
        f"<p><b>Latest retrieval run</b>: {query_count} query(s) · "
        f"mean recall@5 {recall_at_5:.1%} · "
        f"mean recall@10 {recall_at_10:.1%} · "
        f"mean precision@5 {precision_at_5:.1%} · "
        f"mean precision@10 {precision_at_10:.1%}</p>"
    ]
    if evidence_at_5 is not None and evidence_at_10 is not None:
        lines.append(
            f"<p><b>Latest evidence recall</b>: {evidence_query_count} labeled "
            f"query(s) · evidence@5 {evidence_at_5:.1%} · "
            f"evidence@10 {evidence_at_10:.1%}</p>"
        )
    if evidence_precision_at_5 is not None and evidence_precision_at_10 is not None:
        lines.append(
            f"<p><b>Latest evidence anchor precision</b>: "
            f"precision@5 {evidence_precision_at_5:.1%} · "
            f"precision@10 {evidence_precision_at_10:.1%}</p>"
        )

    prior = _previous_retrieval_group(groups)
    if prior is None:
        lines.append("<p class='hint'>Need ≥2 retrieval runs to show a trend diff.</p>")
        return "\n".join(lines)

    prior_stats = _run_retrieval(prior)
    if prior_stats is None:
        lines.append("<p class='hint'>No comparable prior retrieval run found.</p>")
        return "\n".join(lines)

    (
        _,
        prior_at_5,
        prior_at_10,
        prior_precision_at_5,
        prior_precision_at_10,
        _prior_evidence_count,
        prior_evidence_at_5,
        prior_evidence_at_10,
        prior_evidence_precision_at_5,
        prior_evidence_precision_at_10,
    ) = prior_stats
    lines.append(
        f"<p><b>vs prior retrieval</b> ({html.escape(prior.run_id)}, "
        f"{html.escape(prior.git_sha)}): "
        f"recall@5 {_format_pp(recall_at_5 - prior_at_5)} · "
        f"recall@10 {_format_pp(recall_at_10 - prior_at_10)} · "
        f"precision@5 {_format_pp(precision_at_5 - prior_precision_at_5)} · "
        f"precision@10 {_format_pp(precision_at_10 - prior_precision_at_10)}</p>"
    )
    if (
        evidence_at_5 is not None
        and evidence_at_10 is not None
        and prior_evidence_at_5 is not None
        and prior_evidence_at_10 is not None
    ):
        lines.append(
            f"<p><b>vs prior evidence</b>: "
            f"evidence@5 {_format_pp(evidence_at_5 - prior_evidence_at_5)} · "
            f"evidence@10 {_format_pp(evidence_at_10 - prior_evidence_at_10)}</p>"
        )
    if (
        evidence_precision_at_5 is not None
        and evidence_precision_at_10 is not None
        and prior_evidence_precision_at_5 is not None
        and prior_evidence_precision_at_10 is not None
    ):
        lines.append(
            f"<p><b>vs prior evidence precision</b>: "
            f"precision@5 "
            f"{_format_pp(evidence_precision_at_5 - prior_evidence_precision_at_5)} · "
            f"precision@10 "
            f"{_format_pp(evidence_precision_at_10 - prior_evidence_precision_at_10)}</p>"
        )
    return "\n".join(lines)


def _pf(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def _format_pp(delta: float) -> str:
    return f"{delta * 100:+.1f} pp"


def _pass_rate(rows: tuple[RunRow, ...] | list[RunRow]) -> float:
    if not rows:
        return 0.0
    return sum(1 for r in rows if r.field_passed) / len(rows)


def _pass_flips(
    prior: _RunGroup, latest: _RunGroup
) -> list[tuple[str, str, bool, bool]]:
    prior_idx = {(r.paper_id, r.field): r.field_passed for r in prior.rows}
    flips: list[tuple[str, str, bool, bool]] = []
    for r in latest.rows:
        was = prior_idx.get((r.paper_id, r.field))
        if was is None or was == r.field_passed:
            continue
        flips.append((r.paper_id, r.field, was, r.field_passed))
    flips.sort()
    return flips


def _paper_drifts(
    prior: _RunGroup,
    latest: _RunGroup,
    value_fn: Callable[[RunRow], float],
    *,
    threshold: float,
) -> list[tuple[str, float, float, float]]:
    prior_paper = _per_paper_value(prior.rows, value_fn)
    latest_paper = _per_paper_value(latest.rows, value_fn)
    drifts: list[tuple[str, float, float, float]] = []
    for paper_id, after in latest_paper.items():
        before = prior_paper.get(paper_id)
        if before is None or before == 0:
            continue
        pct = (after - before) / before
        if abs(pct) >= threshold:
            drifts.append((paper_id, before, after, pct))
    drifts.sort(key=lambda t: -abs(t[3]))
    return drifts


def _quality_sections(groups: list[_RunGroup]) -> str:
    if not any(_has_quality(g.rows) for g in groups):
        return ""

    coverage_chart = _chart_run_metric(
        groups,
        value_fn=lambda r: r.evidence_coverage_ratio,
        y_format="{:.0%}",
        y_max=1.0,
    )
    unsupported_chart = _chart_run_metric(
        groups,
        value_fn=_unsupported_claim_ratio,
        y_format="{:.0%}",
        y_max=1.0,
    )
    return "\n".join(
        [
            "<section class='chart'><h2>Research evidence coverage</h2>",
            coverage_chart,
            "</section>",
            "<section class='chart'><h2>Research unsupported claim ratio</h2>",
            unsupported_chart,
            "</section>",
        ]
    )


def _retrieval_sections(groups: list[_RunGroup]) -> str:
    retrieval_groups = _filter_group_rows(groups, _is_retrieval)
    if not retrieval_groups:
        return ""

    recall_chart = _chart_retrieval_recall(retrieval_groups)
    detail_table = _retrieval_detail_table(retrieval_groups[-1])
    return "\n".join(
        [
            "<section class='chart'><h2>Retrieval mean recall and precision</h2>",
            recall_chart,
            "</section>",
            "<section class='chart'><h2>Latest retrieval query detail</h2>",
            detail_table,
            "</section>",
        ]
    )


def _retrieval_detail_table(group: _RunGroup) -> str:
    rows = sorted(
        (row for row in group.rows if _is_retrieval(row)),
        key=lambda row: (
            row.retrieval_recall_at_5
            if row.retrieval_recall_at_5 is not None
            else 0.0,
            row.retrieval_recall_at_10
            if row.retrieval_recall_at_10 is not None
            else 0.0,
            row.retrieval_precision_at_5
            if row.retrieval_precision_at_5 is not None
            else 0.0,
            row.retrieval_precision_at_10
            if row.retrieval_precision_at_10 is not None
            else 0.0,
            row.retrieval_evidence_recall_at_5
            if row.retrieval_evidence_recall_at_5 is not None
            else 1.0,
            row.retrieval_evidence_recall_at_10
            if row.retrieval_evidence_recall_at_10 is not None
            else 1.0,
            row.paper_id,
        ),
    )
    body_rows: list[str] = []
    for row in rows:
        body_rows.append(
            "<tr>"
            f"<td><code>{html.escape(row.paper_id)}</code></td>"
            f"<td>{html.escape(row.retrieval_query or '')}</td>"
            f"<td class='num'>{_format_pct(row.retrieval_recall_at_5)}</td>"
            f"<td class='num'>{_format_pct(row.retrieval_recall_at_10)}</td>"
            f"<td class='num'>{_format_pct(row.retrieval_precision_at_5)}</td>"
            f"<td class='num'>{_format_pct(row.retrieval_precision_at_10)}</td>"
            f"<td class='num'>{_format_int(row.retrieval_evidence_anchor_count)}</td>"
            f"<td class='num'>{_format_pct(row.retrieval_evidence_recall_at_5)}</td>"
            f"<td class='num'>{_format_pct(row.retrieval_evidence_recall_at_10)}</td>"
            f"<td class='num'>"
            f"{_format_pct(row.retrieval_evidence_anchor_precision_at_5)}</td>"
            f"<td class='num'>"
            f"{_format_pct(row.retrieval_evidence_anchor_precision_at_10)}</td>"
            f"<td>{_format_ids(row.retrieval_missed_at_5)}</td>"
            f"<td>{_format_ids(row.retrieval_missed_at_10)}</td>"
            f"<td>{_format_ids(row.retrieval_missed_evidence_at_10)}</td>"
            f"<td>{_format_ids(_first_n(row.retrieval_top_papers, 5))}</td>"
            "</tr>"
        )

    return "\n".join(
        [
            "<table class='data-table'>",
            "<thead><tr>",
            "<th>query</th>",
            "<th>text</th>",
            "<th>recall@5</th>",
            "<th>recall@10</th>",
            "<th>precision@5</th>",
            "<th>precision@10</th>",
            "<th>anchors</th>",
            "<th>evidence@5</th>",
            "<th>evidence@10</th>",
            "<th>ev precision@5</th>",
            "<th>ev precision@10</th>",
            "<th>missed@5</th>",
            "<th>missed@10</th>",
            "<th>missed evidence@10</th>",
            "<th>top 5 papers</th>",
            "</tr></thead>",
            f"<tbody>{''.join(body_rows)}</tbody>",
            "</table>",
        ]
    )


def _format_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1%}"


def _format_int(value: int | None) -> str:
    if value is None:
        return "-"
    return str(value)


def _format_ids(values: tuple[str, ...] | None) -> str:
    if not values:
        return "-"
    return ", ".join(f"<code>{html.escape(value)}</code>" for value in values)


def _first_n(values: tuple[str, ...] | None, n: int) -> tuple[str, ...] | None:
    if values is None:
        return None
    return values[:n]


def _chart_retrieval_recall(groups: list[_RunGroup]) -> str:
    series = {
        "paper@5": [
            _avg_metric(group.rows, lambda r: r.retrieval_recall_at_5)
            for group in groups
        ],
        "paper@10": [
            _avg_metric(group.rows, lambda r: r.retrieval_recall_at_10) for group in groups
        ],
        "paper precision@5": [
            _avg_metric(group.rows, lambda r: r.retrieval_precision_at_5)
            for group in groups
        ],
        "paper precision@10": [
            _avg_metric(group.rows, lambda r: r.retrieval_precision_at_10)
            for group in groups
        ],
    }
    has_evidence = any(
        row.retrieval_evidence_recall_at_10 is not None
        for group in groups
        for row in group.rows
    )
    if has_evidence:
        series["evidence@5"] = [
            _avg_metric(group.rows, lambda r: r.retrieval_evidence_recall_at_5)
            for group in groups
        ]
        series["evidence@10"] = [
            _avg_metric(group.rows, lambda r: r.retrieval_evidence_recall_at_10)
            for group in groups
        ]
    has_evidence_precision = any(
        row.retrieval_evidence_anchor_precision_at_10 is not None
        for group in groups
        for row in group.rows
    )
    if has_evidence_precision:
        series["evidence precision@5"] = [
            _avg_metric(
                group.rows, lambda r: r.retrieval_evidence_anchor_precision_at_5
            )
            for group in groups
        ]
        series["evidence precision@10"] = [
            _avg_metric(
                group.rows, lambda r: r.retrieval_evidence_anchor_precision_at_10
            )
            for group in groups
        ]
    return _svg_chart(
        series=series,
        run_labels=[_short_label(g.run_id) for g in groups],
        y_max=1.0,
        y_format="{:.0%}",
    )


def _is_retrieval(row: RunRow) -> bool:
    return row.retrieval_recall_at_10 is not None


def _all_retrieval(rows: tuple[RunRow, ...]) -> bool:
    return bool(rows) and all(_is_retrieval(row) for row in rows)


def _previous_retrieval_group(groups: list[_RunGroup]) -> _RunGroup | None:
    for group in reversed(groups[:-1]):
        if any(_is_retrieval(row) for row in group.rows):
            return group
    return None


def _run_retrieval(
    group: _RunGroup,
) -> tuple[
    int,
    float,
    float,
    float,
    float,
    int,
    float | None,
    float | None,
    float | None,
    float | None,
] | None:
    rows = [row for row in group.rows if _is_retrieval(row)]
    if not rows:
        return None
    recall_at_5 = _avg_metric(tuple(rows), lambda r: r.retrieval_recall_at_5)
    recall_at_10 = _avg_metric(tuple(rows), lambda r: r.retrieval_recall_at_10)
    precision_at_5 = _avg_metric(tuple(rows), lambda r: r.retrieval_precision_at_5)
    precision_at_10 = _avg_metric(tuple(rows), lambda r: r.retrieval_precision_at_10)
    if (
        recall_at_5 is None
        or recall_at_10 is None
        or precision_at_5 is None
        or precision_at_10 is None
    ):
        return None
    evidence_rows = tuple(
        row for row in rows if row.retrieval_evidence_recall_at_10 is not None
    )
    evidence_at_5 = _avg_metric(
        evidence_rows, lambda r: r.retrieval_evidence_recall_at_5
    )
    evidence_at_10 = _avg_metric(
        evidence_rows, lambda r: r.retrieval_evidence_recall_at_10
    )
    evidence_precision_at_5 = _avg_metric(
        evidence_rows, lambda r: r.retrieval_evidence_anchor_precision_at_5
    )
    evidence_precision_at_10 = _avg_metric(
        evidence_rows, lambda r: r.retrieval_evidence_anchor_precision_at_10
    )
    return (
        len(rows),
        recall_at_5,
        recall_at_10,
        precision_at_5,
        precision_at_10,
        len(evidence_rows),
        evidence_at_5,
        evidence_at_10,
        evidence_precision_at_5,
        evidence_precision_at_10,
    )


def _run_quality(group: _RunGroup) -> tuple[float, float] | None:
    coverage = _avg_metric(group.rows, lambda r: r.evidence_coverage_ratio)
    unsupported = _avg_metric(group.rows, _unsupported_claim_ratio)
    if coverage is None or unsupported is None:
        return None
    return coverage, unsupported


def _has_quality(rows: tuple[RunRow, ...]) -> bool:
    return any(r.evidence_coverage_ratio is not None for r in rows)


def _unsupported_claim_ratio(row: RunRow) -> float | None:
    if row.findings_claim_count is None or row.claims_without_refs_count is None:
        return None
    if row.findings_claim_count == 0:
        return 0.0
    return row.claims_without_refs_count / row.findings_claim_count


def _avg_metric(
    rows: tuple[RunRow, ...], value_fn: Callable[[RunRow], float | None]
) -> float | None:
    values = [value for row in rows if (value := value_fn(row)) is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _per_paper_value(
    rows: tuple[RunRow, ...], value_fn: Callable[[RunRow], float]
) -> dict[str, float]:
    # Each row in a run carries paper-level cost/cache_hit duplicated;
    # take any one row per paper.
    out: dict[str, float] = {}
    for r in rows:
        out.setdefault(r.paper_id, value_fn(r))
    return out


def _chart_pass_rate(groups: list[_RunGroup]) -> str:
    fields = sorted({r.field for g in groups for r in g.rows})
    series: dict[str, list[float | None]] = {f: [] for f in fields}
    for g in groups:
        by_field: dict[str, list[bool]] = {}
        for r in g.rows:
            by_field.setdefault(r.field, []).append(r.field_passed)
        for f in fields:
            bucket = by_field.get(f)
            series[f].append(sum(bucket) / len(bucket) if bucket else None)
    return _svg_chart(
        series=series,
        run_labels=[_short_label(g.run_id) for g in groups],
        y_max=1.0,
        y_format="{:.0%}",
    )


def _chart_paper_metric(
    groups: list[_RunGroup],
    *,
    value_fn: Callable[[RunRow], float],
    y_format: str,
    y_max: float | None = None,
) -> str:
    papers = sorted({r.paper_id for g in groups for r in g.rows})
    series: dict[str, list[float | None]] = {p: [] for p in papers}
    for g in groups:
        per_paper = _per_paper_value(g.rows, value_fn)
        for p in papers:
            series[p].append(per_paper.get(p))
    if y_max is None:
        flat = [v for line in series.values() for v in line if v is not None]
        y_max = max(flat) * 1.1 if flat else 1.0
    return _svg_chart(
        series=series,
        run_labels=[_short_label(g.run_id) for g in groups],
        y_max=y_max,
        y_format=y_format,
    )


def _chart_run_metric(
    groups: list[_RunGroup],
    *,
    value_fn: Callable[[RunRow], float | None],
    y_format: str,
    y_max: float,
) -> str:
    series = {"research": [_avg_metric(group.rows, value_fn) for group in groups]}
    return _svg_chart(
        series=series,
        run_labels=[_short_label(g.run_id) for g in groups],
        y_max=y_max,
        y_format=y_format,
    )


def _svg_chart(
    *,
    series: dict[str, list[float | None]],
    run_labels: list[str],
    y_max: float,
    y_format: str,
) -> str:
    n_runs = len(run_labels)
    parts: list[str] = [f'<svg viewBox="0 0 {_W} {_H}" class="chart-svg" role="img">']
    parts.append(_axes_svg(n_runs, y_max, y_format, run_labels))

    for idx, (name, values) in enumerate(series.items()):
        color = _PALETTE[idx % len(_PALETTE)]
        parts.append(_series_svg(name, values, n_runs, y_max, color))

    parts.append("</svg>")
    parts.append(_legend_html(list(series.keys())))
    return "\n".join(parts)


def _axes_svg(
    n_runs: int, y_max: float, y_format: str, run_labels: list[str]
) -> str:
    p: list[str] = []
    # Plot border
    p.append(
        f'<rect x="{_M_L}" y="{_M_T}" width="{_PLOT_W}" height="{_PLOT_H}" '
        f'fill="#fafafa" stroke="#ccc" />'
    )
    # Y ticks (5 lines)
    for i in range(6):
        frac = i / 5
        y = _M_T + _PLOT_H - frac * _PLOT_H
        val = y_max * frac
        p.append(
            f'<line x1="{_M_L}" y1="{y:.2f}" x2="{_M_L + _PLOT_W}" y2="{y:.2f}" '
            f'stroke="#eee" />'
        )
        p.append(
            f'<text x="{_M_L - 6}" y="{y + 4:.2f}" text-anchor="end" '
            f'font-size="11" fill="#666">{y_format.format(val)}</text>'
        )
    # X tick labels (every run, plus rotated for readability)
    if n_runs > 0:
        # Pick every k-th run to avoid label overlap
        step = max(1, n_runs // 8)
        for idx in range(n_runs):
            if idx % step != 0 and idx != n_runs - 1:
                continue
            x = _x_of(idx, n_runs)
            p.append(
                f'<line x1="{x:.2f}" y1="{_M_T + _PLOT_H}" '
                f'x2="{x:.2f}" y2="{_M_T + _PLOT_H + 4}" stroke="#666" />'
            )
            label = html.escape(run_labels[idx])
            p.append(
                f'<text x="{x:.2f}" y="{_M_T + _PLOT_H + 18:.2f}" '
                f'text-anchor="middle" font-size="10" fill="#444" '
                f'transform="rotate(-30 {x:.2f} {_M_T + _PLOT_H + 18:.2f})">{label}</text>'
            )
    return "\n".join(p)


def _series_svg(
    name: str,
    values: list[float | None],
    n_runs: int,
    y_max: float,
    color: str,
) -> str:
    pts: list[tuple[float, float]] = []
    for idx, v in enumerate(values):
        if v is None:
            continue
        pts.append((_x_of(idx, n_runs), _y_of(v, y_max)))

    p: list[str] = []
    if len(pts) >= 2:
        coords = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
        p.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="2" '
            f'points="{coords}"><title>{html.escape(name)}</title></polyline>'
        )
    # Always render circle markers so single-run-only series still show.
    for (x, y), v in zip(pts, [v for v in values if v is not None], strict=False):
        p.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{color}">'
            f'<title>{html.escape(name)} = {v:.4f}</title></circle>'
        )
    return "\n".join(p)


def _legend_html(names: list[str]) -> str:
    items: list[str] = []
    for idx, name in enumerate(names):
        color = _PALETTE[idx % len(_PALETTE)]
        items.append(
            f'<span class="legend-item">'
            f'<span class="swatch" style="background:{color}"></span>'
            f'{html.escape(name)}</span>'
        )
    return f'<div class="legend">{" ".join(items)}</div>'


def _x_of(idx: int, n_runs: int) -> float:
    if n_runs <= 1:
        return _M_L + _PLOT_W / 2
    return _M_L + (idx / (n_runs - 1)) * _PLOT_W


def _y_of(value: float, y_max: float) -> float:
    if y_max <= 0:
        return _M_T + _PLOT_H
    clipped = max(0.0, min(value, y_max))
    return _M_T + _PLOT_H - (clipped / y_max) * _PLOT_H


def _short_label(run_id: str) -> str:
    # 2026-04-27T15-30-45Z → 04-27 15:30
    if "T" not in run_id:
        return run_id
    date_part, time_part = run_id.split("T", 1)
    md = date_part[5:] if len(date_part) >= 10 else date_part
    hm = time_part.replace("-", ":")[:5] if len(time_part) >= 5 else time_part
    return f"{md} {hm}"


def _empty_page(title: str) -> str:
    body = (
        f"<h1>{html.escape(title)}</h1>"
        "<p class='hint'>No runs found. Run <code>paper-copilot eval run "
        "&lt;suite.yaml&gt;</code> or <code>paper-copilot eval record-research "
        "&lt;session.jsonl&gt;</code> or <code>paper-copilot eval retrieval "
        "&lt;queries.yaml&gt;</code> at least twice to see a trend.</p>"
    )
    return _PAGE_TMPL.format(title=html.escape(title), body=body)


_PAGE_TMPL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 960px; margin: 32px auto; padding: 0 16px; color: #222; }}
  h1 {{ font-size: 22px; margin-bottom: 4px; }}
  h2 {{ font-size: 16px; margin: 24px 0 8px; }}
  p.meta {{ color: #666; font-size: 13px; margin-top: 0; }}
  section.summary {{ background: #f7f7f9; padding: 12px 16px; border-radius: 6px;
                     margin: 16px 0; font-size: 13px; }}
  section.summary p {{ margin: 4px 0; }}
  section.summary ul.diff {{ margin: 4px 0; padding-left: 20px; }}
  section.summary li.up {{ color: #2a6; }}
  section.summary li.down {{ color: #b22; }}
  p.hint {{ color: #888; font-style: italic; }}
  section.chart {{ margin-top: 20px; }}
  svg.chart-svg {{ width: 100%; height: auto; max-width: {w}px; display: block; }}
  table.data-table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
  table.data-table th, table.data-table td {{ border-bottom: 1px solid #eee;
         padding: 6px 8px; vertical-align: top; text-align: left; }}
  table.data-table th {{ color: #555; background: #fafafa; font-weight: 600; }}
  table.data-table td.num {{ text-align: right; white-space: nowrap; }}
  div.legend {{ margin-top: 6px; font-size: 11px; color: #444; }}
  span.legend-item {{ display: inline-block; margin: 2px 12px 2px 0; white-space: nowrap; }}
  span.swatch {{ display: inline-block; width: 10px; height: 10px;
                 margin-right: 4px; vertical-align: middle; border-radius: 2px; }}
  code {{ background: #eee; padding: 1px 4px; border-radius: 3px; }}
</style>
</head>
<body>
{body}
</body>
</html>
""".replace("{w}", str(_W))
