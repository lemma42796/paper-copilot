from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from paper_copilot.agents.loop import ToolUseRequest
from paper_copilot.agents.mock_llm import MockLLM, MockResponse, TextBlock, ToolUseBlock
from paper_copilot.agents.research import (
    ResearchToolContext,
    dispatch_research_tool,
    run_research,
)
from paper_copilot.knowledge.embeddings_store import ChunkRow, EmbeddingsStore
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.session import FinalOutput, SessionStore, ToolResult, ToolUse

DIM = 4


def _payload(title: str = "Paper A", year: int = 2024) -> dict[str, Any]:
    return {
        "meta": {
            "title": title,
            "authors": ["A"],
            "arxiv_id": None,
            "year": year,
            "venue": "ICLR",
        },
        "contributions": [
            {
                "claim": "introduces sparse attention",
                "type": "novel_method",
                "evidence_type": "explicit_claim",
            }
        ],
        "methods": [
            {
                "name": "Sparse Attention",
                "description": "keeps top-k attention edges",
                "key_formula": None,
                "novelty_vs_prior": "drops dense softmax attention",
                "is_novel_to_this_paper": True,
            }
        ],
        "experiments": [],
        "limitations": [],
        "cross_paper_links": [],
    }


def _chunk(paper_id: str, text: str) -> ChunkRow:
    return ChunkRow(
        chunk_id=0,
        paper_id=paper_id,
        ord=0,
        section="Abstract",
        page_start=1,
        page_end=1,
        text=text,
    )


def test_dispatch_research_tools_list_search_and_inspect(tmp_path: Path) -> None:
    with (
        FieldsStore.open(tmp_path / "fields.db") as fs,
        EmbeddingsStore.open(tmp_path / "embeddings.db", dim=DIM) as es,
    ):
        fs.upsert("paperA", _payload(), datetime.now(UTC).isoformat())
        es.replace_paper(
            "paperA",
            [_chunk("paperA", "sparse attention over visual tokens")],
            np.array([[1, 0, 0, 0]], dtype=np.float32),
        )
        context = ResearchToolContext(
            fields_store=fs,
            embeddings_store=es,
            encode_query=lambda _query: np.array([1, 0, 0, 0], dtype=np.float32),
        )

        listed = dispatch_research_tool(
            ToolUseRequest(id="t1", name="list_papers", input={"limit": 5}),
            context,
        )
        assert listed.is_error is False
        assert json.loads(listed.output)["papers"][0]["paper_id"] == "paperA"

        searched = dispatch_research_tool(
            ToolUseRequest(
                id="t2",
                name="search_library",
                input={"query": "sparse attention", "k": 1},
            ),
            context,
        )
        assert searched.is_error is False
        assert json.loads(searched.output)["results"][0]["paper_id"] == "paperA"

        inspected = dispatch_research_tool(
            ToolUseRequest(
                id="t3",
                name="inspect_paper",
                input={"paper_id": "paperA", "fields": ["meta", "methods"]},
            ),
            context,
        )
        data = json.loads(inspected.output)
        assert data["meta"]["title"] == "Paper A"
        assert data["methods"][0]["name"] == "Sparse Attention"


def test_dispatch_list_pdfs_reports_candidate_ids(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    pdf_path = pdf_dir / "paper.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        context = ResearchToolContext(fields_store=fs, pdf_dir=pdf_dir)
        result = dispatch_research_tool(
            ToolUseRequest(id="t1", name="list_pdfs", input={"limit": 3}),
            context,
        )

    data = json.loads(result.output)
    assert result.is_error is False
    assert data["pdfs"][0]["filename"] == "paper.pdf"
    assert len(data["pdfs"][0]["paper_id"]) == 12


def test_run_research_uses_tool_loop_and_records_trace(tmp_path: Path) -> None:
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        fs.upsert("paperA", _payload(), datetime.now(UTC).isoformat())
        context = ResearchToolContext(fields_store=fs)
        llm = MockLLM(
            [
                MockResponse(
                    content=[
                        ToolUseBlock(
                            id="inspect1",
                            name="inspect_paper",
                            input={"paper_id": "paperA", "fields": ["meta"]},
                        )
                    ],
                    stop_reason="tool_use",
                    usage={"input_tokens": 10, "output_tokens": 4},
                ),
                MockResponse(
                    content=[TextBlock(text="## Findings\n\npaperA is relevant.")],
                    stop_reason="end_turn",
                    usage={"input_tokens": 20, "output_tokens": 8},
                ),
            ]
        )

        run = asyncio.run(
            run_research(
                topic="sparse attention",
                llm=llm,
                context=context,
                root=tmp_path,
                max_turns=4,
                max_budget_cny=1.0,
            )
        )

    assert run.termination_reason == "end_turn"
    assert "paperA is relevant" in run.report_markdown
    assert run.cost.input_tokens == 30

    paper_id = run.session_path.parent.name
    entries = SessionStore.load(paper_id, root=tmp_path).read_all()
    assert any(isinstance(e, ToolUse) and e.name == "inspect_paper" for e in entries)
    assert any(isinstance(e, ToolResult) and e.is_error is False for e in entries)
    final = next(e for e in reversed(entries) if isinstance(e, FinalOutput))
    assert final.payload["topic"] == "sparse attention"
    assert final.payload["termination_reason"] == "end_turn"
