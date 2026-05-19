from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ChatKind = Literal["knowledge_qa", "framework_composer"]
OutputProfile = Literal["knowledge_qa", "framework_composer"]
TaskProfile = Literal[
    "single_paper_focus",
    "fixed_set_compare",
    "topic_survey",
    "evidence_lookup",
    "claim_check",
    "experiment_extraction",
    "timeline_synthesis",
    "gap_analysis",
    "framework_composer",
]

_FRAMEWORK_KEYWORDS = (
    "创新点",
    "创新",
    "研究想法",
    "研究idea",
    "idea",
    "novelty",
    "research idea",
    "proposal",
    "选题",
    "课题",
    "实验方案",
    "改进方案",
    "可做",
    "可发表",
    "新模型",
    "模型框架",
)
_FRAMEWORK_COMBO_ANCHORS = ("baseline", "基线")
_FRAMEWORK_COMBO_TERMS = (
    "module",
    "ablation",
    "模块",
    "消融",
    "可接入",
    "组合",
    "改进",
    "方案",
)
_CLAIM_CHECK_KEYWORDS = (
    "这个说法",
    "是否支持",
    "能否证明",
    "是否成立",
    "是不是",
    "判断",
    "核验",
    "claim check",
    "verify",
    "supported",
)
_EVIDENCE_LOOKUP_KEYWORDS = (
    "证据",
    "引用",
    "哪篇",
    "有没有论文",
    "提到",
    "支持",
    "evidence",
    "citation",
)
_FIXED_SET_COMPARE_KEYWORDS = (
    "对比",
    "比较",
    "差异",
    "异同",
    "区别",
    "compare",
    "versus",
    " vs ",
)
_EXPERIMENT_KEYWORDS = (
    "实验设置",
    "数据集",
    "指标",
    "训练技巧",
    "复现",
    "消融",
    "dataset",
    "metric",
    "baseline",
    "training",
    "ablation",
)
_TIMELINE_KEYWORDS = (
    "演化",
    "脉络",
    "发展",
    "历史",
    "timeline",
    "evolution",
)
_GAP_KEYWORDS = (
    "局限",
    "不足",
    "gap",
    "future work",
    "未来工作",
    "开放问题",
)
_SINGLE_PAPER_KEYWORDS = (
    "解释",
    "解读",
    "这篇",
    "某篇",
    "单篇",
    "核心方法",
    "主要贡献",
    "paper 的",
    "论文的",
)


@dataclass(frozen=True, slots=True)
class ChatRoute:
    kind: ChatKind
    output_profile: OutputProfile
    task_profile: TaskProfile
    reason: str

    def to_payload(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "output_profile": self.output_profile,
            "task_profile": self.task_profile,
            "reason": self.reason,
        }


def route_chat_request(request: str) -> ChatRoute:
    normalized = request.strip().casefold()
    if _is_framework_composer_request(normalized):
        return ChatRoute(
            kind="framework_composer",
            output_profile="framework_composer",
            task_profile="framework_composer",
            reason="matched_framework_composer_keyword",
        )

    task_profile = _knowledge_task_profile(normalized)
    return ChatRoute(
        kind="knowledge_qa",
        output_profile="knowledge_qa",
        task_profile=task_profile,
        reason=f"matched_{task_profile}",
    )


def _is_framework_composer_request(request: str) -> bool:
    if _contains_any(request, _FRAMEWORK_KEYWORDS):
        return True
    return _contains_any(request, _FRAMEWORK_COMBO_ANCHORS) and _contains_any(
        request,
        _FRAMEWORK_COMBO_TERMS,
    )


def _knowledge_task_profile(request: str) -> TaskProfile:
    if _contains_any(request, _CLAIM_CHECK_KEYWORDS):
        return "claim_check"
    if _contains_any(request, _EVIDENCE_LOOKUP_KEYWORDS):
        return "evidence_lookup"
    if _contains_any(request, _FIXED_SET_COMPARE_KEYWORDS):
        return "fixed_set_compare"
    if _contains_any(request, _EXPERIMENT_KEYWORDS):
        return "experiment_extraction"
    if _contains_any(request, _TIMELINE_KEYWORDS):
        return "timeline_synthesis"
    if _contains_any(request, _GAP_KEYWORDS):
        return "gap_analysis"
    if _contains_any(request, _SINGLE_PAPER_KEYWORDS):
        return "single_paper_focus"
    return "topic_survey"


def _contains_any(request: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in request for keyword in keywords)
