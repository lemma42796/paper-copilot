"""M9 scratch: A/B test whether cache_control on the user message is honored.

Reproduces DeepAgent's exact request shape but lets us toggle the third
cache_control marker (on the user block). Run twice back-to-back to see
if cache_read differs. This file is transient — delete once the question
is answered.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from paper_copilot.agents.deep import (
    _LANGUAGE_INSTRUCTION,
    _SYSTEM_PROMPT,
    _TOOL_NAME,
    _build_tool,
    _build_user_text,
)
from paper_copilot.agents.llm_client import LLMClient
from paper_copilot.retrieval import split_by_sections
from paper_copilot.schemas.paper import PaperSkeleton
from paper_copilot.shared.cache import cached_system, cached_user_text, mark_tools_cached


async def run_once(*, mark_user: bool) -> None:
    pdf = Path.home() / "paper-copilot-test-pdfs" / "transformer.pdf"
    sess = Path.home() / ".paper-copilot" / "papers" / "a639448e61be" / "session.jsonl"
    skel = None
    for line in sess.read_text().splitlines():
        obj = json.loads(line)
        if obj.get("type") == "tool_use" and obj.get("name") == "emit_skim":
            skel = PaperSkeleton.model_validate(obj["input"]["skeleton"])
            break
    assert skel is not None

    sections = split_by_sections(pdf, skel)
    user_text = _build_user_text(sections)

    tools = mark_tools_cached([_build_tool()])
    system = cached_system(_SYSTEM_PROMPT + _LANGUAGE_INSTRUCTION["en"])

    content = cached_user_text(user_text) if mark_user else user_text

    client = LLMClient()
    resp = await client.generate(
        messages=[{"role": "user", "content": content}],
        tools=tools,
        tool_choice={"type": "tool", "name": _TOOL_NAME},
        system=system,
        max_tokens=3000,
    )
    u = resp.usage
    print(
        f"mark_user={mark_user}  "
        f"input={getattr(u, 'input_tokens', 0)}  "
        f"output={getattr(u, 'output_tokens', 0)}  "
        f"cache_create={getattr(u, 'cache_creation_input_tokens', 0)}  "
        f"cache_read={getattr(u, 'cache_read_input_tokens', 0)}  "
        f"latency={resp.latency_ms}ms"
    )


async def main() -> None:
    mark = sys.argv[1] if len(sys.argv) > 1 else "on"
    await run_once(mark_user=(mark == "on"))


if __name__ == "__main__":
    asyncio.run(main())
