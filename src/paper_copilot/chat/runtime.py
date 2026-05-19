from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from paper_copilot.agents.llm_client import LLMClient
from paper_copilot.agents.loop import LLMClientProtocol
from paper_copilot.agents.research import ResearchRun, ResearchToolContext, run_research
from paper_copilot.chat.router import ChatRoute, route_chat_request
from paper_copilot.eval._paths import default_report_path
from paper_copilot.eval.report import write_report
from paper_copilot.eval.runs import load_history, write_research_quality_run
from paper_copilot.knowledge.embeddings_store import EmbeddingsStore
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.knowledge.meta import IndexMeta, require_match, write_meta
from paper_copilot.session.paths import default_pdf_dir, default_root
from paper_copilot.shared.embedder import EMBEDDING_DIM, MODEL_NAME, Embedder
from paper_copilot.shared.errors import KnowledgeError


@dataclass(frozen=True, slots=True)
class ChatRunResult:
    request: str
    route: ChatRoute
    report_markdown: str
    session_path: Path
    report_path: Path
    quality_run_path: Path | None
    eval_report_path: Path | None
    termination_reason: str
    cost_cny: float
    events_count: int
    paper_budget: dict[str, object]


async def handle_chat_request(
    request: str,
    *,
    pdf_dir: Path | None = None,
    max_turns: int = 16,
    budget_cny: float = 2.0,
    max_papers: int = 5,
    root: Path | None = None,
    record_quality: bool = True,
    update_report: bool = True,
    runs_dir: Path | None = None,
    eval_report_path: Path | None = None,
    llm: LLMClientProtocol | None = None,
    read_llm: LLMClient | None = None,
) -> ChatRunResult:
    home = root if root is not None else default_root()
    library_dir = pdf_dir if pdf_dir is not None else default_pdf_dir()
    if library_dir is not None:
        library_dir = library_dir.expanduser().resolve()
    if library_dir is not None and not library_dir.is_dir():
        raise KnowledgeError(f"pdf_dir does not exist: {library_dir}")

    fields_db = home / "fields.db"
    embeddings_db = home / "embeddings.db"
    meta_path = home / "embeddings_meta.json"
    if not fields_db.exists() and library_dir is None:
        raise KnowledgeError(
            f"index missing at {fields_db}. "
            "Run `paper-copilot reindex --pdf-dir <dir>` first."
        )

    route = route_chat_request(request)
    embedder: Embedder | None = None
    with ExitStack() as stack:
        fields_store = stack.enter_context(FieldsStore.open(fields_db))
        embeddings_store: EmbeddingsStore | None = None
        if library_dir is not None or embeddings_db.exists():
            if embeddings_db.exists():
                require_match(
                    meta_path,
                    embedding_model=MODEL_NAME,
                    embedding_dim=EMBEDDING_DIM,
                )
            embedder = Embedder()
            embedder.warmup()
            embeddings_store = stack.enter_context(
                EmbeddingsStore.open(embeddings_db, dim=EMBEDDING_DIM)
            )
            if not meta_path.exists():
                write_meta(
                    meta_path,
                    IndexMeta.fresh(
                        embedding_model=MODEL_NAME,
                        embedding_dim=EMBEDDING_DIM,
                    ).with_counts(
                        n_papers=embeddings_store.count_papers(),
                        n_chunks=embeddings_store.count_chunks(),
                    ),
                )

        client = llm if llm is not None else LLMClient()
        read_client = read_llm if read_llm is not None else _read_client(client)
        context = ResearchToolContext(
            fields_store=fields_store,
            embeddings_store=embeddings_store,
            encode_query=(
                (lambda query: embedder.encode([query])[0]) if embedder is not None else None
            ),
            embedder=embedder,
            pdf_dir=library_dir,
            root=home,
            max_papers=max_papers,
        )
        run = await run_research(
            topic=request,
            llm=client,
            read_llm=read_client,
            context=context,
            root=home,
            max_turns=max_turns,
            max_budget_cny=budget_cny,
        )

    return _persist_chat_result(
        request=request,
        route=route,
        run=run,
        record_quality=record_quality,
        update_report=update_report,
        runs_dir=runs_dir,
        report_out_path=eval_report_path,
    )


def _persist_chat_result(
    *,
    request: str,
    route: ChatRoute,
    run: ResearchRun,
    record_quality: bool,
    update_report: bool,
    runs_dir: Path | None,
    report_out_path: Path | None,
) -> ChatRunResult:
    report_path = run.session_path.parent / "research-report.md"
    report_path.write_text(run.report_markdown, encoding="utf-8")

    quality_run_path: Path | None = None
    eval_report_path: Path | None = None
    if record_quality:
        quality_run_path = write_research_quality_run(run.session_path, runs_dir=runs_dir)
        if update_report:
            eval_report_path = write_report(
                load_history(runs_dir=runs_dir, suite_name="research"),
                report_out_path if report_out_path is not None else default_report_path(),
            )

    return ChatRunResult(
        request=request,
        route=route,
        report_markdown=run.report_markdown,
        session_path=run.session_path,
        report_path=report_path,
        quality_run_path=quality_run_path,
        eval_report_path=eval_report_path,
        termination_reason=run.termination_reason,
        cost_cny=run.cost.cost_cny,
        events_count=len(run.events),
        paper_budget=run.termination_summary.paper_budget,
    )


def _read_client(llm: LLMClientProtocol) -> LLMClient | None:
    return llm if isinstance(llm, LLMClient) else None
