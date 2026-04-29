from __future__ import annotations

import json
from pathlib import Path

import pytest

from paper_copilot.eval.goldens import (
    ALLOWED_FIELDS,
    GoldenRecord,
    file_path,
    mark_from_session,
    read,
    write,
)
from paper_copilot.session import SessionStore
from paper_copilot.shared.errors import EvalError


def _record(**overrides: object) -> GoldenRecord:
    base: dict[str, object] = {
        "paper_id": "abc123",
        "field": "methods",
        "marked_at": "2026-04-25T00:00:00+00:00",
        "value": [{"name": "Transformer"}],
    }
    base.update(overrides)
    return GoldenRecord(**base)  # type: ignore[arg-type]


def test_allowed_fields_excludes_limitations_and_links() -> None:
    assert "limitations" not in ALLOWED_FIELDS
    assert "cross_paper_links" not in ALLOWED_FIELDS
    assert set(ALLOWED_FIELDS) == {"meta", "contributions", "methods", "experiments"}


def test_file_path_layout(tmp_path: Path) -> None:
    p = file_path("abc123", "methods", dir_=tmp_path)
    assert p == tmp_path / "abc123_methods.json"


def test_write_then_read_round_trip(tmp_path: Path) -> None:
    record = _record()
    written_path = write(record, dir_=tmp_path)
    assert written_path.exists()

    loaded = read("abc123", "methods", dir_=tmp_path)
    assert loaded == record


def test_write_overwrites_prior_golden(tmp_path: Path) -> None:
    write(_record(value=[{"name": "old"}]), dir_=tmp_path)
    write(_record(value=[{"name": "new"}]), dir_=tmp_path)
    loaded = read("abc123", "methods", dir_=tmp_path)
    assert loaded.value == [{"name": "new"}]


def test_write_rejects_unsupported_field(tmp_path: Path) -> None:
    bad = _record(field="limitations")
    with pytest.raises(EvalError, match="unsupported field"):
        write(bad, dir_=tmp_path)


def test_read_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(EvalError, match="no golden at"):
        read("nonexistent", "methods", dir_=tmp_path)


def test_write_emits_valid_json_with_utf8(tmp_path: Path) -> None:
    record = _record(value=[{"name": "注意力"}])
    path = write(record, dir_=tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["value"] == [{"name": "注意力"}]


# ---------- mark_from_session ----------


def _seed_session_with_final(root: Path, paper_id: str, payload: dict[str, object]) -> Path:
    store = SessionStore.create(paper_id, model="m", agent="MainAgent", root=root)
    store.append_final_output(payload=payload)
    return store.path


def test_mark_from_session_writes_one_file_per_field(tmp_path: Path) -> None:
    home = tmp_path / "home"
    goldens_dir = tmp_path / "goldens"
    payload: dict[str, object] = {
        "meta": {"title": "T", "year": 2017, "authors": ["A"], "arxiv_id": None},
        "contributions": [
            {"claim": "c", "type": "novel_method", "evidence_type": "explicit_claim"}
        ],
        "methods": [],
        "experiments": [],
        "limitations": [],
        "cross_paper_links": [],
    }
    _seed_session_with_final(home, "pid_x", payload)

    records = mark_from_session(
        "pid_x",
        ("meta", "contributions"),
        root=home,
        dir_=goldens_dir,
    )
    assert len(records) == 2
    assert {r.field for r in records} == {"meta", "contributions"}

    for r in records:
        on_disk = read("pid_x", r.field, dir_=goldens_dir)
        assert on_disk.value == payload[r.field]


def test_mark_from_session_rejects_unsupported_field(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _seed_session_with_final(home, "pid_x", {"meta": {}})
    with pytest.raises(EvalError, match="unsupported field"):
        mark_from_session("pid_x", ("limitations",), root=home, dir_=tmp_path / "g")


def test_mark_from_session_no_final_output_raises(tmp_path: Path) -> None:
    home = tmp_path / "home"
    SessionStore.create("pid_y", model="m", agent="MainAgent", root=home)
    # session has only a header, no final_output yet
    with pytest.raises(EvalError, match="no final_output"):
        mark_from_session("pid_y", ("meta",), root=home, dir_=tmp_path / "g")


def test_mark_from_session_field_missing_in_payload_raises(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _seed_session_with_final(home, "pid_z", {"meta": {"title": "T"}})  # no methods key
    with pytest.raises(EvalError, match="not present in session final_output"):
        mark_from_session("pid_z", ("methods",), root=home, dir_=tmp_path / "g")
