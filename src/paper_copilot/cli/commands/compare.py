"""`paper-copilot compare <paper_id_a> <paper_id_b>` subcommand.

Reads two papers from fields.db and renders a side-by-side comparison.
Methods align by case-insensitive name; experiments align by
(dataset, metric). Shared rows render first, then A-only, then B-only.

No LLM. ``--deep`` is accepted but exits 2 with a deferral message
until M14 gives us an eval suite to keep an LLM-backed synthesis
honest (see CLAUDE.md cost discipline).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from paper_copilot.knowledge.fields_store import FieldsStore, PaperRow
from paper_copilot.session.paths import default_root


def compare(
    paper_id_a: Annotated[str, typer.Argument(help="paper_id of the first paper")],
    paper_id_b: Annotated[str, typer.Argument(help="paper_id of the second paper")],
    format_: Annotated[
        str,
        typer.Option("--format", help="Output format: text or json"),
    ] = "text",
    deep: Annotated[
        bool,
        typer.Option("--deep", help="LLM-backed synthesis (deferred until M14)"),
    ] = False,
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Override PAPER_COPILOT_HOME root"),
    ] = None,
) -> None:
    """Side-by-side compare two indexed papers."""
    if format_ not in ("text", "json"):
        raise typer.BadParameter(f"unsupported format: {format_!r}; use 'text' or 'json'")
    if paper_id_a == paper_id_b:
        raise typer.BadParameter("paper_id_a and paper_id_b must differ")
    if deep:
        typer.echo(
            "--deep is deferred until M14 lands an eval suite "
            "(CLAUDE.md cost discipline: new LLM call sites need eval coverage).",
            err=True,
        )
        raise typer.Exit(code=2)

    home = root if root is not None else default_root()
    db_path = home / "fields.db"
    if not db_path.exists():
        typer.echo(f"no index at {db_path}. Run `paper-copilot reindex` first.", err=True)
        raise typer.Exit(code=1)

    with FieldsStore.open(db_path) as store:
        row_a = store.get(paper_id_a)
        row_b = store.get(paper_id_b)
        missing = [pid for pid, row in [(paper_id_a, row_a), (paper_id_b, row_b)] if row is None]
        if missing:
            typer.echo(
                f"paper_id not found: {', '.join(missing)}. "
                f"Run `paper-copilot list` to see indexed papers.",
                err=True,
            )
            raise typer.Exit(code=1)

    assert row_a is not None and row_b is not None  # narrow for type-checker

    if format_ == "json":
        _emit_json(row_a, row_b)
    else:
        _emit_text(row_a, row_b)


def _emit_text(row_a: PaperRow, row_b: PaperRow) -> None:
    console = Console()
    a, b = row_a.data, row_b.data

    console.print(_meta_table(row_a, row_b))
    console.print()
    console.print(
        _two_col_bullets(
            "Contributions",
            a.get("contributions", []),
            b.get("contributions", []),
            key="claim",
        )
    )
    console.print()
    console.print(_methods_table(a.get("methods", []), b.get("methods", [])))
    console.print()
    console.print(_experiments_table(a.get("experiments", []), b.get("experiments", [])))
    console.print()
    console.print(
        _two_col_bullets(
            "Limitations",
            a.get("limitations", []),
            b.get("limitations", []),
            key="description",
        )
    )

    link_lines = _link_lines(row_a, row_b)
    if link_lines:
        console.print()
        console.print("[bold]Cross-paper links[/bold]")
        for line in link_lines:
            console.print(f"  {line}")


def _emit_json(row_a: PaperRow, row_b: PaperRow) -> None:
    a, b = row_a.data, row_b.data
    payload: dict[str, Any] = {
        "a": {"paper_id": row_a.paper_id, "meta": a.get("meta", {})},
        "b": {"paper_id": row_b.paper_id, "meta": b.get("meta", {})},
        "contributions": {
            "a": a.get("contributions", []),
            "b": b.get("contributions", []),
        },
        "methods_aligned": [
            {
                "key": k,
                "a": ai,
                "b": bi,
            }
            for k, ai, bi in _align(
                a.get("methods", []),
                b.get("methods", []),
                lambda m: _norm(m.get("name", "")),
            )
        ],
        "experiments_aligned": [
            {
                "key": list(k),
                "a": ai,
                "b": bi,
            }
            for k, ai, bi in _align(
                a.get("experiments", []),
                b.get("experiments", []),
                lambda e: (_norm(e.get("dataset", "")), _norm(e.get("metric", ""))),
            )
        ],
        "limitations": {
            "a": a.get("limitations", []),
            "b": b.get("limitations", []),
        },
        "cross_paper_links": _link_records(row_a, row_b),
    }
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


def _meta_table(row_a: PaperRow, row_b: PaperRow) -> Table:
    ma = row_a.data.get("meta", {})
    mb = row_b.data.get("meta", {})
    title = f"compare  {row_a.paper_id}  vs  {row_b.paper_id}"
    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column("", style="dim", no_wrap=True)
    table.add_column(f"A — {row_a.paper_id}", overflow="fold")
    table.add_column(f"B — {row_b.paper_id}", overflow="fold")
    table.add_row("title", str(ma.get("title", "?")), str(mb.get("title", "?")))
    table.add_row(
        "authors",
        _authors_short(ma.get("authors", [])),
        _authors_short(mb.get("authors", [])),
    )
    table.add_row("year", str(ma.get("year", "?")), str(mb.get("year", "?")))
    table.add_row("venue", str(ma.get("venue") or ""), str(mb.get("venue") or ""))
    table.add_row("arxiv_id", str(ma.get("arxiv_id") or ""), str(mb.get("arxiv_id") or ""))
    return table


def _two_col_bullets(
    title: str,
    a_items: list[dict[str, Any]],
    b_items: list[dict[str, Any]],
    *,
    key: str,
) -> Table:
    table = Table(title=title, show_header=True, header_style="bold", show_lines=False)
    table.add_column("A", overflow="fold")
    table.add_column("B", overflow="fold")
    a_text = "\n".join(f"• {x.get(key, '')}" for x in a_items) or "(none)"
    b_text = "\n".join(f"• {x.get(key, '')}" for x in b_items) or "(none)"
    table.add_row(a_text, b_text)
    return table


def _methods_table(a_methods: list[dict[str, Any]], b_methods: list[dict[str, Any]]) -> Table:
    rows = _align(a_methods, b_methods, lambda m: _norm(m.get("name", "")))
    table = Table(title="Methods", show_header=True, header_style="bold", show_lines=True)
    table.add_column("name", style="bold", overflow="fold")
    table.add_column("A", overflow="fold")
    table.add_column("B", overflow="fold")
    for key, ai, bi in rows:
        display_name = (ai or bi or {}).get("name", key)
        a_cell = _method_cell(ai)
        b_cell = _method_cell(bi)
        table.add_row(display_name, a_cell, b_cell)
    if not rows:
        table.add_row("(none)", "", "")
    return table


def _method_cell(m: dict[str, Any] | None) -> str:
    if m is None:
        return "[dim]—[/dim]"
    desc = _truncate(m.get("description", ""), 220)
    nov = _truncate(m.get("novelty_vs_prior", ""), 160)
    novel_flag = "★ novel" if m.get("is_novel_to_this_paper") else "uses"
    return f"[dim]{novel_flag}[/dim]\n{desc}\n\n[dim]vs prior:[/dim] {nov}"


def _experiments_table(a_exps: list[dict[str, Any]], b_exps: list[dict[str, Any]]) -> Table:
    rows = _align(
        a_exps,
        b_exps,
        lambda e: (_norm(e.get("dataset", "")), _norm(e.get("metric", ""))),
    )
    table = Table(title="Experiments", show_header=True, header_style="bold", show_lines=True)
    table.add_column("dataset / metric", style="bold", overflow="fold")
    table.add_column("A", overflow="fold")
    table.add_column("B", overflow="fold")
    for _key, ai, bi in rows:
        ref = ai or bi or {}
        label = f"{ref.get('dataset', '?')} / {ref.get('metric', '?')}"
        table.add_row(label, _exp_cell(ai), _exp_cell(bi))
    if not rows:
        table.add_row("(none)", "", "")
    return table


def _exp_cell(e: dict[str, Any] | None) -> str:
    if e is None:
        return "[dim]—[/dim]"
    raw = _truncate(e.get("raw", ""), 160)
    baseline = e.get("comparison_baseline") or "none"
    return f"{raw}\n[dim]vs {baseline}[/dim]"


def _link_lines(row_a: PaperRow, row_b: PaperRow) -> list[str]:
    out: list[str] = []
    for src, dst, label in [(row_a, row_b, "A → B"), (row_b, row_a, "B → A")]:
        for link in src.data.get("cross_paper_links", []) or []:
            if link.get("related_paper_id") == dst.paper_id:
                rel = link.get("relation_type", "?")
                expl = link.get("explanation", "")
                out.append(f"{label}  [bold]{rel}[/bold]  — {expl}")
    return out


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
    for x in a_items:
        a_by_key.setdefault(key_fn(x), x)
    b_by_key: dict[Any, dict[str, Any]] = {}
    for x in b_items:
        b_by_key.setdefault(key_fn(x), x)

    rows: list[tuple[Any, dict[str, Any] | None, dict[str, Any] | None]] = []
    for k, ai in a_by_key.items():
        if k in b_by_key:
            rows.append((k, ai, b_by_key[k]))
    for k, ai in a_by_key.items():
        if k not in b_by_key:
            rows.append((k, ai, None))
    for k, bi in b_by_key.items():
        if k not in a_by_key:
            rows.append((k, None, bi))
    return rows


def _norm(s: str) -> str:
    return s.strip().lower()


def _truncate(text: str, n: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= n else flat[: n - 1].rstrip() + "…"


def _authors_short(authors: list[str]) -> str:
    if not authors:
        return ""
    if len(authors) == 1:
        return authors[0]
    if len(authors) <= 3:
        return ", ".join(authors)
    return f"{authors[0]} et al. ({len(authors)} authors)"
