from __future__ import annotations

import asyncio
from pathlib import Path

from paper_copilot.agents.mock_llm import MockLLM, MockResponse, TextBlock
from paper_copilot.chat.runtime import handle_chat_request
from paper_copilot.knowledge.fields_store import FieldsStore


def test_handle_chat_request_returns_frontend_ready_result(tmp_path: Path) -> None:
    with FieldsStore.open(tmp_path / "fields.db"):
        pass

    llm = MockLLM(
        [
            MockResponse(
                content=[
                    TextBlock(
                        text=(
                            "## Idea\n\n"
                            "Use diffusion priors for robust medical segmentation.\n\n"
                            "## Evidence\n\n"
                            "- Paper A supports sparse attention [paperA:methods[0]]."
                        )
                    )
                ],
                stop_reason="end_turn",
                usage={"input_tokens": 10, "output_tokens": 4},
            ),
        ]
    )

    result = asyncio.run(
        handle_chat_request(
            (
                "基于 diffusion model 和医学图像分割，"
                "帮我找一个可做的创新点"
            ),
            root=tmp_path,
            runs_dir=tmp_path / "runs",
            eval_report_path=tmp_path / "report.html",
            llm=llm,
        )
    )

    assert result.route.kind == "idea_composer"
    assert result.report_path.exists()
    assert result.session_path.exists()
    assert result.quality_run_path is not None
    assert result.quality_run_path.parent == tmp_path / "runs"
    assert result.quality_run_path.suffix == ".jsonl"
    assert result.eval_report_path is not None
    assert result.eval_report_path == tmp_path / "report.html"
    assert result.eval_report_path.exists()
    assert "diffusion priors" in result.report_markdown
