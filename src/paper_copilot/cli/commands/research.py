"""`paper-copilot research "<topic>"` subcommand."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markdown import Markdown

from paper_copilot.chat.runtime import ChatRunResult, handle_chat_request
from paper_copilot.shared.errors import EvalError, KnowledgeError


def research(
    topic: Annotated[str, typer.Argument(help="Research question or topic")],
    pdf_dir: Annotated[
        Path | None,
        typer.Option("--pdf-dir", help="Optional directory of candidate PDFs to list."),
    ] = None,
    max_turns: Annotated[
        int,
        typer.Option("--max-turns", help="Maximum planner/tool loop turns."),
    ] = 16,
    budget_cny: Annotated[
        float,
        typer.Option("--budget-cny", help="Maximum LLM spend for planner and reads."),
    ] = 2.0,
    max_papers: Annotated[
        int,
        typer.Option("--max-papers", help="Maximum unique papers inspect/compare may touch."),
    ] = 5,
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Override PAPER_COPILOT_HOME root"),
    ] = None,
    no_record_quality: Annotated[
        bool,
        typer.Option(
            "--no-record-quality",
            help="Do not append final_output.quality to eval/runs/.",
        ),
    ] = False,
    no_update_report: Annotated[
        bool,
        typer.Option(
            "--no-update-report",
            help="Do not refresh eval/report.html after recording quality.",
        ),
    ] = False,
) -> None:
    """Run a bounded research tool loop over the local library."""
    if pdf_dir is not None:
        pdf_dir = pdf_dir.resolve()
    if max_turns <= 0:
        raise typer.BadParameter("--max-turns must be positive")
    if budget_cny <= 0:
        raise typer.BadParameter("--budget-cny must be positive")
    if max_papers <= 0:
        raise typer.BadParameter("--max-papers must be positive")
    if pdf_dir is not None and not pdf_dir.is_dir():
        raise typer.BadParameter(f"--pdf-dir is not a directory: {pdf_dir}")
    try:
        result = asyncio.run(
            handle_chat_request(
                topic,
                pdf_dir=pdf_dir,
                max_turns=max_turns,
                budget_cny=budget_cny,
                max_papers=max_papers,
                root=root,
                record_quality=not no_record_quality,
                update_report=not no_update_report,
            )
        )
    except KnowledgeError as exc:
        typer.echo(str(exc), err=True)
        code = 1 if str(exc).startswith("index missing") else 2
        raise typer.Exit(code=code) from exc
    except EvalError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    _print_result(result)


def _print_result(result: ChatRunResult) -> None:
    console = Console()
    console.print(Markdown(result.report_markdown))
    console.print()
    console.print(f"[dim]route:   {result.route.kind}[/dim]")
    console.print(f"[dim]session: {result.session_path}[/dim]")
    console.print(f"[dim]report:  {result.report_path}[/dim]")
    if result.quality_run_path is not None:
        console.print(f"[dim]quality: {result.quality_run_path}[/dim]")
    if result.eval_report_path is not None:
        console.print(f"[dim]eval report: {result.eval_report_path}[/dim]")
    console.print(
        f"[dim]terminated: {result.termination_reason}; "
        f"cost: ¥{result.cost_cny:.4f}; events: {result.events_count}; "
        f"papers: {result.paper_budget['touched_count']}/"
        f"{result.paper_budget['max_papers']}[/dim]"
    )
