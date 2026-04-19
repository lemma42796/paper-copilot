import json
from pathlib import Path
from typing import Any

import pytest

from paper_copilot.shared.logging import configure_logging, get_logger


def _read_jsonl(log_dir: Path) -> list[dict[str, Any]]:
    files = list(log_dir.glob("*.jsonl"))
    assert len(files) == 1, f"expected exactly one jsonl file, got {files}"
    return [json.loads(line) for line in files[0].read_text().splitlines() if line]


def test_configure_is_idempotent(tmp_path: Path) -> None:
    configure_logging(log_dir=tmp_path, console=False)
    configure_logging(log_dir=tmp_path, console=False)
    get_logger("t").info("once")
    assert len(_read_jsonl(tmp_path)) == 1


def test_jsonl_file_written(tmp_path: Path) -> None:
    configure_logging(log_dir=tmp_path, console=False)
    get_logger("t").info("event.a", paper_id="abc", tokens=123)
    entries = _read_jsonl(tmp_path)
    assert len(entries) == 1
    assert entries[0]["event"] == "event.a"
    assert entries[0]["paper_id"] == "abc"
    assert entries[0]["tokens"] == 123


def test_jsonl_contains_required_fields(tmp_path: Path) -> None:
    configure_logging(log_dir=tmp_path, console=False)
    get_logger("t").info("ping")
    entry = _read_jsonl(tmp_path)[0]
    assert entry["event"] == "ping"
    assert entry["level"] == "info"
    assert entry["logger"] == "t"
    assert "timestamp" in entry


def test_console_and_file_both_emit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(log_dir=tmp_path, console=True)
    get_logger("t").info("both.ways", key="v")
    captured = capsys.readouterr()
    assert "both.ways" in captured.err
    entries = _read_jsonl(tmp_path)
    assert len(entries) == 1
    assert entries[0]["event"] == "both.ways"


def test_env_var_overrides_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_COPILOT_LOG_DIR", str(tmp_path))
    configure_logging(console=False)  # no log_dir arg -> env wins
    get_logger("t").info("via.env")
    assert len(_read_jsonl(tmp_path)) == 1


def test_env_var_overrides_level(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_COPILOT_LOG_LEVEL", "ERROR")
    configure_logging(log_dir=tmp_path, level="INFO", console=False)
    log = get_logger("t")
    log.info("should.drop")
    log.error("should.keep")
    entries = _read_jsonl(tmp_path)
    assert len(entries) == 1
    assert entries[0]["event"] == "should.keep"
