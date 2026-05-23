from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from paper_copilot.agents.composer_plan import (
    MODULE_POOL_ORDER,
    TARGET_MODULE_COUNT,
    ComposerDecision,
    ComposerPlanState,
)

IssueSeverity = Literal["error", "warning"]

_EVIDENCE_REF_RE = re.compile(
    r"\[\s*(?P<paper_id>[A-Za-z0-9_-]{3,64})\s*:\s*"
    r"(?P<field>[A-Za-z_][A-Za-z0-9_.\[\]-]*)\s*\]"
)
_PROCESS_CHATTER_RE = re.compile(
    r"^(报告(已)?(准备好|准备就绪|完成)|以下是|下面是|我(已经|将)|"
    r"here is|the report is ready|i have|now i('|’)ll)\b",
    flags=re.IGNORECASE,
)
_THEMATIC_BREAKS = {"---", "***", "___"}
_ENGLISH_HEADING_RE = re.compile(
    r"^#{1,6}\s+"
    r"(Problem|Baseline|Candidate Modules|Compatibility|Proposed Composition|"
    r"Experiment Plan|Risks|Evidence)\s*$",
    flags=re.IGNORECASE | re.MULTILINE,
)
_PERFORMANCE_TERMS = (
    "性能",
    "高起点",
    "强基线",
    "表现",
    "sota",
    "state-of-the-art",
    "high-performing",
    "strong",
    "rank-1",
    "map",
    "accuracy",
    "performance",
)
_OPENING_TERMS = (
    "改进",
    "不足",
    "弱点",
    "局限",
    "瓶颈",
    "缺口",
    "仍",
    "可以",
    "opening",
    "weakness",
    "limitation",
    "gap",
    "bottleneck",
    "improve",
)
_ATTACHMENT_TERMS = (
    "接入",
    "插入",
    "替换",
    "融合",
    "挂载",
    "附着",
    "附加",
    "应用于",
    "置于",
    "之后",
    "attach",
    "attachment",
    "compatible",
    "compatibility",
    "兼容",
)
_HYPOTHESIS_TERMS = (
    "假设",
    "预期",
    "预计",
    "可能",
    "待验证",
    "观察",
    "hypothesis",
    "expected",
    "may",
    "could",
)
_GUESSED_METRIC_RE = re.compile(
    r"(\+\s*\d+(?:\.\d+)?\s*(?:-|~|到|至)\s*\d*(?:\.\d+)?\s*%|\+\s*\d+(?:\.\d+)?\s*%|"
    r"(提升|提高|涨|增益|gain)[^。；;\n]{0,32}\d+(?:\.\d+)?\s*%)",
    flags=re.IGNORECASE,
)
_HYPERPARAM_RE = re.compile(
    r"\b(AdamW|SGD|optimizer|learning rate|lr|batch size|batch|epoch|epochs|weight decay)\b",
    flags=re.IGNORECASE,
)
_COMPLEXITY_RE = re.compile(
    r"(O\([^)]+\)|复杂度[^。；;\n]{0,32}(降低|降到|线性|linear))",
    flags=re.IGNORECASE,
)
_LOSS_COMBINATION_RE = re.compile(
    r"(融合|联合|组合|combine|joint)[^。；;\n]{0,48}(loss|损失)",
    flags=re.IGNORECASE,
)
_SPECIFIC_LABEL_RE = re.compile(r"\b[A-Z][A-Za-z0-9]+-like\b|联合优化")


@dataclass(frozen=True, slots=True)
class ComposerProposalIssue:
    code: str
    severity: IssueSeverity
    message: str
    evidence: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class ComposerProposalCheck:
    method: str
    passed: bool
    issues: tuple[ComposerProposalIssue, ...]
    removed_process_chatter: tuple[str, ...]
    counts: dict[str, int]

    def to_payload(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "passed": self.passed,
            "issues": [issue.to_payload() for issue in self.issues],
            "removed_process_chatter": list(self.removed_process_chatter),
            "counts": self.counts,
        }


def strip_leading_process_chatter(markdown: str) -> tuple[str, tuple[str, ...]]:
    lines = markdown.splitlines()
    index = 0
    removed: list[str] = []
    while index < len(lines) and not lines[index].strip():
        index += 1
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        if stripped.startswith("#"):
            break
        if _PROCESS_CHATTER_RE.search(stripped):
            removed.append(stripped)
            index += 1
            continue
        if removed and stripped in _THEMATIC_BREAKS:
            removed.append(stripped)
            index += 1
            continue
        break
    while removed and index < len(lines) and not lines[index].strip():
        index += 1
    if not removed:
        return markdown, ()
    return "\n".join(lines[index:]).strip(), tuple(removed)


def check_composer_proposal(
    markdown: str,
    plan: ComposerPlanState,
    *,
    removed_process_chatter: tuple[str, ...] = (),
) -> ComposerProposalCheck:
    issues: list[ComposerProposalIssue] = []
    citation_paper_ids = _citation_paper_ids(markdown)
    english_headings = _english_headings(markdown)
    unsupported_specifics = _unsupported_specifics(markdown)

    if _cjk_char_count(markdown) < 20:
        issues.append(
            ComposerProposalIssue(
                code="report_not_chinese",
                severity="error",
                message="最终 proposal 应主要用中文输出。",
            )
        )
    if english_headings:
        issues.append(
            ComposerProposalIssue(
                code="english_section_headings",
                severity="error",
                message="Composer 最终报告应使用中文 section 标题。",
                evidence=", ".join(english_headings),
            )
        )
    if _has_process_chatter(markdown):
        issues.append(
            ComposerProposalIssue(
                code="process_chatter",
                severity="error",
                message="最终报告仍包含 agent 过程话术。",
            )
        )
    if removed_process_chatter:
        issues.append(
            ComposerProposalIssue(
                code="process_chatter_removed",
                severity="warning",
                message="已从最终报告开头移除 agent 过程话术。",
                evidence=" | ".join(removed_process_chatter),
            )
        )

    _check_baseline(markdown, plan, citation_paper_ids, issues)
    _check_modules(markdown, plan, citation_paper_ids, issues)
    _check_fallbacks(markdown, plan, issues)
    for line in unsupported_specifics:
        issues.append(
            ComposerProposalIssue(
                code="unsupported_implementation_specific",
                severity="error",
                message=(
                    "训练细节、复杂度变化或指标提升缺少引用，"
                    "或没有明确标成假设/预期观察。"
                ),
                evidence=_compact(line),
            )
        )

    return ComposerProposalCheck(
        method="composer_proposal_checker_v1",
        passed=not any(issue.severity == "error" for issue in issues),
        issues=tuple(issues),
        removed_process_chatter=removed_process_chatter,
        counts={
            "accepted_module_count": len(plan.accepted_modules),
            "distinct_module_paper_count": len(
                {decision.paper_id for decision in plan.accepted_modules}
            ),
            "citation_paper_count": len(citation_paper_ids),
            "english_heading_count": len(english_headings),
            "unsupported_specific_count": len(unsupported_specifics),
        },
    )


def append_composer_check_section(
    markdown: str,
    check: ComposerProposalCheck,
) -> str:
    if check.passed and not check.removed_process_chatter:
        return markdown

    lines = [
        markdown.rstrip(),
        "",
        "## 质量检查",
        "",
        f"- 状态：{'通过' if check.passed else '未通过'}",
        f"- 方法：{check.method}",
    ]
    for issue in check.issues:
        line = f"- {issue.severity}: {issue.code} - {issue.message}"
        if issue.evidence:
            line += f" 证据：{_strip_citation_brackets(issue.evidence)}"
        lines.append(line)
    return "\n".join(lines).strip()


def _check_baseline(
    markdown: str,
    plan: ComposerPlanState,
    citation_paper_ids: set[str],
    issues: list[ComposerProposalIssue],
) -> None:
    if plan.baseline is None:
        issues.append(
            ComposerProposalIssue(
                code="baseline_not_selected",
                severity="error",
                message="composer_plan 中没有已选择的 baseline。",
            )
        )
        return

    baseline = plan.baseline
    baseline_text = _paragraphs_for(markdown, baseline.paper_id)
    if baseline.paper_id not in markdown:
        issues.append(
            ComposerProposalIssue(
                code="baseline_missing_from_report",
                severity="error",
                message="最终报告没有写出 baseline paper_id。",
                evidence=baseline.paper_id,
            )
        )
    if baseline.paper_id not in citation_paper_ids:
        issues.append(
            ComposerProposalIssue(
                code="baseline_missing_citation",
                severity="error",
                message="baseline 需要至少一个可解析引用。",
                evidence=baseline.paper_id,
            )
        )
    if not _contains_any(baseline_text, _PERFORMANCE_TERMS):
        issues.append(
            ComposerProposalIssue(
                code="baseline_strength_missing",
                severity="error",
                message="baseline 需要说明性能强或高起点证据。",
                evidence=baseline.paper_id,
            )
        )
    if not _contains_any(baseline_text, _OPENING_TERMS):
        issues.append(
            ComposerProposalIssue(
                code="baseline_opening_missing",
                severity="error",
                message="baseline 需要说明仍可改进或有研究故事的 opening。",
                evidence=baseline.paper_id,
            )
        )


def _check_modules(
    markdown: str,
    plan: ComposerPlanState,
    citation_paper_ids: set[str],
    issues: list[ComposerProposalIssue],
) -> None:
    modules = plan.accepted_modules
    module_ids = [decision.paper_id for decision in modules]
    if len(modules) != TARGET_MODULE_COUNT:
        issues.append(
            ComposerProposalIssue(
                code="module_count_not_three",
                severity="error",
                message=(
                    "最终方案需要正好 3 个 accepted modules，"
                    "除非明确是 gap report。"
                ),
                evidence=str(len(modules)),
            )
        )
    if len(set(module_ids)) != len(module_ids):
        issues.append(
            ComposerProposalIssue(
                code="module_papers_not_distinct",
                severity="error",
                message="每篇 module paper 最多只能贡献一个 module。",
            )
        )

    for module in modules:
        _check_single_module(markdown, module, citation_paper_ids, issues)


def _check_single_module(
    markdown: str,
    module: ComposerDecision,
    citation_paper_ids: set[str],
    issues: list[ComposerProposalIssue],
) -> None:
    module_text = _module_report_text(markdown, module)
    if module.paper_id not in markdown:
        issues.append(
            ComposerProposalIssue(
                code="module_missing_from_report",
                severity="error",
                message="最终报告没有写出 accepted module paper_id。",
                evidence=module.paper_id,
            )
        )
    if module.paper_id not in citation_paper_ids:
        issues.append(
            ComposerProposalIssue(
                code="module_missing_citation",
                severity="error",
                message="每个 accepted module 需要至少一个可解析引用。",
                evidence=module.paper_id,
            )
        )
    if not module.attachment_point:
        issues.append(
            ComposerProposalIssue(
                code="module_attachment_missing",
                severity="error",
                message="composer_plan 的 accepted module 缺少 attachment_point。",
                evidence=module.paper_id,
            )
        )
    if not module.compatibility_notes:
        issues.append(
            ComposerProposalIssue(
                code="module_compatibility_missing",
                severity="error",
                message="composer_plan 的 accepted module 缺少 compatibility_notes。",
                evidence=module.paper_id,
            )
        )
    if module_text and not _contains_any(module_text, _ATTACHMENT_TERMS):
        issues.append(
            ComposerProposalIssue(
                code="module_attachment_missing_from_report",
                severity="error",
                message=(
                    "最终报告需要说明 module 接到 baseline 的哪里以及兼容性。"
                ),
                evidence=module.paper_id,
            )
        )


def _check_fallbacks(
    markdown: str,
    plan: ComposerPlanState,
    issues: list[ComposerProposalIssue],
) -> None:
    for module in plan.accepted_modules:
        if module.pool == "ccf_a":
            continue
        pool_index = MODULE_POOL_ORDER.index(module.pool)
        for previous_pool in MODULE_POOL_ORDER[:pool_index]:
            if previous_pool not in plan.closed_module_pools:
                issues.append(
                    ComposerProposalIssue(
                        code="fallback_without_closed_pool",
                        severity="error",
                        message="低优先级 module 需要先关闭更高优先级 pool。",
                        evidence=f"{module.paper_id} from {module.pool}",
                    )
                )
        if module.pool not in markdown:
            issues.append(
                ComposerProposalIssue(
                    code="fallback_pool_missing_from_report",
                    severity="error",
                    message=(
                        "最终报告需要写明低优先级 module 的 pool "
                        "与 fallback 原因。"
                    ),
                    evidence=f"{module.paper_id} from {module.pool}",
                )
            )


def _unsupported_specifics(markdown: str) -> list[str]:
    lines: list[str] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        has_ref = bool(_EVIDENCE_REF_RE.search(line))
        metric_claim = bool(_GUESSED_METRIC_RE.search(line))
        evidence_required = (
            bool(_HYPERPARAM_RE.search(line))
            or bool(_COMPLEXITY_RE.search(line))
            or bool(_LOSS_COMBINATION_RE.search(line))
            or bool(_SPECIFIC_LABEL_RE.search(line))
        )
        if (metric_claim and not has_ref and not _has_hypothesis_term(line)) or (
            evidence_required and not has_ref and not _has_hypothesis_term(line)
        ):
            lines.append(line)
    return lines[:8]


def _module_report_text(markdown: str, module: ComposerDecision) -> str:
    paragraphs = [_paragraphs_for(markdown, module.paper_id)]
    labels = _module_labels(module)
    for line in markdown.splitlines():
        if not _contains_any(line, labels):
            continue
        if _contains_any(line, _ATTACHMENT_TERMS):
            paragraphs.append(line.strip())
    return "\n".join(paragraph for paragraph in paragraphs if paragraph)


def _module_labels(module: ComposerDecision) -> tuple[str, ...]:
    text = " ".join(
        part
        for part in (
            module.rationale,
            module.attachment_point,
            module.compatibility_notes,
        )
        if part
    )
    labels = {
        match.group(0)
        for match in re.finditer(r"\b[A-Z][A-Za-z0-9+-]{1,12}\b", text)
        if match.group(0).casefold() not in {"ccf", "sysu", "rank", "map"}
    }
    return tuple(sorted(labels, key=len, reverse=True))


def _citation_paper_ids(markdown: str) -> set[str]:
    return {match.group("paper_id") for match in _EVIDENCE_REF_RE.finditer(markdown)}


def _english_headings(markdown: str) -> list[str]:
    return [match.group(1) for match in _ENGLISH_HEADING_RE.finditer(markdown)]


def _has_process_chatter(markdown: str) -> bool:
    first_lines = [line.strip() for line in markdown.splitlines()[:4] if line.strip()]
    return any(_PROCESS_CHATTER_RE.search(line) for line in first_lines)


def _cjk_char_count(text: str) -> int:
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    normalized = text.casefold()
    return any(term.casefold() in normalized for term in terms)


def _has_hypothesis_term(text: str) -> bool:
    return _contains_any(text, _HYPOTHESIS_TERMS)


def _paragraphs_for(markdown: str, needle: str) -> str:
    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", markdown)
        if needle in paragraph
    ]
    return "\n".join(paragraphs)


def _compact(text: str, *, limit: int = 160) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def _strip_citation_brackets(text: str) -> str:
    return text.replace("[", "").replace("]", "")
