from pathlib import Path

from paper_copilot.knowledge.graph_store import append_links, graph_path
from paper_copilot.schemas import CrossPaperLink


def _link(related: str = "abc123def456", rtype: str = "builds_on") -> CrossPaperLink:
    return CrossPaperLink(
        related_paper_id=related,
        related_title="Attention Is All You Need",
        relation_type=rtype,  # type: ignore[arg-type]
        explanation="extends scaled dot-product attention with a sparse top-k variant",
    )


def _read_lines(path: Path) -> list[dict]:
    import json

    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_append_creates_graph_dir_and_writes_one_line_per_link(tmp_path: Path) -> None:
    links = [_link("a" * 12), _link("b" * 12, rtype="compares_against")]
    append_links("new123456789", links, root=tmp_path, clock=lambda: "2026-04-24T10:00:00+00:00")

    path = graph_path(tmp_path)
    assert path.exists()
    rows = _read_lines(path)
    assert len(rows) == 2
    assert rows[0]["paper_id"] == "new123456789"
    assert rows[0]["related_paper_id"] == "a" * 12
    assert rows[0]["relation_type"] == "builds_on"
    assert rows[0]["indexed_at"] == "2026-04-24T10:00:00+00:00"
    assert rows[1]["relation_type"] == "compares_against"


def test_append_is_additive_across_calls(tmp_path: Path) -> None:
    append_links("paper_a_1234", [_link("rel_aaa_0001")], root=tmp_path)
    append_links("paper_b_5678", [_link("rel_bbb_0002")], root=tmp_path)

    rows = _read_lines(graph_path(tmp_path))
    assert [r["paper_id"] for r in rows] == ["paper_a_1234", "paper_b_5678"]


def test_empty_links_is_noop(tmp_path: Path) -> None:
    append_links("paper_x_9999", [], root=tmp_path)
    assert not graph_path(tmp_path).exists()


def test_unicode_explanation_preserved(tmp_path: Path) -> None:
    link = CrossPaperLink(
        related_paper_id="zh00000000zh",
        related_title="注意力就是你所需的一切",
        relation_type="builds_on",
        explanation="扩展了 scaled dot-product attention 的稀疏变体",
    )
    append_links("src000000001", [link], root=tmp_path)

    rows = _read_lines(graph_path(tmp_path))
    assert rows[0]["related_title"] == "注意力就是你所需的一切"
    assert "稀疏" in rows[0]["explanation"]


def test_graph_path_respects_root(tmp_path: Path) -> None:
    assert graph_path(tmp_path) == tmp_path / "graph" / "cross-paper-links.jsonl"
