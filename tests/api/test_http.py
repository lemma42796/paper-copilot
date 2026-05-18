from __future__ import annotations

from pathlib import Path

from paper_copilot.api.http import ChatHttpRequest, ChatHttpResponse, ChatReportsHttpResponse
from paper_copilot.chat.history import list_chat_reports
from paper_copilot.chat.router import ChatRoute
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


def test_chat_http_response_serializes_chat_result() -> None:
    result = ChatRunResult(
        request="找一个创新点",
        route=ChatRoute(
            kind="idea_composer",
            output_profile="idea_composer",
            reason="matched_idea_composer_keyword",
        ),
        report_markdown="## Idea\n\nUse diffusion priors.",
        session_path=Path("/tmp/session.jsonl"),
        report_path=Path("/tmp/research-report.md"),
        quality_run_path=Path("/tmp/runs/r1.jsonl"),
        eval_report_path=Path("/tmp/report.html"),
        termination_reason="end_turn",
        cost_cny=0.12,
        events_count=3,
        paper_budget={"touched_count": 2, "max_papers": 5},
    )

    response = ChatHttpResponse.from_result(result).model_dump(mode="json")

    assert response["route"]["kind"] == "idea_composer"
    assert response["session_path"] == "/tmp/session.jsonl"
    assert response["quality_run_path"] == "/tmp/runs/r1.jsonl"
    assert response["paper_budget"]["touched_count"] == 2


def test_reports_response_serializes_history(tmp_path: Path) -> None:
    store = SessionStore.create(
        "research-20260518T000000000000Z-topic",
        model="qwen3.6-flash",
        agent="ResearchAgent",
        root=tmp_path,
    )
    store.append_final_output(
        {
            "topic": "比较注意力机制",
            "request_route": {
                "kind": "research",
                "output_profile": "research",
                "reason": "default",
            },
            "termination_reason": "end_turn",
            "cost": {"cost_cny": 0.0123},
            "paper_budget": {"touched_count": 2, "max_papers": 5},
            "termination_summary": {"events_count": 7},
        }
    )
    report_path = store.path.parent / "research-report.md"
    report_path.write_text("# Findings\n\nEvidence.", encoding="utf-8")

    items = list_chat_reports(root=tmp_path)
    response = ChatReportsHttpResponse.from_items(items).model_dump(mode="json")

    assert response["reports"][0]["request"] == "比较注意力机制"
    assert response["reports"][0]["route"]["kind"] == "research"
    assert response["reports"][0]["report_markdown"] == "# Findings\n\nEvidence."
    assert response["reports"][0]["cost_cny"] == 0.0123
    assert response["reports"][0]["events_count"] == 7
