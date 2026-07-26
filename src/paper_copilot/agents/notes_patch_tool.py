from __future__ import annotations

import difflib
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from paper_copilot.shared.errors import KnowledgeError

NoteOperation = Literal["inspect", "write_document"]

_MAX_NOTE_BYTES = 512_000
_MAX_CONTENT_CHARS = 100_000
_MAX_DIFF_CHARS = 16_000
_MAX_INSPECT_CHARS = 30_000


class NotesPatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: NoteOperation
    path: str = Field(
        min_length=1,
        max_length=500,
        description=(
            "Markdown note path relative to the paper library, for example "
            "'创新点/paper-title.md'."
        ),
    )
    content: str | None = Field(
        default=None,
        min_length=1,
        max_length=_MAX_CONTENT_CHARS,
        description=(
            "Complete replacement Markdown document. Include every heading and "
            "section that should remain in the file."
        ),
    )

    @model_validator(mode="after")
    def _arguments_match_operation(self) -> NotesPatchInput:
        if self.operation == "inspect":
            if self.content is not None:
                raise ValueError("inspect accepts path only")
        else:
            if self.content is None or not self.content.strip():
                raise ValueError("write_document requires non-whitespace content")
        return self


def notes_patch_tool_description() -> str:
    return (
        "Read or replace one complete Markdown note inside the paper library. inspect "
        "returns the current document and SHA-256. write_document accepts the complete "
        "new Markdown document and requires host approval with a unified diff preview "
        "bound to the current file hash. Use it to save discussion notes or reusable "
        "highlights under paths such as 创新点/paper-title.md. Only relative .md paths "
        "are accepted."
    )


def build_notes_patch_preview(
    args: NotesPatchInput,
    library_root: Path | None,
) -> dict[str, Any]:
    if args.operation != "write_document":
        raise KnowledgeError("a note change preview requires write_document")
    root = _resolve_library_root(library_root)
    path = _resolve_note_path(root, args.path)
    before = _read_note(path, allow_missing=True)
    after = _render_document(args)
    return _change_preview(args, path, before, after)


def _change_preview(
    args: NotesPatchInput,
    path: Path,
    before: str,
    after: str,
) -> dict[str, Any]:
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{args.path}",
            tofile=f"b/{args.path}",
        )
    )
    bounded_diff, diff_truncated = _bounded_text(diff, _MAX_DIFF_CHARS)
    return {
        "path": args.path,
        "before_exists": path.exists(),
        "before_sha256": _sha256_text(before) if path.exists() else None,
        "after_sha256": _sha256_text(after),
        "diff": bounded_diff,
        "diff_truncated": diff_truncated,
    }


def notes_target_snapshot(
    args: NotesPatchInput,
    library_root: Path | None,
) -> list[dict[str, Any]]:
    root = _resolve_library_root(library_root)
    path = _resolve_note_path(root, args.path)
    if not path.exists():
        return [{"path": args.path, "status": "missing"}]
    stat = path.stat()
    text = _read_note(path, allow_missing=False)
    return [
        {
            "path": args.path,
            "status": "present",
            "kind": "file",
            "size_bytes": stat.st_size,
            "modified_ns": stat.st_mtime_ns,
            "sha256": _sha256_text(text),
        }
    ]


def run_notes_patch(
    args: NotesPatchInput,
    library_root: Path | None,
) -> dict[str, Any]:
    root = _resolve_library_root(library_root)
    path = _resolve_note_path(root, args.path)
    if args.operation == "inspect":
        text = _read_note(path, allow_missing=False)
        bounded, truncated = _bounded_text(text, _MAX_INSPECT_CHARS)
        return {
            "status": "ok",
            "operation": "inspect",
            "path": args.path,
            "sha256": _sha256_text(text),
            "content": bounded,
            "content_truncated": truncated,
            "content_chars": len(text),
        }

    before = _read_note(path, allow_missing=True)
    after = _render_document(args)
    preview = _change_preview(args, path, before, after)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, after)
    return {
        "status": "ok",
        "operation": "write_document",
        "path": args.path,
        "created": not bool(preview["before_exists"]),
        "before_sha256": preview["before_sha256"],
        "after_sha256": preview["after_sha256"],
        "diff": preview["diff"],
        "diff_truncated": preview["diff_truncated"],
    }


def _resolve_library_root(library_root: Path | None) -> Path:
    if library_root is None:
        raise KnowledgeError("notes_patch requires a configured paper library")
    root = library_root.expanduser().resolve()
    if not root.is_dir():
        raise KnowledgeError(f"PDF library does not exist: {root}")
    return root


def _resolve_note_path(root: Path, raw_path: str) -> Path:
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise KnowledgeError("note path must be relative and stay inside the paper library")
    if relative.suffix.lower() != ".md":
        raise KnowledgeError("notes_patch only accepts .md files")
    if any(part.startswith(".") for part in relative.parts):
        raise KnowledgeError("hidden note paths are not available")
    candidate = root / relative
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise KnowledgeError(
                f"note path must not contain symbolic links: {raw_path}"
            )
        if current.exists() and current != candidate and not current.is_dir():
            raise KnowledgeError(f"note parent is not a directory: {raw_path}")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise KnowledgeError("note path escapes the paper library")
    if resolved.exists() and not resolved.is_file():
        raise KnowledgeError(f"note path is not a file: {raw_path}")
    return resolved


def _read_note(path: Path, *, allow_missing: bool) -> str:
    if not path.exists():
        if allow_missing:
            return ""
        raise KnowledgeError(f"note does not exist: {path.name}")
    size = path.stat().st_size
    if size > _MAX_NOTE_BYTES:
        raise KnowledgeError(
            f"note exceeds the {_MAX_NOTE_BYTES}-byte editing limit: {path.name}"
        )
    return path.read_text(encoding="utf-8")


def _render_document(args: NotesPatchInput) -> str:
    assert args.content is not None
    return _require_note_size(args.content.rstrip() + "\n")


def _atomic_write_text(path: Path, text: str) -> None:
    descriptor, raw_temp_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temp_path = Path(raw_temp_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require_note_size(text: str) -> str:
    size = len(text.encode("utf-8"))
    if size > _MAX_NOTE_BYTES:
        raise KnowledgeError(
            f"updated note exceeds the {_MAX_NOTE_BYTES}-byte editing limit"
        )
    return text


def _bounded_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True
