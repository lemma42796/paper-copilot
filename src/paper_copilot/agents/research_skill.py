from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from paper_copilot.shared.errors import AgentError

__all__ = [
    "ResearchSkill",
    "load_formula_ocr_skill",
    "load_research_skill",
]

_SKILL_NAME = "research-papers"
_FORMULA_OCR_SKILL_NAME = "formula-ocr"
_SKILL_VERSION_PATTERN = re.compile(
    r"^Skill version: (?P<version>[1-9][0-9]*)$",
    re.MULTILINE,
)
_SKILL_DESCRIPTION_PATTERN = re.compile(
    r"^description: (?P<description>.+)$",
    re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class ResearchSkill:
    name: str
    description: str
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
    return _load_bundled_skill(_SKILL_NAME)


@lru_cache(maxsize=1)
def load_formula_ocr_skill() -> ResearchSkill:
    return _load_bundled_skill(_FORMULA_OCR_SKILL_NAME)


def _load_bundled_skill(name: str) -> ResearchSkill:
    skill_path = Path(__file__).with_name("skills") / name / "SKILL.md"
    try:
        contents = skill_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise AgentError(f"bundled {name} Skill is unavailable") from error
    expected_frontmatter = f"---\nname: {name}\n"
    if not contents.startswith(expected_frontmatter):
        raise AgentError(f"bundled {name} Skill has invalid frontmatter")
    version_matches = _SKILL_VERSION_PATTERN.findall(contents)
    if len(version_matches) != 1:
        raise AgentError(f"bundled {name} Skill must declare exactly one version")
    description_matches = _SKILL_DESCRIPTION_PATTERN.findall(contents)
    if len(description_matches) != 1:
        raise AgentError(
            f"bundled {name} Skill must declare exactly one description"
        )
    return ResearchSkill(
        name=name,
        # The frontmatter description is the single source of truth; the
        # catalog and system prompt must not drift from the shipped Skill.
        description=description_matches[0],
        version=version_matches[0],
        sha256=hashlib.sha256(contents.encode("utf-8")).hexdigest(),
        resource_uri=(
            f"resource://paper-copilot/agents/skills/{name}/SKILL.md"
        ),
        contents=contents,
    )
