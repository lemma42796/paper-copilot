from typing import Any

import pytest
from pydantic import ValidationError

from paper_copilot.agents.related import (
    _MAX_LINKS,
    _build_query_text,
    _build_user_text,
    _RelatedToolInput,
    _validate_links,
)
from paper_copilot.knowledge.embeddings_store import ChunkHit
from paper_copilot.knowledge.hybrid_search import SearchResult
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
    title: str = "Sparse Top-K Attention",
    claims: list[str] | None = None,
    method_names: list[str] | None = None,
) -> Paper:
    return Paper(
        meta=PaperMeta(title=title, authors=["A", "B"], arxiv_id=None, year=2024, venue=None),
        contributions=[
            Contribution(claim=c, type="novel_method", evidence_type="explicit_claim")
            for c in (claims or ["claim one", "claim two"])
        ],
        methods=[
            Method(
                name=n,
                description="d",
                key_formula=None,
                novelty_vs_prior="v",
                is_novel_to_this_paper=True,
            )
            for n in (method_names or ["SparseTopK"])
        ],
        experiments=[
            Experiment(
                dataset="X",
                metric="m",
                value=1.0,
                unit="%",
                raw="r",
                comparison_baseline="b",
            )
        ],
        limitations=[Limitation(type="scope", description="d")],
    )


def _make_candidate(
    paper_id: str,
    *,
    title: str = "Attention Is All You Need",
    year: int = 2017,
    distance: float = 0.25,
    contributions: list[str] | None = None,
    methods: list[str] | None = None,
) -> SearchResult:
    paper_data: dict[str, Any] = {
        "meta": {"title": title, "year": year},
        "contributions": [{"claim": c} for c in (contributions or ["Transformer idea"])],
        "methods": [{"name": m} for m in (methods or ["ScaledDotProductAttention"])],
    }
    return SearchResult(
        paper_id=paper_id,
        title=title,
        year=year,
        best_chunk=ChunkHit(
            chunk_id=1,
            paper_id=paper_id,
            ord=0,
            section="Abstract",
            page_start=1,
            page_end=1,
            text="...",
            distance=distance,
        ),
        paper_data=paper_data,
    )


def _link(related: str, rtype: str = "builds_on") -> CrossPaperLink:
    return CrossPaperLink(
        related_paper_id=related,
        related_title="Attention Is All You Need",
        relation_type=rtype,  # type: ignore[arg-type]
        explanation="extends scaled dot-product attention with a sparse top-k variant",
    )


def test_build_query_text_joins_title_and_top_claims() -> None:
    paper = _make_paper(
        title="Sparse Top-K Attention",
        claims=["first claim", "second claim", "third claim", "fourth claim"],
        method_names=["AlphaMethod", "BetaMethod"],
    )
    text = _build_query_text(paper)
    assert text.startswith("Sparse Top-K Attention")
    assert "first claim" in text
    assert "third claim" in text
    assert "fourth claim" not in text  # cap at top 3
    assert "AlphaMethod" in text
    assert "BetaMethod" in text


def test_build_user_text_includes_each_candidate_with_id_and_distance() -> None:
    paper = _make_paper()
    cands = [
        _make_candidate("abc123", distance=0.18),
        _make_candidate("def456", title="ViT", distance=0.31),
    ]
    text = _build_user_text(paper, cands)
    assert "related_paper_id=abc123" in text
    assert "distance=0.180" in text
    assert "related_paper_id=def456" in text
    assert "distance=0.310" in text
    assert "[1]" in text and "[2]" in text
    # new paper block present
    assert "Sparse Top-K Attention" in text


def test_build_user_text_survives_sparse_candidate_data() -> None:
    paper = _make_paper()
    cand = SearchResult(
        paper_id="sparse000001",
        title="",
        year=0,
        best_chunk=ChunkHit(
            chunk_id=0,
            paper_id="sparse000001",
            ord=0,
            section="",
            page_start=1,
            page_end=1,
            text="",
            distance=0.5,
        ),
        paper_data={"meta": {}},  # no contributions / methods / year
    )
    text = _build_user_text(paper, [cand])
    assert "related_paper_id=sparse000001" in text


def test_tool_input_caps_at_three_links() -> None:
    data = {"links": [_link(f"id{i:010d}").model_dump() for i in range(_MAX_LINKS + 1)]}
    with pytest.raises(ValidationError):
        _RelatedToolInput.model_validate(data)


def test_tool_input_accepts_empty_list() -> None:
    parsed = _RelatedToolInput.model_validate({"links": []})
    assert parsed.links == []


def test_tool_input_extra_forbidden() -> None:
    data = {"links": [], "debug": "nope"}
    with pytest.raises(ValidationError) as exc:
        _RelatedToolInput.model_validate(data)
    assert any(e["type"] == "extra_forbidden" for e in exc.value.errors())


def test_filter_drops_self_reference() -> None:
    cands = [_make_candidate("abc123"), _make_candidate("def456")]
    links = [_link("new_self_id"), _link("abc123")]
    kept = _validate_links(links, cands, new_paper_id="new_self_id", new_paper_year=2024)
    assert [link.related_paper_id for link in kept] == ["abc123"]


def test_filter_drops_unknown_candidate() -> None:
    cands = [_make_candidate("abc123")]
    links = [_link("unknown999"), _link("abc123")]
    kept = _validate_links(links, cands, new_paper_id="new000000001", new_paper_year=2024)
    assert [link.related_paper_id for link in kept] == ["abc123"]


def test_filter_preserves_valid_order() -> None:
    cands = [_make_candidate("a" * 12), _make_candidate("b" * 12)]
    links = [_link("b" * 12, "compares_against"), _link("a" * 12, "builds_on")]
    kept = _validate_links(links, cands, new_paper_id="new000000001", new_paper_year=2024)
    assert [link.related_paper_id for link in kept] == ["b" * 12, "a" * 12]
    assert [link.relation_type for link in kept] == ["compares_against", "builds_on"]


def test_filter_drops_future_candidate_on_directional_relation() -> None:
    # New paper from 2015 cannot "build_on" a 2017 candidate.
    cands = [_make_candidate("future999999", year=2017)]
    links = [_link("future999999", "builds_on")]
    kept = _validate_links(links, cands, new_paper_id="new000000001", new_paper_year=2015)
    assert kept == []


def test_filter_drops_future_candidate_on_compares_against() -> None:
    cands = [_make_candidate("future999999", year=2020)]
    links = [_link("future999999", "compares_against")]
    kept = _validate_links(links, cands, new_paper_id="new000000001", new_paper_year=2018)
    assert kept == []


def test_filter_keeps_future_candidate_on_symmetric_relation() -> None:
    # `shares_method` and `contrasts_with` carry no temporal direction —
    # contemporaneous or even later candidates are legitimate.
    cands = [_make_candidate("later00000001", year=2020)]
    links = [
        _link("later00000001", "shares_method"),
    ]
    kept = _validate_links(links, cands, new_paper_id="new000000001", new_paper_year=2018)
    assert [link.related_paper_id for link in kept] == ["later00000001"]


def test_filter_keeps_directional_when_candidate_year_unknown() -> None:
    # Candidate year=0 means "unknown" (SearchResult fallback). Don't drop
    # on missing data — only drop when temporal violation is definitive.
    cands = [_make_candidate("unknown00000y", year=0)]
    links = [_link("unknown00000y", "builds_on")]
    kept = _validate_links(links, cands, new_paper_id="new000000001", new_paper_year=2018)
    assert [link.related_paper_id for link in kept] == ["unknown00000y"]
