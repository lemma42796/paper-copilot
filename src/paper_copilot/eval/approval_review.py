from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

from paper_copilot.agents.approval_review import review_tool_approval
from paper_copilot.agents.loop import LLMClientProtocol
from paper_copilot.agents.tool_security import (
    ToolApprovalRequest,
    tool_input_sha256,
)


class ApprovalReviewCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    user_request: str
    tool_input: dict[str, Any]
    expected_outcome: Literal["allow", "deny"]


class ApprovalReviewSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    cases: list[ApprovalReviewCase]


class ApprovalReviewCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    expected_outcome: Literal["allow", "deny"]
    actual_outcome: Literal["allow", "deny"]
    passed: bool
    rationale: str


def load_approval_review_suite(path: Path) -> ApprovalReviewSuite:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ApprovalReviewSuite.model_validate(payload)


async def run_approval_review_suite(
    suite: ApprovalReviewSuite,
    *,
    llm: LLMClientProtocol,
) -> list[ApprovalReviewCaseResult]:
    results: list[ApprovalReviewCaseResult] = []
    for case in suite.cases:
        approval = ToolApprovalRequest(
            id=f"eval-{case.name}",
            tool_call_id=f"tool-{case.name}",
            tool_name="library_files",
            reason="Approval review evaluation case.",
            effects=["write_library"],
            tool_input=case.tool_input,
            input_sha256=tool_input_sha256(case.tool_input),
            target_snapshot=[],
            requirement="approval",
            auto_review_allowed=True,
        )
        review = await review_tool_approval(
            llm,
            user_request=case.user_request,
            approval=approval,
        )
        actual = review.assessment.outcome
        results.append(
            ApprovalReviewCaseResult(
                name=case.name,
                expected_outcome=case.expected_outcome,
                actual_outcome=actual,
                passed=actual == case.expected_outcome,
                rationale=review.assessment.rationale,
            )
        )
    return results
