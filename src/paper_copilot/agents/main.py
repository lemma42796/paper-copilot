"""MainAgent: single-paper orchestrator for `paper-copilot read`.

For M7 the pipeline has exactly two leaf LLM calls (SkimAgent then DeepAgent)
with no tool iteration, so MainAgent is a plain async coroutine — not an
async generator. When M12's RelatedAgent or future loop-based agents join,
this becomes an async generator yielding Events; the public-API cost of that
later refactor is a one-line change on the caller side.

Session ownership: MainAgent creates the SessionStore and hands it to both
inner agents. `final_output` is reserved for MainAgent — inner agents only
write tool_use + schema_validation trace.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from paper_copilot.agents.deep import DeepAgent, DeepResult, DeepRun
from paper_copilot.agents.llm_client import DEFAULT_MODEL, LLMClient
from paper_copilot.agents.skim import SkimAgent, SkimRun
from paper_copilot.schemas.paper import Paper, PaperMeta
from paper_copilot.session import SessionStore
from paper_copilot.session.paths import compute_paper_id
from paper_copilot.shared.cost import CostSnapshot, CostTracker

__all__ = ["MainAgent", "MainRun"]

_AGENT_NAME = "MainAgent"


@dataclass(frozen=True, slots=True)
class MainRun:
    paper: Paper
    skim_run: SkimRun
    deep_run: DeepRun
    cost: CostSnapshot
    session_path: Path


class MainAgent:
    def __init__(self, client: LLMClient, root: Path | None = None) -> None:
        self._client = client
        self._root = root

    async def run(self, pdf_path: Path) -> MainRun:
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
        deep_run = await deep.run(pdf_path, skim_run.result.skeleton)

        paper = _assemble_paper(skim_run.result.meta, deep_run.result)
        store.append_final_output(payload=paper.model_dump(mode="json"))

        tracker = CostTracker()
        if skim_run.response.usage is not None:
            tracker.record(skim_run.response.usage)
        if deep_run.response.usage is not None:
            tracker.record(deep_run.response.usage)

        return MainRun(
            paper=paper,
            skim_run=skim_run,
            deep_run=deep_run,
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
