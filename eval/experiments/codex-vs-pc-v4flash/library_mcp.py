from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from paper_copilot.agents.library_exec_tool import (
    LibraryExecInput,
    LibraryWriteStdinInput,
    library_exec_tool_description,
    library_write_stdin_tool_description,
    run_library_exec,
    run_library_write_stdin,
)
from paper_copilot.agents.paper_copilot import (
    PaperCopilotContext,
    _prepare_paper_cache,
)
from paper_copilot.agents.tools.runtimes import LibraryEnvironment
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.session.paths import pdf_cache_dir

Command = Annotated[
    str,
    Field(
        min_length=1,
        max_length=8_000,
        description="Shell command to run in the fixed library workspace.",
    ),
]
YieldTime = Annotated[
    int,
    Field(
        ge=250,
        le=30_000,
        description="Wait before yielding a still-running command, in milliseconds.",
    ),
]
OutputBudget = Annotated[
    int,
    Field(
        ge=256,
        description="Output token budget; larger requests may be capped by policy.",
    ),
]
SessionId = Annotated[
    str,
    Field(
        min_length=16,
        max_length=64,
        description="Opaque session_id returned by library_exec.",
    ),
]
StdinChars = Annotated[
    str,
    Field(
        max_length=8_000,
        description="Characters to write; an empty value polls for new output.",
    ),
]


@dataclass(frozen=True, slots=True)
class ExperimentPaths:
    library_root: Path
    paper_copilot_root: Path
    environment_root: Path


def _required_path(name: str) -> Path:
    import os

    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        raise RuntimeError(f"missing required environment variable: {name}")
    return Path(raw_value).expanduser().resolve()


def _experiment_paths() -> ExperimentPaths:
    paths = ExperimentPaths(
        library_root=_required_path("PAPER_COPILOT_PDF_DIR"),
        paper_copilot_root=_required_path("PAPER_COPILOT_HOME"),
        environment_root=_required_path("CODEX_LIBRARY_ENV_ROOT"),
    )
    if not paths.library_root.is_dir():
        raise RuntimeError("PAPER_COPILOT_PDF_DIR must be an existing directory")
    return paths


async def _prepare_environment(
    paths: ExperimentPaths,
    *,
    max_papers: int,
) -> LibraryEnvironment:
    fields_store = FieldsStore(sqlite3.connect(":memory:"))
    try:
        context = PaperCopilotContext(
            fields_store=fields_store,
            pdf_dir=paths.library_root,
            root=paths.paper_copilot_root,
            max_papers=max_papers,
        )
        preflight = await _prepare_paper_cache(context)
    finally:
        fields_store.close()

    environment = LibraryEnvironment(paths.environment_root)
    cache_root = pdf_cache_dir(paths.paper_copilot_root).expanduser().resolve()
    await asyncio.to_thread(
        environment.configure_research_view,
        preflight.research_view(cache_root=cache_root),
        total_pdf_count=preflight.total_pdf_count,
        failures=preflight.failures,
        truncated_by_paper_budget=(
            preflight.total_pdf_count
            > len(preflight.prepared) + len(preflight.failures)
        ),
    )
    return environment


def create_server() -> FastMCP:
    import os

    paths = _experiment_paths()
    max_papers = int(os.environ.get("CODEX_LIBRARY_MAX_PAPERS", "14"))
    if max_papers < 1:
        raise RuntimeError("CODEX_LIBRARY_MAX_PAPERS must be at least 1")
    environment = asyncio.run(_prepare_environment(paths, max_papers=max_papers))
    cache_root = pdf_cache_dir(paths.paper_copilot_root).expanduser().resolve()

    server = FastMCP(
        "paper-copilot-library-ablation",
        instructions=(
            "Private causal-ablation bridge exposing only Paper Copilot's current "
            "library command runtime. The prepared manifest is authoritative."
        ),
    )

    @server.tool(description=library_exec_tool_description())
    async def library_exec(
        cmd: Command,
        yield_time_ms: YieldTime = 10_000,
        max_output_tokens: OutputBudget = 10_000,
    ) -> str:
        parsed = LibraryExecInput(
            cmd=cmd,
            yield_time_ms=yield_time_ms,
            max_output_tokens=max_output_tokens,
        )
        execution = await run_library_exec(
            parsed,
            paths.library_root,
            cache_root=cache_root,
            environment=environment,
        )
        return execution.output

    @server.tool(description=library_write_stdin_tool_description())
    async def library_write_stdin(
        session_id: SessionId,
        chars: StdinChars = "",
        yield_time_ms: YieldTime = 5_000,
        max_output_tokens: OutputBudget = 10_000,
    ) -> str:
        parsed = LibraryWriteStdinInput(
            session_id=session_id,
            chars=chars,
            yield_time_ms=yield_time_ms,
            max_output_tokens=max_output_tokens,
        )
        execution = await run_library_write_stdin(
            parsed,
            environment=environment,
        )
        return execution.output

    return server


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
