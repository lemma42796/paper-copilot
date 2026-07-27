from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from paper_copilot.shared.errors import AgentError

__all__ = ["ResearchSkill", "load_research_skill"]

_SKILL_NAME = "research-papers"
_SKILL_VERSION = "2"
_SKILL_RESOURCE_URI = (
    "resource://paper-copilot/agents/skills/research-papers/SKILL.md"
)


@dataclass(frozen=True, slots=True)
class ResearchSkill:
    name: str
    version: str
    sha256: str
    resource_uri: str
    contents: str

    def context_fragment(self) -> str:
        return (
            "<skill>\n"
            f"<name>{self.name}</name>\n"
            f"<version>{self.version}</version>\n"
            f"<sha256>{self.sha256}</sha256>\n"
            f"<path>{self.resource_uri}</path>\n"
            f"{self.contents}\n"
            "</skill>"
        )

    def trace_attributes(self) -> dict[str, str]:
        return {
            "skill_name": self.name,
            "skill_version": self.version,
            "skill_sha256": self.sha256,
            "skill_resource_uri": self.resource_uri,
        }


@lru_cache(maxsize=1)
def load_research_skill() -> ResearchSkill:
    skill_path = (
        Path(__file__).with_name("skills") / _SKILL_NAME / "SKILL.md"
    )
    try:
        contents = skill_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise AgentError("bundled research Skill is unavailable") from error
    expected_frontmatter = f"---\nname: {_SKILL_NAME}\n"
    if not contents.startswith(expected_frontmatter):
        raise AgentError("bundled research Skill has invalid frontmatter")
    return ResearchSkill(
        name=_SKILL_NAME,
        version=_SKILL_VERSION,
        sha256=hashlib.sha256(contents.encode("utf-8")).hexdigest(),
        resource_uri=_SKILL_RESOURCE_URI,
        contents=contents,
    )
