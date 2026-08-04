from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paper_copilot.agents.llm_client import LLMClient
from paper_copilot.agents.loop import (
    Event,
    LLMClientProtocol,
    LLMStreamEventCallback,
)
from paper_copilot.agents.paper_copilot import (
    PaperCopilotContext,
    PaperCopilotRun,
    run_paper_copilot,
)
from paper_copilot.agents.tools.runtimes import get_library_environment
from paper_copilot.agents.tool_security import (
    ApprovalMode,
    ToolApprovalRequest,
    ToolApprovalReviewEvent,
)
from paper_copilot.schemas.compaction import CompactionSummary
from paper_copilot.session import SessionStore
from paper_copilot.session.paths import default_pdf_dir, default_root
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
    citation_targets: dict[str, str]
    composer_plan: dict[str, Any] | None
    proposal_check: dict[str, Any] | None
    conversation_compaction: CompactionSummary | None = None


async def handle_chat_request(
    request: str,
    *,
    pdf_dir: Path | None = None,
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
    session_store: SessionStore | None = None,
    turn_input_persisted: bool = False,
    turn_id: str | None = None,
    event_callback: Callable[[Event], None] | None = None,
    stream_event_callback: LLMStreamEventCallback | None = None,
    conversation_context: str | None = None,
    previous_compaction_summary: CompactionSummary | None = None,
    resume_history: list[dict[str, Any]] | None = None,
    resume_world_state_baseline: dict[str, Any] | None = None,
    resume_runtime_state: dict[str, Any] | None = None,
    recovery_source_session: str | None = None,
    continuation_prompt: str | None = None,
    request_tool_approval: (
        Callable[[ToolApprovalRequest], Awaitable[bool]] | None
    ) = None,
    approval_mode: ApprovalMode = "ask",
    approval_review_callback: Callable[[ToolApprovalReviewEvent], None] | None = None,
) -> ChatRunResult:
    home = root if root is not None else default_root()
    library_dir = pdf_dir if pdf_dir is not None else default_pdf_dir()
    if library_dir is not None:
        library_dir = library_dir.expanduser().resolve()
    if library_dir is not None and not library_dir.is_dir():
        raise KnowledgeError(f"pdf_dir does not exist: {library_dir}")

    client = llm if llm is not None else LLMClient()
    read_client = read_llm if read_llm is not None else _read_client(client)
    context = PaperCopilotContext(
        pdf_dir=library_dir,
        root=home,
        max_papers=max_papers,
        library_environment=(
            get_library_environment(session_store.path.parent / "library-environment")
            if session_store is not None
            else None
        ),
    )
    run = await run_paper_copilot(
            prompt=request,
            llm=client,
            read_llm=read_client,
            context=context,
            root=home,
            max_budget_cny=budget_cny,
            session_id=session_id,
            session_store=session_store,
            turn_input_persisted=turn_input_persisted,
            event_callback=event_callback,
            stream_event_callback=stream_event_callback,
            conversation_context=conversation_context,
            previous_compaction_summary=previous_compaction_summary,
            resume_history=resume_history,
            resume_world_state_baseline=resume_world_state_baseline,
            resume_runtime_state=resume_runtime_state,
            recovery_source_session=recovery_source_session,
            continuation_prompt=continuation_prompt,
            request_tool_approval=request_tool_approval,
            approval_mode=approval_mode,
            approval_review_callback=approval_review_callback,
    )

    return _persist_chat_result(
        request=request,
        run=run,
        record_quality=record_quality,
        update_report=update_report,
        runs_dir=runs_dir,
        report_out_path=eval_report_path,
        turn_id=turn_id,
    )


def _persist_chat_result(
    *,
    request: str,
    run: PaperCopilotRun,
    record_quality: bool,
    update_report: bool,
    runs_dir: Path | None,
    report_out_path: Path | None,
    turn_id: str | None,
) -> ChatRunResult:
    report_path = run.session_path.parent / "research-report.md"
    report_path.write_text(run.report_markdown, encoding="utf-8")

    quality_run_path: Path | None = None
    eval_report_path: Path | None = None
    # Paper-index retrieval evaluation was removed with the paper index. Session
    # and trace artifacts remain the authoritative runtime record.

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
        citation_targets=run.citation_targets,
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
