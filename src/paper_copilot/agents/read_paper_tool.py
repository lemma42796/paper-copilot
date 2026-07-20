"""ReadPaperTool: single-paper reading workflow.

The skim, extraction, and linking steps are bounded tools. Their LLM tool_use
calls are structured-output channels, not autonomous agent loops.

Session ownership: ReadPaperTool creates the SessionStore and hands it to every
inner tool. `final_output` is reserved for ReadPaperTool; inner tools only write
tool_use and schema_validation trace.

The linking tool runs only when the caller supplies all three knowledge handles
(embedder + both stores). Missing handles keep cross_paper_links empty. The tool
also skips when fields.db is empty (the first read has no library to link).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from paper_copilot.agents.extract_paper_tool import (
    DeepResult,
    ExtractPaperTool,
    ExtractPaperToolRun,
)
from paper_copilot.agents.link_related_papers_tool import (
    LinkRelatedPapersTool,
    LinkRelatedPapersToolRun,
)
from paper_copilot.agents.llm_client import DEFAULT_MODEL, LLMClient
from paper_copilot.agents.skim_paper_tool import SkimPaperTool, SkimPaperToolRun
from paper_copilot.knowledge.embeddings_store import EmbeddingsStore
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.schemas.paper import Paper, PaperMeta
from paper_copilot.session import SessionStore
from paper_copilot.session.paths import compute_paper_id
from paper_copilot.shared.cost import CostSnapshot, CostTracker, pricing_for_model
from paper_copilot.shared.embedding_cache import EmbeddingEncoder

__all__ = ["ReadPaperTool", "ReadPaperToolRun"]

_TOOL_NAME = "ReadPaperTool"


@dataclass(frozen=True, slots=True)
class ReadPaperToolRun:
    paper: Paper
    skim_run: SkimPaperToolRun
    deep_run: ExtractPaperToolRun
    related_run: LinkRelatedPapersToolRun | None
    cost: CostSnapshot
    session_path: Path


class ReadPaperTool:
    def __init__(self, client: LLMClient, root: Path | None = None) -> None:
        self._client = client
        self._root = root

    async def run(
        self,
        pdf_path: Path,
        *,
        language: Literal["en", "zh"] = "en",
        embedder: EmbeddingEncoder | None = None,
        fields_store: FieldsStore | None = None,
        embeddings_store: EmbeddingsStore | None = None,
    ) -> ReadPaperToolRun:
        paper_id = compute_paper_id(pdf_path)
        store = SessionStore.create(
            paper_id,
            model=DEFAULT_MODEL,
            agent=_TOOL_NAME,
            root=self._root,
        )

        skim = SkimPaperTool(self._client, store)
        skim_run = await skim.run(pdf_path)

        deep = ExtractPaperTool(self._client, store)
        deep_run = await deep.run(pdf_path, skim_run.result.skeleton, language=language)

        paper_draft = _assemble_paper(skim_run.result.meta, deep_run.result)

        related_run: LinkRelatedPapersToolRun | None = None
        if (
            embedder is not None
            and fields_store is not None
            and embeddings_store is not None
            and fields_store.count() > 0
        ):
            related = LinkRelatedPapersTool(self._client, store)
            related_run = await related.run(
                paper_draft,
                paper_id,
                embedder=embedder,
                fields_store=fields_store,
                embeddings_store=embeddings_store,
            )

        links = related_run.result.links if related_run is not None else []
        paper = paper_draft.model_copy(update={"cross_paper_links": links})
        store.append_final_output(payload=paper.model_dump(mode="json"))

        tracker = CostTracker(pricing=pricing_for_model(DEFAULT_MODEL))
        for response in skim_run.responses:
            if response.usage is not None:
                tracker.record(response.usage)
        for response in deep_run.responses:
            if response.usage is not None:
                tracker.record(response.usage)
        if related_run is not None:
            for response in related_run.responses:
                if response.usage is not None:
                    tracker.record(response.usage)

        return ReadPaperToolRun(
            paper=paper,
            skim_run=skim_run,
            deep_run=deep_run,
            related_run=related_run,
            cost=tracker.snapshot(),
            session_path=store.path,
        )


def _assemble_paper(meta: PaperMeta, deep: DeepResult) -> Paper:
    return Paper(
        meta=meta,
        contributions=list(deep.contributions),
        methods=list(deep.methods),
        experiments=list(deep.experiments),
        limitations=list(deep.limitations),
    )
