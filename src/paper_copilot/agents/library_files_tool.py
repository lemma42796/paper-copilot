from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from paper_copilot.shared.errors import KnowledgeError

LibraryFileOperation = Literal[
    "list",
    "inspect",
    "mkdir",
    "copy",
    "move",
    "trash",
    "restore",
]

_MAX_PATHS = 100
_MAX_LIST_RESULTS = 500
_LEGACY_TRASH_DIR_NAME = ".paper-copilot-trash"
_MOVE_TO_MACOS_TRASH_SCRIPT = """\
on run itemPaths
    repeat with itemPath in itemPaths
        set sourceFile to POSIX file (itemPath as text)
        tell application "Finder" to delete sourceFile
    end repeat
end run
"""


class LibraryFilesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: LibraryFileOperation
    paths: list[str] = Field(default_factory=list, max_length=_MAX_PATHS)
    destination: str | None = None
    recursive: bool = False
    include_hash: bool = False
    receipt_id: str | None = Field(default=None, pattern=r"^[0-9A-Za-z-]{8,80}$")
    limit: int = Field(default=200, ge=1, le=_MAX_LIST_RESULTS)

    @model_validator(mode="after")
    def _operation_arguments_are_valid(self) -> LibraryFilesInput:
        match self.operation:
            case "list":
                if len(self.paths) > 1:
                    raise ValueError("list accepts zero or one directory path")
            case "inspect" | "trash":
                if not self.paths:
                    raise ValueError(f"{self.operation} requires at least one path")
            case "copy" | "move":
                if not self.paths or self.destination is None:
                    raise ValueError(
                        f"{self.operation} requires paths and destination"
                    )
            case "mkdir":
                if self.destination is None or self.paths:
                    raise ValueError("mkdir requires destination and no paths")
            case "restore":
                if self.receipt_id is None:
                    raise ValueError("restore requires a legacy receipt_id")
        return self


def library_files_tool_description() -> str:
    return (
        "Inspect and organize PDF files inside the user-selected paper library. "
        "Compose list and inspect to answer file questions. mkdir, copy, move, "
        "trash, and restore modify the library and require host approval. All paths "
        "must be relative to the library root. trash moves PDFs to the macOS system "
        "Trash. restore only accepts receipts created by the legacy application trash."
    )


def run_library_files(args: LibraryFilesInput, library_root: Path | None) -> dict[str, Any]:
    if library_root is None:
        raise KnowledgeError("library_files requires a configured PDF library")
    root = library_root.expanduser().resolve()
    if not root.is_dir():
        raise KnowledgeError(f"PDF library does not exist: {root}")
    match args.operation:
        case "list":
            return _list_files(args, root)
        case "inspect":
            return _inspect_files(args, root)
        case "mkdir":
            return _make_directory(args, root)
        case "copy" | "move":
            return _copy_or_move(args, root)
        case "trash":
            return _trash_files(args, root)
        case "restore":
            return _restore_legacy_files(args, root)


def _list_files(args: LibraryFilesInput, root: Path) -> dict[str, Any]:
    directory = _resolve_library_path(root, args.paths[0] if args.paths else ".")
    if not directory.is_dir():
        raise KnowledgeError(f"library path is not a directory: {_relative(root, directory)}")
    iterator = directory.rglob("*") if args.recursive else directory.iterdir()
    entries: list[dict[str, Any]] = []
    for path in sorted(iterator):
        if _is_legacy_trash_path(root, path) or path.name.startswith("."):
            continue
        if path.is_dir():
            entries.append(_entry_payload(root, path, include_hash=False))
        elif path.is_file() and path.suffix.lower() == ".pdf":
            entries.append(_entry_payload(root, path, include_hash=False))
        if len(entries) >= args.limit:
            break
    return {
        "status": "ok",
        "operation": "list",
        "library_root": str(root),
        "directory": _relative(root, directory),
        "entries": entries,
        "limit": args.limit,
        "limit_reached": len(entries) >= args.limit,
    }


def _inspect_files(args: LibraryFilesInput, root: Path) -> dict[str, Any]:
    entries = [
        _entry_payload(
            root,
            _resolve_existing_pdf_or_directory(root, raw),
            include_hash=args.include_hash,
        )
        for raw in args.paths
    ]
    return {"status": "ok", "operation": "inspect", "entries": entries}


def _make_directory(args: LibraryFilesInput, root: Path) -> dict[str, Any]:
    assert args.destination is not None
    destination = _resolve_library_path(root, args.destination)
    if _is_legacy_trash_path(root, destination):
        raise KnowledgeError(
            "library_files cannot create directories inside its legacy trash area"
        )
    destination.mkdir(parents=args.recursive, exist_ok=False)
    return {
        "status": "ok",
        "operation": "mkdir",
        "created": _relative(root, destination),
    }


def _copy_or_move(args: LibraryFilesInput, root: Path) -> dict[str, Any]:
    assert args.destination is not None
    sources = [_resolve_existing_pdf(root, raw) for raw in args.paths]
    destination = _resolve_library_path(root, args.destination)
    if _is_legacy_trash_path(root, destination):
        raise KnowledgeError("legacy trash contents are not available to file operations")
    targets = _operation_targets(root, sources, destination)
    _require_unique_paths(sources, label="source")
    _require_unique_paths(targets, label="destination")
    for target in targets:
        if target.exists():
            raise KnowledgeError(f"destination already exists: {_relative(root, target)}")
    completed: list[dict[str, str]] = []
    for source, target in zip(sources, targets, strict=True):
        target.parent.mkdir(parents=True, exist_ok=True)
        if args.operation == "copy":
            shutil.copy2(source, target)
        else:
            shutil.move(str(source), str(target))
        completed.append(
            {"source": _relative(root, source), "destination": _relative(root, target)}
        )
    return {"status": "ok", "operation": args.operation, "files": completed}


def _trash_files(args: LibraryFilesInput, root: Path) -> dict[str, Any]:
    if sys.platform != "darwin":
        raise KnowledgeError("trash requires macOS")
    sources = [_resolve_existing_pdf(root, raw) for raw in args.paths]
    _require_unique_paths(sources, label="source")
    completed = subprocess.run(
        [
            "/usr/bin/osascript",
            "-e",
            _MOVE_TO_MACOS_TRASH_SCRIPT,
            *(str(source) for source in sources),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or "Finder did not move the PDFs to Trash"
        raise KnowledgeError(f"macOS Trash operation failed: {message}")
    return {
        "status": "ok",
        "operation": "trash",
        "destination": "macos_trash",
        "files": [_relative(root, source) for source in sources],
    }


def _restore_legacy_files(
    args: LibraryFilesInput,
    root: Path,
) -> dict[str, Any]:
    assert args.receipt_id is not None
    receipt_root = root / _LEGACY_TRASH_DIR_NAME / args.receipt_id
    manifest_path = receipt_root / "manifest.json"
    if not manifest_path.is_file():
        raise KnowledgeError(f"legacy trash receipt does not exist: {args.receipt_id}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest.get("files")
    if not isinstance(records, list):
        raise KnowledgeError(f"legacy trash receipt is invalid: {args.receipt_id}")
    restore_pairs: list[tuple[Path, Path, str]] = []
    for record in records:
        if not isinstance(record, dict):
            raise KnowledgeError(f"legacy trash receipt is invalid: {args.receipt_id}")
        original_raw = record.get("original")
        trashed_raw = record.get("trashed")
        if not isinstance(original_raw, str) or not isinstance(trashed_raw, str):
            raise KnowledgeError(f"legacy trash receipt is invalid: {args.receipt_id}")
        source = _resolve_library_path(root, trashed_raw)
        destination = _resolve_library_path(root, original_raw)
        if not source.is_file() or source.suffix.lower() != ".pdf":
            raise KnowledgeError(f"legacy trashed PDF is missing: {trashed_raw}")
        if destination.exists():
            raise KnowledgeError(f"restore destination already exists: {original_raw}")
        restore_pairs.append((source, destination, original_raw))
    _require_unique_paths(
        [pair[1] for pair in restore_pairs],
        label="restore destination",
    )
    restored: list[str] = []
    for source, destination, original_raw in restore_pairs:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        restored.append(original_raw)
    manifest_path.unlink()
    _remove_empty_parents(
        receipt_root,
        stop=root / _LEGACY_TRASH_DIR_NAME,
    )
    return {
        "status": "ok",
        "operation": "restore",
        "receipt_id": args.receipt_id,
        "restored": restored,
    }


def _operation_targets(root: Path, sources: list[Path], destination: Path) -> list[Path]:
    if len(sources) > 1:
        if not destination.is_dir():
            raise KnowledgeError("destination must be an existing directory for multiple files")
        return [destination / source.name for source in sources]
    if destination.is_dir():
        return [destination / sources[0].name]
    if destination.suffix.lower() != ".pdf":
        raise KnowledgeError("single-file destination must be a PDF path or directory")
    return [destination]


def _resolve_existing_pdf_or_directory(root: Path, raw: str) -> Path:
    path = _resolve_library_path(root, raw)
    if path.is_dir():
        return path
    if path.is_file() and path.suffix.lower() == ".pdf":
        return path
    raise KnowledgeError(f"library path is not a PDF or directory: {raw}")


def _resolve_existing_pdf(root: Path, raw: str) -> Path:
    path = _resolve_library_path(root, raw)
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise KnowledgeError(f"library path is not a PDF: {raw}")
    if _is_legacy_trash_path(root, path):
        raise KnowledgeError("legacy trash contents are not available to file operations")
    return path


def _resolve_library_path(root: Path, raw: str) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute():
        raise KnowledgeError("library_files paths must be relative to the PDF library")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise KnowledgeError(f"library path escapes the configured root: {raw}") from exc
    return resolved


def _entry_payload(root: Path, path: Path, *, include_hash: bool) -> dict[str, Any]:
    stat = path.stat()
    payload: dict[str, Any] = {
        "path": _relative(root, path),
        "kind": "directory" if path.is_dir() else "pdf",
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
    }
    if include_hash and path.is_file():
        payload["sha256"] = _sha256(path)
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    return str(relative) if relative.parts else "."


def _is_legacy_trash_path(root: Path, path: Path) -> bool:
    trash_root = root / _LEGACY_TRASH_DIR_NAME
    return path == trash_root or trash_root in path.parents


def _remove_empty_parents(path: Path, *, stop: Path) -> None:
    current = path
    while current != stop.parent and current.exists():
        try:
            current.rmdir()
        except OSError:
            return
        if current == stop:
            return
        current = current.parent


def _require_unique_paths(paths: list[Path], *, label: str) -> None:
    if len(paths) != len(set(paths)):
        raise KnowledgeError(f"duplicate {label} paths are not allowed")
