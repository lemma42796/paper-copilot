from pathlib import Path

from paper_copilot.session.paths import compute_paper_id, session_file


def test_compute_paper_id_deterministic(tmp_path: Path) -> None:
    p1 = tmp_path / "a.pdf"
    p2 = tmp_path / "b.pdf"
    p1.write_bytes(b"hello world" * 100)
    p2.write_bytes(b"hello world" * 100)
    assert compute_paper_id(p1) == compute_paper_id(p2)


def test_compute_paper_id_differs(tmp_path: Path) -> None:
    p1 = tmp_path / "a.pdf"
    p2 = tmp_path / "b.pdf"
    p1.write_bytes(b"content one")
    p2.write_bytes(b"content two")
    assert compute_paper_id(p1) != compute_paper_id(p2)


def test_session_file_path(tmp_path: Path) -> None:
    assert session_file("abc", root=tmp_path) == tmp_path / "papers" / "abc" / "session.jsonl"
