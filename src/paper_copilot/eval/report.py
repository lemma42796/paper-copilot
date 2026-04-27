"""Static HTML trend report from eval run history.

Three hand-rolled SVG line charts (no JS / chart-lib deps) over the
last N runs:

1. Per-field PASS rate — answers M14's noise-floor question:
   single-run PASS/FAIL is binary noise, but the line over ≥3 runs
   shows whether a field is truly degrading or just flickering.
2. Per-paper cost (CNY) — catches model/prompt cost regressions.
3. Per-paper cache-hit ratio — catches M9 cache regressions
   (cache_read / total billed prompt tokens).

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
    pass_chart = _chart_pass_rate(groups)
    cost_chart = _chart_paper_metric(
        groups,
        value_fn=lambda r: r.cost_cny,
        y_format="{:.4f}",
    )
    cache_chart = _chart_paper_metric(
        groups,
        value_fn=lambda r: r.cache_hit_ratio,
        y_format="{:.2%}",
        y_max=1.0,
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
            "<section class='chart'><h2>PASS rate per field</h2>",
            pass_chart,
            "</section>",
            "<section class='chart'><h2>Per-paper cost (¥)</h2>",
            cost_chart,
            "</section>",
            "<section class='chart'><h2>Per-paper cache-hit ratio</h2>",
            cache_chart,
            "</section>",
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


def _summary_md(groups: list[_RunGroup]) -> str:
    latest = groups[-1]
    fields = sorted({r.field for r in latest.rows})
    papers = sorted({r.paper_id for r in latest.rows})

    lines: list[str] = []
    lines.append(
        f"<p><b>Latest run</b>: {len(papers)} paper(s) · "
        f"{len(fields)} field(s) · "
        f"PASS rate { _pass_rate(latest.rows):.0%}</p>"
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


def _pf(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


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
        "&lt;suite.yaml&gt;</code> at least twice to see a trend.</p>"
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
