"""`paper-copilot doctor` subcommand: cache hit rate + cost + latency report.

Walks ``$PAPER_COPILOT_HOME/papers/*/session.jsonl``, aggregates the
``llm_call`` events emitted by Skim/Deep agents (added in M9), and
renders a per-session breakdown plus global p50/p95 latency and top-3
most expensive sessions. Single source of truth for the M9 DoD check.

Sessions written before the ``llm_call`` event existed (pre-M9, plus
the 2026-04-24 batch where Skim/Deep wrote ``final_output`` /
``tool_use`` only) carry no telemetry. Their rows still surface so the
paper isn't hidden from the report, but every numeric column renders
``—``; in JSON those fields are ``null`` and ``has_telemetry=false``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import quantiles
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from paper_copilot.session.paths import default_root
from paper_copilot.session.store import SessionStore
from paper_copilot.session.types import LLMCall, SessionEntry, SessionHeader
from paper_copilot.shared.cost import QwenFlashPricing
from paper_copilot.shared.errors import SessionError


@dataclass(frozen=True, slots=True)
class _SessionAgg:
    paper_id: str
    mtime: float
    has_telemetry: bool
    n_calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    latency_ms_total: int
    cost_cny: float
    hit_rate: float


def doctor(
    n: Annotated[
        int,
        typer.Option("--n", "-n", help="Number of most recent sessions to include in the report."),
    ] = 10,
    format_: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: text (default, table) or json."),
    ] = "text",
) -> None:
    """Cache hit rate, latency, and ¥ cost across the last N sessions (no LLM calls)."""
    if n <= 0:
        raise typer.BadParameter(f"--n must be positive, got {n}")
    if format_ not in ("text", "json"):
        raise typer.BadParameter(f"unsupported format: {format_!r}; use 'text' or 'json'")

    sessions = _collect_sessions(n)
    latencies = _all_latencies(sessions)

    if format_ == "json":
        _emit_json(sessions, latencies)
    else:
        _emit_text(sessions, latencies)


def _collect_sessions(n: int) -> list[_SessionAgg]:
    root = default_root() / "papers"
    if not root.exists():
        return []

    candidates: list[tuple[float, Path]] = []
    for paper_dir in root.iterdir():
        jsonl = paper_dir / "session.jsonl"
        if jsonl.exists():
            candidates.append((jsonl.stat().st_mtime, jsonl))
    candidates.sort(reverse=True)

    pricing = QwenFlashPricing()
    aggs: list[_SessionAgg] = []
    for mtime, path in candidates[:n]:
        paper_id = path.parent.name
        try:
            store = SessionStore.load(paper_id)
            entries = store.read_all()
        except SessionError as e:
            typer.echo(f"[warn] skipping {path}: {e}", err=True)
            continue

        calls = [e for e in entries if isinstance(e, LLMCall)]
        if not calls:
            # no llm_call events: pre-M9/M14 session, or still running
            aggs.append(
                _SessionAgg(
                    paper_id=_short_paper_id(entries, paper_id),
                    mtime=mtime,
                    has_telemetry=False,
                    n_calls=0,
                    input_tokens=0,
                    output_tokens=0,
                    cache_read_tokens=0,
                    cache_creation_tokens=0,
                    latency_ms_total=0,
                    cost_cny=0.0,
                    hit_rate=0.0,
                )
            )
            continue

        input_t = sum(c.input_tokens for c in calls)
        output_t = sum(c.output_tokens for c in calls)
        cache_read_t = sum(c.cache_read_input_tokens for c in calls)
        cache_create_t = sum(c.cache_creation_input_tokens for c in calls)
        lat_total = sum(c.latency_ms for c in calls)

        cost = _cost_cny(input_t, output_t, cache_create_t, cache_read_t, pricing)
        hit_rate = _hit_rate(input_t, cache_read_t, cache_create_t)

        aggs.append(
            _SessionAgg(
                paper_id=_short_paper_id(entries, paper_id),
                mtime=mtime,
                has_telemetry=True,
                n_calls=len(calls),
                input_tokens=input_t,
                output_tokens=output_t,
                cache_read_tokens=cache_read_t,
                cache_creation_tokens=cache_create_t,
                latency_ms_total=lat_total,
                cost_cny=cost,
                hit_rate=hit_rate,
            )
        )
    return aggs


def _short_paper_id(entries: list[SessionEntry], fallback: str) -> str:
    for e in entries:
        if isinstance(e, SessionHeader):
            return e.paper_id
    return fallback


def _all_latencies(sessions: list[_SessionAgg]) -> list[int]:
    # per-call latencies are lost when we aggregate to totals; re-read
    # the files just for the distribution. Cheap on 10 small JSONLs.
    out: list[int] = []
    root = default_root() / "papers"
    if not root.exists():
        return out
    paper_ids = {s.paper_id for s in sessions}
    for pid in paper_ids:
        try:
            store = SessionStore.load(pid)
        except SessionError:
            continue
        for e in store.read_all():
            if isinstance(e, LLMCall):
                out.append(e.latency_ms)
    return out


def _cost_cny(
    input_t: int,
    output_t: int,
    cache_create_t: int,
    cache_read_t: int,
    p: QwenFlashPricing,
) -> float:
    return (
        input_t * p.INPUT_PER_MTOK_CNY
        + output_t * p.OUTPUT_PER_MTOK_CNY
        + cache_create_t * p.CACHE_CREATE_PER_MTOK_CNY
        + cache_read_t * p.CACHE_HIT_PER_MTOK_CNY
    ) / 1_000_000


def _hit_rate(input_t: int, cache_read_t: int, cache_create_t: int) -> float:
    denom = input_t + cache_read_t + cache_create_t
    return cache_read_t / denom if denom else 0.0


def _emit_text(sessions: list[_SessionAgg], latencies: list[int]) -> None:
    console = Console()
    if not sessions:
        console.print(f"[yellow]no sessions found under[/yellow] {default_root() / 'papers'}")
        return

    top3 = sorted(
        [s for s in sessions if s.has_telemetry],
        key=lambda s: s.cost_cny,
        reverse=True,
    )[:3]
    top3_ids = {s.paper_id for s in top3}

    table = Table(title="paper-copilot doctor — recent sessions", show_lines=False)
    table.add_column("paper_id", style="bold")
    table.add_column("calls", justify="right")
    table.add_column("in", justify="right")
    table.add_column("out", justify="right")
    table.add_column("cache_r", justify="right")
    table.add_column("cache_c", justify="right")
    table.add_column("hit %", justify="right")
    table.add_column("latency", justify="right")
    table.add_column("cost ¥", justify="right")

    blank = "[dim]—[/dim]"
    for s in sessions:
        style = "red" if s.paper_id in top3_ids and s.cost_cny > 0 else None
        if s.has_telemetry:
            table.add_row(
                s.paper_id,
                str(s.n_calls),
                f"{s.input_tokens:,}",
                f"{s.output_tokens:,}",
                f"{s.cache_read_tokens:,}",
                f"{s.cache_creation_tokens:,}",
                f"{s.hit_rate * 100:.1f}",
                f"{s.latency_ms_total:,}ms",
                f"{s.cost_cny:.4f}",
                style=style,
            )
        else:
            table.add_row(s.paper_id, blank, blank, blank, blank, blank, blank, blank, blank)
    console.print(table)

    # global stats
    total_in = sum(s.input_tokens for s in sessions)
    total_read = sum(s.cache_read_tokens for s in sessions)
    total_create = sum(s.cache_creation_tokens for s in sessions)
    global_hit = _hit_rate(total_in, total_read, total_create)
    p50, p95 = _p50_p95(latencies)

    legacy = sum(1 for s in sessions if not s.has_telemetry)
    legacy_suffix = f" ({legacy} pre-M14, no telemetry)" if legacy else ""
    console.print(
        f"[dim]global hit rate: {global_hit * 100:.1f}%  "
        f"latency p50={p50}ms  p95={p95}ms  "
        f"sessions={len(sessions)}{legacy_suffix}[/dim]"
    )
    if top3:
        console.print("[dim]top-3 most expensive:[/dim]")
        for s in top3:
            console.print(f"  [red]¥{s.cost_cny:.4f}[/red]  {s.paper_id}")


def _emit_json(sessions: list[_SessionAgg], latencies: list[int]) -> None:
    total_in = sum(s.input_tokens for s in sessions)
    total_read = sum(s.cache_read_tokens for s in sessions)
    total_create = sum(s.cache_creation_tokens for s in sessions)
    p50, p95 = _p50_p95(latencies)

    payload = {
        "sessions": [_session_json(s) for s in sessions],
        "global": {
            "hit_rate": _hit_rate(total_in, total_read, total_create),
            "latency_ms_p50": p50,
            "latency_ms_p95": p95,
            "n_sessions": len(sessions),
            "n_sessions_no_telemetry": sum(1 for s in sessions if not s.has_telemetry),
        },
    }
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


def _session_json(s: _SessionAgg) -> dict[str, object]:
    if not s.has_telemetry:
        return {
            "paper_id": s.paper_id,
            "has_telemetry": False,
            "n_calls": None,
            "input_tokens": None,
            "output_tokens": None,
            "cache_read_tokens": None,
            "cache_creation_tokens": None,
            "hit_rate": None,
            "latency_ms_total": None,
            "cost_cny": None,
        }
    return {
        "paper_id": s.paper_id,
        "has_telemetry": True,
        "n_calls": s.n_calls,
        "input_tokens": s.input_tokens,
        "output_tokens": s.output_tokens,
        "cache_read_tokens": s.cache_read_tokens,
        "cache_creation_tokens": s.cache_creation_tokens,
        "hit_rate": s.hit_rate,
        "latency_ms_total": s.latency_ms_total,
        "cost_cny": s.cost_cny,
    }


def _p50_p95(values: list[int]) -> tuple[int, int]:
    if not values:
        return 0, 0
    if len(values) == 1:
        return values[0], values[0]
    qs = quantiles(sorted(values), n=100, method="inclusive")
    return int(qs[49]), int(qs[94])
