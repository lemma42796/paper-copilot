from __future__ import annotations

from dataclasses import dataclass

from paper_copilot.agents.research_skill import ResearchSkill
from paper_copilot.shared.errors import AgentError


@dataclass(frozen=True, slots=True)
class SkillCatalogEntry:
    name: str
    description: str
    version: str
    sha256: str
    resource_uri: str

    def to_payload(self) -> dict[str, str]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "sha256": self.sha256,
            "resource_uri": self.resource_uri,
        }


class SkillRegistry:
    def __init__(self, *skills: ResearchSkill) -> None:
        self._skills = {skill.name: skill for skill in skills}
        if len(self._skills) != len(skills):
            raise AgentError("Skill registry contains duplicate names")

    def catalog(self) -> tuple[SkillCatalogEntry, ...]:
        return tuple(
            SkillCatalogEntry(
                name=skill.name,
                description=skill.description,
                version=skill.version,
                sha256=skill.sha256,
                resource_uri=skill.resource_uri,
            )
            for skill in self._skills.values()
        )

    def load(self, name: str) -> ResearchSkill:
        skill = self._skills.get(name)
        if skill is None:
            raise AgentError(f"unknown Skill: {name}")
        return skill
