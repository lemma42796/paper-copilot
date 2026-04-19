"""Structured output contracts for LLM paper extraction. Every `Field(description=...)`
is injected into the JSON schema the model sees — treat descriptions as prompt text."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ContributionType = Literal[
    "novel_method",
    "novel_result",
    "novel_dataset",
    "novel_theory",
    "analysis",
    "survey",
]

LimitationType = Literal["scope", "method", "empirical"]


class PaperMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        description=(
            "Canonical paper identifier. Prefer the arXiv id (e.g. '2307.09288'); "
            "otherwise any stable unique string provided by the harness."
        )
    )
    title: str = Field(
        description=(
            "The exact paper title as printed on the first page. "
            "Preserve the original capitalization and do not paraphrase or truncate."
        )
    )
    authors: list[str] = Field(
        description=(
            "Author names in the order listed on the paper, one name per element. "
            "Keep original formatting (e.g. 'Tom B. Brown'). "
            "Include every author — do not abbreviate with 'et al'."
        )
    )
    arxiv_id: str | None = Field(
        default=None,
        description=(
            "ArXiv identifier if present (e.g. '2307.09288'; no 'arXiv:' prefix, "
            "no version suffix). Null for papers without an arXiv mirror."
        ),
    )
    year: int = Field(
        ge=1900,
        le=2100,
        description=(
            "Publication year as a 4-digit integer. "
            "Use the arXiv submission year for preprint-only papers."
        ),
    )
    venue: str | None = Field(
        default=None,
        description=(
            "Publication venue if known (e.g. 'NeurIPS 2023', 'ACL 2024 Findings'). "
            "Null for unpublished preprints."
        ),
    )


class Contribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(
        description=(
            "A single self-contained sentence stating one contribution the paper claims. "
            "Write as if the reader has not read the paper. "
            "Bad: 'we propose a new method'. "
            "Good: 'a sparse top-k attention variant that reduces attention FLOPs by 4x "
            "at equal perplexity on C4'."
        ),
        examples=[
            "a sparse top-k attention variant that reduces attention FLOPs by 4x "
            "at equal perplexity on C4",
            "scaling laws for transformer language models over 5 orders of magnitude "
            "of training compute",
        ],
    )
    type: ContributionType = Field(
        description=(
            "Kind of contribution. Choose the single closest match. "
            "'novel_method' = a new technique/algorithm/architecture; "
            "'novel_result' = a new empirical finding using existing methods; "
            "'novel_dataset' = a new benchmark or dataset; "
            "'novel_theory' = a new mathematical or formal result; "
            "'analysis' = probing or interpretability of existing methods; "
            "'survey' = review or taxonomy of prior work. "
            "If a paper both proposes a method and reports a separate finding, split "
            "into two Contribution entries, one of each type. "
            "If none fit cleanly, pick the closest and put the nuance in `claim`."
        )
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Your confidence (0.0-1.0) that the paper itself supports this claim with "
            "evidence it presents. 1.0 = directly demonstrated in the paper's own "
            "experiments. 0.5 = stated but weakly supported. "
            "Below 0.3 = probably should not include this Contribution at all."
        ),
    )


class Method(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        description=(
            "Short canonical name of the component (e.g. 'FlashAttention', "
            "'Rotary Position Embedding', 'contrastive pre-training loss'). "
            "Use the paper's own name if it coins one; otherwise a descriptive noun "
            "phrase. This name is used to align methods across papers — keep it stable "
            "and lowercase-insensitive where possible."
        )
    )
    description: str = Field(
        description=(
            "2-4 sentences describing the mechanism — what it does and how. "
            "Focus on 'what/how', not 'why it's better'. "
            "Bad: 'improves efficiency'. "
            "Good: 'splits Q into blocks and recomputes softmax normalization per "
            "block, avoiding materializing the N x N attention matrix'."
        )
    )
    key_formula: str | None = Field(
        default=None,
        description=(
            "The single most important equation defining this component, in LaTeX "
            "source (no surrounding $$). Null if the component has no distinctive "
            "formula."
        ),
        examples=[r"\mathrm{Attention}(Q,K,V) = \mathrm{softmax}(QK^\top / \sqrt{d_k})\,V"],
    )
    novelty_vs_prior: str = Field(
        description=(
            "How this method differs from prior work. 1-2 sentences, mechanism-focused, "
            "not metric-focused. "
            "Bad: 'achieves 2% higher F1'. "
            "Good: 'replaces softmax attention with sparse top-k selection'."
        )
    )


class Experiment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str = Field(
        description=(
            "Name of the benchmark or dataset (e.g. 'GLUE', 'ImageNet-1k', "
            "'custom 1B-token arXiv crawl'). "
            "For multi-dataset experiments, emit one Experiment per dataset."
        )
    )
    metric: str = Field(
        description=(
            "Metric reported (e.g. 'top-1 accuracy', 'BLEU', 'perplexity', "
            "'wall-clock speedup')."
        )
    )
    value: float | None = Field(
        default=None,
        description=(
            "Headline numeric value of the paper's own method (not the baseline). "
            "Null when the result is genuinely non-numeric (e.g. a human preference "
            "study with no single number, or a qualitative categorical outcome)."
        ),
    )
    unit: str | None = Field(
        default=None,
        description=(
            "Unit of `value` (e.g. '%', 'points', 'x' for speedup, 'ms'). "
            "Null if dimensionless or if `value` is null."
        ),
    )
    raw: str = Field(
        description=(
            "The result phrased as it appears in the paper's prose or tables. "
            "Always fill this field, even when `value`/`unit` are set — it preserves "
            "context (split, seeds, confidence intervals) that the structured fields drop."
        ),
        examples=[
            "83.4% top-1 on ImageNet-1k validation split",
            "reduces wall-clock training time by ~3x at matched quality",
        ],
    )
    comparison_baseline: str = Field(
        description=(
            "Name of the strongest baseline or prior SOTA this result is compared "
            "against (e.g. 'BERT-large', 'supervised fine-tuning without RLHF'). "
            "Use 'none' if the paper reports no direct comparison."
        )
    )


class Limitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: LimitationType = Field(
        description=(
            "Category of limitation. "
            "'scope' = the paper only covers a narrow setting (e.g. English-only); "
            "'method' = the technique itself has an intrinsic weakness "
            "(e.g. quadratic memory); "
            "'empirical' = evaluation is insufficient (e.g. single seed, small test set)."
        )
    )
    description: str = Field(
        description=(
            "One concrete sentence stating the limitation. "
            "Prefer limitations the authors state themselves; if extrapolating, "
            "prefix with 'Not stated but likely:'. "
            "Bad: 'there are some limitations'. "
            "Good: 'experiments are English-only; transfer to low-resource languages "
            "is not evaluated'."
        )
    )


class CrossPaperLink(BaseModel):
    """Placeholder for cross-paper relations. Schema finalized in M12 (RelatedAgent)."""

    model_config = ConfigDict(extra="forbid")

    related_paper_id: str = Field(
        description="paper_id of the related paper in the local library."
    )
    explanation: str = Field(
        description=(
            "1-2 sentences describing how the two papers relate. "
            "Schema finalized in M12 — keep this free-text for now."
        )
    )


class Paper(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meta: PaperMeta
    contributions: list[Contribution] = Field(
        description=(
            "All claimed contributions of this paper. "
            "Extract at least one — a paper with zero contributions is unusual and "
            "usually means extraction failed."
        )
    )
    methods: list[Method] = Field(
        description=(
            "Every named component the paper uses or introduces, including well-known "
            "ones it builds on (e.g. include 'Transformer' if the paper builds on "
            "transformers). This creates an alignable structure across papers."
        )
    )
    experiments: list[Experiment] = Field(
        description=(
            "All headline experimental results. One Experiment per (dataset, metric) "
            "pair."
        )
    )
    limitations: list[Limitation] = Field(
        description=(
            "Limitations stated by the authors, or inferable from the experimental "
            "setup. An empty list is acceptable when the paper genuinely has none "
            "worth noting."
        )
    )
    cross_paper_links: list[CrossPaperLink] = Field(
        default_factory=list,
        description=(
            "Links to related papers in the local library. "
            "Empty until populated by RelatedAgent in M12."
        ),
    )
