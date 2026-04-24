"""`paper-copilot reindex` subcommand.

Rebuilds both ``fields.db`` (always) and ``embeddings.db`` (when
``--pdf-dir`` is supplied). Historical sessions do not record the
original PDF path, so embeddings reindex is opt-in: the caller points at
a directory, we hash-match each PDF to its ``paper_id`` (same sha1 scheme
as ``compute_paper_id``) and re-extract sections on the fly.

Skeleton is recovered from the SkimAgent's ``emit_skim`` tool_use entry
inside ``session.jsonl``. That avoids paying for another SkimAgent run,
and keeps reindex a pure index-rebuild step (no LLM cost).

Tolerates schema drift in historical payloads — fields_store holds raw
JSON, PaperSkeleton is re-validated (only skeleton.sections are needed
for splitting).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from paper_copilot.knowledge.embeddings_store import EmbeddingsStore
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.knowledge.meta import IndexMeta, write_meta
from paper_copilot.knowledge.sync import index_paper, index_paper_embeddings
from paper_copilot.retrieval.sections import split_by_sections
from paper_copilot.schemas.paper import PaperSkeleton
from paper_copilot.session.paths import compute_paper_id, default_root
from paper_copilot.session.store import SessionStore
from paper_copilot.session.types import ToolUse
from paper_copilot.shared.chunking import Section
from paper_copilot.shared.embedder import EMBEDDING_DIM, MODEL_NAME, Embedder
from paper_copilot.shared.errors import SessionError


def reindex(
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Override PAPER_COPILOT_HOME root"),
    ] = None,
    pdf_dir: Annotated[
        Path | None,
        typer.Option(
            "--pdf-dir",
            help="Directory containing the source PDFs; enables embeddings rebuild.",
        ),
    ] = None,
) -> None:
    """Rebuild fields.db (and embeddings.db if --pdf-dir is given)."""
    home = root if root is not None else default_root()
    papers_dir = home / "papers"
    if not papers_dir.exists():
        typer.echo(f"no papers directory at {papers_dir}", err=True)
        raise typer.Exit(code=1)

    console = Console()
    t0 = time.perf_counter()

    pdf_map: dict[str, Path] = _index_pdfs(pdf_dir) if pdf_dir is not None else {}

    embedder: Embedder | None = None
    embeddings_store: EmbeddingsStore | None = None
    if pdf_dir is not None:
        with console.status("[dim]loading bge-m3 (first run downloads ~2.3 GB)…[/dim]"):
            embedder = Embedder()
        embeddings_store = EmbeddingsStore.open(
            home / "embeddings.db", dim=EMBEDDING_DIM
        )

    indexed_fields = 0
    indexed_embeds = 0
    skipped_fields: list[tuple[str, str]] = []
    skipped_embeds: list[tuple[str, str]] = []
    now = datetime.now(UTC).isoformat()

    try:
        with FieldsStore.open(home / "fields.db") as fstore, fstore.begin_batch():
            for paper_dir in sorted(papers_dir.iterdir()):
                if not (paper_dir / "session.jsonl").exists():
                    continue
                paper_id = paper_dir.name
                try:
                    session = SessionStore.load(paper_id, root=home)
                    final = session.last_final_output()
                except SessionError as e:
                    skipped_fields.append((paper_id, f"session error: {e}"))
                    continue
                if final is None:
                    skipped_fields.append((paper_id, "no final_output entry"))
                    continue
                index_paper(final.payload, paper_id, fstore, indexed_at=now)
                indexed_fields += 1

                if embeddings_store is None or embedder is None:
                    continue
                pdf_path = pdf_map.get(paper_id)
                if pdf_path is None:
                    skipped_embeds.append((paper_id, "no matching pdf"))
                    continue
                skeleton = _load_skeleton(session)
                if skeleton is None:
                    skipped_embeds.append((paper_id, "no emit_skim tool_use"))
                    continue
                raw_sections = split_by_sections(pdf_path, skeleton)
                sections = [
                    Section(
                        title=s.title,
                        page_start=s.page_start,
                        page_end=s.page_end,
                        text=s.text,
                    )
                    for s in raw_sections
                ]
                n = index_paper_embeddings(
                    paper_id, sections, store=embeddings_store, embedder=embedder
                )
                console.print(
                    f"  [dim]{paper_id}[/dim]  {n} chunks  ({pdf_path.name})"
                )
                indexed_embeds += 1

        if embeddings_store is not None:
            write_meta(
                home / "embeddings_meta.json",
                IndexMeta.fresh(
                    embedding_model=MODEL_NAME, embedding_dim=EMBEDDING_DIM
                ).with_counts(
                    n_papers=embeddings_store.count_papers(),
                    n_chunks=embeddings_store.count_chunks(),
                ),
            )
    finally:
        if embeddings_store is not None:
            embeddings_store.close()

    elapsed = time.perf_counter() - t0
    console.print(
        f"[green]fields.db[/green] indexed {indexed_fields} paper(s) "
        f"into {home / 'fields.db'}"
    )
    if skipped_fields:
        console.print(f"[yellow]fields skipped[/yellow] {len(skipped_fields)}:")
        for pid, reason in skipped_fields:
            console.print(f"  [dim]{pid}[/dim]  {reason}")
    if pdf_dir is not None:
        console.print(
            f"[green]embeddings.db[/green] indexed {indexed_embeds} paper(s) "
            f"into {home / 'embeddings.db'}"
        )
        if skipped_embeds:
            console.print(f"[yellow]embeddings skipped[/yellow] {len(skipped_embeds)}:")
            for pid, reason in skipped_embeds:
                console.print(f"  [dim]{pid}[/dim]  {reason}")
    console.print(f"[dim]elapsed: {elapsed:.1f}s[/dim]")


def _index_pdfs(pdf_dir: Path) -> dict[str, Path]:
    if not pdf_dir.exists():
        raise typer.BadParameter(f"--pdf-dir not found: {pdf_dir}")
    out: dict[str, Path] = {}
    for pdf in pdf_dir.rglob("*.pdf"):
        if pdf.is_file():
            out[compute_paper_id(pdf)] = pdf
    return out


def _load_skeleton(session: SessionStore) -> PaperSkeleton | None:
    for entry in session.read_all():
        if not isinstance(entry, ToolUse) or entry.name != "emit_skim":
            continue
        payload = entry.input.get("skeleton")
        if payload is None:
            return None
        return PaperSkeleton.model_validate(payload)
    return None
