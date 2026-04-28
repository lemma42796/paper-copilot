"""Render a Paper to Markdown for CLI output and report.md."""

from __future__ import annotations

from typing import Literal

from paper_copilot.schemas.paper import Paper

__all__ = ["to_markdown"]

_HEADERS: dict[str, dict[str, str]] = {
    "en": {
        "authors": "Authors",
        "year": "Year",
        "venue": "Venue",
        "arxiv": "arXiv",
        "contributions": "Contributions",
        "methods": "Methods",
        "experiments": "Experiments",
        "limitations": "Limitations",
        "novelty": "Novelty",
        "related": "Related Papers",
        "baseline": "baseline",
    },
    "zh": {
        "authors": "作者",
        "year": "年份",
        "venue": "会议",
        "arxiv": "arXiv",
        "contributions": "贡献",
        "methods": "方法",
        "experiments": "实验",
        "limitations": "局限",
        "novelty": "新意",
        "related": "相关论文",
        "baseline": "基线",
    },
}

_EVIDENCE_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "explicit_claim": "explicit",
        "author_hedge": "authors hedge",
        "our_inference": "inferred",
    },
    "zh": {
        "explicit_claim": "明说",
        "author_hedge": "作者缓和措辞",
        "our_inference": "推断",
    },
}

_RELATION_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "builds_on": "builds on",
        "compares_against": "compares against",
        "shares_method": "shares method with",
        "contrasts_with": "contrasts with",
        "applies_in_different_domain": "applies in a different domain from",
    },
    "zh": {
        "builds_on": "基于",
        "compares_against": "对比基线",
        "shares_method": "方法相近",
        "contrasts_with": "对立路线",
        "applies_in_different_domain": "跨领域应用",
    },
}


def to_markdown(paper: Paper, *, language: Literal["en", "zh"] = "en") -> str:
    h = _HEADERS[language]
    m = paper.meta
    lines: list[str] = [f"# {m.title}", ""]

    bib: list[str] = [
        f"**{h['authors']}:** {', '.join(m.authors)}",
        f"**{h['year']}:** {m.year}",
    ]
    if m.venue:
        bib.append(f"**{h['venue']}:** {m.venue}")
    if m.arxiv_id:
        bib.append(f"**{h['arxiv']}:** {m.arxiv_id}")
    lines.append("  \n".join(bib))
    lines.append("")

    evidence = _EVIDENCE_LABELS[language]
    lines.append(f"## {h['contributions']}")
    lines.append("")
    for c in paper.contributions:
        lines.append(f"- **[{c.type}]** ({evidence[c.evidence_type]}) {c.claim}")
    lines.append("")

    lines.append(f"## {h['methods']}")
    lines.append("")
    for method in paper.methods:
        tag = "" if method.is_novel_to_this_paper else f" *[{h['baseline']}]*"
        lines.append(f"### {method.name}{tag}")
        lines.append("")
        lines.append(method.description)
        lines.append("")
        lines.append(f"*{h['novelty']}:* {method.novelty_vs_prior}")
        if method.key_formula:
            lines.append("")
            lines.append(f"$${method.key_formula}$$")
        lines.append("")

    lines.append(f"## {h['experiments']}")
    lines.append("")
    for e in paper.experiments:
        val = f"{e.value}{e.unit or ''}" if e.value is not None else "n/a"
        pages = f" (p. {', '.join(str(p) for p in e.pages)})" if e.pages else ""
        lines.append(f"- **{e.dataset}** / {e.metric}: **{val}** vs {e.comparison_baseline}{pages}")
        already_shown = f"{val} vs {e.comparison_baseline}".lower()
        raw_norm = (e.raw or "").strip().lower()
        if raw_norm and raw_norm not in already_shown:
            lines.append(f"  - _{e.raw}_")
    lines.append("")

    lines.append(f"## {h['limitations']}")
    lines.append("")
    for lim in paper.limitations:
        lines.append(f"- **[{lim.type}]** {lim.description}")
    lines.append("")

    if paper.cross_paper_links:
        relation = _RELATION_LABELS[language]
        lines.append(f"## {h['related']}")
        lines.append("")
        for link in paper.cross_paper_links:
            label = relation[link.relation_type]
            lines.append(
                f"- *{link.related_title}* (`{link.related_paper_id}`) "
                f"**[{label}]** — {link.explanation}"
            )
        lines.append("")

    return "\n".join(lines)
