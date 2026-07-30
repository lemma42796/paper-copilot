from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import sysconfig
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from paper_copilot.agents.tools.runtimes import (
    LibraryEnvironment,
    LibraryProcessOutput,
)
from paper_copilot.session.paths import pdf_cache_dir
from paper_copilot.shared.errors import KnowledgeError
from paper_copilot.shared.logging import get_logger
from paper_copilot.shared.poppler import find_poppler_executable

_SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
_SHELL = Path("/bin/zsh")
_COMMAND_MAX_CHARS = 8_000
_DEFAULT_OUTPUT_MAX_TOKENS = 10_000
_MAX_OUTPUT_MAX_TOKENS = 10_000
_PAPER_CACHE_COMMAND_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.-])paper-cache(?![A-Za-z0-9_.-])"
)
_APPROX_BYTES_PER_TOKEN = 4
_DEFAULT_YIELD_TIME_MS = 10_000
_DEFAULT_STDIN_YIELD_TIME_MS = 5_000
_MIN_YIELD_TIME_MS = 250
_MAX_YIELD_TIME_MS = 30_000
_CPU_LIMIT_SECONDS = 35
_FILE_SIZE_LIMIT = "64m"
_SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
_OTOOL = Path("/usr/bin/otool")
_SCHEMA_VERSION = 3
_SANDBOX_POLICY_ID = "library_workspace_v3"
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
            "working directory contains read-only library/, cache/, and papers/ roots, "
            "read-only research-manifests/, plus a writable scratch/ directory. "
            "Network access and reads outside the "
            "authorized roots are blocked."
        ),
    )
    yield_time_ms: StrictInt = Field(
        default=_DEFAULT_YIELD_TIME_MS,
        ge=_MIN_YIELD_TIME_MS,
        le=_MAX_YIELD_TIME_MS,
        description=(
            "Wait before yielding a still-running command. If it remains active, "
            "the result returns a session_id for library_write_stdin."
        ),
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


class LibraryWriteStdinInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(
        min_length=16,
        max_length=64,
        description="Opaque session_id returned by library_exec.",
    )
    chars: str = Field(
        default="",
        max_length=8_000,
        description=(
            "Characters to write to the running command. Use an empty string to "
            "poll for more output."
        ),
    )
    yield_time_ms: StrictInt = Field(
        default=_DEFAULT_STDIN_YIELD_TIME_MS,
        ge=_MIN_YIELD_TIME_MS,
        le=_MAX_YIELD_TIME_MS,
        description="Wait before yielding another output chunk.",
    )
    max_output_tokens: StrictInt = Field(
        default=_DEFAULT_OUTPUT_MAX_TOKENS,
        ge=256,
        le=_MAX_OUTPUT_MAX_TOKENS,
        description="Output token budget for this interaction.",
    )


@dataclass(frozen=True, slots=True)
class _ResolvedCommand:
    argv: tuple[str, ...]
    source_cmd: str


@dataclass(frozen=True, slots=True)
class _FileSystemSandboxPolicy:
    readable_roots: tuple[Path, ...]
    writable_roots: tuple[Path, ...]
    external_executable_files: tuple[Path, ...]
    external_dependency_directories: tuple[Path, ...]
    denied_directories: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class _SandboxPolicy:
    file_system: _FileSystemSandboxPolicy
    network_access: bool


@dataclass(frozen=True, slots=True)
class _ExternalCommandSet:
    commands: tuple[tuple[str, Path], ...]
    sandbox_files: tuple[Path, ...]
    sandbox_directories: tuple[Path, ...]
    readable_directories: tuple[Path, ...]
    denied_directories: tuple[Path, ...]


def library_exec_tool_description() -> str:
    return (
        "Run a bounded command in a Codex-style macOS sandbox. The fixed logical "
        "workspace exposes the configured paper library as read-only library/, "
        "derived text cache as read-only cache/, short prepared-text aliases as "
        "read-only papers/, research-manifests/ as their machine-readable indexes, "
        "and only scratch/ as writable "
        "persistent storage for this conversation. Runtime provides prepared cache paths in "
        "research_cache_index. Read and search those page-delimited text files "
        "directly; the returned command output becomes model-visible evidence. "
        "paper-cache commands are not supported. The environment contains no user "
        "credentials; sandboxing "
        "blocks network access, library/cache writes, and reads outside authorized "
        "roots. A command still running after yield_time_ms returns a session_id; "
        "continue it with library_write_stdin. The tool has no permission-escalation path."
    )


def library_write_stdin_tool_description() -> str:
    return (
        "Write characters to, or poll, a running library_exec command. Pass the "
        "opaque session_id returned by library_exec. An empty chars value polls for "
        "new output. The original command keeps the same sandbox and authorization."
    )


async def run_library_exec(
    args: LibraryExecInput,
    library_root: Path | None,
    *,
    cache_root: Path | None = None,
    environment: LibraryEnvironment | None = None,
) -> LibraryExecRun:
    root = _resolve_library_root(library_root)
    resolved_cache_root = (
        pdf_cache_dir().expanduser().resolve()
        if cache_root is None
        else cache_root.expanduser().resolve()
    )
    resolved_command = _resolve_command(args.cmd)
    if _PAPER_CACHE_COMMAND_PATTERN.search(resolved_command.source_cmd):
        raise KnowledgeError(
            "paper-cache is not exposed through library_exec; use the Runtime "
            "research_cache_index and read its prepared text paths directly"
        )

    _require_macos_sandbox()
    _LOGGER.debug(
        "library_command_started",
        command_preview=args.cmd[:200],
        command_length=len(args.cmd),
        yield_time_ms=args.yield_time_ms,
    )
    temporary_directory: tempfile.TemporaryDirectory[str] | None = None
    if environment is None:
        temporary_directory = tempfile.TemporaryDirectory(
            prefix="paper-copilot-command-"
        )
        environment = LibraryEnvironment(Path(temporary_directory.name))
    external_commands = await asyncio.to_thread(_resolve_external_commands)
    visible_cache_root = environment.configure(
        library_root=root,
        cache_root=resolved_cache_root,
        external_commands=external_commands.commands,
    )
    sandbox_policy = _SandboxPolicy(
        file_system=_FileSystemSandboxPolicy(
            readable_roots=(
                root,
                visible_cache_root,
                environment.root,
                *external_commands.readable_directories,
            ),
            writable_roots=(environment.scratch,),
            external_executable_files=external_commands.sandbox_files,
            external_dependency_directories=external_commands.sandbox_directories,
            denied_directories=external_commands.denied_directories,
        ),
        network_access=False,
    )
    profile = _render_macos_seatbelt(sandbox_policy)
    profile_sha256 = hashlib.sha256(profile.encode("utf-8")).hexdigest()
    command_ref = _command_ref(resolved_command, _SANDBOX_POLICY_ID)
    process_output = await environment.exec(
        argv=resolved_command.argv,
        command=args.cmd,
        profile=profile,
        env=_command_environment(environment.scratch, environment.tool_bin),
        yield_time_ms=args.yield_time_ms,
    )
    if temporary_directory is not None:
        if process_output.session_id is not None:
            environment.terminate_all()
            raise KnowledgeError(
                "yielded library commands require a persistent LibraryEnvironment"
            )
        temporary_directory.cleanup()
    output_text, original_token_count = _bounded_process_output(
        process_output,
        args.max_output_tokens,
    )
    _LOGGER.debug(
        "library_command_finished",
        exit_code=process_output.exit_code,
        yielded=process_output.session_id is not None,
        wall_time_seconds=process_output.wall_time_seconds,
        output_bytes=process_output.total_output_bytes,
        output_omitted_bytes=process_output.output_omitted_bytes,
    )
    return LibraryExecRun(
        output=_model_output(
            output=output_text,
            exit_code=process_output.exit_code,
            wall_time_seconds=process_output.wall_time_seconds,
            session_id=process_output.session_id,
            chunk_id=process_output.chunk_id,
            original_token_count=original_token_count,
            output_omitted_bytes=process_output.output_omitted_bytes,
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
            "yield_time_ms": args.yield_time_ms,
            "yielded": process_output.session_id is not None,
            "session_id": process_output.session_id,
            "chunk_id": process_output.chunk_id,
            "exit_code": process_output.exit_code,
            "output_bytes": process_output.total_output_bytes,
            "output_omitted_bytes": process_output.output_omitted_bytes,
            "available_external_commands": [
                command_name for command_name, _executable in external_commands.commands
            ],
        },
    )


async def run_library_write_stdin(
    args: LibraryWriteStdinInput,
    *,
    environment: LibraryEnvironment,
) -> LibraryExecRun:
    process_output = await environment.write_stdin(
        session_id=args.session_id,
        chars=args.chars,
        yield_time_ms=args.yield_time_ms,
    )
    output_text, original_token_count = _bounded_process_output(
        process_output,
        args.max_output_tokens,
    )
    return LibraryExecRun(
        output=_model_output(
            output=output_text,
            exit_code=process_output.exit_code,
            wall_time_seconds=process_output.wall_time_seconds,
            session_id=process_output.session_id,
            chunk_id=process_output.chunk_id,
            original_token_count=original_token_count,
            output_omitted_bytes=process_output.output_omitted_bytes,
        ),
        trace_attributes={
            "library_exec_schema_version": _SCHEMA_VERSION,
            "interaction": "write_stdin" if args.chars else "poll",
            "session_id": args.session_id,
            "chunk_id": process_output.chunk_id,
            "yield_time_ms": args.yield_time_ms,
            "yielded": process_output.session_id is not None,
            "exit_code": process_output.exit_code,
            "output_bytes": process_output.total_output_bytes,
            "output_omitted_bytes": process_output.output_omitted_bytes,
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
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _resolve_external_commands() -> _ExternalCommandSet:
    commands: list[tuple[str, Path]] = []
    sandbox_files: set[Path] = set()
    sandbox_directories: set[Path] = set()
    readable_directories: set[Path] = set()
    denied_directories: set[Path] = set()
    for command_name in ("rg", "pdfinfo", "pdftotext", "python"):
        executable = (
            find_poppler_executable(command_name)
            if command_name in {"pdfinfo", "pdftotext"}
            else (
                Path(sys.executable).expanduser().resolve()
                if command_name == "python"
                else _first_external_command_candidate(command_name)
            )
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
        command_aliases = (
            (command_name, "python3")
            if command_name == "python"
            else (command_name,)
        )
        commands.extend(
            (command_alias, executable)
            for command_alias in command_aliases
        )
        sandbox_files.update(command_files)
        sandbox_directories.update(path.parent for path in command_files)
        if command_name == "python":
            readable_directories.add(
                Path(sysconfig.get_path("stdlib")).expanduser().resolve()
            )
            for scheme_name in ("purelib", "platlib"):
                scheme_path = sysconfig.get_path(scheme_name)
                if scheme_path:
                    denied_directories.add(
                        Path(scheme_path).expanduser().resolve()
                    )
    return _ExternalCommandSet(
        commands=tuple(commands),
        sandbox_files=tuple(sorted(sandbox_files)),
        sandbox_directories=tuple(sorted(sandbox_directories)),
        readable_directories=tuple(sorted(readable_directories)),
        denied_directories=tuple(sorted(denied_directories)),
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


def _model_output(
    *,
    output: str,
    exit_code: int | None,
    wall_time_seconds: float,
    session_id: str | None,
    chunk_id: str,
    original_token_count: int | None,
    output_omitted_bytes: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "wall_time_seconds": round(wall_time_seconds, 3),
        "exit_code": exit_code,
        "output": output,
        "session_id": session_id,
        "chunk_id": chunk_id,
    }
    if original_token_count is not None:
        payload["original_token_count"] = original_token_count
    if output_omitted_bytes:
        payload["output_omitted_bytes"] = output_omitted_bytes
    return payload


def _bounded_process_output(
    process_output: LibraryProcessOutput,
    max_output_tokens: int,
) -> tuple[str, int | None]:
    raw_text = process_output.output.decode("utf-8", errors="replace")
    output_text, token_count = _truncate_for_token_budget(
        raw_text,
        max_output_tokens,
    )
    return (
        output_text,
        _original_token_count(
            token_count,
            total_bytes=process_output.total_output_bytes,
            omitted_bytes=process_output.output_omitted_bytes,
        ),
    )


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
    denied_directories = "\n".join(
        f"(deny file-read* file-test-existence (subpath {_sandbox_string(path)}))"
        for path in policy.file_system.denied_directories
    )
    return f"""\
(version 1)
(deny default)

{denied_directories}

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
