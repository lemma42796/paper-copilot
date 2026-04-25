"""M7 ST2 reality check — run DeepAgent against a real paper.

One-off. Not reusable infrastructure. Hard-coded paths.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from paper_copilot.agents.deep import DeepAgent
from paper_copilot.agents.llm_client import LLMClient
from paper_copilot.agents.loop import ToolUseBlock
from paper_copilot.schemas.paper import PaperSkeleton
from paper_copilot.shared.cost import CostTracker

PDF_PATH = Path("/Users/a123/paper-copilot-test-pdfs/transformer.pdf")
SESSION_PATH = Path.home() / ".paper-copilot/papers/a639448e61be/session.jsonl"
_REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_OUT = _REPO_ROOT / "tests/fixtures/deep_transformer_tool_input.json"


def _load_skeleton() -> PaperSkeleton:
    last_final: dict[str, Any] | None = None
    with SESSION_PATH.open() as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("type") == "final_output":
                last_final = entry
    assert last_final is not None, "no final_output entry in session.jsonl"
    return PaperSkeleton.model_validate(last_final["payload"]["skeleton"])


async def _run() -> None:
    skeleton = _load_skeleton()
    client = LLMClient()
    agent = DeepAgent(client=client)

    t0 = time.monotonic()
    run = await agent.run(PDF_PATH, skeleton)
    wall = time.monotonic() - t0

    result = run.result
    response = run.response

    print("### counts")
    print(f"contributions: {len(result.contributions)}")
    print(f"methods: {len(result.methods)}")
    print(f"experiments: {len(result.experiments)}")
    print(f"limitations: {len(result.limitations)}")
    print()

    print("### contributions")
    for i, c in enumerate(result.contributions, 1):
        print(f"{i}. [{c.type} conf={c.confidence}] {c.claim}")
    print()

    print("### methods")
    for i, m in enumerate(result.methods, 1):
        print(f"{i}. {m.name}  |  novelty: {m.novelty_vs_prior}")
    print()

    print("### experiments")
    for i, e in enumerate(result.experiments, 1):
        val = f"{e.value}{e.unit or ''}" if e.value is not None else "(no value)"
        print(f"{i}. {e.dataset} / {e.metric} = {val}  vs {e.comparison_baseline}  pages={e.pages}")
    print()

    print("### limitations")
    for i, lim in enumerate(result.limitations, 1):
        print(f"{i}. [{lim.type}] {lim.description}")
    print()

    print("### cost / latency")
    tracker = CostTracker()
    tracker.record(response.usage)
    snap = tracker.snapshot()
    print(f"input_tokens: {snap.input_tokens}")
    print(f"output_tokens: {snap.output_tokens}")
    print(f"cache_creation_input_tokens: {snap.cache_creation_tokens}")
    print(f"cache_read_input_tokens: {snap.cache_read_tokens}")
    print(f"total_cost_cny: {snap.cost_cny:.4f}")
    print(f"wall_clock_seconds: {wall:.2f}")
    print(f"stop_reason: {response.stop_reason}")
    print()

    tool_use = next(b for b in response.content if isinstance(b, ToolUseBlock))
    FIXTURE_OUT.parent.mkdir(parents=True, exist_ok=True)
    with FIXTURE_OUT.open("w") as f:
        json.dump(tool_use.input, f, indent=2, ensure_ascii=False)
    print(f"### fixture saved: {FIXTURE_OUT}")


if __name__ == "__main__":
    asyncio.run(_run())
