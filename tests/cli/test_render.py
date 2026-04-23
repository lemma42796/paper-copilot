from paper_copilot.cli.render import to_markdown
from paper_copilot.schemas.paper import (
    Contribution,
    Experiment,
    Limitation,
    Method,
    Paper,
    PaperMeta,
)


def _make_paper(
    *,
    key_formula: str | None = r"y = \sigma(Wx + b)",
    pages: list[int] | None = None,
    venue: str | None = "NeurIPS 2025",
    arxiv_id: str | None = "2505.12345",
) -> Paper:
    return Paper(
        meta=PaperMeta(
            id="test_id",
            title="Test Title",
            authors=["Alice", "Bob"],
            arxiv_id=arxiv_id,
            year=2025,
            venue=venue,
        ),
        contributions=[
            Contribution(claim="a brilliant insight", type="novel_method", confidence=0.9),
        ],
        methods=[
            Method(
                name="FooNet",
                description="it foos",
                key_formula=key_formula,
                novelty_vs_prior="introduces sigma",
            ),
        ],
        experiments=[
            Experiment(
                dataset="MNIST",
                metric="accuracy",
                value=99.5,
                unit="%",
                raw="99.5% on MNIST test",
                comparison_baseline="LeNet",
                pages=pages or [],
            ),
        ],
        limitations=[
            Limitation(type="scope", description="only MNIST evaluated"),
        ],
    )


def test_to_markdown_contains_all_sections_when_populated() -> None:
    md = to_markdown(_make_paper(pages=[7, 8]))
    assert "# Test Title" in md
    assert "Alice, Bob" in md
    assert "NeurIPS 2025" in md
    assert "2505.12345" in md
    assert "## Contributions" in md
    assert "a brilliant insight" in md
    assert "## Methods" in md
    assert "FooNet" in md
    assert r"y = \sigma(Wx + b)" in md
    assert "## Experiments" in md
    assert "99.5" in md
    assert "LeNet" in md
    assert "p. 7, 8" in md
    assert "## Limitations" in md
    assert "only MNIST" in md


def test_to_markdown_elides_optional_fields() -> None:
    md = to_markdown(_make_paper(key_formula=None, venue=None, arxiv_id=None))
    assert "Venue" not in md
    assert "arXiv" not in md
    assert "$$" not in md
    assert "(p." not in md


def test_to_markdown_zh_headers() -> None:
    md = to_markdown(_make_paper(pages=[7, 8]), language="zh")
    assert "## 贡献" in md
    assert "## 方法" in md
    assert "## 实验" in md
    assert "## 局限" in md
    assert "**作者:**" in md
    assert "**年份:**" in md
    assert "**会议:**" in md
    assert "*新意:*" in md
    assert "置信度" in md
    # English section titles should NOT appear
    assert "## Contributions" not in md
    assert "## Methods" not in md
