from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from paper_copilot.shared.errors import SessionError
from paper_copilot.shared.logging import get_logger

from .paths import paper_dir, session_file
from .types import (
    FinalOutput,
    Message,
    SchemaValidation,
    SessionEntry,
    SessionHeader,
    ToolResult,
    ToolUse,
)

_log = get_logger(__name__)
_ADAPTER: TypeAdapter[SessionEntry] = TypeAdapter(SessionEntry)


def _new_id() -> str:
    return uuid4().hex[:16]


def _now_ts() -> str:
    return datetime.now(UTC).isoformat()


class SessionStore:
    def __init__(self, path: Path, last_id: str) -> None:
        self._path = path
        self._last_id = last_id

    @property
    def path(self) -> Path:
        return self._path

    @classmethod
    def create(
        cls,
        paper_id: str,
        *,
        model: str,
        agent: str,
        root: Path | None = None,
    ) -> SessionStore:
        pdir = paper_dir(paper_id, root)
        if pdir.exists():
            raise SessionError(f"session dir already exists: {pdir}")
        pdir.mkdir(parents=True)
        path = session_file(paper_id, root)
        header = SessionHeader(
            id=_new_id(),
            ts=_now_ts(),
            paper_id=paper_id,
            cwd=os.getcwd(),
            model=model,
            agent=agent,
        )
        store = cls(path, header.id)
        store._write(header)
        return store

    @classmethod
    def load(cls, paper_id: str, *, root: Path | None = None) -> SessionStore:
        path = session_file(paper_id, root)
        if not path.exists():
            raise SessionError(f"session file not found: {path}")
        store = cls(path, last_id="")
        entries = store.read_all()
        if not entries:
            raise SessionError(f"session file is empty: {path}")
        store._last_id = entries[-1].id
        return store

    def _write(self, entry: SessionEntry) -> None:
        line = json.dumps(entry.model_dump(mode="json"), ensure_ascii=False)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        self._last_id = entry.id

    def append_message(self, role: str, text: str) -> str:
        entry = Message(
            id=_new_id(),
            ts=_now_ts(),
            parent_id=self._last_id,
            role=role,  # type: ignore[arg-type]
            text=text,
        )
        self._write(entry)
        return entry.id

    def append_tool_use(
        self, tool_use_id: str, name: str, input_: dict[str, Any]
    ) -> str:
        entry = ToolUse(
            id=_new_id(),
            ts=_now_ts(),
            parent_id=self._last_id,
            tool_use_id=tool_use_id,
            name=name,
            input=input_,
        )
        self._write(entry)
        return entry.id

    def append_tool_result(
        self, tool_use_id: str, output: str, is_error: bool
    ) -> str:
        entry = ToolResult(
            id=_new_id(),
            ts=_now_ts(),
            parent_id=self._last_id,
            tool_use_id=tool_use_id,
            output=output,
            is_error=is_error,
        )
        self._write(entry)
        return entry.id

    def append_schema_validation(
        self, success: bool, error: str | None = None, retry_count: int = 0
    ) -> str:
        entry = SchemaValidation(
            id=_new_id(),
            ts=_now_ts(),
            parent_id=self._last_id,
            success=success,
            error=error,
            retry_count=retry_count,
        )
        self._write(entry)
        return entry.id

    def append_final_output(self, payload: dict[str, Any]) -> str:
        entry = FinalOutput(
            id=_new_id(),
            ts=_now_ts(),
            parent_id=self._last_id,
            payload=payload,
        )
        self._write(entry)
        return entry.id

    def read_all(self) -> list[SessionEntry]:
        text = self._path.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        if lines and not lines[-1].endswith("\n"):
            _log.warning("session.torn_tail_line", path=str(self._path))
            lines.pop()
        entries: list[SessionEntry] = []
        for raw in lines:
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as e:
                raise SessionError(f"corrupt json in {self._path}: {e}") from e
            try:
                entries.append(_ADAPTER.validate_python(obj))
            except ValidationError as e:
                raise SessionError(f"invalid entry in {self._path}: {e}") from e
        return entries

    def tail(self, n: int) -> list[SessionEntry]:
        return self.read_all()[-n:]

    def last_final_output(self) -> FinalOutput | None:
        for entry in reversed(self.read_all()):
            if isinstance(entry, FinalOutput):
                return entry
        return None
