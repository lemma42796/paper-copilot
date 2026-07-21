from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from paper_copilot.agents.loop import ToolUseRequest
from paper_copilot.agents.mock_llm import MockLLM, MockResponse, TextBlock, ToolUseBlock
from paper_copilot.agents.paper_copilot import (
    PaperCopilotContext,
    dispatch_paper_copilot_tool,
    paper_copilot_tools,
    run_paper_copilot,
)
from paper_copilot.knowledge.embeddings_store import ChunkRow, EmbeddingsStore
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.knowledge.graph_store import append_links
from paper_copilot.schemas import CrossPaperLink
from paper_copilot.session import (
    FinalOutput,
    Message,
    SessionStore,
    SystemMessage,
    ToolResult,
    ToolUse,
)
from paper_copilot.session.paths import compute_paper_id

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


def _chunk(paper_id: str, text: str, *, ord_: int = 0) -> ChunkRow:
    return ChunkRow(
        chunk_id=0,
        paper_id=paper_id,
        ord=ord_,
        section="Abstract",
        page_start=1,
        page_end=1,
        text=text,
    )


def _system_text(system: str | list[dict[str, Any]] | None) -> str:
    assert system is not None
    if isinstance(system, str):
        return system
    return "\n".join(str(block["text"]) for block in system)


def _runtime_payload(messages: list[dict[str, Any]]) -> dict[str, Any]:
    content = messages[0]["content"]
    assert isinstance(content, list)
    runtime_text = content[0]["text"]
    assert isinstance(runtime_text, str)
    prefix = "<runtime_context>\n"
    suffix = "\n</runtime_context>"
    assert runtime_text.startswith(prefix)
    assert runtime_text.endswith(suffix)
    payload = json.loads(runtime_text.removeprefix(prefix).removesuffix(suffix))
    assert isinstance(payload, dict)
    return payload


def test_dispatch_paper_copilot_tools_browse_search_and_query(tmp_path: Path) -> None:
    with (
        FieldsStore.open(tmp_path / "fields.db") as fs,
        EmbeddingsStore.open(tmp_path / "embeddings.db", dim=DIM) as es,
    ):
        fs.upsert("paperA", _payload(), datetime.now(UTC).isoformat())
        es.replace_paper(
            "paperA",
            [
                _chunk("paperA", "sparse attention over visual tokens", ord_=0),
                _chunk("paperA", "top-k attention keeps salient edges", ord_=1),
            ],
            np.array([[1, 0, 0, 0], [1, 0.1, 0, 0]], dtype=np.float32),
        )
        context = PaperCopilotContext(
            fields_store=fs,
            embeddings_store=es,
            encode_query=lambda _query: np.array([1, 0, 0, 0], dtype=np.float32),
        )

        browsed = dispatch_paper_copilot_tool(
            ToolUseRequest(id="t1", name="search_papers", input={"limit": 5}),
            context,
        )
        assert browsed.is_error is False
        assert json.loads(browsed.output)["papers"][0]["paper_id"] == "paperA"

        searched = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="t2",
                name="search_papers",
                input={"query": "sparse attention", "limit": 1},
            ),
            context,
        )
        assert searched.is_error is False
        search_data = json.loads(searched.output)
        assert search_data["citation_format"] == "[paper_id:chunks[chunk_id]]"
        assert search_data["papers"][0]["paper_id"] == "paperA"
        assert search_data["papers"][0]["match_kind"] == "hybrid"
        evidence = search_data["papers"][0]["evidence"]
        assert evidence[0]["paper_id"] == "paperA"
        assert evidence[0]["source_kind"] == "pdf_text"
        assert evidence[0]["section"] == "Abstract"
        assert evidence[0]["page_start"] == 1
        assert evidence[0]["score_kind"] == "rrf"
        assert evidence[0]["vector_rank"] == 1
        assert evidence[0]["bm25_rank"] == 1
        assert evidence[0]["citation_ref"].startswith("[paperA:chunks[")
        assert evidence[1]["paper_id"] == "paperA"
        assert evidence[1]["chunk_rank"] == 2
        assert search_data["papers"][0]["citation_ref"] == evidence[0]["citation_ref"]

        queried = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="t-query",
                name="query_paper",
                input={
                    "paper": {"paper_id": "paperA"},
                    "question": "How does top-k attention work?",
                    "evidence_limit": 2,
                },
            ),
            context,
        )
        query_data = json.loads(queried.output)
        assert queried.is_error is False
        assert query_data["status"] == "ok"
        assert query_data["paper"]["methods"][0]["name"] == "Sparse Attention"
        assert len(query_data["evidence"]) == 2
        assert {item["paper_id"] for item in query_data["evidence"]} == {"paperA"}


def test_paper_tool_schemas_expose_locator_and_query_contract() -> None:
    tools = {tool["name"]: tool for tool in paper_copilot_tools()}

    assert "search_papers" in tools
    assert {"list_papers", "list_pdfs", "search_library"}.isdisjoint(tools)
    search_properties = tools["search_papers"]["input_schema"]["properties"]
    assert set(search_properties) == {"query", "scope", "filters", "limit"}
    search_schema_text = json.dumps(tools["search_papers"]["input_schema"])
    assert "max_chunks_per_paper" not in search_schema_text
    assert "evidence_pool_per_paper" not in search_schema_text
    assert "inspect_paper" not in tools
    assert "query_paper" in tools
    assert tools["read_paper"]["input_schema"]["required"] == ["paper"]
    locator = tools["read_paper"]["input_schema"]["$defs"]["_PaperLocatorInput"]
    assert len(locator["anyOf"]) == 3
    locator_defs = tools["read_paper"]["input_schema"]["$defs"]
    required_options = {
        tuple(locator_defs[option["$ref"].rsplit("/", maxsplit=1)[-1]]["required"])
        for option in locator["anyOf"]
    }
    assert required_options == {("paper_id",), ("title",), ("pdf_path",)}
    assert "Ambiguous titles" in tools["read_paper"]["description"]
    assert "Search is restricted to the selected paper" in tools["query_paper"]["description"]
    compare_properties = tools["compare_papers"]["input_schema"]["properties"]
    assert set(compare_properties) == {"papers", "aspects"}
    related_properties = tools["find_related_papers"]["input_schema"]["properties"]
    assert set(related_properties) == {"paper", "direction", "relation_types", "limit"}


def test_dispatch_rejects_string_numeric_inputs(tmp_path: Path) -> None:
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        context = PaperCopilotContext(fields_store=fs)
        result = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="t1",
                name="search_papers",
                input={"filters": {"year_from": "2017"}},
            ),
            context,
        )

    assert result.is_error is True
    assert "valid integer" in json.loads(result.output)["error"]


def test_search_papers_filters_dataset_and_baseline(tmp_path: Path) -> None:
    matching = _payload("Matching Paper", 2024)
    matching["experiments"] = [
        {
            "dataset": "Market-1501",
            "metric": "mAP",
            "value": "90.1",
            "unit": "%",
            "comparison_baseline": "ResNet-50",
            "raw": "ResNet-50 baseline on Market-1501",
        }
    ]
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        now = datetime.now(UTC).isoformat()
        fs.upsert("paperA", matching, now)
        fs.upsert("paperB", _payload("Other Paper", 2019), now)
        context = PaperCopilotContext(fields_store=fs)
        result = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="t1",
                name="search_papers",
                input={
                    "filters": {
                        "year_from": 2020,
                        "dataset": "market 1501",
                        "baseline": "resnet-50",
                    }
                },
            ),
            context,
        )
    data = json.loads(result.output)
    assert result.is_error is False
    assert data["status"] == "ok"
    assert [paper["paper_id"] for paper in data["papers"]] == ["paperA"]
    assert data["papers"][0]["match_kind"] == "structured_filter"


def test_dispatch_compare_papers_returns_structured_alignment(tmp_path: Path) -> None:
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        now = datetime.now(UTC).isoformat()
        fs.upsert("paperA", _payload(method_name="Shared Method"), now)
        fs.upsert("paperB", _payload("Paper B", 2023, method_name="Shared Method"), now)
        context = PaperCopilotContext(fields_store=fs)
        result = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="t1",
                name="compare_papers",
                input={
                    "papers": [
                        {"paper_id": "paperA"},
                        {"title": "Paper B"},
                    ]
                },
            ),
            context,
        )

    data = json.loads(result.output)
    assert result.is_error is False
    assert data["status"] == "ok"
    assert [paper["paper_id"] for paper in data["papers"]] == ["paperA", "paperB"]
    methods = data["pairwise_alignment"]["methods_aligned"]
    assert methods[0]["key"] == "shared method"
    assert methods[0]["a"]["name"] == "Shared Method"
    assert methods[0]["b"]["name"] == "Shared Method"
    assert data["shared_exact_matches"]["method_names"] == ["Shared Method"]
    assert data["paper_budget"]["touched_count"] == 2


def test_compare_papers_supports_three_papers_and_selected_aspects(tmp_path: Path) -> None:
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        now = datetime.now(UTC).isoformat()
        for paper_id, title in [
            ("paperA", "Paper A"),
            ("paperB", "Paper B"),
            ("paperC", "Paper C"),
        ]:
            fs.upsert(paper_id, _payload(title, method_name="Shared Method"), now)
        context = PaperCopilotContext(fields_store=fs, max_papers=3)
        result = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="t1",
                name="compare_papers",
                input={
                    "papers": [
                        {"paper_id": "paperA"},
                        {"paper_id": "paperB"},
                        {"paper_id": "paperC"},
                    ],
                    "aspects": ["methods"],
                },
            ),
            context,
        )

    data = json.loads(result.output)
    assert result.is_error is False
    assert len(data["comparison"]) == 3
    assert set(data["comparison"][0]) == {"paper_id", "meta", "methods"}
    assert data["shared_exact_matches"] == {"method_names": ["Shared Method"]}
    assert "pairwise_alignment" not in data


def test_compare_papers_returns_resolution_issues_without_spending_budget(
    tmp_path: Path,
) -> None:
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        now = datetime.now(UTC).isoformat()
        fs.upsert("paperA", _payload("Shared Paper"), now)
        fs.upsert("paperB", _payload("shared-paper", 2023), now)
        fs.upsert("paperC", _payload("Paper C", 2022), now)
        context = PaperCopilotContext(fields_store=fs, max_papers=2)
        result = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="t1",
                name="compare_papers",
                input={
                    "papers": [
                        {"title": "Shared Paper"},
                        {"paper_id": "paperC"},
                    ]
                },
            ),
            context,
        )

    data = json.loads(result.output)
    assert result.is_error is False
    assert data["status"] == "needs_resolution"
    assert data["issues"][0]["status"] == "ambiguous"
    assert [candidate["paper_id"] for candidate in data["issues"][0]["candidates"]] == [
        "paperA",
        "paperB",
    ]
    assert context.touched_paper_ids == set()


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
        context = PaperCopilotContext(fields_store=fs, max_papers=3)
        result = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="t1",
                name="find_related_papers",
                input={"paper": {"title": "Paper A"}, "limit": 5},
            ),
            context,
        )
        filtered = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="t2",
                name="find_related_papers",
                input={
                    "paper": {"paper_id": "paperA"},
                    "direction": "incoming",
                    "relation_types": ["compares_against"],
                },
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
    assert data["paper_budget"]["touched_paper_ids"] == []
    filtered_data = json.loads(filtered.output)
    assert [paper["candidate_paper_id"] for paper in filtered_data["related_papers"]] == [
        "paperC"
    ]


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
        context = PaperCopilotContext(fields_store=fs, root=tmp_path, max_papers=2)
        result = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="t1",
                name="find_related_papers",
                input={"paper": {"paper_id": "paperA"}, "limit": 1},
            ),
            context,
        )

    data = json.loads(result.output)
    assert result.is_error is False
    assert data["related_papers"][0]["candidate_paper_id"] == "paperB"
    assert data["related_papers"][0]["relation_type"] == "shares_method"
    assert data["related_papers"][0]["link_source"] == "graph"
    assert data["related_papers"][0]["indexed_at"] == "2026-05-18T00:00:00+00:00"


def test_dispatch_enforces_max_papers_across_query_and_compare(tmp_path: Path) -> None:
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        now = datetime.now(UTC).isoformat()
        fs.upsert("paperA", _payload("Paper A"), now)
        fs.upsert("paperB", _payload("Paper B"), now)
        fs.upsert("paperC", _payload("Paper C"), now)
        context = PaperCopilotContext(fields_store=fs, max_papers=2)

        first = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="t1",
                name="query_paper",
                input={
                    "paper": {"paper_id": "paperA"},
                    "question": "What is the method?",
                },
            ),
            context,
        )
        repeat = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="t2",
                name="query_paper",
                input={
                    "paper": {"paper_id": "paperA"},
                    "question": "What is the method?",
                },
            ),
            context,
        )
        second = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="t3",
                name="compare_papers",
                input={
                    "papers": [
                        {"paper_id": "paperA"},
                        {"paper_id": "paperB"},
                    ]
                },
            ),
            context,
        )
        over_limit = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="t4",
                name="query_paper",
                input={
                    "paper": {"paper_id": "paperC"},
                    "question": "What is the method?",
                },
            ),
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
        context = PaperCopilotContext(fields_store=fs, root=tmp_path, max_papers=1)
        result = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="t1",
                name="read_paper",
                input={"paper": {"title": "Paper A"}},
            ),
            context,
        )

    data = json.loads(result.output)
    assert result.is_error is False
    assert data["status"] == "already_read"
    assert data["paper_id"] == "paperA"
    assert data["report_exists"] is True
    assert data["session_exists"] is True
    assert data["paper"]["methods"][0]["name"] == "Sparse Attention"
    assert data["paper"]["suggested_citations"][0]["field"] == "meta.title"
    assert data["can_query_same_paper"] is True
    assert data["paper_budget"]["touched_paper_ids"] == ["paperA"]


def test_dispatch_read_paper_needs_user_action_for_unread_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        context = PaperCopilotContext(
            fields_store=fs,
            pdf_dir=tmp_path,
            root=tmp_path,
            max_papers=1,
        )
        result = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="t1",
                name="read_paper",
                input={"paper": {"pdf_path": str(pdf_path)}},
            ),
            context,
        )

    data = json.loads(result.output)
    assert result.is_error is False
    assert data["status"] == "needs_user_action"
    assert data["can_query_same_paper"] is False
    assert data["paper_id"] in context.touched_paper_ids
    assert data["pdf_path"] == str(pdf_path)


def test_query_paper_returns_ambiguous_title_candidates(tmp_path: Path) -> None:
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        now = datetime.now(UTC).isoformat()
        fs.upsert("paperA", _payload("Shared Paper"), now)
        fs.upsert("paperB", _payload("shared-paper", 2023), now)
        context = PaperCopilotContext(fields_store=fs)
        result = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="t1",
                name="query_paper",
                input={
                    "paper": {"title": "Shared Paper"},
                    "question": "What is the method?",
                },
            ),
            context,
        )

    data = json.loads(result.output)
    assert result.is_error is False
    assert data["status"] == "ambiguous"
    assert [candidate["paper_id"] for candidate in data["candidates"]] == [
        "paperA",
        "paperB",
    ]
    assert context.touched_paper_ids == set()


def test_query_paper_returns_structured_fields_when_rag_is_unavailable(
    tmp_path: Path,
) -> None:
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        fs.upsert("paperA", _payload("Paper A"), datetime.now(UTC).isoformat())
        context = PaperCopilotContext(fields_store=fs)
        result = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="t1",
                name="query_paper",
                input={
                    "paper": {"paper_id": "paperA"},
                    "question": "What is the main contribution?",
                },
            ),
            context,
        )

    data = json.loads(result.output)
    assert result.is_error is False
    assert data["status"] == "structured_only"
    assert data["paper"]["contributions"][0]["claim"] == "introduces sparse attention"
    assert data["evidence"] == []
    assert "embedding index is not configured" in data["gaps"][0]
    assert context.touched_paper_ids == {"paperA"}


def test_query_paper_requests_read_for_unindexed_local_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "Sparse-Attention.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        context = PaperCopilotContext(fields_store=fs, pdf_dir=tmp_path)
        result = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="t1",
                name="query_paper",
                input={
                    "paper": {"title": "sparse attention"},
                    "question": "What is the main contribution?",
                },
            ),
            context,
        )

    data = json.loads(result.output)
    assert result.is_error is False
    assert data["status"] == "needs_read"
    assert data["paper"]["pdf_path"] == str(pdf_path)
    assert data["next_tool"] == {
        "name": "read_paper",
        "input": {"paper": {"pdf_path": str(pdf_path)}},
    }
    assert context.touched_paper_ids == set()


def test_search_papers_local_scope_reports_pdf_candidates(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    pdf_path = pdf_dir / "paper.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        context = PaperCopilotContext(fields_store=fs, pdf_dir=pdf_dir)
        result = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="t1",
                name="search_papers",
                input={"scope": "local", "limit": 3},
            ),
            context,
        )

    data = json.loads(result.output)
    assert result.is_error is False
    assert data["papers"][0]["relative_path"] == "paper.pdf"
    assert data["papers"][0]["indexed"] is False
    assert len(data["papers"][0]["paper_id"]) == 12


def test_dispatch_composer_plan_enforces_pool_workflow(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    baseline_pdf = pdf_dir / "baseline.pdf"
    module_pdf = pdf_dir / "module.pdf"
    baseline_pdf.write_bytes(b"%PDF fake baseline")
    module_pdf.write_bytes(b"%PDF fake module")
    baseline_id = compute_paper_id(baseline_pdf)
    module_id = compute_paper_id(module_pdf)

    with (
        FieldsStore.open(tmp_path / "fields.db") as fs,
        EmbeddingsStore.open(tmp_path / "embeddings.db", dim=DIM) as es,
    ):
        fs.upsert(
            baseline_id,
            _payload("Baseline Paper", method_name="Strong Baseline"),
            datetime.now(UTC).isoformat(),
        )
        fs.upsert(
            module_id,
            _payload("Module Paper", method_name="Compatible Module"),
            datetime.now(UTC).isoformat(),
        )
        es.replace_paper(
            baseline_id,
            [_chunk(baseline_id, "strong reproducible baseline", ord_=0)],
            np.array([[1, 0, 0, 0]], dtype=np.float32),
        )
        es.replace_paper(
            module_id,
            [_chunk(module_id, "compatible module trick", ord_=0)],
            np.array([[1, 0.1, 0, 0]], dtype=np.float32),
        )
        context = PaperCopilotContext(
            fields_store=fs,
            embeddings_store=es,
            encode_query=lambda _query: np.array([1, 0, 0, 0], dtype=np.float32),
            pdf_dir=pdf_dir,
        )

        blocked = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="blocked",
                name="search_composer_candidates",
                input={"role": "baseline", "query": "baseline", "k": 2},
            ),
            context,
        )
        listed = dispatch_paper_copilot_tool(
            ToolUseRequest(id="list", name="list_composer_library", input={}),
            context,
        )
        baseline_search = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="baseline",
                name="search_composer_candidates",
                input={"role": "baseline", "query": "baseline", "k": 2},
            ),
            context,
        )
        premature_module_search = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="module-early",
                name="search_composer_candidates",
                input={"role": "module", "query": "module", "k": 2},
            ),
            context,
        )
        dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="query-baseline",
                name="query_paper",
                input={
                    "paper": {"paper_id": baseline_id},
                    "question": "What makes this a strong baseline?",
                },
            ),
            context,
        )
        selected = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="select-baseline",
                name="update_composer_plan",
                input={
                    "action": "select_baseline",
                    "paper_id": baseline_id,
                    "rationale": "Strong reproducible baseline in CCF A.",
                    "evidence_refs": [f"[{baseline_id}:methods[0]]"],
                },
            ),
            context,
        )
        premature_fallback = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="fallback-early",
                name="search_composer_candidates",
                input={
                    "role": "module",
                    "pool": "ccf_b",
                    "query": "module",
                    "rejected_ccf_a_modules": [module_id],
                    "rejection_reason": "CCF A modules are incompatible.",
                },
            ),
            context,
        )
        module_search = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="module",
                name="search_composer_candidates",
                input={"role": "module", "query": "module", "k": 2},
            ),
            context,
        )
        dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="query-module",
                name="query_paper",
                input={
                    "paper": {"paper_id": module_id},
                    "question": "How can this module attach to the baseline?",
                },
            ),
            context,
        )
        accepted = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="accept-module",
                name="update_composer_plan",
                input={
                    "action": "accept_module",
                    "paper_id": module_id,
                    "pool": "ccf_a",
                    "rationale": "The module can attach to the baseline encoder.",
                    "evidence_refs": [f"[{module_id}:methods[0]]"],
                    "attachment_point": "baseline encoder",
                    "compatibility_notes": "Both methods operate on token features.",
                },
            ),
            context,
        )
        duplicate_module = dispatch_paper_copilot_tool(
            ToolUseRequest(
                id="accept-duplicate-module",
                name="update_composer_plan",
                input={
                    "action": "accept_module",
                    "paper_id": module_id,
                    "pool": "ccf_a",
                    "rationale": "Trying to reuse the same paper for another module.",
                    "evidence_refs": [f"[{module_id}:methods[0]]"],
                    "attachment_point": "baseline classifier",
                    "compatibility_notes": "This should be rejected as a duplicate.",
                },
            ),
            context,
        )

    assert blocked.is_error is True
    assert "list_composer_library" in json.loads(blocked.output)["error"]
    assert listed.is_error is False
    assert json.loads(listed.output)["composer_plan"]["current_step"] == (
        "search_ccf_a_baseline"
    )
    assert baseline_search.is_error is False
    assert json.loads(baseline_search.output)["composer_plan"]["current_step"] == (
        "query_and_select_baseline"
    )
    assert premature_module_search.is_error is True
    premature_module_error = json.loads(premature_module_search.output)["error"]
    assert "select a CCF A baseline" in premature_module_error
    assert selected.is_error is False
    assert premature_fallback.is_error is True
    assert "close ccf_a" in json.loads(premature_fallback.output)["error"]
    assert module_search.is_error is False
    assert accepted.is_error is False
    assert duplicate_module.is_error is True
    assert "at most one module" in json.loads(duplicate_module.output)["error"]
    accepted_payload = json.loads(accepted.output)
    assert accepted_payload["composer_plan"]["report_ready"] is False
    assert accepted_payload["composer_plan"]["current_step"] == (
        "check_or_close_ccf_a_modules"
    )


def test_run_paper_copilot_separates_stable_system_and_runtime_context(
    tmp_path: Path,
) -> None:
    pdf_dir = tmp_path / "papers&private"
    pdf_dir.mkdir()
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        first_llm = MockLLM(
            [MockResponse(content=[TextBlock(text="hello")], stop_reason="end_turn")]
        )
        second_llm = MockLLM(
            [MockResponse(content=[TextBlock(text="hello again")], stop_reason="end_turn")]
        )

        asyncio.run(
            run_paper_copilot(
                prompt="first prompt",
                llm=first_llm,
                context=PaperCopilotContext(fields_store=fs, max_papers=1),
                root=tmp_path,
            )
        )
        asyncio.run(
            run_paper_copilot(
                prompt="second prompt",
                llm=second_llm,
                context=PaperCopilotContext(
                    fields_store=fs,
                    pdf_dir=pdf_dir,
                    max_papers=3,
                    touched_paper_ids={"paperA"},
                ),
                root=tmp_path,
            )
        )

    first_call = first_llm.calls[0]
    second_call = second_llm.calls[0]
    assert _system_text(first_call.system) == _system_text(second_call.system)
    assert isinstance(first_call.system, list)
    assert first_call.system[-1]["cache_control"] == {"type": "ephemeral"}
    assert first_call.tools[-1]["cache_control"] == {"type": "ephemeral"}

    first_runtime = _runtime_payload(first_call.messages)
    second_runtime = _runtime_payload(second_call.messages)
    assert first_runtime == {
        "pdf_library_available": False,
        "paper_budget": {
            "max_papers": 1,
            "touched_count": 0,
            "remaining_count": 1,
            "touched_paper_ids": [],
        },
    }
    assert second_runtime == {
        "pdf_library_available": True,
        "paper_budget": {
            "max_papers": 3,
            "touched_count": 1,
            "remaining_count": 2,
            "touched_paper_ids": ["paperA"],
        },
    }
    assert str(pdf_dir) not in json.dumps(second_call.messages, ensure_ascii=False)
    first_content = first_call.messages[0]["content"]
    second_content = second_call.messages[0]["content"]
    assert isinstance(first_content, list)
    assert isinstance(second_content, list)
    assert first_content[1] == {"type": "text", "text": "first prompt"}
    assert second_content[1] == {"type": "text", "text": "second prompt"}


def test_run_paper_copilot_uses_tool_loop_and_records_trace(tmp_path: Path) -> None:
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        fs.upsert("paperA", _payload(), datetime.now(UTC).isoformat())
        context = PaperCopilotContext(fields_store=fs)
        llm = MockLLM(
            [
                MockResponse(
                    content=[
                        ToolUseBlock(
                            id="query1",
                            name="query_paper",
                            input={
                                "paper": {"paper_id": "paperA"},
                                "question": "What is this paper about?",
                            },
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
            run_paper_copilot(
                prompt="sparse attention",
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
    assert run.tool_names == ("query_paper",)
    assert run.composer_used is False

    paper_id = run.session_path.parent.name
    entries = SessionStore.load(paper_id, root=tmp_path).read_all()
    assert any(isinstance(e, ToolUse) and e.name == "query_paper" for e in entries)
    assert any(isinstance(e, ToolResult) and e.is_error is False for e in entries)
    final = next(e for e in reversed(entries) if isinstance(e, FinalOutput))
    assert final.payload["prompt"] == "sparse attention"
    assert final.payload["tool_names"] == ["query_paper"]
    assert "request_route" not in final.payload
    assert final.payload["termination_reason"] == "end_turn"
    assert final.payload["evidence_refs"] == []
    assert final.payload["quality"] == {
        "method": "heuristic_v1",
        "evidence_ref_count": 0,
        "findings_claim_count": 1,
        "findings_inline_ref_count": 0,
        "claims_without_refs_count": 1,
        "evidence_coverage_ratio": 0.0,
    }
    assert final.payload["termination_summary"]["reason"] == "end_turn"
    assert final.payload["termination_summary"]["paper_budget"]["touched_count"] == 1
    initial = next(e for e in entries if isinstance(e, Message) and e.role == "user")
    assert initial.text == "sparse attention"
    system = next(e for e in entries if isinstance(e, SystemMessage))
    assert "decide whether to answer directly or call" in system.text
    assert "Answer greetings, casual conversation" in system.text
    assert "Do not call a tool merely to classify" in system.text
    assert "untrusted source material" in system.text
    assert "Tool inputs must match their JSON schemas exactly" in system.text
    assert "PDF directory:" not in system.text
    assert "问题定义" not in system.text


def test_run_paper_copilot_activates_composer_after_model_uses_tool(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdfs"
    for pool in ("ccf_a", "ccf_b", "other"):
        (pdf_dir / pool).mkdir(parents=True)
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        fs.upsert("paperA", _payload(), datetime.now(UTC).isoformat())
        context = PaperCopilotContext(fields_store=fs, pdf_dir=pdf_dir)
        llm = MockLLM(
            [
                MockResponse(
                    content=[
                        ToolUseBlock(
                            id="composer-list",
                            name="list_composer_library",
                            input={},
                        )
                    ],
                    stop_reason="tool_use",
                    usage={"input_tokens": 8, "output_tokens": 3},
                ),
                MockResponse(
                    content=[
                        TextBlock(
                            text=(
                                "## Idea\n\n"
                                "Use diffusion priors for robust segmentation.\n\n"
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

        run = asyncio.run(
            run_paper_copilot(
                prompt="基于 diffusion model 和医学图像分割, 帮我找一个可做的创新点",
                llm=llm,
                context=context,
                root=tmp_path,
                max_turns=2,
                max_budget_cny=1.0,
            )
        )

    paper_id = run.session_path.parent.name
    entries = SessionStore.load(paper_id, root=tmp_path).read_all()
    initial = next(e for e in entries if isinstance(e, Message) and e.role == "user")
    system = next(e for e in entries if isinstance(e, SystemMessage))
    final = next(e for e in reversed(entries) if isinstance(e, FinalOutput))

    assert initial.text == "基于 diffusion model 和医学图像分割, 帮我找一个可做的创新点"
    assert "问题定义" not in system.text
    assert "list_composer_library" in system.text
    assert len(llm.calls) == 2
    assert '"max_words": 900' not in _system_text(llm.calls[0].system)
    first_request = json.dumps(llm.calls[0].messages, ensure_ascii=False)
    second_request = json.dumps(llm.calls[1].messages, ensure_ascii=False)
    assert "final_report_contract" not in first_request
    assert "final_report_contract" in second_request
    assert "问题定义" in second_request
    second_tool_results = llm.calls[1].messages[-1]["content"]
    assert isinstance(second_tool_results, list)
    composer_payload = json.loads(second_tool_results[0]["content"])
    assert composer_payload["composer_plan"]["final_report_contract"]["max_words"] == 900
    assert final.payload["tool_names"] == ["list_composer_library"]
    assert "request_route" not in final.payload
    assert final.payload["quality"]["findings_claim_count"] == 1
    assert final.payload["proposal_check"]["passed"] is False


def test_run_paper_copilot_can_answer_from_read_paper_summary(tmp_path: Path) -> None:
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        fs.upsert("paperA", _payload(), datetime.now(UTC).isoformat())
        pdir = tmp_path / "papers" / "paperA"
        pdir.mkdir(parents=True)
        (pdir / "session.jsonl").write_text("", encoding="utf-8")
        (pdir / "report.md").write_text("# Paper A", encoding="utf-8")
        context = PaperCopilotContext(fields_store=fs, root=tmp_path, max_papers=1)
        llm = MockLLM(
            [
                MockResponse(
                    content=[
                        ToolUseBlock(
                            id="read1",
                            name="read_paper",
                            input={"paper": {"paper_id": "paperA"}},
                        )
                    ],
                    stop_reason="tool_use",
                    usage={"input_tokens": 10, "output_tokens": 4},
                ),
                MockResponse(
                    content=[
                        TextBlock(
                            text=(
                                "## Findings\n\n"
                                "`paperA` is Paper A and uses Sparse Attention."
                            )
                        )
                    ],
                    stop_reason="end_turn",
                    usage={"input_tokens": 20, "output_tokens": 8},
                ),
            ]
        )

        run = asyncio.run(
            run_paper_copilot(
                prompt="read then summarize",
                llm=llm,
                context=context,
                root=tmp_path,
                max_turns=4,
                max_budget_cny=1.0,
            )
        )

    assert run.termination_reason == "end_turn"
    assert "Sparse Attention" in run.report_markdown
    assert run.termination_summary.paper_budget["touched_paper_ids"] == ["paperA"]

    paper_id = run.session_path.parent.name
    entries = SessionStore.load(paper_id, root=tmp_path).read_all()
    tool_names = [e.name for e in entries if isinstance(e, ToolUse)]
    assert tool_names == ["read_paper"]
    tool_results = [e for e in entries if isinstance(e, ToolResult)]
    assert '"can_query_same_paper": true' in tool_results[0].output
    assert "Sparse Attention" in tool_results[0].output


def test_run_paper_copilot_synthesis_path_uses_related_and_compare(tmp_path: Path) -> None:
    link_to_b = {
        "related_paper_id": "paperB",
        "related_title": "Paper B",
        "relation_type": "shares_method",
        "explanation": "both use sparse attention variants",
    }
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        fs.upsert(
            "paperA",
            _payload(
                "Paper A",
                method_name="Sparse Attention",
                cross_paper_links=[link_to_b],
            ),
            datetime.now(UTC).isoformat(),
        )
        fs.upsert(
            "paperB",
            _payload("Paper B", method_name="Windowed Sparse Attention"),
            datetime.now(UTC).isoformat(),
        )
        pdir = tmp_path / "papers" / "paperA"
        pdir.mkdir(parents=True)
        (pdir / "session.jsonl").write_text("", encoding="utf-8")
        (pdir / "report.md").write_text("# Paper A", encoding="utf-8")
        context = PaperCopilotContext(fields_store=fs, root=tmp_path, max_papers=2)
        llm = MockLLM(
            [
                MockResponse(
                    content=[
                        ToolUseBlock(
                            id="read1",
                            name="read_paper",
                            input={"paper": {"paper_id": "paperA"}},
                        )
                    ],
                    stop_reason="tool_use",
                    usage={"input_tokens": 10, "output_tokens": 4},
                ),
                MockResponse(
                    content=[
                        ToolUseBlock(
                            id="related1",
                            name="find_related_papers",
                            input={"paper": {"paper_id": "paperA"}, "limit": 1},
                        )
                    ],
                    stop_reason="tool_use",
                    usage={"input_tokens": 14, "output_tokens": 5},
                ),
                MockResponse(
                    content=[
                        ToolUseBlock(
                            id="compare1",
                            name="compare_papers",
                            input={
                                "papers": [
                                    {"paper_id": "paperA"},
                                    {"paper_id": "paperB"},
                                ]
                            },
                        )
                    ],
                    stop_reason="tool_use",
                    usage={"input_tokens": 18, "output_tokens": 6},
                ),
                MockResponse(
                    content=[
                        TextBlock(
                            text=(
                                "## Findings\n\n"
                                "`paperA` and `paperB` share sparse-attention evidence.\n\n"
                                "## Evidence\n\n"
                                "- `paperA` uses Sparse Attention "
                                "[paperA:methods[0]].\n"
                                "- `paperB` uses Windowed Sparse Attention "
                                "[paperB:methods[0]]."
                            )
                        )
                    ],
                    stop_reason="end_turn",
                    usage={"input_tokens": 20, "output_tokens": 8},
                ),
            ]
        )

        run = asyncio.run(
            run_paper_copilot(
                prompt="synthesize related sparse attention papers",
                llm=llm,
                context=context,
                root=tmp_path,
                max_turns=8,
                max_budget_cny=1.0,
            )
        )

    assert run.termination_reason == "end_turn"
    assert run.termination_summary.paper_budget["touched_paper_ids"] == [
        "paperA",
        "paperB",
    ]
    paper_id = run.session_path.parent.name
    entries = SessionStore.load(paper_id, root=tmp_path).read_all()
    tool_names = [e.name for e in entries if isinstance(e, ToolUse)]
    assert tool_names == [
        "read_paper",
        "find_related_papers",
        "compare_papers",
    ]
    tool_results = [e for e in entries if isinstance(e, ToolResult)]
    assert "related_papers" in tool_results[1].output
    assert "pairwise_alignment" in tool_results[-1].output
    final = next(e for e in reversed(entries) if isinstance(e, FinalOutput))
    assert final.payload["evidence_refs"] == [
        {"paper_id": "paperA", "field": "methods[0]", "raw": "[paperA:methods[0]]"},
        {"paper_id": "paperB", "field": "methods[0]", "raw": "[paperB:methods[0]]"},
    ]
    assert final.payload["quality"] == {
        "method": "heuristic_v1",
        "evidence_ref_count": 2,
        "findings_claim_count": 1,
        "findings_inline_ref_count": 0,
        "claims_without_refs_count": 0,
        "evidence_coverage_ratio": 1.0,
    }


def test_run_paper_copilot_summary_records_last_tool_error(tmp_path: Path) -> None:
    with FieldsStore.open(tmp_path / "fields.db") as fs:
        context = PaperCopilotContext(fields_store=fs)
        llm = MockLLM(
            [
                MockResponse(
                    content=[
                        ToolUseBlock(
                            id="missing1",
                            name="unknown_tool",
                            input={},
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
            run_paper_copilot(
                prompt="missing paper",
                llm=llm,
                context=context,
                root=tmp_path,
                max_turns=4,
                max_budget_cny=1.0,
            )
        )

    assert run.termination_summary.last_tool_error is not None
    assert run.termination_summary.last_tool_error["tool_use_id"] == "missing1"
    assert "unknown research tool" in run.termination_summary.last_tool_error["output"]
