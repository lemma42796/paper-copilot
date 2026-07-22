from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from paper_copilot.agents.loop import (
    AssistantMessage,
    Event,
    Terminated,
    ToolResult,
    ToolUse,
)
from paper_copilot.chat.runtime import ChatRunResult, handle_chat_request
from paper_copilot.observability import (
    RolloutDiagnostics,
    RolloutRecorder,
    diagnose_rollout,
    reduce_trace_bundle,
)
from paper_copilot.schemas.compaction import CompactionSummary
from paper_copilot.session import SessionStore, reconstruct_rollout
from paper_copilot.session.paths import default_root, session_file
from paper_copilot.shared.errors import JobError, RolloutTimeoutError

JobStatus = Literal["queued", "running", "completed", "interrupted", "failed"]
AttemptStatus = Literal["running", "completed", "interrupted", "failed"]

_JOB_ID_RE = re.compile(r"^job-[0-9A-Za-z-]{8,80}$")
_CONVERSATION_ID_RE = re.compile(r"^conversation-[0-9A-Za-z-]{8,80}$")
_REGISTRIES: dict[Path, ChatJobRegistry] = {}
_REGISTRIES_LOCK = threading.Lock()


class ChatJobSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: str = Field(min_length=1)
    conversation_id: str | None = Field(
        default=None,
        pattern=_CONVERSATION_ID_RE.pattern,
    )
    pdf_dir: str | None = None
    max_turns: int = Field(default=16, ge=1)
    budget_cny: float = Field(default=2.0, gt=0)
    max_papers: int = Field(default=5, ge=1)
    record_quality: bool = True
    update_report: bool = True
    recovery_mode: Literal["restart_from_request", "rollout_replay"] = "rollout_replay"
    rollout_timeout_seconds: float | None = Field(default=3600.0, gt=0)


class ChatJobResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: str
    report_markdown: str
    session_path: str
    report_path: str
    quality_run_path: str | None
    eval_report_path: str | None
    termination_reason: str
    cost_cny: float
    events_count: int
    paper_budget: dict[str, object]
    composer_plan: dict[str, object] | None
    proposal_check: dict[str, object] | None
    conversation_compaction: CompactionSummary | None = None

    @classmethod
    def from_run(cls, run: ChatRunResult) -> ChatJobResult:
        return cls(
            request=run.request,
            report_markdown=run.report_markdown,
            session_path=str(run.session_path),
            report_path=str(run.report_path),
            quality_run_path=(
                str(run.quality_run_path) if run.quality_run_path is not None else None
            ),
            eval_report_path=(
                str(run.eval_report_path) if run.eval_report_path is not None else None
            ),
            termination_reason=run.termination_reason,
            cost_cny=run.cost_cny,
            events_count=run.events_count,
            paper_budget=run.paper_budget,
            composer_plan=run.composer_plan,
            proposal_check=run.proposal_check,
            conversation_compaction=run.conversation_compaction,
        )


class ChatJobAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int = Field(ge=1)
    status: AttemptStatus
    session_id: str
    session_path: str
    started_at: str
    finished_at: str | None = None
    error: str | None = None
    resumed_from_attempt: int | None = Field(default=None, ge=1)


class ChatJobRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    id: str
    status: JobStatus
    created_at: str
    updated_at: str
    spec: ChatJobSpec
    attempts: list[ChatJobAttempt] = Field(default_factory=list)
    result: ChatJobResult | None = None
    error: str | None = None


class ChatJobEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=1)
    ts: str
    type: Literal[
        "created",
        "started",
        "progress",
        "completed",
        "interrupted",
        "failed",
        "resumed",
    ]
    status: JobStatus
    attempt: int
    message: str


class ChatJobRegistry:
    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()
        self._jobs_dir = self._root / "jobs"
        self._jobs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._events_changed = threading.Condition(self._lock)
        self._threads: dict[str, threading.Thread] = {}
        self._async_tasks: dict[
            str,
            tuple[asyncio.AbstractEventLoop, asyncio.Task[Any]],
        ] = {}
        self._interrupt_requested: set[str] = set()
        self._recover_orphaned_jobs()

    def create(self, spec: ChatJobSpec) -> ChatJobRecord:
        if spec.conversation_id is None:
            spec = spec.model_copy(
                update={"conversation_id": _new_conversation_id()}
            )
        now = _now_ts()
        job_id = _new_job_id()
        record = ChatJobRecord(
            id=job_id,
            status="queued",
            created_at=now,
            updated_at=now,
            spec=spec,
        )
        with self._lock:
            self._write_record(record)
            self._append_event(
                job_id,
                event_type="created",
                status="queued",
                attempt=0,
                message="任务已创建, 等待本地执行。",
            )
            self._start(job_id)
        return record

    def get(self, job_id: str) -> ChatJobRecord:
        _validate_job_id(job_id)
        with self._lock:
            return self._read_record(job_id)

    def list(self, *, limit: int = 50) -> list[ChatJobRecord]:
        with self._lock:
            records = [self._read_record(path.parent.name) for path in self._job_files()]
        records.sort(key=lambda record: record.updated_at, reverse=True)
        return records[:limit]

    def events(
        self,
        job_id: str,
        *,
        after: int = 0,
        limit: int = 200,
    ) -> list[ChatJobEvent]:
        _validate_job_id(job_id)
        with self._lock:
            self._read_record(job_id)
            events = self._read_events(job_id)
        return [event for event in events if event.seq > after][:limit]

    def diagnostics(
        self,
        job_id: str,
        *,
        attempt: int | None = None,
        slow_ms: int = 1000,
        repeat_threshold: int = 3,
    ) -> RolloutDiagnostics:
        _validate_job_id(job_id)
        with self._lock:
            record = self._read_record(job_id)
            if not record.attempts:
                raise JobError(f"job {job_id} has no attempts")
            attempt_number = (
                attempt if attempt is not None else record.attempts[-1].number
            )
            if not any(item.number == attempt_number for item in record.attempts):
                raise JobError(
                    f"job {job_id} has no attempt {attempt_number}"
                )
            bundle_dir = self._job_dir(job_id) / "attempts" / str(attempt_number)
            state = reduce_trace_bundle(bundle_dir)
            return diagnose_rollout(
                bundle_dir,
                state,
                slow_ms=slow_ms,
                repeat_threshold=repeat_threshold,
            )

    def wait_for_events(
        self,
        job_id: str,
        *,
        after: int,
        limit: int = 200,
        timeout: float = 15.0,
    ) -> tuple[ChatJobRecord, list[ChatJobEvent]]:
        _validate_job_id(job_id)
        with self._events_changed:
            record = self._read_record(job_id)
            events = [
                event for event in self._read_events(job_id) if event.seq > after
            ][:limit]
            if not events and record.status in {"queued", "running"}:
                self._events_changed.wait(timeout=timeout)
                record = self._read_record(job_id)
                events = [
                    event for event in self._read_events(job_id) if event.seq > after
                ][:limit]
            return record, events

    def resume(self, job_id: str) -> ChatJobRecord:
        _validate_job_id(job_id)
        with self._lock:
            record = self._read_record(job_id)
            if record.status not in {"interrupted", "failed"}:
                raise JobError(
                    f"job {job_id} cannot resume from status {record.status}"
                )
            existing = self._threads.get(job_id)
            if existing is not None and existing.is_alive():
                raise JobError(f"job {job_id} is still stopping")
            now = _now_ts()
            record.status = "queued"
            record.updated_at = now
            record.error = None
            record.spec = record.spec.model_copy(
                update={"recovery_mode": "rollout_replay"}
            )
            self._write_record(record)
            self._append_event(
                job_id,
                event_type="resumed",
                status="queued",
                attempt=len(record.attempts) + 1,
                message="已请求恢复, 将从最近持久化 rollout 创建新的执行 attempt。",
            )
            self._start(job_id)
            return record

    def interrupt(self, job_id: str) -> ChatJobRecord:
        _validate_job_id(job_id)
        with self._lock:
            record = self._read_record(job_id)
            if record.status not in {"queued", "running"}:
                raise JobError(
                    f"job {job_id} cannot interrupt from status {record.status}"
                )
            if job_id in self._interrupt_requested:
                return record
            self._interrupt_requested.add(job_id)
            record.updated_at = _now_ts()
            self._write_record(record)
            self._append_event(
                job_id,
                event_type="progress",
                status=record.status,
                attempt=len(record.attempts),
                message="正在停止当前任务。",
            )
            running = self._async_tasks.get(job_id)
            if running is not None:
                loop, task = running
                loop.call_soon_threadsafe(task.cancel)
            return record

    def _start(self, job_id: str) -> None:
        existing = self._threads.get(job_id)
        if existing is not None and existing.is_alive():
            raise JobError(f"job {job_id} is already running")
        thread = threading.Thread(
            target=self._run_job,
            args=(job_id,),
            daemon=True,
            name=f"paper-copilot-{job_id}",
        )
        self._threads[job_id] = thread
        thread.start()

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            record = self._read_record(job_id)
            attempt_number = len(record.attempts) + 1
            source_attempt = record.attempts[-1] if record.attempts else None
            session_id = f"paper-copilot-{job_id}-attempt-{attempt_number}"
            now = _now_ts()
            record.status = "running"
            record.updated_at = now
            record.error = None
            record.attempts.append(
                ChatJobAttempt(
                    number=attempt_number,
                    status="running",
                    session_id=session_id,
                    session_path=str(session_file(session_id, self._root)),
                    started_at=now,
                    resumed_from_attempt=(
                        source_attempt.number if source_attempt is not None else None
                    ),
                )
            )
            self._write_record(record)
            self._append_event(
                job_id,
                event_type="started",
                status="running",
                attempt=attempt_number,
                message="本地 Agent 已开始执行。",
            )
            conversation_context, previous_compaction_summary = (
                self._build_conversation_context(record)
            )

        rollout_started_at = time.perf_counter()
        recorder: RolloutRecorder | None = None
        try:
            recorder = RolloutRecorder.create(
                self._job_dir(job_id) / "attempts" / str(attempt_number),
                job_id=job_id,
                attempt=attempt_number,
                session_id=session_id,
                turn_id=f"turn:{job_id}:{attempt_number}",
            )
            recorder.record(
                entity_type="rollout",
                entity_id=recorder.rollout_entity_id,
                event_type="rollout.started",
                status="running",
                attributes={
                    "resumed_from_attempt": (
                        source_attempt.number if source_attempt is not None else None
                    ),
                    "rollout_timeout_seconds": record.spec.rollout_timeout_seconds,
                },
                payloads={"request": {"text": record.spec.request}},
            )
            resume_history: list[dict[str, Any]] | None = None
            resume_runtime_state: dict[str, Any] | None = None
            recovery_source_session: str | None = None
            if (
                source_attempt is not None
                and Path(source_attempt.session_path).is_file()
            ):
                source_store = SessionStore.load(
                    source_attempt.session_id,
                    root=self._root,
                )
                recovered = reconstruct_rollout(
                    source_store.read_all(),
                    fallback_history=[
                        {"role": "user", "content": record.spec.request}
                    ],
                )
                resume_history = recovered.history
                resume_runtime_state = recovered.runtime_state
                recovery_source_session = source_attempt.session_path
                if recovered.compaction_summary is not None:
                    previous_compaction_summary = CompactionSummary.model_validate(
                        recovered.compaction_summary
                    )

            tool_names: dict[str, str] = {}

            def record_event(event: Event) -> None:
                if isinstance(event, ToolUse):
                    tool_names[event.id] = event.name
                    message = f"正在调用工具: {event.name}"
                elif isinstance(event, ToolResult):
                    name = tool_names.get(event.id, "unknown")
                    outcome = "失败" if event.is_error else "完成"
                    message = f"工具 {name} {outcome}。"
                elif isinstance(event, AssistantMessage):
                    message = "Agent 已生成阶段性内容。"
                elif isinstance(event, Terminated):
                    message = f"Agent 循环结束: {event.reason}。"
                else:
                    return
                self._record_progress(job_id, attempt_number, message)

            async def execute_request() -> ChatRunResult:
                with recorder.activate():
                    return await handle_chat_request(
                        record.spec.request,
                        pdf_dir=(
                            Path(record.spec.pdf_dir)
                            if record.spec.pdf_dir is not None
                            else None
                        ),
                        max_turns=record.spec.max_turns,
                        budget_cny=record.spec.budget_cny,
                        max_papers=record.spec.max_papers,
                        root=self._root,
                        record_quality=record.spec.record_quality,
                        update_report=record.spec.update_report,
                        session_id=session_id,
                        event_callback=record_event,
                        conversation_context=conversation_context,
                        previous_compaction_summary=previous_compaction_summary,
                        resume_history=resume_history,
                        resume_runtime_state=resume_runtime_state,
                        recovery_source_session=recovery_source_session,
                    )

            async def run_request() -> ChatRunResult:
                task = asyncio.create_task(
                    execute_request(),
                    name=f"paper-copilot-agent-{job_id}-{attempt_number}",
                )
                with self._lock:
                    self._async_tasks[job_id] = (
                        asyncio.get_running_loop(),
                        task,
                    )
                    interrupt_requested = job_id in self._interrupt_requested
                if interrupt_requested:
                    task.cancel()
                timeout_seconds = record.spec.rollout_timeout_seconds
                if timeout_seconds is None:
                    return await task
                done, _pending = await asyncio.wait((task,), timeout=timeout_seconds)
                if task in done:
                    return task.result()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise RolloutTimeoutError(
                    f"rollout attempt timed out after {timeout_seconds:g} seconds"
                )

            result = asyncio.run(run_request())
        except asyncio.CancelledError:
            if recorder is not None:
                recorder.record(
                    entity_type="rollout",
                    entity_id=recorder.rollout_entity_id,
                    event_type="rollout.cancelled",
                    status="cancelled",
                    duration_ms=int((time.perf_counter() - rollout_started_at) * 1000),
                )
            self._finish_interrupted(
                job_id,
                attempt_number,
                "任务已由用户中断。",
            )
            return
        except Exception as exc:
            if self._is_interrupt_requested(job_id):
                if recorder is not None:
                    recorder.record(
                        entity_type="rollout",
                        entity_id=recorder.rollout_entity_id,
                        event_type="rollout.cancelled",
                        status="cancelled",
                        duration_ms=int((time.perf_counter() - rollout_started_at) * 1000),
                        error_type=exc.__class__.__name__,
                        error_message=str(exc),
                    )
                self._finish_interrupted(
                    job_id,
                    attempt_number,
                    "任务已由用户中断。",
                )
                return
            if recorder is not None:
                recorder.record(
                    entity_type="rollout",
                    entity_id=recorder.rollout_entity_id,
                    event_type="rollout.failed",
                    status="failed",
                    duration_ms=int((time.perf_counter() - rollout_started_at) * 1000),
                    error_type=exc.__class__.__name__,
                    error_message=str(exc),
                )
            self._finish_failed(job_id, attempt_number, str(exc))
            return
        if result.termination_reason == "cancelled":
            recorder.record(
                entity_type="rollout",
                entity_id=recorder.rollout_entity_id,
                event_type="rollout.cancelled",
                status="cancelled",
                duration_ms=int((time.perf_counter() - rollout_started_at) * 1000),
            )
            self._finish_interrupted(
                job_id,
                attempt_number,
                "任务已由用户中断。",
            )
            return
        recorder.record(
            entity_type="rollout",
            entity_id=recorder.rollout_entity_id,
            event_type="rollout.completed",
            status="completed",
            duration_ms=int((time.perf_counter() - rollout_started_at) * 1000),
            attributes={
                "termination_reason": result.termination_reason,
                "cost_cny": result.cost_cny,
                "events_count": result.events_count,
            },
        )
        self._finish_completed(job_id, attempt_number, result)

    def _finish_completed(
        self,
        job_id: str,
        attempt_number: int,
        result: ChatRunResult,
    ) -> None:
        with self._lock:
            if job_id in self._interrupt_requested:
                self._finish_interrupted(
                    job_id,
                    attempt_number,
                    "任务已由用户中断。",
                )
                return
            record = self._read_record(job_id)
            attempt = _attempt(record, attempt_number)
            now = _now_ts()
            attempt.status = "completed"
            attempt.finished_at = now
            record.status = "completed"
            record.updated_at = now
            record.result = ChatJobResult.from_run(result)
            record.error = None
            self._write_record(record)
            self._append_event(
                job_id,
                event_type="completed",
                status="completed",
                attempt=attempt_number,
                message="任务已完成。",
            )
            self._clear_running(job_id)

    def _finish_failed(self, job_id: str, attempt_number: int, error: str) -> None:
        with self._lock:
            record = self._read_record(job_id)
            attempt = _attempt(record, attempt_number)
            now = _now_ts()
            attempt.status = "failed"
            attempt.finished_at = now
            attempt.error = error
            if Path(attempt.session_path).is_file():
                SessionStore.load(attempt.session_id, root=self._root).append_turn_aborted(
                    error
                )
            record.status = "failed"
            record.updated_at = now
            record.error = error
            self._write_record(record)
            self._append_event(
                job_id,
                event_type="failed",
                status="failed",
                attempt=attempt_number,
                message=error,
            )
            self._clear_running(job_id)

    def _finish_interrupted(
        self,
        job_id: str,
        attempt_number: int,
        reason: str,
    ) -> None:
        with self._lock:
            record = self._read_record(job_id)
            attempt = _attempt(record, attempt_number)
            now = _now_ts()
            attempt.status = "interrupted"
            attempt.finished_at = now
            attempt.error = reason
            if Path(attempt.session_path).is_file():
                SessionStore.load(
                    attempt.session_id,
                    root=self._root,
                ).append_turn_aborted(reason)
            record.status = "interrupted"
            record.updated_at = now
            record.error = reason
            self._write_record(record)
            self._append_event(
                job_id,
                event_type="interrupted",
                status="interrupted",
                attempt=attempt_number,
                message=reason,
            )
            self._clear_running(job_id)

    def _is_interrupt_requested(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._interrupt_requested

    def _clear_running(self, job_id: str) -> None:
        self._threads.pop(job_id, None)
        self._async_tasks.pop(job_id, None)
        self._interrupt_requested.discard(job_id)

    def _record_progress(self, job_id: str, attempt_number: int, message: str) -> None:
        with self._lock:
            record = self._read_record(job_id)
            if record.status != "running":
                return
            record.updated_at = _now_ts()
            self._write_record(record)
            self._append_event(
                job_id,
                event_type="progress",
                status="running",
                attempt=attempt_number,
                message=message,
            )

    def _recover_orphaned_jobs(self) -> None:
        with self._lock:
            for path in self._job_files():
                record = self._read_record(path.parent.name)
                if record.status not in {"queued", "running"}:
                    continue
                now = _now_ts()
                if record.attempts and record.attempts[-1].status == "running":
                    record.attempts[-1].status = "interrupted"
                    record.attempts[-1].finished_at = now
                    record.attempts[-1].error = "本地服务在任务完成前停止。"
                    attempt = record.attempts[-1]
                    if Path(attempt.session_path).is_file():
                        SessionStore.load(
                            attempt.session_id,
                            root=self._root,
                        ).append_turn_aborted("本地服务在任务完成前停止。")
                record.status = "interrupted"
                record.updated_at = now
                record.error = "本地服务在任务完成前停止, 可从持久化 rollout 恢复。"
                self._write_record(record)
                self._append_event(
                    record.id,
                    event_type="interrupted",
                    status="interrupted",
                    attempt=len(record.attempts),
                    message=record.error,
                )

    def _job_files(self) -> list[Path]:
        return list(self._jobs_dir.glob("*/job.json"))

    def _build_conversation_context(
        self,
        current: ChatJobRecord,
    ) -> tuple[str | None, CompactionSummary | None]:
        conversation_id = current.spec.conversation_id
        if conversation_id is None:
            return None, None
        previous = [
            self._read_record(path.parent.name)
            for path in self._job_files()
            if path.parent.name != current.id
        ]
        completed = [
            record
            for record in previous
            if record.spec.conversation_id == conversation_id
            and record.status == "completed"
            and record.result is not None
            and record.created_at <= current.created_at
        ]
        completed.sort(key=lambda record: record.created_at)

        checkpoint_index: int | None = None
        checkpoint_summary: CompactionSummary | None = None
        for index in range(len(completed) - 1, -1, -1):
            result = completed[index].result
            assert result is not None
            if result.conversation_compaction is not None:
                checkpoint_index = index
                checkpoint_summary = result.conversation_compaction
                break

        active_records = (
            completed if checkpoint_index is None else completed[checkpoint_index:]
        )
        active_turns: list[dict[str, str]] = []
        for record in active_records:
            assert record.result is not None
            active_turns.append(
                {
                    "job_id": record.id,
                    "user": record.spec.request,
                    "assistant": record.result.report_markdown,
                }
            )
        if not active_turns:
            return None, checkpoint_summary
        payload = {
            "conversation_id": conversation_id,
            "compaction_summary": (
                checkpoint_summary.model_dump(mode="json")
                if checkpoint_summary is not None
                else None
            ),
            "completed_turns": active_turns,
        }
        context = (
            "<conversation_context>\n"
            f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n"
            "</conversation_context>"
        )
        return context, checkpoint_summary

    def _job_dir(self, job_id: str) -> Path:
        _validate_job_id(job_id)
        return self._jobs_dir / job_id

    def _read_record(self, job_id: str) -> ChatJobRecord:
        path = self._job_dir(job_id) / "job.json"
        if not path.exists():
            raise JobError(f"job not found: {job_id}")
        return ChatJobRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def _write_record(self, record: ChatJobRecord) -> None:
        job_dir = self._job_dir(record.id)
        job_dir.mkdir(parents=True, exist_ok=True)
        path = job_dir / "job.json"
        temp_path = job_dir / "job.json.tmp"
        with temp_path.open("w", encoding="utf-8") as stream:
            stream.write(record.model_dump_json(indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)

    def _read_events(self, job_id: str) -> list[ChatJobEvent]:
        path = self._job_dir(job_id) / "events.jsonl"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        if lines and not lines[-1].endswith("\n"):
            lines.pop()
        events: list[ChatJobEvent] = []
        for line in lines:
            if line.strip():
                events.append(ChatJobEvent.model_validate_json(line))
        return events

    def _append_event(
        self,
        job_id: str,
        *,
        event_type: Literal[
            "created",
            "started",
            "progress",
            "completed",
            "interrupted",
            "failed",
            "resumed",
        ],
        status: JobStatus,
        attempt: int,
        message: str,
    ) -> None:
        with self._events_changed:
            path = self._job_dir(job_id) / "events.jsonl"
            self._truncate_torn_event_tail(path)
            seq = len(self._read_events(job_id)) + 1
            event = ChatJobEvent(
                seq=seq,
                ts=_now_ts(),
                type=event_type,
                status=status,
                attempt=attempt,
                message=message,
            )
            with path.open("a", encoding="utf-8") as stream:
                stream.write(event.model_dump_json() + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._events_changed.notify_all()

    def _truncate_torn_event_tail(self, path: Path) -> None:
        if not path.exists():
            return
        raw = path.read_bytes()
        if not raw or raw.endswith(b"\n"):
            return
        last_newline = raw.rfind(b"\n")
        complete = raw[: last_newline + 1] if last_newline >= 0 else b""
        with path.open("wb") as stream:
            stream.write(complete)
            stream.flush()
            os.fsync(stream.fileno())


def job_registry(root: Path | None = None) -> ChatJobRegistry:
    resolved_root = (root if root is not None else default_root()).expanduser().resolve()
    with _REGISTRIES_LOCK:
        registry = _REGISTRIES.get(resolved_root)
        if registry is None:
            registry = ChatJobRegistry(resolved_root)
            _REGISTRIES[resolved_root] = registry
        return registry


def _attempt(record: ChatJobRecord, number: int) -> ChatJobAttempt:
    for attempt in record.attempts:
        if attempt.number == number:
            return attempt
    raise JobError(f"attempt {number} not found for job {record.id}")


def _new_job_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    return f"job-{stamp}-{uuid4().hex[:10]}"


def _new_conversation_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    return f"conversation-{stamp}-{uuid4().hex[:10]}"


def _validate_job_id(job_id: str) -> None:
    if _JOB_ID_RE.fullmatch(job_id) is None:
        raise JobError(f"invalid job id: {job_id}")


def _now_ts() -> str:
    return datetime.now(UTC).isoformat()
