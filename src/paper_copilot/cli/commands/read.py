"""`paper-copilot read <pdf>` subcommand."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Annotated, Literal, cast

import typer
from rich.console import Console
from rich.markdown import Markdown

from paper_copilot.agents.llm_client import LLMClient
from paper_copilot.agents.main import MainAgent
from paper_copilot.cli.render import to_markdown
from paper_copilot.session.paths import compute_paper_id, paper_dir


def read(
    pdf_path: Annotated[Path, typer.Argument(help="Path to the paper PDF")],
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite existing session for this paper"),
    ] = False,
    lang: Annotated[
        str,
        typer.Option("--lang", "-l", help="Output language: en or zh"),
    ] = "en",
) -> None:
    """Deep-read a paper and write a structured Markdown report."""
    if lang not in ("en", "zh"):
        raise typer.BadParameter(f"unsupported language: {lang!r}; use 'en' or 'zh'")
    asyncio.run(_read_async(pdf_path, force, cast("Literal['en', 'zh']", lang)))


async def _read_async(pdf_path: Path, force: bool, language: Literal["en", "zh"]) -> None:
    if not pdf_path.exists():
        raise typer.BadParameter(f"PDF not found: {pdf_path}")

    pid = compute_paper_id(pdf_path)
    pdir = paper_dir(pid)
    if pdir.exists():
        if not force:
            raise typer.BadParameter(
                f"session already exists for paper_id={pid} at {pdir}. "
                "Rerun with --force to overwrite."
            )
        shutil.rmtree(pdir)

    agent = MainAgent(LLMClient())
    run = await agent.run(pdf_path, language=language)

    md = to_markdown(run.paper, language=language)
    report_path = pdir / "report.md"
    report_path.write_text(md, encoding="utf-8")

    console = Console()
    console.print(Markdown(md))
    console.print()
    console.print(f"[dim]session: {run.session_path}[/dim]")
    console.print(f"[dim]report:  {report_path}[/dim]")
    c = run.cost
    console.print(
        f"[dim]cost:    ¥{c.cost_cny:.4f} "
        f"(in={c.input_tokens}, out={c.output_tokens}, "
        f"cache_read={c.cache_read_tokens})[/dim]"
    )
