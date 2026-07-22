from __future__ import annotations

import subprocess
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from paper_copilot.api import http
from paper_copilot.api.http import (
    ChatHttpRequest,
    ChatHttpResponse,
    ChatReportsHttpResponse,
    DirectorySelectionHttpResponse,
    JobCreateHttpRequest,
)
from paper_copilot.chat.history import list_chat_reports
from paper_copilot.chat.runtime import ChatRunResult
from paper_copilot.session.store import SessionStore


def test_chat_http_request_accepts_frontend_payload() -> None:
    request = ChatHttpRequest.model_validate(
        {
            "message": (
                "基于 diffusion model 和医学图像分割,"
                "帮我找一个创新点"
            ),
            "pdf_dir": "/tmp/pdfs",
            "max_papers": 3,
        }
    )

    assert request.message.startswith("基于 diffusion")
    assert request.pdf_dir == Path("/tmp/pdfs")
    assert request.max_papers == 3
    assert request.record_quality is True


def test_job_create_request_accepts_conversation_follow_up() -> None:
    request = JobCreateHttpRequest.model_validate(
        {
            "message": "继续解释上一轮的 baseline",
            "conversation_id": "conversation-20260722T120000-1234567890",
            "rollout_timeout_seconds": 900,
        }
    )

    assert request.conversation_id == "conversation-20260722T120000-1234567890"
    assert request.rollout_timeout_seconds == 900


def test_chat_http_response_serializes_chat_result() -> None:
    result = ChatRunResult(
        request="找一个创新点",
        report_markdown="## Idea\n\nUse diffusion priors.",
        session_path=Path("/tmp/session.jsonl"),
        report_path=Path("/tmp/research-report.md"),
        quality_run_path=Path("/tmp/runs/r1.jsonl"),
        eval_report_path=Path("/tmp/report.html"),
        termination_reason="end_turn",
        cost_cny=0.12,
        events_count=3,
        paper_budget={"touched_count": 2, "max_papers": 5},
        composer_plan={"baseline": {"paper_id": "paperA"}},
        proposal_check={"passed": True, "issues": []},
    )

    response = ChatHttpResponse.from_result(result).model_dump(mode="json")

    assert "route" not in response
    assert response["session_path"] == "/tmp/session.jsonl"
    assert response["quality_run_path"] == "/tmp/runs/r1.jsonl"
    assert response["paper_budget"]["touched_count"] == 2
    assert response["composer_plan"]["baseline"]["paper_id"] == "paperA"
    assert response["proposal_check"]["passed"] is True


def test_reports_response_serializes_history(tmp_path: Path) -> None:
    store = SessionStore.create(
        "research-20260518T000000000000Z-topic",
        model="qwen3.6-flash",
        agent="PaperCopilot",
        root=tmp_path,
    )
    store.append_final_output(
        {
            "prompt": "比较注意力机制",
            "termination_reason": "end_turn",
            "cost": {"cost_cny": 0.0123},
            "paper_budget": {"touched_count": 2, "max_papers": 5},
            "termination_summary": {"events_count": 7},
            "composer_plan": {
                "baseline": {"paper_id": "paperA"},
                "accepted_modules": [],
            },
            "proposal_check": {"passed": True, "issues": []},
        }
    )
    report_path = store.path.parent / "research-report.md"
    report_path.write_text("# Findings\n\nEvidence.", encoding="utf-8")

    items = list_chat_reports(root=tmp_path)
    response = ChatReportsHttpResponse.from_items(items).model_dump(mode="json")

    assert response["reports"][0]["request"] == "比较注意力机制"
    assert "route" not in response["reports"][0]
    assert response["reports"][0]["report_markdown"] == "# Findings\n\nEvidence."
    assert response["reports"][0]["cost_cny"] == 0.0123
    assert response["reports"][0]["events_count"] == 7
    assert response["reports"][0]["composer_plan"]["baseline"]["paper_id"] == "paperA"
    assert response["reports"][0]["proposal_check"]["passed"] is True


def test_directory_selection_response_serializes_selected_path() -> None:
    response = DirectorySelectionHttpResponse(path="/Users/a123/Documents/papers")

    assert response.model_dump(mode="json") == {
        "path": "/Users/a123/Documents/papers",
    }


def test_select_directory_macos_returns_none_when_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> CompletedProcess[str]:
        return CompletedProcess(
            args=["osascript"],
            returncode=1,
            stdout="",
            stderr="User canceled.",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert http._select_directory_macos() is None


def test_select_directory_macos_returns_selected_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> CompletedProcess[str]:
        return CompletedProcess(
            args=["osascript"],
            returncode=0,
            stdout="/Users/a123/Documents/papers/\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert http._select_directory_macos() == Path("/Users/a123/Documents/papers")
