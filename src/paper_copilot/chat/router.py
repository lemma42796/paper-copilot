from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ChatKind = Literal["research", "idea_composer"]
OutputProfile = Literal["research_report", "idea_composer"]

_IDEA_KEYWORDS = (
    "baseline",
    "module",
    "ablation",
    "基线",
    "模块",
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
)


@dataclass(frozen=True, slots=True)
class ChatRoute:
    kind: ChatKind
    output_profile: OutputProfile
    reason: str

    def to_payload(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "output_profile": self.output_profile,
            "reason": self.reason,
        }


def route_chat_request(request: str) -> ChatRoute:
    normalized = request.strip().casefold()
    if any(keyword in normalized for keyword in _IDEA_KEYWORDS):
        return ChatRoute(
            kind="idea_composer",
            output_profile="idea_composer",
            reason="matched_idea_composer_keyword",
        )

    return ChatRoute(
        kind="research",
        output_profile="research_report",
        reason="default_research_route",
    )
