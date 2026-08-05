from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from paper_copilot.mcp.jobs import MCPJobService
JobId = Annotated[str, Field(pattern=r"^job-[0-9A-Za-z-]{8,80}$")]
EventCursor = Annotated[int, Field(ge=0)]
JobEventLimit = Annotated[int, Field(ge=1, le=50)]


def create_server(
    *,
    root: Path | None = None,
    pdf_dir: Path | None = None,
) -> FastMCP:
    job_service = MCPJobService.from_environment(root=root, pdf_dir=pdf_dir)
    server = FastMCP(
        "paper-copilot",
        instructions=(
            "Bounded access to Paper Copilot job state. Paper discovery and reading "
            "use the Agent's filesystem and paper reading tools; no paper index or "
            "embedding database is maintained."
        ),
    )

    @server.tool()
    def get_job_status(
        job_id: JobId,
        after_event_seq: EventCursor = 0,
        event_limit: JobEventLimit = 20,
    ) -> dict[str, Any]:
        """Get job/attempt state and bounded incremental progress events."""
        return job_service.get_job_status(
            job_id,
            after_event_seq=after_event_seq,
            event_limit=event_limit,
        )

    @server.tool()
    def get_job_result(job_id: JobId) -> dict[str, Any]:
        """Return a completed job's bounded Markdown report without local paths."""
        return job_service.get_job_result(job_id)

    @server.tool()
    def cancel_job(job_id: JobId) -> dict[str, Any]:
        """Request cancellation without claiming success before the Agent exits."""
        return job_service.cancel_job(job_id)

    return server


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
