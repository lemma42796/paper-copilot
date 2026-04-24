from paper_copilot.agents.deep import DeepResult
from paper_copilot.agents.main import _assemble_paper
from paper_copilot.schemas.paper import (
    Contribution,
    Experiment,
    Limitation,
    Method,
    Paper,
    PaperMeta,
)


def _make_meta() -> PaperMeta:
    return PaperMeta(
        title="Test Title",
        authors=["Alice", "Bob"],
        arxiv_id=None,
        year=2025,
        venue=None,
    )


def _make_deep_result() -> DeepResult:
    return DeepResult(
        contributions=[
            Contribution(
                claim="a novel method",
                type="novel_method",
                evidence_type="explicit_claim",
            ),
        ],
        methods=[
            Method(
                name="ThingNet",
                description="it does stuff",
                key_formula=None,
                novelty_vs_prior="replaces X with Y",
                is_novel_to_this_paper=True,
            ),
        ],
        experiments=[
            Experiment(
                dataset="SomeBench",
                metric="accuracy",
                value=90.0,
                unit="%",
                raw="90% on SomeBench test split",
                comparison_baseline="ResNet",
            ),
        ],
        limitations=[
            Limitation(type="scope", description="English-only evaluation."),
        ],
    )


def test_assemble_paper_produces_valid_paper() -> None:
    paper = _assemble_paper(_make_meta(), _make_deep_result())
    assert paper.meta.title == "Test Title"
    assert len(paper.contributions) == 1
    assert len(paper.methods) == 1
    assert len(paper.experiments) == 1
    assert len(paper.limitations) == 1
    assert paper.cross_paper_links == []


def test_assemble_paper_json_roundtrip() -> None:
    paper = _assemble_paper(_make_meta(), _make_deep_result())
    restored = Paper.model_validate_json(paper.model_dump_json())
    assert restored == paper
