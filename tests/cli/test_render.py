from paper_copilot.cli.render import to_markdown
from paper_copilot.schemas.paper import (
    Contribution,
    CrossPaperLink,
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
            title="Test Title",
            authors=["Alice", "Bob"],
            arxiv_id=arxiv_id,
            year=2025,
            venue=venue,
        ),
        contributions=[
            Contribution(
                claim="a brilliant insight",
                type="novel_method",
                evidence_type="explicit_claim",
            ),
        ],
        methods=[
            Method(
                name="FooNet",
                description="it foos",
                key_formula=key_formula,
                novelty_vs_prior="introduces sigma",
                is_novel_to_this_paper=True,
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
    assert "明说" in md
    # English section titles should NOT appear
    assert "## Contributions" not in md
    assert "## Methods" not in md


def _make_paper_with_links(links: list[CrossPaperLink]) -> Paper:
    paper = _make_paper()
    return paper.model_copy(update={"cross_paper_links": links})


def test_related_section_hidden_when_empty() -> None:
    md = to_markdown(_make_paper())
    assert "Related Papers" not in md
    assert "相关论文" not in md


def test_related_section_renders_title_id_label_and_explanation() -> None:
    link = CrossPaperLink(
        related_paper_id="a639448e61be",
        related_title="Attention Is All You Need",
        relation_type="builds_on",
        explanation="extends scaled dot-product attention with a sparse top-k variant",
    )
    md = to_markdown(_make_paper_with_links([link]))
    assert "## Related Papers" in md
    assert "Attention Is All You Need" in md
    assert "`a639448e61be`" in md
    assert "[builds on]" in md
    assert "sparse top-k variant" in md


def test_related_section_zh_labels() -> None:
    link = CrossPaperLink(
        related_paper_id="a639448e61be",
        related_title="Attention Is All You Need",
        relation_type="compares_against",
        explanation="pits FooNet against the Transformer baseline on WMT14",
    )
    md = to_markdown(_make_paper_with_links([link]), language="zh")
    assert "## 相关论文" in md
    assert "[对比基线]" in md
    assert "[compares_against]" not in md  # raw enum should not leak


def test_related_section_renders_each_relation_type() -> None:
    by_type = {
        "builds_on": "builds on",
        "compares_against": "compares against",
        "shares_method": "shares method with",
        "contrasts_with": "contrasts with",
        "applies_in_different_domain": "applies in a different domain from",
    }
    links = [
        CrossPaperLink(
            related_paper_id=f"pid_{rtype}",
            related_title=f"Paper for {rtype}",
            relation_type=rtype,  # type: ignore[arg-type]
            explanation=f"exp for {rtype}",
        )
        for rtype in by_type
    ]
    md = to_markdown(_make_paper_with_links(links))
    for label in by_type.values():
        assert f"[{label}]" in md
