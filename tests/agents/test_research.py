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
from paper_copilot.knowledge.graph_store import append_links
from paper_copilot.schemas import CrossPaperLink
from paper_copilot.session import FinalOutput, SessionStore, ToolResult, ToolUse

DIM = 4


def _payload(
    title: str = "Paper A",
    year: int = 2024,
    method_name: str = "Sparse Attention",
    cross_paper_links: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
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
                "name": method_name,
                "description": "keeps top-k attention edges",
                "key_formula": None,
                "novelty_vs_prior": "drops dense softmax attention",
                "is_novel_to_this_paper": True,
            }
        ],
        "experiments": [],
        "limitations": [],
        "cross_paper_links": cross_paper_links or [],
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


def test_dispatch_compare_papers_returns_structured_alignment(tmp_path: Path) -> None:
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        now = datetime.now(UTC).isoformat()
        fs.upsert("paperA", _payload(method_name="Shared Method"), now)
        fs.upsert("paperB", _payload("Paper B", 2023, method_name="Shared Method"), now)
        context = ResearchToolContext(fields_store=fs)
        result = dispatch_research_tool(
            ToolUseRequest(
                id="t1",
                name="compare_papers",
                input={"paper_id_a": "paperA", "paper_id_b": "paperB"},
            ),
            context,
        )

    data = json.loads(result.output)
    assert result.is_error is False
    assert data["a"]["paper_id"] == "paperA"
    assert data["b"]["paper_id"] == "paperB"
    assert data["methods_aligned"][0]["key"] == "shared method"
    assert data["methods_aligned"][0]["a"]["name"] == "Shared Method"
    assert data["methods_aligned"][0]["b"]["name"] == "Shared Method"
    assert data["paper_budget"]["touched_count"] == 2


def test_dispatch_find_related_papers_uses_field_links(tmp_path: Path) -> None:
    link_to_b = {
        "related_paper_id": "paperB",
        "related_title": "Paper B",
        "relation_type": "builds_on",
        "explanation": "extends the sparse attention mechanism",
    }
    link_to_a = {
        "related_paper_id": "paperA",
        "related_title": "Paper A",
        "relation_type": "compares_against",
        "explanation": "uses Paper A as the prior sparse-attention baseline",
    }
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        now = datetime.now(UTC).isoformat()
        fs.upsert("paperA", _payload("Paper A", cross_paper_links=[link_to_b]), now)
        fs.upsert("paperB", _payload("Paper B", 2023), now)
        fs.upsert("paperC", _payload("Paper C", 2022, cross_paper_links=[link_to_a]), now)
        context = ResearchToolContext(fields_store=fs, max_papers=3)
        result = dispatch_research_tool(
            ToolUseRequest(
                id="t1",
                name="find_related_papers",
                input={"paper_id": "paperA", "k": 5},
            ),
            context,
        )

    data = json.loads(result.output)
    assert result.is_error is False
    assert data["paper_id"] == "paperA"
    assert data["returned"] == 2
    assert [p["candidate_paper_id"] for p in data["related_papers"]] == ["paperB", "paperC"]
    assert [p["direction"] for p in data["related_papers"]] == ["outgoing", "incoming"]
    assert data["related_papers"][0]["link_source"] == "fields"
    assert data["paper_budget"]["touched_paper_ids"] == ["paperA", "paperB", "paperC"]


def test_dispatch_find_related_papers_reads_graph_log(tmp_path: Path) -> None:
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        now = datetime.now(UTC).isoformat()
        fs.upsert("paperA", _payload("Paper A"), now)
        fs.upsert("paperB", _payload("Paper B", 2023), now)
        append_links(
            "paperA",
            [
                CrossPaperLink(
                    related_paper_id="paperB",
                    related_title="Paper B from graph",
                    relation_type="shares_method",
                    explanation="both use local sparse attention",
                )
            ],
            root=tmp_path,
            clock=lambda: "2026-05-18T00:00:00+00:00",
        )
        context = ResearchToolContext(fields_store=fs, root=tmp_path, max_papers=2)
        result = dispatch_research_tool(
            ToolUseRequest(
                id="t1",
                name="find_related_papers",
                input={"paper_id": "paperA", "k": 1},
            ),
            context,
        )

    data = json.loads(result.output)
    assert result.is_error is False
    assert data["related_papers"][0]["candidate_paper_id"] == "paperB"
    assert data["related_papers"][0]["relation_type"] == "shares_method"
    assert data["related_papers"][0]["link_source"] == "graph"
    assert data["related_papers"][0]["indexed_at"] == "2026-05-18T00:00:00+00:00"


def test_dispatch_enforces_max_papers_across_inspect_and_compare(tmp_path: Path) -> None:
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        now = datetime.now(UTC).isoformat()
        fs.upsert("paperA", _payload("Paper A"), now)
        fs.upsert("paperB", _payload("Paper B"), now)
        fs.upsert("paperC", _payload("Paper C"), now)
        context = ResearchToolContext(fields_store=fs, max_papers=2)

        first = dispatch_research_tool(
            ToolUseRequest(id="t1", name="inspect_paper", input={"paper_id": "paperA"}),
            context,
        )
        repeat = dispatch_research_tool(
            ToolUseRequest(id="t2", name="inspect_paper", input={"paper_id": "paperA"}),
            context,
        )
        second = dispatch_research_tool(
            ToolUseRequest(
                id="t3",
                name="compare_papers",
                input={"paper_id_a": "paperA", "paper_id_b": "paperB"},
            ),
            context,
        )
        over_limit = dispatch_research_tool(
            ToolUseRequest(id="t4", name="inspect_paper", input={"paper_id": "paperC"}),
            context,
        )

    assert first.is_error is False
    assert repeat.is_error is False
    assert second.is_error is False
    assert over_limit.is_error is True
    assert "max_papers exceeded" in json.loads(over_limit.output)["error"]
    assert context.touched_paper_ids == {"paperA", "paperB"}


def test_dispatch_read_paper_reports_existing_index_entry(tmp_path: Path) -> None:
    pdir = tmp_path / "papers" / "paperA"
    pdir.mkdir(parents=True)
    (pdir / "session.jsonl").write_text("", encoding="utf-8")
    (pdir / "report.md").write_text("# Report", encoding="utf-8")
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        fs.upsert("paperA", _payload("Paper A"), datetime.now(UTC).isoformat())
        context = ResearchToolContext(fields_store=fs, root=tmp_path, max_papers=1)
        result = dispatch_research_tool(
            ToolUseRequest(id="t1", name="read_paper", input={"paper_id": "paperA"}),
            context,
        )

    data = json.loads(result.output)
    assert result.is_error is False
    assert data["status"] == "already_read"
    assert data["paper_id"] == "paperA"
    assert data["report_exists"] is True
    assert data["session_exists"] is True
    assert data["paper_budget"]["touched_paper_ids"] == ["paperA"]


def test_dispatch_read_paper_needs_user_action_for_unread_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        context = ResearchToolContext(fields_store=fs, root=tmp_path, max_papers=1)
        result = dispatch_research_tool(
            ToolUseRequest(
                id="t1",
                name="read_paper",
                input={"pdf_path": str(pdf_path)},
            ),
            context,
        )

    data = json.loads(result.output)
    assert result.is_error is False
    assert data["status"] == "needs_user_action"
    assert data["paper_id"] in context.touched_paper_ids
    assert "paper-copilot read" in data["next_command"]


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
    assert run.termination_summary.reason == "end_turn"
    assert run.termination_summary.events_count == len(run.events)
    assert run.termination_summary.paper_budget["touched_paper_ids"] == ["paperA"]
    assert run.termination_summary.last_tool_error is None
    assert "paperA is relevant" in run.report_markdown
    assert run.cost.input_tokens == 30

    paper_id = run.session_path.parent.name
    entries = SessionStore.load(paper_id, root=tmp_path).read_all()
    assert any(isinstance(e, ToolUse) and e.name == "inspect_paper" for e in entries)
    assert any(isinstance(e, ToolResult) and e.is_error is False for e in entries)
    final = next(e for e in reversed(entries) if isinstance(e, FinalOutput))
    assert final.payload["topic"] == "sparse attention"
    assert final.payload["termination_reason"] == "end_turn"
    assert final.payload["termination_summary"]["reason"] == "end_turn"
    assert final.payload["termination_summary"]["paper_budget"]["touched_count"] == 1


def test_run_research_summary_records_last_tool_error(tmp_path: Path) -> None:
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        context = ResearchToolContext(fields_store=fs)
        llm = MockLLM(
            [
                MockResponse(
                    content=[
                        ToolUseBlock(
                            id="missing1",
                            name="inspect_paper",
                            input={"paper_id": "missing"},
                        )
                    ],
                    stop_reason="tool_use",
                    usage={"input_tokens": 10, "output_tokens": 4},
                ),
                MockResponse(
                    content=[TextBlock(text="## Gaps\n\nmissing is not indexed.")],
                    stop_reason="end_turn",
                    usage={"input_tokens": 20, "output_tokens": 8},
                ),
            ]
        )

        run = asyncio.run(
            run_research(
                topic="missing paper",
                llm=llm,
                context=context,
                root=tmp_path,
                max_turns=4,
                max_budget_cny=1.0,
            )
        )

    assert run.termination_summary.last_tool_error is not None
    assert run.termination_summary.last_tool_error["tool_use_id"] == "missing1"
    assert "paper_id not found" in run.termination_summary.last_tool_error["output"]
