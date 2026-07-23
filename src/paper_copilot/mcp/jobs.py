from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paper_copilot.chat.jobs import ChatJobEvent, ChatJobRecord, ChatJobSpec, job_registry
from paper_copilot.session.paths import compute_paper_id, default_pdf_dir, default_root
from paper_copilot.shared.errors import JobError, KnowledgeError

_PAPER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,64}$")
_JOB_ID_RE = re.compile(r"^job-[0-9A-Za-z-]{8,80}$")
_MAX_OBJECTIVE_TEXT = 2_000
_MAX_STATUS_EVENTS = 50
_MAX_EVENT_TEXT = 1_000
_MAX_ERROR_TEXT = 2_000
_MAX_REPORT_TEXT = 30_000
_JOB_BUDGET_CNY = 2.0


@dataclass(frozen=True, slots=True)
class MCPJobService:
    root: Path
    pdf_dir: Path | None

    @classmethod
    def from_environment(
        cls,
        *,
        root: Path | None = None,
        pdf_dir: Path | None = None,
    ) -> MCPJobService:
        resolved_root = (
            root if root is not None else default_root()
        ).expanduser().resolve()
        configured_pdf_dir = pdf_dir if pdf_dir is not None else default_pdf_dir()
        resolved_pdf_dir = (
            configured_pdf_dir.expanduser().resolve()
            if configured_pdf_dir is not None
            else None
        )
        return cls(root=resolved_root, pdf_dir=resolved_pdf_dir)

    def start_read_paper(
        self,
        paper_id: str,
        *,
        objective: str | None = None,
    ) -> dict[str, Any]:
        _validate_paper_id(paper_id)
        pdf_dir = self._require_local_pdf(paper_id)
        normalized_objective = _normalize_objective(objective)
        request = (
            f"深度阅读本地论文，目标论文必须使用 paper_id `{paper_id}` 精确定位。"
            "调用 read_paper 获取或更新结构化论文内容，并基于论文证据完成任务。"
            "不要修改、移动或删除论文库文件，最终报告不要包含本机绝对路径。"
        )
        if normalized_objective is not None:
            request += f"\n\n具体任务：{normalized_objective}"
        else:
            request += "\n\n具体任务：总结核心贡献、方法、实验结论和局限，并给出可核查证据。"
        record = job_registry(self.root).create(
            ChatJobSpec(
                request=request,
                pdf_dir=str(pdf_dir),
                max_papers=1,
                budget_cny=_JOB_BUDGET_CNY,
            )
        )
        return {
            "status": "accepted",
            "job_id": record.id,
            "job_status": record.status,
            "paper_id": paper_id,
            "created_at": record.created_at,
            "budget_cny": record.spec.budget_cny,
            "next_action": (
                "Call get_job_status with this job_id. Pass next_after_event_seq "
                "back as after_event_seq on later calls."
            ),
        }

    def get_job_status(
        self,
        job_id: str,
        *,
        after_event_seq: int = 0,
        event_limit: int = 20,
    ) -> dict[str, Any]:
        _validate_job_id(job_id)
        if after_event_seq < 0:
            raise JobError("after_event_seq must be non-negative")
        if not 1 <= event_limit <= _MAX_STATUS_EVENTS:
            raise JobError(
                f"event_limit must be between 1 and {_MAX_STATUS_EVENTS}"
            )
        registry = job_registry(self.root)
        record = registry.get(job_id)
        events = registry.events(
            job_id,
            after=after_event_seq,
            limit=event_limit + 1,
        )
        selected_events = events[:event_limit]
        next_after = (
            selected_events[-1].seq if selected_events else after_event_seq
        )
        return {
            "status": "ok",
            "job_id": record.id,
            "job_status": record.status,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "latest_attempt": _latest_attempt_payload(record),
            "error": _bounded_optional_text(record.error, _MAX_ERROR_TEXT),
            "waiting_for_approval": record.status == "waiting_for_approval",
            "events": [_event_payload(event) for event in selected_events],
            "next_after_event_seq": next_after,
            "has_more_events": len(events) > event_limit,
            "terminal": record.status in {"completed", "interrupted", "failed"},
        }

    def get_job_result(self, job_id: str) -> dict[str, Any]:
        _validate_job_id(job_id)
        record = job_registry(self.root).get(job_id)
        if record.status != "completed":
            active = record.status in {
                "queued",
                "running",
                "waiting_for_approval",
            }
            return {
                "status": "not_ready" if active else "no_result",
                "job_id": record.id,
                "job_status": record.status,
                "terminal": record.status in {"interrupted", "failed"},
                "error": _bounded_optional_text(record.error, _MAX_ERROR_TEXT),
                "next_action": (
                    "Call get_job_status for progress."
                    if active
                    else "This attempt has no completed result."
                ),
            }
        if record.result is None:
            raise JobError(f"completed job {job_id} has no result")
        report = _bounded_text(record.result.report_markdown, _MAX_REPORT_TEXT)
        return {
            "status": "ok",
            "job_id": record.id,
            "job_status": record.status,
            "completed_at": record.updated_at,
            "termination_reason": record.result.termination_reason,
            "cost_cny": record.result.cost_cny,
            "events_count": record.result.events_count,
            "paper_budget": record.result.paper_budget,
            "report_markdown": report["text"],
            "report_truncated": report["truncated"],
            "report_original_chars": report["original_chars"],
        }

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        _validate_job_id(job_id)
        registry = job_registry(self.root)
        record = registry.get(job_id)
        if record.status in {"completed", "interrupted", "failed"}:
            return {
                "status": "already_terminal",
                "job_id": record.id,
                "job_status": record.status,
                "cancellation_requested": False,
            }
        record = registry.interrupt(job_id)
        return {
            "status": "cancellation_requested",
            "job_id": record.id,
            "job_status": record.status,
            "cancellation_requested": True,
            "next_action": (
                "Call get_job_status until job_status is interrupted, completed, "
                "or failed."
            ),
        }

    def _require_local_pdf(self, paper_id: str) -> Path:
        if self.pdf_dir is None or not self.pdf_dir.is_dir():
            raise KnowledgeError("start_read_paper requires a configured PDF directory")
        for pdf_path in sorted(self.pdf_dir.rglob("*")):
            if (
                pdf_path.is_file()
                and pdf_path.suffix.lower() == ".pdf"
                and compute_paper_id(pdf_path) == paper_id
            ):
                return self.pdf_dir
        raise KnowledgeError(
            f"local PDF not found for paper_id under the configured directory: {paper_id}"
        )


def _validate_paper_id(paper_id: str) -> None:
    if _PAPER_ID_RE.fullmatch(paper_id) is None:
        raise KnowledgeError(f"invalid paper id: {paper_id}")


def _validate_job_id(job_id: str) -> None:
    if _JOB_ID_RE.fullmatch(job_id) is None:
        raise JobError(f"invalid job id: {job_id}")


def _normalize_objective(objective: str | None) -> str | None:
    if objective is None:
        return None
    normalized = objective.strip()
    if not normalized:
        raise JobError("objective must be non-empty when provided")
    if len(normalized) > _MAX_OBJECTIVE_TEXT:
        raise JobError(
            f"objective must contain at most {_MAX_OBJECTIVE_TEXT} characters"
        )
    return normalized


def _latest_attempt_payload(record: ChatJobRecord) -> dict[str, Any] | None:
    if not record.attempts:
        return None
    attempt = record.attempts[-1]
    return {
        "number": attempt.number,
        "status": attempt.status,
        "started_at": attempt.started_at,
        "finished_at": attempt.finished_at,
        "error": _bounded_optional_text(attempt.error, _MAX_ERROR_TEXT),
        "resumed_from_attempt": attempt.resumed_from_attempt,
    }


def _event_payload(event: ChatJobEvent) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "seq": event.seq,
            "ts": event.ts,
            "type": event.type,
            "status": event.status,
            "attempt": event.attempt,
            "message": _bounded_optional_text(event.message, _MAX_EVENT_TEXT),
            "activity_id": event.activity_id,
            "activity_kind": event.activity_kind,
            "activity_phase": event.activity_phase,
            "title": _bounded_optional_text(event.title, _MAX_EVENT_TEXT),
            "delta": _bounded_optional_text(event.delta, _MAX_EVENT_TEXT),
            "detail": _bounded_optional_text(event.detail, _MAX_EVENT_TEXT),
        }.items()
        if value is not None
    }


def _bounded_optional_text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return value if len(value) <= limit else f"{value[:limit]}…"


def _bounded_text(value: str, limit: int) -> dict[str, Any]:
    return {
        "text": value if len(value) <= limit else f"{value[:limit]}…",
        "truncated": len(value) > limit,
        "original_chars": len(value),
    }
