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

EvidenceType = Literal["explicit_claim", "author_hedge", "our_inference"]

LimitationType = Literal["scope", "method", "empirical"]


class PaperMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
            "ArXiv identifier as printed on the paper. Copy EXACTLY as it appears, "
            "including any 'arXiv:' prefix and any version suffix like 'v7'. "
            "NEVER invent or infer an arXiv id from the title, authors, year, or your "
            "own memory of the paper. If no arXiv id is visibly printed anywhere in "
            "the extracted text, return null. Pre-2007 papers used formats like "
            "'cs/0406013' — only return these when literally printed; do not "
            "construct them from the publication date."
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
    evidence_type: EvidenceType = Field(
        description=(
            "How grounded this claim is in the paper's own language. Pick exactly one.\n"
            "The decision is about the supporting sentence(s) the paper uses for the "
            "claim, not about how citable the claim is in general.\n"
            "'author_hedge' — FIRST CHECK. If the supporting sentence(s) contain any "
            "hedge marker ('we postulate', 'we argue', 'we believe', 'we hypothesize', "
            "'may', 'appears to', 'suggests', 'likely', 'conjecture') select this. "
            "The authors are signaling they have a view but not a demonstration. This "
            "is the correct answer for analysis/interpretation claims even when the "
            "paragraph is long and detailed.\n"
            "'explicit_claim' — otherwise, if the paper states it directly with "
            "numbers (e.g. '21.2% top-1 error'), definitions (e.g. 'LSR is defined "
            "as...'), or demonstrated experiments. Default to this ONLY when there "
            "is no hedge language in the supporting prose.\n"
            "'our_inference' — you are extrapolating from indirect evidence; the "
            "paper does not say this. Avoid this category — prefer to drop the "
            "contribution entirely rather than include one you had to invent."
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
            "Good: 'replaces softmax attention with sparse top-k selection'. "
            "When `is_novel_to_this_paper` is false, describe the method's actual "
            "origin (e.g. 'Rumelhart et al. 1986, used here as a training primitive') "
            "rather than inventing novelty it does not have."
        )
    )
    is_novel_to_this_paper: bool = Field(
        description=(
            "True only if this paper proposes this method as one of its own "
            "contributions. False when it is background (e.g. backpropagation in a "
            "2025 deep-learning paper), a baseline the paper is compared against, or "
            "an existing technique the paper merely uses as a building block. "
            "Prior-work sections, literature reviews, and 'we build on X' mentions "
            "should be false."
        )
    )


class Experiment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str = Field(
        description=(
            "Name of the benchmark or dataset (e.g. 'GLUE', 'ImageNet-1k', "
            "'custom 1B-token arXiv crawl'). "
            "Emit one Experiment per (dataset, metric) pair — if a single table "
            "reports top-1 and top-5 on ImageNet, that is two Experiments, not one "
            "with a combined metric string. Same for multi-condition reports like "
            "'All' vs 'No UNK' — split into separate Experiments with the condition "
            "in the metric or raw field."
        )
    )
    metric: str = Field(
        description=(
            "A single metric reported (e.g. 'top-1 accuracy', 'BLEU', 'perplexity', "
            "'wall-clock speedup'). Never combine two metrics with a slash like "
            "'mAP / Rank-1' — that produces one Experiment covering two results, and "
            "`value` loses one of them. If the paper reports both, emit two "
            "Experiments."
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
    pages: list[int] = Field(
        default_factory=list,
        description=(
            "1-based page number(s) where this result is reported in the "
            "paper. Use the page of the table or paragraph that states the "
            "result. A list because a result may span pages (e.g. a table "
            "header on page 5 with continuation on page 6). Empty list if "
            "the result cannot be localized to specific pages."
        ),
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
            "One concrete sentence stating the limitation, as the authors themselves "
            "describe it. Only include limitations the paper discusses — in its own "
            "limitations / conclusion / discussion sections, or in hedged phrasing "
            "within the main body. Do NOT speculate on limitations the authors do "
            "not address, and do NOT apply template phrasings from unrelated domains "
            "(e.g. do not add 'low-resource languages' to a vision paper, do not add "
            "'scalability' to a method paper that never discusses scale). If the "
            "paper genuinely discusses no limitation, the list around this field "
            "should be empty — return zero Limitation entries rather than inventing "
            "one. Do not prefix with 'Not stated but likely' or similar; if you feel "
            "the need to do so, the limitation should not be in the list."
        )
    )


class CrossPaperLink(BaseModel):
    """Placeholder for cross-paper relations. Schema finalized in M12 (RelatedAgent)."""

    model_config = ConfigDict(extra="forbid")

    related_paper_id: str = Field(description="paper_id of the related paper in the local library.")
    explanation: str = Field(
        description=(
            "1-2 sentences describing how the two papers relate. "
            "Schema finalized in M12 — keep this free-text for now."
        )
    )


class SectionMarker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        description=(
            "Exact section title as printed in the paper body or its PDF outline, "
            "including the paper's own numbering if present (e.g. '3.2 Attention', "
            "'Abstract'). Preserve capitalization and wording. Do not add a number "
            "to an unnumbered section (e.g. 'Why Self-Attention' stays as-is), do "
            "not rewrite for brevity, do not normalize."
        )
    )
    page_start: int = Field(
        ge=1,
        description=(
            "1-based page number where the section begins, matching the page "
            "numbering a human reader of the PDF sees (not a 0-based index)."
        ),
    )
    page_end: int | None = Field(
        default=None,
        description=(
            "1-based page number where the section ends, inclusive. "
            "Null if the section continues beyond the pages you were given or the "
            "end is genuinely uncertain. Do not guess — null is correct when "
            "unknown."
        ),
    )
    depth: int = Field(
        ge=1,
        description=(
            "Nesting depth, starting at 1 for top-level sections. A '3. Methodology' "
            "heading is depth 1; its '3.1' subsection is depth 2; a '3.1.1' leaf is "
            "depth 3. Use the paper's own numbering as the authoritative signal when "
            "available; for unnumbered sections, infer from visual hierarchy."
        ),
    )


class PaperSkeleton(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: list[SectionMarker] = Field(
        description=(
            "Every named section of the paper, in reading order, including "
            "sub-sections. Include 'Abstract' only if the paper renders it as a "
            "titled section. Exclude figure and table captions, footnotes, "
            "acknowledgements that are not titled sections, and the references "
            "list — those are not sections."
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
            "All headline experimental results. One Experiment per (dataset, metric) pair."
        )
    )
    limitations: list[Limitation] = Field(
        description=(
            "Limitations the authors themselves state. An empty list is the correct "
            "answer when the paper does not discuss its own limitations — it is "
            "better to return zero entries than to invent template-shaped ones."
        )
    )
    cross_paper_links: list[CrossPaperLink] = Field(
        default_factory=list,
        description=(
            "Links to related papers in the local library. "
            "Empty until populated by RelatedAgent in M12."
        ),
    )
