"""`paper-copilot eval` subcommands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from paper_copilot.cli.commands._shared import resolve_paper_arg
from paper_copilot.eval.goldens import (
    ALLOWED_FIELDS,
    file_path,
    mark_from_session,
)
from paper_copilot.eval.report import write_report
from paper_copilot.eval.retrieval import (
    RetrievalEvalResult,
    RetrievalQueryResult,
    load_retrieval_suite,
    run_retrieval_eval,
)
from paper_copilot.eval.runs import (
    load_history,
    write_research_quality_run,
    write_retrieval_run,
    write_run,
)
from paper_copilot.eval.suite import (
    SuiteResult,
    load_suite,
    run_suite_sync,
)
from paper_copilot.shared.errors import PaperCopilotError

app = typer.Typer(
    name="eval",
    help=(
        "Eval workflow: `mark` goldens, `run` regression suites, "
        "`retrieval` search labels, `report` HTML trend."
    ),
    no_args_is_help=True,
)


@app.command("mark")
def mark(
    paper: Annotated[
        str,
        typer.Argument(help="paper_id (from `paper-copilot list`) or path to a PDF"),
    ],
    field: Annotated[
        list[str] | None,
        typer.Option(
            "--field",
            "-f",
            help=f"Field(s) to mark. Choose from: {', '.join(ALLOWED_FIELDS)}",
        ),
    ] = None,
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Override PAPER_COPILOT_HOME root"),
    ] = None,
    dir_: Annotated[
        Path | None,
        typer.Option("--goldens-dir", help="Override default eval/goldens/ location"),
    ] = None,
) -> None:
    """Snapshot one or more fields from a paper's latest session into goldens."""
    fields = field or []
    if not fields:
        raise typer.BadParameter("provide at least one --field")
    invalid = [f for f in fields if f not in ALLOWED_FIELDS]
    if invalid:
        raise typer.BadParameter(
            f"unsupported field(s) {invalid}; allowed: {', '.join(ALLOWED_FIELDS)}"
        )

    paper_id = resolve_paper_arg(paper)
    try:
        records = mark_from_session(paper_id, fields, root=root, dir_=dir_)
    except PaperCopilotError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e

    console = Console()
    for r in records:
        path = file_path(r.paper_id, r.field, dir_=dir_)
        console.print(f"[green]marked[/green] {r.field}  →  {path}")


@app.command("run")
def run(
    suite_path: Annotated[Path, typer.Argument(help="Path to a suite YAML file")],
    dir_: Annotated[
        Path | None,
        typer.Option("--goldens-dir", help="Override default eval/goldens/ location"),
    ] = None,
    runs_dir: Annotated[
        Path | None,
        typer.Option("--runs-dir", help="Override default eval/runs/ location"),
    ] = None,
    no_record: Annotated[
        bool,
        typer.Option(
            "--no-record",
            help=(
                "Don't append this run to eval/runs/. For ad-hoc debugging; "
                "skipping the record means `eval report` won't see it."
            ),
        ),
    ] = False,
) -> None:
    """Execute a suite: rerun the pipeline on each paper, compare to goldens."""
    try:
        suite = load_suite(suite_path)
    except PaperCopilotError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2) from e

    console = Console()
    console.print(f"[bold]suite:[/bold] {suite.name}  ({len(suite.papers)} paper(s))")
    console.print()

    try:
        result = run_suite_sync(suite, goldens_dir=dir_)
    except PaperCopilotError as e:
        typer.echo(f"suite aborted: {e}", err=True)
        raise typer.Exit(code=2) from e

    _render(console, result)

    if not no_record:
        try:
            run_path = write_run(result, runs_dir=runs_dir)
            console.print(f"[dim]recorded run → {run_path}[/dim]")
        except PaperCopilotError as e:
            console.print(f"[yellow]warning:[/yellow] could not record run: {e}")

    raise typer.Exit(code=0 if result.passed else 1)


@app.command("retrieval")
def retrieval(
    suite_path: Annotated[Path, typer.Argument(help="Path to a retrieval query YAML file")],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Override PAPER_COPILOT_HOME root"),
    ] = None,
    runs_dir: Annotated[
        Path | None,
        typer.Option("--runs-dir", help="Override default eval/runs/ location"),
    ] = None,
    no_record: Annotated[
        bool,
        typer.Option(
            "--no-record",
            help=(
                "Don't append this retrieval run to eval/runs/. For ad-hoc "
                "debugging; skipping the record means `eval report` won't see it."
            ),
        ),
    ] = False,
    k: Annotated[
        int,
        typer.Option("--k", help="Number of top papers to retrieve; must be >= 10"),
    ] = 10,
) -> None:
    """Run retrieval labels against the current hybrid search index."""
    try:
        suite = load_retrieval_suite(suite_path)
        result = run_retrieval_eval(suite, root=root, k=k)
    except PaperCopilotError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2) from e

    console = Console()
    _render_retrieval(console, result)
    if not no_record:
        try:
            run_path = write_retrieval_run(result, runs_dir=runs_dir)
            console.print(f"[dim]recorded retrieval run → {run_path}[/dim]")
        except PaperCopilotError as e:
            console.print(f"[yellow]warning:[/yellow] could not record run: {e}")


@app.command("record-research")
def record_research(
    session_path: Annotated[
        Path,
        typer.Argument(help="Path to a ResearchAgent session.jsonl"),
    ],
    runs_dir: Annotated[
        Path | None,
        typer.Option("--runs-dir", help="Override default eval/runs/ location"),
    ] = None,
    suite_name: Annotated[
        str,
        typer.Option("--suite-name", help="Suite name to write into run history"),
    ] = "research",
) -> None:
    """Record a ResearchAgent final_output.quality row for eval report trends."""
    session_path = session_path.expanduser()
    if not session_path.is_file():
        raise typer.BadParameter(f"session file not found: {session_path}")
    try:
        run_path = write_research_quality_run(
            session_path,
            runs_dir=runs_dir,
            suite_name=suite_name,
        )
    except PaperCopilotError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e

    Console().print(f"[green]recorded research quality[/green] → {run_path}")


@app.command("report")
def report(
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Output HTML path"),
    ] = Path("eval/report.html"),
    last: Annotated[
        int | None,
        typer.Option("--last", "-n", help="Only include the last N runs (default: all)."),
    ] = None,
    suite: Annotated[
        str | None,
        typer.Option("--suite", help="Filter to one suite name"),
    ] = None,
    runs_dir: Annotated[
        Path | None,
        typer.Option("--runs-dir", help="Override default eval/runs/ location"),
    ] = None,
) -> None:
    """Render an HTML trend report from recorded eval runs."""
    rows = load_history(runs_dir=runs_dir, suite_name=suite, last=last)
    write_report(rows, out)
    console = Console()
    if not rows:
        console.print(
            "[yellow]no run history found[/yellow] — run "
            "[cyan]paper-copilot eval run <suite.yaml>[/cyan] or "
            "[cyan]paper-copilot eval record-research <session.jsonl>[/cyan] first."
        )
    else:
        n_runs = len({r.run_id for r in rows})
        console.print(f"[green]wrote[/green] {out}  ({n_runs} run(s), {len(rows)} row(s))")


def _render(console: Console, result: SuiteResult) -> None:
    summary = Table(title=f"suite: {result.suite_name}", show_header=True, header_style="bold")
    summary.add_column("paper_id")
    summary.add_column("status")
    summary.add_column("cost ¥", justify="right")
    summary.add_column("latency s", justify="right")
    summary.add_column("failures", justify="right")

    for p in result.papers:
        status = "[green]PASS[/green]" if p.passed else "[red]FAIL[/red]"
        n_fail = sum(len(fr.failures) for fr in p.fields) + len(p.budget_failures)
        summary.add_row(
            p.paper_id,
            status,
            f"{p.cost.cost_cny:.4f}",
            f"{p.latency_s:.1f}",
            str(n_fail),
        )
    console.print(summary)

    for p in result.papers:
        if p.passed:
            continue
        console.print()
        console.print(f"[bold red]FAIL {p.paper_id}[/bold red]")
        for fr in p.fields:
            for f in fr.failures:
                console.print(f"  [{fr.field}]  [yellow]{f.kind}[/yellow]  {f.field}  — {f.detail}")
        for f in p.budget_failures:
            console.print(f"  [budget]  [yellow]{f.kind}[/yellow]  {f.field}  — {f.detail}")

    console.print()
    overall = "[green]PASS[/green]" if result.passed else "[red]FAIL[/red]"
    console.print(f"overall: {overall}")


def _render_retrieval(console: Console, result: RetrievalEvalResult) -> None:
    table = Table(
        title=f"retrieval: {result.suite_name}",
        show_header=True,
        header_style="bold",
    )
    table.add_column("query")
    table.add_column("recall@5", justify="right")
    table.add_column("recall@10", justify="right")
    table.add_column("prec@5", justify="right")
    table.add_column("prec@10", justify="right")
    table.add_column("evidence@5", justify="right")
    table.add_column("evidence@10", justify="right")
    table.add_column("ev prec@5", justify="right")
    table.add_column("ev prec@10", justify="right")
    table.add_column("top papers")
    table.add_column("missed@10")
    table.add_column("missed evidence@10")

    for query in result.queries:
        table.add_row(
            query.query_id,
            f"{query.recall_at_5:.1%}",
            f"{query.recall_at_10:.1%}",
            f"{query.precision_at_5:.1%}",
            f"{query.precision_at_10:.1%}",
            _format_optional_pct(query.evidence_recall_at_5),
            _format_optional_pct(query.evidence_recall_at_10),
            _format_optional_pct(query.evidence_anchor_precision_at_5),
            _format_optional_pct(query.evidence_anchor_precision_at_10),
            _format_hits(query),
            ", ".join(query.missed_at_10) if query.missed_at_10 else "-",
            ", ".join(query.missed_evidence_at_10)
            if query.missed_evidence_at_10
            else "-",
        )

    console.print(table)
    console.print()
    console.print(
        "mean recall: "
        f"@5={result.mean_recall_at_5:.1%}  "
        f"@10={result.mean_recall_at_10:.1%}"
    )
    console.print(
        "mean precision: "
        f"@5={result.mean_precision_at_5:.1%}  "
        f"@10={result.mean_precision_at_10:.1%}"
    )
    evidence_at_5 = result.mean_evidence_recall_at_5
    evidence_at_10 = result.mean_evidence_recall_at_10
    if evidence_at_5 is not None and evidence_at_10 is not None:
        console.print(
            "mean evidence recall: "
            f"@5={evidence_at_5:.1%}  "
            f"@10={evidence_at_10:.1%}"
        )
    evidence_precision_at_5 = result.mean_evidence_anchor_precision_at_5
    evidence_precision_at_10 = result.mean_evidence_anchor_precision_at_10
    if evidence_precision_at_5 is not None and evidence_precision_at_10 is not None:
        console.print(
            "mean evidence anchor precision: "
            f"@5={evidence_precision_at_5:.1%}  "
            f"@10={evidence_precision_at_10:.1%}"
        )


def _format_optional_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1%}"


def _format_hits(query: RetrievalQueryResult) -> str:
    hits = query.hits
    labels: list[str] = []
    relevant = set(query.relevant_papers)
    for hit in hits[:5]:
        marker = "*" if hit.paper_id in relevant else ""
        labels.append(f"{hit.rank}.{hit.paper_id}{marker}")
    return "  ".join(labels) if labels else "-"
