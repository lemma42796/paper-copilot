"""`paper-copilot eval mark` and `paper-copilot eval run` subcommands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from paper_copilot.eval.goldens import (
    ALLOWED_FIELDS,
    file_path,
    mark_from_session,
)
from paper_copilot.eval.report import write_report
from paper_copilot.eval.runs import load_history, write_run
from paper_copilot.eval.suite import (
    SuiteResult,
    load_suite,
    run_suite_sync,
)
from paper_copilot.shared.errors import EvalError

app = typer.Typer(
    name="eval",
    help="Mark goldens and run regression suites.",
    no_args_is_help=True,
)


@app.command("mark")
def mark(
    paper_id: Annotated[str, typer.Argument(help="paper_id from `paper-copilot list`")],
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

    try:
        records = mark_from_session(paper_id, fields, root=root, dir_=dir_)
    except EvalError as e:
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
        typer.Option("--no-record", help="Skip writing run history to eval/runs/"),
    ] = False,
) -> None:
    """Execute a suite: rerun the pipeline on each paper, compare to goldens."""
    try:
        suite = load_suite(suite_path)
    except EvalError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2) from e

    console = Console()
    console.print(f"[bold]suite:[/bold] {suite.name}  ({len(suite.papers)} paper(s))")
    console.print()

    try:
        result = run_suite_sync(suite, goldens_dir=dir_)
    except EvalError as e:
        typer.echo(f"suite aborted: {e}", err=True)
        raise typer.Exit(code=2) from e

    _render(console, result)

    if not no_record:
        try:
            run_path = write_run(result, runs_dir=runs_dir)
            console.print(f"[dim]recorded run → {run_path}[/dim]")
        except EvalError as e:
            console.print(f"[yellow]warning:[/yellow] could not record run: {e}")

    raise typer.Exit(code=0 if result.passed else 1)


@app.command("report")
def report(
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Output HTML path"),
    ] = Path("eval/report.html"),
    last: Annotated[
        int | None,
        typer.Option("--last", "-n", help="Only include the last N runs"),
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
            "[cyan]paper-copilot eval run <suite.yaml>[/cyan] first."
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
