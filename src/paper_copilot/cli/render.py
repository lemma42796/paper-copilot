"""Render a Paper to Markdown for CLI output and report.md."""

from __future__ import annotations

from paper_copilot.schemas.paper import Paper

__all__ = ["to_markdown"]


def to_markdown(paper: Paper) -> str:
    m = paper.meta
    lines: list[str] = [f"# {m.title}", ""]

    bib: list[str] = [
        f"**Authors:** {', '.join(m.authors)}",
        f"**Year:** {m.year}",
    ]
    if m.venue:
        bib.append(f"**Venue:** {m.venue}")
    if m.arxiv_id:
        bib.append(f"**arXiv:** {m.arxiv_id}")
    lines.append("  \n".join(bib))
    lines.append("")

    lines.append("## Contributions")
    lines.append("")
    for c in paper.contributions:
        lines.append(f"- **[{c.type}]** (confidence {c.confidence}) {c.claim}")
    lines.append("")

    lines.append("## Methods")
    lines.append("")
    for method in paper.methods:
        lines.append(f"### {method.name}")
        lines.append("")
        lines.append(method.description)
        lines.append("")
        lines.append(f"*Novelty:* {method.novelty_vs_prior}")
        if method.key_formula:
            lines.append("")
            lines.append(f"$${method.key_formula}$$")
        lines.append("")

    lines.append("## Experiments")
    lines.append("")
    for e in paper.experiments:
        val = f"{e.value}{e.unit or ''}" if e.value is not None else "n/a"
        pages = f" (p. {', '.join(str(p) for p in e.pages)})" if e.pages else ""
        lines.append(f"- **{e.dataset}** / {e.metric}: **{val}** vs {e.comparison_baseline}{pages}")
        lines.append(f"  - _{e.raw}_")
    lines.append("")

    lines.append("## Limitations")
    lines.append("")
    for lim in paper.limitations:
        lines.append(f"- **[{lim.type}]** {lim.description}")
    lines.append("")

    if paper.cross_paper_links:
        lines.append("## Related Papers")
        lines.append("")
        for link in paper.cross_paper_links:
            lines.append(f"- **{link.related_paper_id}**: {link.explanation}")
        lines.append("")

    return "\n".join(lines)
