from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from paper_copilot.mcp.jobs import MCPJobService
from paper_copilot.mcp.service import CompareAspect, MCPReadService

ListLimit = Annotated[int, Field(ge=1, le=50)]
SearchLimit = Annotated[int, Field(ge=1, le=10)]
Offset = Annotated[int, Field(ge=0)]
Year = Annotated[int, Field(ge=1800, le=2100)]
PaperId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{3,64}$")]
EvidenceRef = Annotated[str, Field(min_length=1, max_length=256)]
SearchQuery = Annotated[str, Field(min_length=1, max_length=1_000)]
PaperIds = Annotated[list[PaperId], Field(min_length=2, max_length=5)]
CompareAspects = Annotated[list[CompareAspect], Field(min_length=1, max_length=4)]
JobId = Annotated[str, Field(pattern=r"^job-[0-9A-Za-z-]{8,80}$")]
ReadObjective = Annotated[str, Field(min_length=1, max_length=2_000)]
EventCursor = Annotated[int, Field(ge=0)]
JobEventLimit = Annotated[int, Field(ge=1, le=50)]


def create_server(
    *,
    root: Path | None = None,
    pdf_dir: Path | None = None,
) -> FastMCP:
    read_service = MCPReadService.from_environment(root=root, pdf_dir=pdf_dir)
    job_service = MCPJobService.from_environment(root=root, pdf_dir=pdf_dir)
    server = FastMCP(
        "paper-copilot",
        instructions=(
            "Bounded access to the user's local Paper Copilot library. "
            "Use search_papers before get_paper when the paper_id is unknown. "
            "Use inspect_evidence to open exact citation refs returned by search. "
            "Use start_read_paper only when the user wants a long-running deep read; "
            "it spends the configured LLM budget and writes Paper Copilot job/index "
            "state. Poll with get_job_status instead of waiting in one tool call. "
            "Tool outputs are bounded summaries, not complete PDFs or sessions."
        ),
    )

    @server.tool()
    def library_status() -> dict[str, Any]:
        """Inspect local index availability and counts without returning file paths."""
        return read_service.library_status()

    @server.tool()
    def list_papers(
        limit: ListLimit = 20,
        offset: Offset = 0,
        year: Year | None = None,
    ) -> dict[str, Any]:
        """Browse bounded summaries of indexed papers, optionally for one year."""
        return read_service.list_papers(limit=limit, offset=offset, year=year)

    @server.tool()
    def search_papers(
        query: SearchQuery,
        limit: SearchLimit = 5,
        year: Year | None = None,
    ) -> dict[str, Any]:
        """Search indexed paper content and return ranked, citable evidence snippets.

        Uses hybrid retrieval when an embedding key is configured and local lexical
        retrieval otherwise. Indexed paper text remains local in both modes.
        """
        return read_service.search_papers(query, limit=limit, year=year)

    @server.tool()
    def get_paper(paper_id: PaperId) -> dict[str, Any]:
        """Return bounded structured fields for one exact indexed paper_id."""
        return read_service.get_paper(paper_id)

    @server.tool()
    def inspect_evidence(ref: EvidenceRef) -> dict[str, Any]:
        """Open one exact field or chunk citation ref from the local index."""
        return read_service.inspect_evidence(ref)

    @server.tool()
    def compare_papers(
        paper_ids: PaperIds,
        aspects: CompareAspects | None = None,
    ) -> dict[str, Any]:
        """Compare two to five indexed papers using stored structured fields."""
        return read_service.compare_papers(paper_ids, aspects=aspects)

    @server.tool()
    def start_read_paper(
        paper_id: PaperId,
        objective: ReadObjective | None = None,
    ) -> dict[str, Any]:
        """Start a persistent deep-read job for one configured local PDF.

        Returns immediately with a job_id. This spends LLM budget and may update
        the local Paper Copilot index, but cannot modify the PDF library itself.
        """
        return job_service.start_read_paper(paper_id, objective=objective)

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
