from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from paper_copilot.session.paths import pdf_cache_dir
from paper_copilot.shared.errors import KnowledgeError, PaperCopilotError
from paper_copilot.shared.logging import get_logger
from paper_copilot.shared.pdf_cache import PdfCacheLookup, PdfTextCache
from paper_copilot.shared.poppler import find_poppler_executable

_SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
_SHELL = Path("/bin/zsh")
_COMMAND_MAX_CHARS = 8_000
_RAW_OUTPUT_MAX_BYTES = 64_000
_DEFAULT_OUTPUT_MAX_TOKENS = 10_000
_MAX_OUTPUT_MAX_TOKENS = 10_000
_PAPER_CACHE_COMMAND_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.-])paper-cache(?![A-Za-z0-9_.-])"
)
_APPROX_BYTES_PER_TOKEN = 4
_READ_CHUNK_BYTES = 8_192
_DEFAULT_TIMEOUT_MS = 15_000
_MAX_TIMEOUT_MS = 30_000
_CPU_LIMIT_SECONDS = 35
_FILE_SIZE_LIMIT = "64m"
_SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
_OTOOL = Path("/usr/bin/otool")
_SCHEMA_VERSION = 2
_SANDBOX_POLICY_ID = "library_workspace_v2"
_BROKER_POLICY_ID = "paper_cache_broker_v1"
_RESOURCE_WRAPPER = (
    "setopt errexit; "
    f"limit -h cputime {_CPU_LIMIT_SECONDS}; "
    f"limit cputime {_CPU_LIMIT_SECONDS}; "
    f"limit -h filesize {_FILE_SIZE_LIMIT}; "
    f"limit filesize {_FILE_SIZE_LIMIT}; "
    'exec /bin/zsh -f -c "$1"'
)
_LOGGER = get_logger(__name__)


class LibraryExecInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cmd: str = Field(
        min_length=1,
        max_length=_COMMAND_MAX_CHARS,
        description=(
            "Shell command to run in a bounded Codex-style sandbox. The fixed logical "
            "working directory contains read-only library/ and cache/ roots plus a "
            "writable scratch/ directory. Network access and reads outside the "
            "authorized roots are blocked."
        ),
    )
    timeout_ms: StrictInt = Field(
        default=_DEFAULT_TIMEOUT_MS,
        ge=1_000,
        le=_MAX_TIMEOUT_MS,
        description="Hard execution deadline in milliseconds.",
    )
    max_output_tokens: StrictInt = Field(
        default=_DEFAULT_OUTPUT_MAX_TOKENS,
        ge=256,
        le=_MAX_OUTPUT_MAX_TOKENS,
        description=(
            "Output token budget. Defaults to 10000 tokens; larger requests are "
            "capped by policy."
        ),
    )

    @field_validator("cmd")
    @classmethod
    def _command_has_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("cmd must contain a non-whitespace character")
        if "\x00" in value:
            raise ValueError("cmd must not contain NUL bytes")
        return value


@dataclass(frozen=True, slots=True)
class LibraryExecRun:
    output: dict[str, Any]
    trace_attributes: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _ResolvedCommand:
    argv: tuple[str, ...]
    source_cmd: str


@dataclass(frozen=True, slots=True)
class _PaperCacheCommand:
    operation: str
    arguments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _FileSystemSandboxPolicy:
    readable_roots: tuple[Path, ...]
    writable_roots: tuple[Path, ...]
    external_executable_files: tuple[Path, ...]
    external_dependency_directories: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class _SandboxPolicy:
    file_system: _FileSystemSandboxPolicy
    network_access: bool


@dataclass(frozen=True, slots=True)
class _ExternalCommandSet:
    commands: tuple[tuple[str, Path], ...]
    sandbox_files: tuple[Path, ...]
    sandbox_directories: tuple[Path, ...]


class _HeadTailBuffer:
    def __init__(self, max_bytes: int) -> None:
        self._max_bytes = max_bytes
        self._head_budget = max_bytes // 2
        self._tail_budget = max_bytes - self._head_budget
        self._head = bytearray()
        self._tail: deque[int] = deque()
        self._omitted_bytes = 0

    @property
    def omitted_bytes(self) -> int:
        return self._omitted_bytes

    @property
    def total_bytes(self) -> int:
        return len(self._head) + len(self._tail) + self._omitted_bytes

    def push(self, chunk: bytes) -> None:
        if not chunk:
            return
        remaining_head = self._head_budget - len(self._head)
        head_length = min(remaining_head, len(chunk))
        if head_length:
            self._head.extend(chunk[:head_length])
        self._push_tail(chunk[head_length:])

    def text(self) -> str:
        if self._omitted_bytes == 0:
            raw_output = bytes(self._head) + bytes(self._tail)
        else:
            marker = (
                f"\n[... omitted {self._omitted_bytes} bytes from command output ...]\n"
            ).encode()
            raw_output = bytes(self._head) + marker + bytes(self._tail)
        return raw_output.decode("utf-8", errors="replace")

    def _push_tail(self, chunk: bytes) -> None:
        if not chunk:
            return
        if self._tail_budget == 0:
            self._omitted_bytes += len(chunk)
            return
        if len(chunk) >= self._tail_budget:
            kept = chunk[-self._tail_budget :]
            self._omitted_bytes += len(self._tail) + len(chunk) - len(kept)
            self._tail.clear()
            self._tail.extend(kept)
            return
        self._tail.extend(chunk)
        excess = len(self._tail) - self._tail_budget
        if excess > 0:
            for _ in range(excess):
                self._tail.popleft()
            self._omitted_bytes += excess


def library_exec_tool_description() -> str:
    return (
        "Run a bounded command in a Codex-style macOS sandbox. The fixed logical "
        "workspace exposes the configured paper library as read-only library/, "
        "derived text cache as read-only cache/, and only scratch/ as writable "
        "temporary storage. Runtime normally provides prepared cache paths in "
        "research_cache_index; paper-cache remains available for bounded page reads "
        "and on-demand preparation outside that index. The environment contains no "
        "user credentials; sandboxing "
        "blocks network access, library/cache writes, and reads outside authorized "
        "roots. The tool has no permission-escalation path."
    )


async def run_library_exec(
    args: LibraryExecInput,
    library_root: Path | None,
) -> LibraryExecRun:
    root = _resolve_library_root(library_root)
    cache_root = pdf_cache_dir().expanduser().resolve()
    resolved_command = _resolve_command(args.cmd)
    paper_cache_command = _intercept_paper_cache(resolved_command)
    if paper_cache_command is not None:
        return await _run_paper_cache_command(
            paper_cache_command,
            resolved_command=resolved_command,
            args=args,
            library_root=root,
            cache_root=cache_root,
        )

    _require_macos_sandbox()
    started = time.monotonic()
    _LOGGER.debug(
        "library_command_started",
        command_preview=args.cmd[:200],
        command_length=len(args.cmd),
        timeout_ms=args.timeout_ms,
    )
    with tempfile.TemporaryDirectory(prefix="paper-copilot-command-") as raw_runtime:
        runtime_root = Path(raw_runtime).resolve()
        workspace = runtime_root / "workspace"
        scratch = runtime_root / "scratch"
        empty_cache = runtime_root / "empty-cache"
        tool_bin = runtime_root / "bin"
        workspace.mkdir()
        scratch.mkdir()
        empty_cache.mkdir()
        tool_bin.mkdir()
        external_commands = await asyncio.to_thread(_resolve_external_commands)
        for command_name, executable in external_commands.commands:
            (tool_bin / command_name).symlink_to(executable)
        (workspace / "library").symlink_to(root, target_is_directory=True)
        visible_cache_root = cache_root if cache_root.is_dir() else empty_cache
        (workspace / "cache").symlink_to(
            visible_cache_root,
            target_is_directory=True,
        )
        (workspace / "scratch").symlink_to(scratch, target_is_directory=True)

        sandbox_policy = _SandboxPolicy(
            file_system=_FileSystemSandboxPolicy(
                readable_roots=(root, visible_cache_root, runtime_root),
                writable_roots=(scratch,),
                external_executable_files=external_commands.sandbox_files,
                external_dependency_directories=(
                    external_commands.sandbox_directories
                ),
            ),
            network_access=False,
        )
        profile = _render_macos_seatbelt(sandbox_policy)
        profile_sha256 = hashlib.sha256(profile.encode("utf-8")).hexdigest()
        command_ref = _command_ref(resolved_command, _SANDBOX_POLICY_ID)
        process = await asyncio.create_subprocess_exec(
            str(_SANDBOX_EXEC),
            "-p",
            profile,
            *resolved_command.argv,
            cwd=workspace,
            env=_command_environment(scratch, tool_bin),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        if process.stdout is None or process.stderr is None:
            raise KnowledgeError("library command did not create output pipes")
        output_buffer = _HeadTailBuffer(_RAW_OUTPUT_MAX_BYTES)
        stdout_task = asyncio.create_task(
            _capture_stream(process.stdout, output_buffer)
        )
        stderr_task = asyncio.create_task(
            _capture_stream(process.stderr, output_buffer)
        )
        wait_task = asyncio.create_task(process.wait())
        try:
            done, _pending = await asyncio.wait(
                {wait_task},
                timeout=args.timeout_ms / 1_000,
            )
            timed_out = wait_task not in done
            if timed_out:
                os.killpg(process.pid, signal.SIGKILL)
            exit_code = await wait_task
            await asyncio.gather(stdout_task, stderr_task)
        finally:
            if process.returncode is None:
                os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
            for task in (stdout_task, stderr_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(
                stdout_task,
                stderr_task,
                return_exceptions=True,
            )

    wall_time_seconds = time.monotonic() - started
    raw_text = output_buffer.text()
    if timed_out:
        timeout_notice = (
            f"Command timed out after {args.timeout_ms} milliseconds."
        )
        raw_text = f"{raw_text}\n{timeout_notice}".lstrip()
    output_text, token_count = _truncate_for_token_budget(
        raw_text,
        args.max_output_tokens,
    )
    original_token_count = _original_token_count(
        token_count,
        total_bytes=output_buffer.total_bytes,
        omitted_bytes=output_buffer.omitted_bytes,
    )
    _LOGGER.debug(
        "library_command_finished",
        exit_code=exit_code,
        timed_out=timed_out,
        wall_time_seconds=wall_time_seconds,
        output_bytes=output_buffer.total_bytes,
        output_omitted_bytes=output_buffer.omitted_bytes,
    )
    return LibraryExecRun(
        output=_model_output(
            output=output_text,
            exit_code=exit_code,
            wall_time_seconds=wall_time_seconds,
            timed_out=timed_out,
            original_token_count=original_token_count,
            output_omitted_bytes=output_buffer.omitted_bytes,
        ),
        trace_attributes={
            "library_exec_schema_version": _SCHEMA_VERSION,
            "command": args.cmd,
            "resolved_command": list(resolved_command.argv),
            "command_ref": command_ref,
            "cwd": "workspace",
            "sandbox_policy": _SANDBOX_POLICY_ID,
            "sandbox_profile_sha256": profile_sha256,
            "network_access": False,
            "timeout_ms": args.timeout_ms,
            "timed_out": timed_out,
            "exit_code": exit_code,
            "output_bytes": output_buffer.total_bytes,
            "output_omitted_bytes": output_buffer.omitted_bytes,
            "available_external_commands": [
                command_name for command_name, _executable in external_commands.commands
            ],
        },
    )


def _resolve_library_root(library_root: Path | None) -> Path:
    if library_root is None:
        raise KnowledgeError("library_exec requires a configured PDF library")
    root = library_root.expanduser().resolve()
    if not root.is_dir():
        raise KnowledgeError(f"PDF library does not exist: {root}")
    return root


def _require_macos_sandbox() -> None:
    if sys.platform != "darwin":
        raise KnowledgeError("library_exec currently requires the macOS sandbox")
    if not _SANDBOX_EXEC.is_file():
        raise KnowledgeError(f"macOS sandbox executable is missing: {_SANDBOX_EXEC}")
    if not _SHELL.is_file():
        raise KnowledgeError(f"command shell is missing: {_SHELL}")


def _resolve_command(command: str) -> _ResolvedCommand:
    return _ResolvedCommand(
        argv=(
            str(_SHELL),
            "-f",
            "-c",
            _RESOURCE_WRAPPER,
            "--",
            command,
        ),
        source_cmd=command,
    )


def _command_environment(scratch: Path, tool_bin: Path) -> dict[str, str]:
    return {
        "NO_COLOR": "1",
        "TERM": "dumb",
        "LANG": "C.UTF-8",
        "LC_CTYPE": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "COLORTERM": "",
        "PAGER": "cat",
        "GIT_PAGER": "cat",
        "GH_PAGER": "cat",
        "PATH": f"{tool_bin}:{_SYSTEM_PATH}",
        "TMPDIR": str(scratch),
    }


def _resolve_external_commands() -> _ExternalCommandSet:
    commands: list[tuple[str, Path]] = []
    sandbox_files: set[Path] = set()
    sandbox_directories: set[Path] = set()
    for command_name in ("rg", "pdfinfo", "pdftotext"):
        executable = (
            find_poppler_executable(command_name)
            if command_name in {"pdfinfo", "pdftotext"}
            else _first_external_command_candidate(command_name)
        )
        if executable is None:
            continue
        try:
            command_files = _macho_dependency_files(executable)
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            _LOGGER.warning(
                "library_external_command_unavailable",
                command=command_name,
                error_type=error.__class__.__name__,
            )
            continue
        commands.append((command_name, executable))
        sandbox_files.update(command_files)
        sandbox_directories.update(path.parent for path in command_files)
    return _ExternalCommandSet(
        commands=tuple(commands),
        sandbox_files=tuple(sorted(sandbox_files)),
        sandbox_directories=tuple(sorted(sandbox_directories)),
    )


def _first_external_command_candidate(command_name: str) -> Path | None:
    bundled_candidate = Path(sys.executable).resolve().parent / "bin" / command_name
    candidates = (
        bundled_candidate,
        Path("/opt/homebrew/bin") / command_name,
        Path("/usr/local/bin") / command_name,
    )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    return None


def _macho_dependency_files(executable: Path) -> tuple[Path, ...]:
    pending = [executable]
    inspected: set[Path] = set()
    sandbox_files: set[Path] = set()
    while pending:
        object_path = pending.pop()
        resolved_object = object_path.resolve(strict=True)
        if resolved_object in inspected:
            continue
        inspected.add(resolved_object)
        sandbox_files.update(_path_resolution_chain(object_path))
        for dependency in _otool_dependencies(resolved_object):
            dependency_path = _resolve_macho_dependency(
                dependency,
                object_path=resolved_object,
                main_executable=executable,
            )
            if dependency_path is None:
                continue
            normalized_dependency = Path(os.path.normpath(str(dependency_path)))
            resolved_dependency = normalized_dependency.resolve(strict=True)
            sandbox_files.update(_path_resolution_chain(normalized_dependency))
            pending.append(resolved_dependency)
    return tuple(sorted(sandbox_files))


def _path_resolution_chain(path: Path) -> tuple[Path, ...]:
    normalized_path = Path(os.path.normpath(str(path)))
    if not normalized_path.is_absolute():
        raise ValueError(f"Mach-O dependency path must be absolute: {path}")
    chain: set[Path] = {normalized_path}
    current = Path(normalized_path.anchor)
    for part in normalized_path.parts[1:]:
        candidate = current / part
        if candidate.is_symlink():
            chain.add(candidate)
            target = Path(os.readlink(candidate))
            current = (
                target
                if target.is_absolute()
                else Path(os.path.normpath(str(candidate.parent / target)))
            )
        else:
            current = candidate
    chain.add(current)
    return tuple(sorted(chain))


@lru_cache(maxsize=256)
def _otool_dependencies(object_path: Path) -> tuple[str, ...]:
    completed = _run_otool("-L", object_path)
    return tuple(
        line.strip().split(" (", 1)[0]
        for line in completed.stdout.splitlines()[1:]
        if line.startswith("\t")
    )


@lru_cache(maxsize=256)
def _otool_rpaths(object_path: Path) -> tuple[str, ...]:
    completed = _run_otool("-l", object_path)
    rpaths: list[str] = []
    waiting_for_path = False
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if stripped == "cmd LC_RPATH":
            waiting_for_path = True
        elif waiting_for_path and stripped.startswith("path "):
            rpaths.append(stripped.removeprefix("path ").split(" (offset", 1)[0])
            waiting_for_path = False
    return tuple(rpaths)


def _run_otool(option: str, object_path: Path) -> subprocess.CompletedProcess[str]:
    if not _OTOOL.is_file():
        raise OSError(f"Mach-O dependency inspector is missing: {_OTOOL}")
    return subprocess.run(
        [str(_OTOOL), option, str(object_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
        env={
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": _SYSTEM_PATH,
        },
    )


def _resolve_macho_dependency(
    dependency: str,
    *,
    object_path: Path,
    main_executable: Path,
) -> Path | None:
    if dependency.startswith(("/System/", "/usr/lib/")):
        return None
    if dependency.startswith("@loader_path/"):
        return object_path.parent / dependency.removeprefix("@loader_path/")
    if dependency.startswith("@executable_path/"):
        return main_executable.parent / dependency.removeprefix("@executable_path/")
    if dependency.startswith("@rpath/"):
        suffix = dependency.removeprefix("@rpath/")
        for raw_rpath in _otool_rpaths(object_path):
            rpath = _expand_macho_loader_path(
                raw_rpath,
                object_path=object_path,
                main_executable=main_executable,
            )
            candidate = Path(os.path.normpath(str(rpath / suffix)))
            if candidate.exists():
                return candidate
        raise ValueError(
            f"unable to resolve Mach-O dependency {dependency!r} for {object_path}"
        )
    if dependency.startswith("/"):
        return Path(dependency)
    raise ValueError(
        f"unsupported Mach-O dependency {dependency!r} for {object_path}"
    )


def _expand_macho_loader_path(
    path: str,
    *,
    object_path: Path,
    main_executable: Path,
) -> Path:
    if path == "@loader_path":
        return object_path.parent
    if path.startswith("@loader_path/"):
        return object_path.parent / path.removeprefix("@loader_path/")
    if path == "@executable_path":
        return main_executable.parent
    if path.startswith("@executable_path/"):
        return main_executable.parent / path.removeprefix("@executable_path/")
    if path.startswith("/"):
        return Path(path)
    raise ValueError(f"unsupported Mach-O rpath {path!r} for {object_path}")


def _intercept_paper_cache(
    resolved_command: _ResolvedCommand,
) -> _PaperCacheCommand | None:
    try:
        arguments = shlex.split(resolved_command.source_cmd, posix=True)
    except ValueError as error:
        if _PAPER_CACHE_COMMAND_PATTERN.search(resolved_command.source_cmd):
            raise KnowledgeError(f"invalid paper-cache command: {error}") from error
        return None
    if not arguments or arguments[0] != "paper-cache":
        if _PAPER_CACHE_COMMAND_PATTERN.search(resolved_command.source_cmd):
            raise KnowledgeError(
                "paper-cache must be the entire library_exec cmd; do not place it "
                "inside a shell loop, pipeline, chained command, substitution, or "
                "find -exec"
            )
        return None
    if len(arguments) < 2:
        raise KnowledgeError("paper-cache requires status, ensure, or page")
    return _PaperCacheCommand(
        operation=arguments[1],
        arguments=tuple(arguments[2:]),
    )


async def _run_paper_cache_command(
    command: _PaperCacheCommand,
    *,
    resolved_command: _ResolvedCommand,
    args: LibraryExecInput,
    library_root: Path,
    cache_root: Path,
) -> LibraryExecRun:
    started = time.monotonic()
    command_ref = _command_ref(resolved_command, _BROKER_POLICY_ID)
    cache = PdfTextCache(cache_root)
    artifacts: list[str] = []
    timed_out = False
    exit_code: int | None = 0
    try:
        async with asyncio.timeout(args.timeout_ms / 1_000):
            match command.operation, command.arguments:
                case ("status", (relative_pdf,)):
                    pdf_path, _source_locator = _resolve_library_pdf(
                        library_root,
                        relative_pdf,
                    )
                    payload = _cache_lookup_payload(await cache.status(pdf_path))
                case ("ensure", (relative_pdf,)):
                    pdf_path, source_locator = _resolve_library_pdf(
                        library_root,
                        relative_pdf,
                    )
                    payload = _cache_lookup_payload(
                        await cache.ensure(
                            pdf_path,
                            source_locator=source_locator,
                        )
                    )
                case ("page", (paper_id, raw_page)):
                    try:
                        page_number = int(raw_page)
                    except ValueError as error:
                        raise KnowledgeError(
                            "paper-cache page requires an integer page number"
                        ) from error
                    cache_page = await cache.page_for_paper_id(
                        paper_id,
                        page=page_number,
                    )
                    payload = cache_page.model_dump(mode="json")
                case _:
                    raise KnowledgeError(
                        "usage: paper-cache status <relative-pdf> | "
                        "paper-cache ensure <relative-pdf> | "
                        "paper-cache page <paper-id> <page>"
                    )
        artifact_ref = _artifact_ref(payload)
        if artifact_ref is not None:
            artifacts.append(artifact_ref)
        raw_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except TimeoutError:
        timed_out = True
        exit_code = None
        raw_text = f"paper-cache timed out after {args.timeout_ms} milliseconds"
    except (PaperCopilotError, OSError, ValueError) as error:
        exit_code = 1
        raw_text = str(error)

    wall_time_seconds = time.monotonic() - started
    output_text, original_token_count = _truncate_for_token_budget(
        raw_text,
        args.max_output_tokens,
    )
    return LibraryExecRun(
        output=_model_output(
            output=output_text,
            exit_code=exit_code,
            wall_time_seconds=wall_time_seconds,
            timed_out=timed_out,
            original_token_count=original_token_count,
            output_omitted_bytes=0,
        ),
        trace_attributes={
            "library_exec_schema_version": _SCHEMA_VERSION,
            "command": args.cmd,
            "resolved_command": list(resolved_command.argv),
            "command_ref": command_ref,
            "cwd": "workspace",
            "sandbox_policy": _BROKER_POLICY_ID,
            "network_access": False,
            "timeout_ms": args.timeout_ms,
            "timed_out": timed_out,
            "exit_code": exit_code,
            "artifacts": artifacts,
            "paper_cache_operation": command.operation,
        },
    )


def _resolve_library_pdf(
    library_root: Path,
    relative_pdf: str,
) -> tuple[Path, str]:
    locator = Path(relative_pdf)
    if locator.is_absolute() or ".." in locator.parts:
        raise KnowledgeError(
            "paper-cache requires a PDF path relative to the authorized library"
        )
    if locator.parts[:1] == ("library",):
        locator = Path(*locator.parts[1:])
    if not locator.parts:
        raise KnowledgeError("paper-cache requires a PDF path")
    candidate = (library_root / locator).resolve()
    try:
        source_locator = candidate.relative_to(library_root).as_posix()
    except ValueError as error:
        raise KnowledgeError("PDF path resolves outside the authorized library") from error
    if candidate.suffix.lower() != ".pdf" or not candidate.is_file():
        raise KnowledgeError("paper-cache target must be an existing PDF")
    return candidate, source_locator


def _cache_lookup_payload(lookup: PdfCacheLookup) -> dict[str, Any]:
    return lookup.model_dump(mode="json", exclude_none=True)


def _artifact_ref(payload: dict[str, Any]) -> str | None:
    cache_ref = payload.get("cache_ref")
    if isinstance(cache_ref, dict):
        pdf_sha256 = cache_ref.get("pdf_sha256")
        extractor_fingerprint = cache_ref.get("extractor_fingerprint")
        revision_id = cache_ref.get("revision_id")
        if all(
            isinstance(value, str)
            for value in (pdf_sha256, extractor_fingerprint, revision_id)
        ):
            return (
                f"paper-cache:{pdf_sha256}:{extractor_fingerprint}:{revision_id}"
            )
    artifact_sha256 = payload.get("artifact_sha256")
    paper_id = payload.get("paper_id")
    page = payload.get("page")
    if (
        isinstance(artifact_sha256, str)
        and isinstance(paper_id, str)
        and isinstance(page, int)
    ):
        return f"paper-cache:{paper_id}:page:{page}:{artifact_sha256}"
    return None


def _model_output(
    *,
    output: str,
    exit_code: int | None,
    wall_time_seconds: float,
    timed_out: bool,
    original_token_count: int | None,
    output_omitted_bytes: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "wall_time_seconds": round(wall_time_seconds, 3),
        "exit_code": exit_code,
        "output": output,
    }
    if timed_out:
        payload["timed_out"] = True
    if original_token_count is not None:
        payload["original_token_count"] = original_token_count
    if output_omitted_bytes:
        payload["output_omitted_bytes"] = output_omitted_bytes
    return payload


def _truncate_for_token_budget(
    text: str,
    max_tokens: int,
) -> tuple[str, int | None]:
    max_bytes = max_tokens * _APPROX_BYTES_PER_TOKEN
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, None
    original_token_count = _approx_tokens_from_bytes(len(encoded))
    head_budget = max_bytes // 2
    tail_budget = max_bytes - head_budget
    head = encoded[:head_budget].decode("utf-8", errors="ignore")
    tail = encoded[-tail_budget:].decode("utf-8", errors="ignore")
    marker = (
        "Warning: truncated output "
        f"(original token count: {original_token_count})"
    )
    return (
        f"{marker}\n\n{head}\n[... truncated middle output ...]\n{tail}",
        original_token_count,
    )


def _original_token_count(
    token_truncation_count: int | None,
    *,
    total_bytes: int,
    omitted_bytes: int,
) -> int | None:
    if token_truncation_count is not None:
        return token_truncation_count
    if omitted_bytes:
        return _approx_tokens_from_bytes(total_bytes)
    return None


def _approx_tokens_from_bytes(byte_count: int) -> int:
    return (byte_count + _APPROX_BYTES_PER_TOKEN - 1) // _APPROX_BYTES_PER_TOKEN


def _command_ref(
    resolved_command: _ResolvedCommand,
    sandbox_policy_id: str,
) -> str:
    payload = json.dumps(
        {
            "schema_version": _SCHEMA_VERSION,
            "command": resolved_command.argv,
            "cwd": "workspace",
            "sandbox_policy_id": sandbox_policy_id,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


async def _capture_stream(
    stream: asyncio.StreamReader,
    output_buffer: _HeadTailBuffer,
) -> None:
    while chunk := await stream.read(_READ_CHUNK_BYTES):
        output_buffer.push(chunk)


def _render_macos_seatbelt(policy: _SandboxPolicy) -> str:
    readable_roots = "\n".join(
        f"  (subpath {_sandbox_string(path)})"
        for path in policy.file_system.readable_roots
    )
    writable_roots = "\n".join(
        f"  (subpath {_sandbox_string(path)})"
        for path in policy.file_system.writable_roots
    )
    external_executable_files = "\n".join(
        f"  (literal {_sandbox_string(path)})"
        for path in policy.file_system.external_executable_files
    )
    external_dependency_directories = "\n".join(
        f"  (literal {_sandbox_string(path)})"
        for path in policy.file_system.external_dependency_directories
    )
    external_dependency_policy = (
        "(allow file-read* file-test-existence\n"
        f"{external_dependency_directories})"
        if external_dependency_directories
        else ""
    )
    root_ancestors = "\n".join(
        f"  (path-ancestors {_sandbox_string(path)})"
        for path in (
            *policy.file_system.readable_roots,
            *policy.file_system.writable_roots,
            *policy.file_system.external_executable_files,
            *policy.file_system.external_dependency_directories,
        )
    )
    network_policy = "(allow network*)" if policy.network_access else ""
    return f"""\
(version 1)
(deny default)

(allow process-exec)
(allow process-fork)
(allow signal (target same-sandbox))
(allow process-info* (target same-sandbox))

(allow sysctl-read)
(allow system-mac-syscall (mac-policy-name "vnguard"))
(allow system-mac-syscall
  (require-all
    (mac-policy-name "Sandbox")
    (mac-syscall-number 67)))

(allow file-read* file-test-existence
  (subpath "/System")
  (subpath "/Library/Apple")
  (subpath "/Library/Filesystems/NetFSPlugins")
  (subpath "/Library/Preferences/Logging")
  (subpath "/usr/bin")
  (subpath "/usr/lib")
  (subpath "/usr/libexec")
  (subpath "/usr/sbin")
  (subpath "/usr/share")
  (subpath "/bin")
  (subpath "/sbin")
  (subpath "/private/etc")
  (subpath "/private/var/db/timezone")
{external_executable_files}
{readable_roots})

{external_dependency_policy}

(allow file-read-metadata file-test-existence
  (literal "/")
  (literal "/Users")
  (literal "/private")
  (literal "/private/var")
  (literal "/private/var/folders")
{root_ancestors})

; Allow processes to resolve their current working directory.
(allow file-read* file-test-existence
  (literal "/"))

(allow file-map-executable
  (subpath "/System")
  (subpath "/Library/Apple")
  (subpath "/usr/bin")
  (subpath "/usr/lib")
  (subpath "/usr/libexec")
  (subpath "/usr/sbin")
  (subpath "/bin")
  (subpath "/sbin")
{external_executable_files})

(allow file-read* file-test-existence file-write* file-ioctl
{writable_roots}
  (literal "/dev/null")
  (literal "/dev/zero")
  (subpath "/dev/fd"))

(allow file-read-metadata file-test-existence
  (literal "/dev")
  (literal "/dev/stdin")
  (literal "/dev/stdout")
  (literal "/dev/stderr"))

(allow mach-lookup
  (global-name "com.apple.system.opendirectoryd.libinfo")
  (global-name "com.apple.system.opendirectoryd.membership"))

{network_policy}
"""


def _sandbox_string(path: Path) -> str:
    return json.dumps(str(path), ensure_ascii=False)
