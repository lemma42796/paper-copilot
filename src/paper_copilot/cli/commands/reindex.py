"""`paper-copilot reindex` subcommand.

M10 scope: rebuild fields.db from every paper's ``session.jsonl``. M11
extends this command to also rebuild ``embeddings.db``.

Tolerates schema drift in historical payloads — the fields store holds
raw JSON and does not re-validate, so pre-M8 sessions with extra
``meta.id`` fields index fine.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.knowledge.sync import index_paper
from paper_copilot.session.paths import default_root
from paper_copilot.session.store import SessionStore
from paper_copilot.shared.errors import SessionError


def reindex(
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Override PAPER_COPILOT_HOME root"),
    ] = None,
) -> None:
    """Rebuild fields.db from every paper's session.jsonl."""
    home = root if root is not None else default_root()
    papers_dir = home / "papers"
    if not papers_dir.exists():
        typer.echo(f"no papers directory at {papers_dir}", err=True)
        raise typer.Exit(code=1)

    console = Console()
    db_path = home / "fields.db"
    indexed = 0
    skipped: list[tuple[str, str]] = []
    now = datetime.now(UTC).isoformat()

    with FieldsStore.open(db_path) as store, store.begin_batch():
        for paper_dir in sorted(papers_dir.iterdir()):
            if not (paper_dir / "session.jsonl").exists():
                continue
            paper_id = paper_dir.name
            try:
                session = SessionStore.load(paper_id, root=home)
                final = session.last_final_output()
            except SessionError as e:
                skipped.append((paper_id, f"session error: {e}"))
                continue
            if final is None:
                skipped.append((paper_id, "no final_output entry"))
                continue
            index_paper(final.payload, paper_id, store, indexed_at=now)
            indexed += 1

    console.print(f"[green]indexed[/green] {indexed} paper(s) into {db_path}")
    if skipped:
        console.print(f"[yellow]skipped[/yellow] {len(skipped)}:")
        for pid, reason in skipped:
            console.print(f"  [dim]{pid}[/dim]  {reason}")
