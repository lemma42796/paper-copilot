"""Manual reality check for SkimAgent.

Run: `uv run python scripts/try_skim.py <pdf_path>`

Prints PaperMeta / PaperSkeleton / CostSnapshot to the terminal, and writes
a JSON dump of the full request+response to /tmp for post-hoc inspection.
Not a test — the output is for human eyeballs.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import time
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from paper_copilot.agents.llm_client import DEFAULT_MODEL, LLMClient
from paper_copilot.agents.skim import SkimAgent, SkimResult, SkimRun
from paper_copilot.session import SessionStore, compute_paper_id, session_file
from paper_copilot.shared.cost import CostTracker


def _usage_to_dict(usage: Any) -> dict[str, int]:
    return {
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }


def _content_block_to_dict(block: Any) -> dict[str, Any]:
    d = dataclasses.asdict(block)
    return d


def _render(console: Console, result: SkimResult, cost: CostTracker) -> None:
    meta = result.meta
    table = Table(title="PaperMeta", show_header=False, title_style="bold cyan")
    table.add_column("field", style="bold")
    table.add_column("value")
    table.add_row("id", meta.id)
    table.add_row("title", meta.title)
    table.add_row("authors", "\n".join(meta.authors))
    table.add_row("arxiv_id", repr(meta.arxiv_id))
    table.add_row("year", str(meta.year))
    table.add_row("venue", repr(meta.venue))
    console.print(table)

    tree = Tree("[bold cyan]PaperSkeleton[/bold cyan]")
    for section in result.skeleton.sections:
        indent = "  " * (section.depth - 1)
        end = section.page_end if section.page_end is not None else "?"
        tree.add(
            f"{indent}[d={section.depth}] p{section.page_start}-{end} | {section.title}"
        )
    console.print(tree)

    snap = cost.snapshot()
    console.print(
        Panel.fit(
            f"input_tokens          = {snap.input_tokens}\n"
            f"output_tokens         = {snap.output_tokens}\n"
            f"cache_creation_tokens = {snap.cache_creation_tokens}\n"
            f"cache_read_tokens     = {snap.cache_read_tokens}\n"
            f"cost_cny              = ¥{snap.cost_cny:.6f}",
            title="CostSnapshot",
            title_align="left",
        )
    )


def _write_dump(run: SkimRun, pdf_stem: str) -> Path:
    ts = int(time.time())
    dump_path = Path(f"/tmp/try_skim_{pdf_stem}_{ts}_{DEFAULT_MODEL}.json")
    payload: dict[str, Any] = {
        "model": DEFAULT_MODEL,
        "request": {
            "messages": run.request_messages,
            "tools": run.request_tools,
        },
        "response": {
            "content": [_content_block_to_dict(b) for b in run.response.content],
            "stop_reason": run.response.stop_reason,
            "usage": _usage_to_dict(run.response.usage),
        },
    }
    dump_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return dump_path


async def _amain(pdf_path: Path) -> None:
    console = Console()
    client = LLMClient()
    paper_id = compute_paper_id(pdf_path)
    store = SessionStore.create(paper_id, model=DEFAULT_MODEL, agent="skim")
    agent = SkimAgent(client, store=store)
    cost = CostTracker()

    run = await agent.run(pdf_path)
    if run.response.usage is not None:
        cost.record(run.response.usage)

    _render(console, run.result, cost)
    dump_path = _write_dump(run, pdf_path.stem)
    console.print(f"\n[dim]debug dump:[/dim] {dump_path}")
    console.print(f"[dim]session log:[/dim] {session_file(paper_id)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manual SkimAgent reality check.")
    parser.add_argument("pdf_path", type=Path, help="absolute path to a PDF file")
    args = parser.parse_args()
    asyncio.run(_amain(args.pdf_path))


if __name__ == "__main__":
    main()
