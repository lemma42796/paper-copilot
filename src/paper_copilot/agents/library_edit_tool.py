from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from paper_copilot.agents.library_files_tool import (
    LibraryFilesInput,
    run_library_files,
)
from paper_copilot.agents.notes_patch_tool import (
    NotesPatchInput,
    run_notes_patch,
)

LibraryEditOperation = Literal[
    "mkdir",
    "copy",
    "move",
    "trash",
    "restore",
    "write_document",
]

_MAX_PATHS = 100
_MAX_CONTENT_CHARS = 100_000


class LibraryEditInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: LibraryEditOperation = Field(
        description=(
            "Exact mutation to perform. move also handles PDF renaming. "
            "write_document replaces one complete Markdown document."
        )
    )
    paths: list[str] = Field(
        default_factory=list,
        max_length=_MAX_PATHS,
        description="Source PDF paths relative to the paper library.",
    )
    destination: str | None = Field(
        default=None,
        description="Relative destination used by mkdir, copy, and move.",
    )
    recursive: bool = Field(
        default=False,
        description="For mkdir, create missing parent directories.",
    )
    receipt_id: str | None = Field(
        default=None,
        pattern=r"^[0-9A-Za-z-]{8,80}$",
        description="Legacy trash receipt accepted only by restore.",
    )
    path: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="Relative .md path accepted only by write_document.",
    )
    content: str | None = Field(
        default=None,
        min_length=1,
        max_length=_MAX_CONTENT_CHARS,
        description=(
            "Complete replacement Markdown content accepted only by write_document."
        ),
    )

    @model_validator(mode="after")
    def _arguments_match_operation(self) -> LibraryEditInput:
        if self.operation == "write_document":
            NotesPatchInput.model_validate(
                {
                    "operation": "write_document",
                    "path": self.path,
                    "content": self.content,
                }
            )
            if (
                self.paths
                or self.destination is not None
                or self.recursive
                or self.receipt_id is not None
            ):
                raise ValueError(
                    "write_document accepts operation, path, and content only"
                )
            return self

        if self.path is not None or self.content is not None:
            raise ValueError(
                f"{self.operation} does not accept Markdown path or content"
            )
        library_files_input(self)
        return self


def library_edit_tool_description() -> str:
    return (
        "Modify files inside the paper library. Use mkdir, copy, move, trash, or "
        "restore for PDF and directory organization. Use write_document to create "
        "or replace one complete Markdown note. All operations are path-confined "
        "and require host approval bound to the exact parameters and current target "
        "state; Markdown writes also include a unified diff preview. Use library_exec "
        "to read an existing Markdown document before replacing it, and for other "
        "read-only listing, inspection, statistics, and duplicate discovery."
    )


def library_files_input(args: LibraryEditInput) -> LibraryFilesInput:
    return LibraryFilesInput.model_validate(
        {
            "operation": args.operation,
            "paths": args.paths,
            "destination": args.destination,
            "recursive": args.recursive,
            "receipt_id": args.receipt_id,
        }
    )


def notes_input(args: LibraryEditInput) -> NotesPatchInput:
    return NotesPatchInput.model_validate(
        {
            "operation": "write_document",
            "path": args.path,
            "content": args.content,
        }
    )


def run_library_edit(
    args: LibraryEditInput,
    library_root: Path | None,
) -> dict[str, Any]:
    if args.operation == "write_document":
        return run_notes_patch(notes_input(args), library_root)
    return run_library_files(library_files_input(args), library_root)
