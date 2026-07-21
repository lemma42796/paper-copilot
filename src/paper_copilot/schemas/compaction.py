from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CompactionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = Field(
        default=1,
        description="Schema version. Always return 1.",
    )
    original_goal: str = Field(
        min_length=1,
        description=(
            "The user's active goal and requested deliverable. Preserve scope and "
            "acceptance criteria; do not add a new objective."
        ),
    )
    active_constraints: list[str] = Field(
        description=(
            "Requirements that still govern future work. Copy exact limits, names, "
            "paths, identifiers, and configuration values when present."
        )
    )
    decisions: list[str] = Field(
        description=(
            "Decisions already made, with their stated reasons. Keep rejected "
            "alternatives only when they prevent repeated work."
        )
    )
    completed_work: list[str] = Field(
        description=(
            "Work already completed and its verified outcome. Distinguish completed "
            "work from proposals or plans."
        )
    )
    evidence_and_identifiers: list[str] = Field(
        description=(
            "Evidence references and exact identifiers needed later, including paper "
            "IDs, citation refs, file paths, field names, commands, and numeric results."
        )
    )
    failed_attempts: list[str] = Field(
        description=(
            "Failed approaches, errors, and why they failed, when retaining them avoids "
            "repeating the same mistake."
        )
    )
    open_questions: list[str] = Field(
        description="Unresolved questions, missing evidence, and unverified assumptions."
    )
    next_actions: list[str] = Field(
        description=(
            "Concrete remaining actions in dependency order. Do not mark an action "
            "complete unless the source history says it is complete."
        )
    )
    superseded_information: list[str] = Field(
        description=(
            "Earlier information explicitly replaced by a later decision or fact. "
            "State both the obsolete value and its replacement."
        )
    )
