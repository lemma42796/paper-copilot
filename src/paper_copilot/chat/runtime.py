from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paper_copilot.agents.llm_client import LLMClient
from paper_copilot.agents.loop import Event, LLMClientProtocol
from paper_copilot.agents.paper_copilot import (
    PaperCopilotContext,
    PaperCopilotRun,
    run_paper_copilot,
)
from paper_copilot.agents.tool_security import ToolApprovalRequest
from paper_copilot.eval._paths import default_report_path
from paper_copilot.eval.report import write_report
from paper_copilot.eval.runs import load_history, write_research_quality_run
from paper_copilot.knowledge.embeddings_store import EmbeddingsStore
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.knowledge.meta import IndexMeta, require_match, write_meta
from paper_copilot.schemas.compaction import CompactionSummary
from paper_copilot.session.paths import default_pdf_dir, default_root, embedding_cache_file
from paper_copilot.shared.embedder import EMBEDDING_DIM, MODEL_NAME, Embedder
from paper_copilot.shared.embedding_cache import CachedEmbedder, EmbeddingCache, EmbeddingEncoder
from paper_copilot.shared.errors import KnowledgeError


@dataclass(frozen=True, slots=True)
class ChatRunResult:
    request: str
    report_markdown: str
    session_path: Path
    report_path: Path
    quality_run_path: Path | None
    eval_report_path: Path | None
    termination_reason: str
    cost_cny: float
    events_count: int
    paper_budget: dict[str, object]
    composer_plan: dict[str, Any] | None
    proposal_check: dict[str, Any] | None
    conversation_compaction: CompactionSummary | None = None


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
    session_id: str | None = None,
    event_callback: Callable[[Event], None] | None = None,
    conversation_context: str | None = None,
    previous_compaction_summary: CompactionSummary | None = None,
    resume_history: list[dict[str, Any]] | None = None,
    resume_runtime_state: dict[str, Any] | None = None,
    recovery_source_session: str | None = None,
    request_tool_approval: Callable[[ToolApprovalRequest], Awaitable[bool]] | None = None,
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
    embedder: EmbeddingEncoder | None = None
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
            raw_embedder = Embedder()
            raw_embedder.warmup()
            embedding_cache = stack.enter_context(
                EmbeddingCache.open(embedding_cache_file(home), dim=EMBEDDING_DIM)
            )
            embedder = CachedEmbedder(raw_embedder, embedding_cache)
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
        context = PaperCopilotContext(
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
        run = await run_paper_copilot(
            prompt=request,
            llm=client,
            read_llm=read_client,
            context=context,
            root=home,
            max_turns=max_turns,
            max_budget_cny=budget_cny,
            session_id=session_id,
            event_callback=event_callback,
            conversation_context=conversation_context,
            previous_compaction_summary=previous_compaction_summary,
            resume_history=resume_history,
            resume_runtime_state=resume_runtime_state,
            recovery_source_session=recovery_source_session,
            request_tool_approval=request_tool_approval,
        )

    return _persist_chat_result(
        request=request,
        run=run,
        record_quality=record_quality,
        update_report=update_report,
        runs_dir=runs_dir,
        report_out_path=eval_report_path,
    )


def _persist_chat_result(
    *,
    request: str,
    run: PaperCopilotRun,
    record_quality: bool,
    update_report: bool,
    runs_dir: Path | None,
    report_out_path: Path | None,
) -> ChatRunResult:
    report_path = run.session_path.parent / "research-report.md"
    report_path.write_text(run.report_markdown, encoding="utf-8")

    quality_run_path: Path | None = None
    eval_report_path: Path | None = None
    if record_quality and run.tool_names:
        quality_run_path = write_research_quality_run(run.session_path, runs_dir=runs_dir)
        if update_report:
            eval_report_path = write_report(
                load_history(runs_dir=runs_dir, suite_name="research"),
                report_out_path if report_out_path is not None else default_report_path(),
            )

    return ChatRunResult(
        request=request,
        report_markdown=run.report_markdown,
        session_path=run.session_path,
        report_path=report_path,
        quality_run_path=quality_run_path,
        eval_report_path=eval_report_path,
        termination_reason=run.termination_reason,
        cost_cny=run.cost.cost_cny,
        events_count=len(run.events),
        paper_budget=run.termination_summary.paper_budget,
        composer_plan=_optional_payload_dict(run.final_payload.get("composer_plan")),
        proposal_check=_optional_payload_dict(run.final_payload.get("proposal_check")),
        conversation_compaction=run.conversation_compaction,
    )


def _read_client(llm: LLMClientProtocol) -> LLMClient | None:
    return llm if isinstance(llm, LLMClient) else None


def _optional_payload_dict(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return {str(key): item for key, item in value.items()}
