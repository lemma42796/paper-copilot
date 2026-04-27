"""MainAgent: single-paper orchestrator for `paper-copilot read`.

Leaf agents (Skim, Deep, Related) all bypass `agents.loop` — their tool_use
calls are structured-output channels, not real tool executions. MainAgent is
therefore a plain async coroutine, not a generator.

Session ownership: MainAgent creates the SessionStore and hands it to every
inner agent. `final_output` is reserved for MainAgent — inner agents only
write tool_use + schema_validation trace.

M12: RelatedAgent runs only when the caller supplies all three knowledge
handles (embedder + both stores). Missing handles = Skim/Deep-only run,
cross_paper_links stays empty. The handles also short-circuit to skip when
fields.db is empty (first read has no library to relate against).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from paper_copilot.agents.deep import DeepAgent, DeepResult, DeepRun
from paper_copilot.agents.llm_client import DEFAULT_MODEL, LLMClient
from paper_copilot.agents.related import RelatedAgent, RelatedRun
from paper_copilot.agents.skim import SkimAgent, SkimRun
from paper_copilot.knowledge.embeddings_store import EmbeddingsStore
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.schemas.paper import Paper, PaperMeta
from paper_copilot.session import SessionStore
from paper_copilot.session.paths import compute_paper_id
from paper_copilot.shared.cost import CostSnapshot, CostTracker, pricing_for_model
from paper_copilot.shared.embedder import Embedder

__all__ = ["MainAgent", "MainRun"]

_AGENT_NAME = "MainAgent"


@dataclass(frozen=True, slots=True)
class MainRun:
    paper: Paper
    skim_run: SkimRun
    deep_run: DeepRun
    related_run: RelatedRun | None
    cost: CostSnapshot
    session_path: Path


class MainAgent:
    def __init__(self, client: LLMClient, root: Path | None = None) -> None:
        self._client = client
        self._root = root

    async def run(
        self,
        pdf_path: Path,
        *,
        language: Literal["en", "zh"] = "en",
        embedder: Embedder | None = None,
        fields_store: FieldsStore | None = None,
        embeddings_store: EmbeddingsStore | None = None,
    ) -> MainRun:
        paper_id = compute_paper_id(pdf_path)
        store = SessionStore.create(
            paper_id,
            model=DEFAULT_MODEL,
            agent=_AGENT_NAME,
            root=self._root,
        )

        skim = SkimAgent(self._client, store)
        skim_run = await skim.run(pdf_path)

        deep = DeepAgent(self._client, store)
        deep_run = await deep.run(pdf_path, skim_run.result.skeleton, language=language)

        paper_draft = _assemble_paper(skim_run.result.meta, deep_run.result)

        related_run: RelatedRun | None = None
        if (
            embedder is not None
            and fields_store is not None
            and embeddings_store is not None
            and fields_store.count() > 0
        ):
            related = RelatedAgent(self._client, store)
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
        if skim_run.response.usage is not None:
            tracker.record(skim_run.response.usage)
        if deep_run.response.usage is not None:
            tracker.record(deep_run.response.usage)
        if related_run is not None and related_run.response is not None:
            tracker.record(related_run.response.usage)

        return MainRun(
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
