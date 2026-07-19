from __future__ import annotations

import asyncio
from pathlib import Path

from paper_copilot.agents.mock_llm import MockLLM, MockResponse, TextBlock
from paper_copilot.chat.runtime import handle_chat_request
from paper_copilot.session import Message, SessionStore, ToolUse


def test_handle_chat_request_allows_direct_answer_without_index(tmp_path: Path) -> None:
    llm = MockLLM(
        [
            MockResponse(
                content=[TextBlock(text="你好")],
                stop_reason="end_turn",
                usage={"input_tokens": 10, "output_tokens": 4},
            ),
        ]
    )

    result = asyncio.run(
        handle_chat_request(
            "你好",
            root=tmp_path,
            runs_dir=tmp_path / "runs",
            eval_report_path=tmp_path / "report.html",
            llm=llm,
        )
    )

    assert result.report_path.exists()
    assert result.session_path.exists()
    assert result.quality_run_path is None
    assert result.eval_report_path is None
    assert result.report_markdown == "你好"

    entries = SessionStore(result.session_path, last_id="").read_all()
    user_message = next(
        entry for entry in entries if isinstance(entry, Message) and entry.role == "user"
    )
    assert user_message.text == "你好"
    assert not any(isinstance(entry, ToolUse) for entry in entries)
