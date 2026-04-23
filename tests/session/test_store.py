from pathlib import Path

import pytest

from paper_copilot.session import (
    FinalOutput,
    Message,
    SchemaValidation,
    SessionHeader,
    SessionStore,
    ToolResult,
    ToolUse,
)
from paper_copilot.session import store as store_mod
from paper_copilot.shared.errors import SessionError


def test_create_writes_header(tmp_path: Path) -> None:
    s = SessionStore.create("abc", model="m", agent="skim", root=tmp_path)
    entries = s.read_all()
    assert len(entries) == 1
    h = entries[0]
    assert isinstance(h, SessionHeader)
    assert h.paper_id == "abc"
    assert h.model == "m"
    assert h.agent == "skim"


def test_create_existing_dir_raises(tmp_path: Path) -> None:
    SessionStore.create("abc", model="m", agent="skim", root=tmp_path)
    with pytest.raises(SessionError):
        SessionStore.create("abc", model="m", agent="skim", root=tmp_path)


def test_load_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(SessionError):
        SessionStore.load("nope", root=tmp_path)


def test_parent_id_chain(tmp_path: Path) -> None:
    s = SessionStore.create("abc", model="m", agent="skim", root=tmp_path)
    s.append_message("user", "hi")
    s.append_tool_use("tu1", "read", {"x": 1})
    entries = s.read_all()
    assert len(entries) == 3
    assert isinstance(entries[1], Message)
    assert isinstance(entries[2], ToolUse)
    assert entries[1].parent_id == entries[0].id
    assert entries[2].parent_id == entries[1].id


def test_all_entry_types_roundtrip(tmp_path: Path) -> None:
    s = SessionStore.create("abc", model="m", agent="skim", root=tmp_path)
    s.append_message("user", "hello")
    s.append_tool_use("tu1", "read", {"path": "p"})
    s.append_tool_result("tu1", "ok", is_error=False)
    s.append_schema_validation(success=True)
    s.append_final_output({"k": "v"})
    entries = s.read_all()
    assert [type(e) for e in entries] == [
        SessionHeader,
        Message,
        ToolUse,
        ToolResult,
        SchemaValidation,
        FinalOutput,
    ]


def test_crash_recovery_50_messages(tmp_path: Path) -> None:
    s = SessionStore.create("abc", model="m", agent="skim", root=tmp_path)
    for i in range(50):
        s.append_message("user", f"msg {i}")
    del s
    s2 = SessionStore.load("abc", root=tmp_path)
    entries = s2.read_all()
    assert len(entries) == 51


def test_torn_tail_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = SessionStore.create("abc", model="m", agent="skim", root=tmp_path)
    s.append_message("user", "a")
    s.append_message("assistant", "b")
    s.append_message("user", "c")
    with s.path.open("a", encoding="utf-8") as f:
        f.write('{"incomplete":')

    warnings: list[tuple[str, dict[str, object]]] = []

    class _Spy:
        def warning(self, event: str, **kw: object) -> None:
            warnings.append((event, kw))

    monkeypatch.setattr(store_mod, "_log", _Spy())

    s2 = SessionStore.load("abc", root=tmp_path)
    entries = s2.read_all()
    assert len(entries) == 4
    assert any(w[0] == "session.torn_tail_line" for w in warnings)
