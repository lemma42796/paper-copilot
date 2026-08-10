from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import sysconfig
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from paper_copilot.agents.tools.runtimes import (
    LibraryEnvironment,
    LibraryProcessOutput,
)
from paper_copilot.session.paths import pdf_cache_dir
from paper_copilot.shared.errors import KnowledgeError, PaperCopilotError
from paper_copilot.shared.logging import get_logger
from paper_copilot.shared.pdf_cache import PdfCacheLookup, PdfTextCache
from paper_copilot.shared.poppler import find_poppler_executable

_SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
_SHELL = Path("/bin/zsh")
_COMMAND_MAX_CHARS = 8_000
_APPROX_BYTES_PER_TOKEN = 4
_DEFAULT_OUTPUT_MAX_TOKENS = 10_000
_OUTPUT_COLLECTION_MAX_BYTES = 1024 * 1024
_OUTPUT_COLLECTION_MAX_TOKENS = (
    _OUTPUT_COLLECTION_MAX_BYTES // _APPROX_BYTES_PER_TOKEN
)
_PAPER_READ_COMMAND_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.-])paper[ \t]+(?:read|search)(?![A-Za-z0-9_.-])"
)
_DEFAULT_YIELD_TIME_MS = 10_000
_DEFAULT_STDIN_YIELD_TIME_MS = 5_000
_MIN_YIELD_TIME_MS = 250
_MAX_YIELD_TIME_MS = 30_000
_DEFAULT_TIMEOUT_MS = 20 * 60 * 1_000
_MAX_TIMEOUT_MS = 60 * 60 * 1_000
_CPU_LIMIT_SECONDS = 35
_FILE_SIZE_LIMIT = "64m"
_SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
_OTOOL = Path("/usr/bin/otool")
_SCHEMA_VERSION = 5
_SANDBOX_POLICY_ID = "library_workspace_v4"
_ADDITIONAL_SANDBOX_POLICY_ID = "library_workspace_additional_v1"
_ESCALATED_POLICY_ID = "library_require_escalated_v1"
_BROKER_POLICY_ID = "paper_cache_broker_v2"
_BROKER_TIMEOUT_SECONDS = 120
_RESOURCE_WRAPPER = (
    "setopt errexit; "
    f"limit -h cputime {_CPU_LIMIT_SECONDS}; "
    f"limit cputime {_CPU_LIMIT_SECONDS}; "
    f"limit -h filesize {_FILE_SIZE_LIMIT}; "
    f"limit filesize {_FILE_SIZE_LIMIT}; "
    'exec /bin/zsh -f -o pipefail -c "$1"'
)
_ESCALATED_WRAPPER = 'exec /bin/zsh -f -o pipefail -c "$1"'
_LOGGER = get_logger(__name__)

SandboxPermissions = Literal[
    "use_default",
    "with_additional_permissions",
    "require_escalated",
]


class NetworkPermissions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description="True requests network access; false or omitted requests none.",
    )


class FileSystemPermissions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read: list[str] = Field(
        default_factory=list,
        max_length=16,
        description="Absolute paths to grant read access; omit when none are needed.",
    )
    write: list[str] = Field(
        default_factory=list,
        max_length=16,
        description="Absolute paths to grant write access; omit when none are needed.",
    )

    @field_validator("read", "write")
    @classmethod
    def _paths_are_absolute(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            path = Path(value)
            if not path.is_absolute():
                raise ValueError(
                    f"additional permission path must be absolute: {value}"
                )
            if "\x00" in value:
                raise ValueError(
                    "additional permission path must not contain NUL bytes"
                )
            normalized.append(str(path.resolve()))
        return list(dict.fromkeys(normalized))


class AdditionalPermissionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    network: NetworkPermissions = Field(default_factory=NetworkPermissions)
    file_system: FileSystemPermissions = Field(default_factory=FileSystemPermissions)

    def is_empty(self) -> bool:
        return not (
            self.network.enabled
            or self.file_system.read
            or self.file_system.write
        )


class LibraryExecInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cmd: str = Field(
        min_length=1,
        max_length=_COMMAND_MAX_CHARS,
        description=(
            "Shell command to run in the fixed library workspace described by this tool."
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
        description=(
            "Output token budget. Defaults to 10000 tokens; larger requests are "
            "capped by policy."
        ),
    )
    timeout_ms: StrictInt = Field(
        default=_DEFAULT_TIMEOUT_MS,
        ge=1_000,
        le=_MAX_TIMEOUT_MS,
        description=(
            "Hard wall-clock timeout for the original process. The entire process "
            "group is terminated when the timeout expires."
        ),
    )
    sandbox_permissions: SandboxPermissions = Field(
        default="use_default",
        description=(
            "Per-command sandbox override. Defaults to use_default; use "
            "with_additional_permissions with additional_permissions, or "
            "require_escalated for execution outside the sandbox. Overrides are "
            "bound to an exact approval."
        ),
    )
    additional_permissions: AdditionalPermissionProfile | None = Field(
        default=None,
        description=(
            "Sandboxed filesystem or network access for this command; only with "
            "sandbox_permissions=with_additional_permissions."
        ),
    )
    justification: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description=(
            "User-facing reason for a permission override; omit with use_default."
        ),
    )
    administrator_privileges: bool = Field(
        default=False,
        description=(
            "Use a macOS hidden password dialog for sudo. Only valid with "
            "require_escalated. The password is never returned to the model, "
            "session, or trace."
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

    @model_validator(mode="after")
    def _permission_request_is_consistent(self) -> LibraryExecInput:
        if self.sandbox_permissions == "use_default":
            if (
                self.additional_permissions is not None
                or self.justification is not None
            ):
                raise ValueError(
                    "use_default must omit additional_permissions and justification"
                )
            if self.administrator_privileges:
                raise ValueError(
                    "administrator_privileges requires require_escalated"
                )
            return self
        if self.justification is None or not self.justification.strip():
            raise ValueError("permission overrides require a justification")
        if self.sandbox_permissions == "with_additional_permissions":
            if (
                self.additional_permissions is None
                or self.additional_permissions.is_empty()
            ):
                raise ValueError(
                    "with_additional_permissions requires at least one additional permission"
                )
            if self.administrator_privileges:
                raise ValueError(
                    "administrator_privileges requires require_escalated"
                )
            return self
        if self.additional_permissions is not None:
            raise ValueError(
                "require_escalated must omit additional_permissions"
            )
        return self


@dataclass(frozen=True, slots=True)
class LibraryExecRun:
    output: str
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
        description=(
            "Output token budget for this interaction. Larger requests may be "
            "capped by policy."
        ),
    )


@dataclass(frozen=True, slots=True)
class _ResolvedCommand:
    argv: tuple[str, ...]
    source_cmd: str


@dataclass(frozen=True, slots=True)
class _PaperCommand:
    operation: str
    arguments: tuple[str, ...]


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
        "optional extracted-text aliases as read-only papers/, research-manifests/ "
        "as their machine-readable inventory, and only scratch/ as writable "
        "persistent storage for this conversation. The research manifest lists the "
        "authorized PDFs but does not extract their text up front. When a paper is "
        "needed, read a page with `paper read <library-relative-pdf> <page>`, or "
        "search it with `paper search <library-relative-pdf> <query>`. These "
        "commands return page text or matching lines as model-visible evidence; "
        "text preparation and consistency checks are handled automatically. "
        "`paper read`/`paper search` must occupy the whole cmd and cannot be "
        "chained. The environment contains no user credentials; the default sandbox "
        "blocks network access, library/cache writes, and reads outside authorized "
        "roots. If a required operation fails at this boundary, retry the exact "
        "command with either with_additional_permissions and the smallest filesystem "
        "or network grant, or require_escalated for execution outside the sandbox. "
        "Every override is evaluated and approved against the exact command, fixed "
        "cwd, permissions, and input hash. Use administrator_privileges only when "
        "sudo is required; macOS collects the password outside model-visible I/O. "
        "A command still running after yield-time_ms returns a session_id; continue "
        "it with library_write_stdin. Timeout, cancellation, and conversation "
        "teardown terminate the original process group."
    )


def library_write_stdin_tool_description() -> str:
    return (
        "Write characters to, or poll, a running library_exec command. Pass the "
        "opaque session_id returned by library_exec. An empty chars value polls for "
        "new output. The original command keeps the same sandbox and authorization."
    )


def library_exec_approval_snapshot(
    args: LibraryExecInput,
) -> list[dict[str, Any]]:
    return [
        {
            "cwd": _execution_cwd_id(args.sandbox_permissions),
            "sandbox_permissions": args.sandbox_permissions,
            "additional_permissions": (
                args.additional_permissions.model_dump(mode="json")
                if args.additional_permissions is not None
                else None
            ),
            "administrator_privileges": args.administrator_privileges,
            "command_segments": _shell_command_segments(args.cmd),
        }
    ]


async def run_library_exec(
    args: LibraryExecInput,
    library_root: Path | None,
    *,
    cache_root: Path | None = None,
    environment: LibraryEnvironment | None = None,
    research_manifest: Path | None = None,
) -> LibraryExecRun:
    root = _resolve_library_root(library_root)
    resolved_cache_root = (
        pdf_cache_dir().expanduser().resolve()
        if cache_root is None
        else cache_root.expanduser().resolve()
    )
    resolved_command = _resolve_command(
        args.cmd,
        apply_resource_limits=args.sandbox_permissions != "require_escalated",
    )
    paper_command = _intercept_paper_read(resolved_command)
    if paper_command is not None:
        if args.sandbox_permissions != "use_default":
            raise KnowledgeError(
                "paper read/search uses its dedicated broker and cannot request "
                "sandbox overrides"
            )
        return await _run_paper_read_command(
            paper_command,
            resolved_command=resolved_command,
            args=args,
            library_root=root,
            cache_root=resolved_cache_root,
            research_manifest=research_manifest,
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
    additional_read_roots, additional_write_roots, network_access = (
        _additional_permission_roots(
            args,
            protected_roots=(root, resolved_cache_root, environment.root),
        )
    )
    sandbox_policy = _SandboxPolicy(
        file_system=_FileSystemSandboxPolicy(
            readable_roots=(
                root,
                visible_cache_root,
                environment.root,
                *external_commands.readable_directories,
                *additional_read_roots,
                *additional_write_roots,
            ),
            writable_roots=(environment.scratch, *additional_write_roots),
            external_executable_files=external_commands.sandbox_files,
            external_dependency_directories=external_commands.sandbox_directories,
            denied_directories=external_commands.denied_directories,
        ),
        network_access=network_access,
    )
    profile = (
        None
        if args.sandbox_permissions == "require_escalated"
        else _render_macos_seatbelt(sandbox_policy)
    )
    profile_sha256 = (
        hashlib.sha256(profile.encode("utf-8")).hexdigest()
        if profile is not None
        else None
    )
    sandbox_policy_id = _sandbox_policy_id(args.sandbox_permissions)
    execution_cwd_id = _execution_cwd_id(args.sandbox_permissions)
    command_ref = _command_ref(
        resolved_command,
        sandbox_policy_id,
        cwd_id=execution_cwd_id,
    )
    command_environment = _command_environment(
        environment.scratch,
        environment.tool_bin,
        sandbox_permissions=args.sandbox_permissions,
    )
    if args.administrator_privileges:
        command_environment["SUDO_ASKPASS"] = str(
            environment.administrator_askpass()
        )
    process_output = await environment.exec(
        argv=resolved_command.argv,
        command=args.cmd,
        profile=profile,
        env=command_environment,
        yield_time_ms=args.yield_time_ms,
        timeout_ms=args.timeout_ms,
    )
    if temporary_directory is not None:
        if process_output.session_id is not None:
            environment.terminate_all()
            raise KnowledgeError(
                "yielded library commands require a persistent LibraryEnvironment"
            )
        environment.terminate_all()
        temporary_directory.cleanup()
    effective_max_output_tokens = min(
        args.max_output_tokens,
        _OUTPUT_COLLECTION_MAX_TOKENS,
    )
    output_text, original_token_count = _bounded_process_output(
        process_output,
        effective_max_output_tokens,
    )
    sandbox_denied = (
        profile is not None
        and process_output.exit_code not in {None, 0}
        and _sandbox_denial_detected(process_output.output)
    )
    if sandbox_denied:
        output_text = (
            "Sandbox denied this operation. If it is required for the user's "
            "request, retry with the smallest explicit sandbox_permissions override "
            "and a user-facing justification; the retry requires a fresh approval.\n\n"
            f"{output_text}"
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
            timed_out=process_output.timed_out,
            wall_time_seconds=process_output.wall_time_seconds,
            session_id=process_output.session_id,
            chunk_id=process_output.chunk_id,
            original_token_count=original_token_count,
        ),
        trace_attributes={
            "library_exec_schema_version": _SCHEMA_VERSION,
            "command": args.cmd,
            "resolved_command": list(resolved_command.argv),
            "command_ref": command_ref,
            "cwd": execution_cwd_id,
            "sandbox_policy": sandbox_policy_id,
            "sandbox_profile_sha256": profile_sha256,
            "sandbox_permissions": args.sandbox_permissions,
            "additional_permissions": (
                args.additional_permissions.model_dump(mode="json")
                if args.additional_permissions is not None
                else None
            ),
            "network_access": network_access,
            "administrator_privileges": args.administrator_privileges,
            "command_segments": _shell_command_segments(args.cmd),
            "yield_time_ms": args.yield_time_ms,
            "timeout_ms": args.timeout_ms,
            "yielded": process_output.session_id is not None,
            "timed_out": process_output.timed_out,
            "sandbox_denied": sandbox_denied,
            "session_id": process_output.session_id,
            "chunk_id": process_output.chunk_id,
            "exit_code": process_output.exit_code,
            "output_bytes": process_output.total_output_bytes,
            "output_omitted_bytes": process_output.output_omitted_bytes,
            "requested_max_output_tokens": args.max_output_tokens,
            "effective_max_output_tokens": effective_max_output_tokens,
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
    effective_max_output_tokens = min(
        args.max_output_tokens,
        _OUTPUT_COLLECTION_MAX_TOKENS,
    )
    output_text, original_token_count = _bounded_process_output(
        process_output,
        effective_max_output_tokens,
    )
    return LibraryExecRun(
        output=_model_output(
            output=output_text,
            exit_code=process_output.exit_code,
            timed_out=process_output.timed_out,
            wall_time_seconds=process_output.wall_time_seconds,
            session_id=process_output.session_id,
            chunk_id=process_output.chunk_id,
            original_token_count=original_token_count,
        ),
        trace_attributes={
            "library_exec_schema_version": _SCHEMA_VERSION,
            "interaction": "write_stdin" if args.chars else "poll",
            "session_id": args.session_id,
            "chunk_id": process_output.chunk_id,
            "yield_time_ms": args.yield_time_ms,
            "yielded": process_output.session_id is not None,
            "timed_out": process_output.timed_out,
            "exit_code": process_output.exit_code,
            "output_bytes": process_output.total_output_bytes,
            "output_omitted_bytes": process_output.output_omitted_bytes,
            "requested_max_output_tokens": args.max_output_tokens,
            "effective_max_output_tokens": effective_max_output_tokens,
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


def _resolve_command(
    command: str,
    *,
    apply_resource_limits: bool,
) -> _ResolvedCommand:
    wrapper = _RESOURCE_WRAPPER if apply_resource_limits else _ESCALATED_WRAPPER
    return _ResolvedCommand(
        argv=(
            str(_SHELL),
            "-f",
            "-c",
            wrapper,
            "--",
            command,
        ),
        source_cmd=command,
    )


def _command_environment(
    scratch: Path,
    tool_bin: Path,
    *,
    sandbox_permissions: SandboxPermissions,
) -> dict[str, str]:
    path_entries: list[str] = []
    if sandbox_permissions != "require_escalated":
        path_entries.append(str(tool_bin))
    if sandbox_permissions != "use_default":
        path_entries.extend(("/opt/homebrew/bin", "/usr/local/bin"))
    path_entries.append(_SYSTEM_PATH)
    temporary_directory = str(scratch)
    if sandbox_permissions == "require_escalated":
        temporary_directory = os.environ.get("TMPDIR", "/private/tmp")
    environment = {
        "NO_COLOR": "1",
        "TERM": "dumb",
        "LANG": "C.UTF-8",
        "LC_CTYPE": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "COLORTERM": "",
        "PAGER": "cat",
        "GIT_PAGER": "cat",
        "GH_PAGER": "cat",
        "PATH": ":".join(path_entries),
        "TMPDIR": temporary_directory,
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "HOMEBREW_NO_ANALYTICS": "1",
        "HOMEBREW_NO_ENV_HINTS": "1",
    }
    if sandbox_permissions != "use_default":
        for name in ("HOME", "USER", "LOGNAME"):
            value = os.environ.get(name)
            if value:
                environment[name] = value
    return environment


def _additional_permission_roots(
    args: LibraryExecInput,
    *,
    protected_roots: tuple[Path, ...],
) -> tuple[tuple[Path, ...], tuple[Path, ...], bool]:
    if args.sandbox_permissions == "require_escalated":
        return (), (), True
    profile = args.additional_permissions
    if profile is None:
        return (), (), False
    read_roots = tuple(Path(value).resolve() for value in profile.file_system.read)
    write_roots = tuple(
        Path(value).resolve() for value in profile.file_system.write
    )
    for write_root in write_roots:
        if any(_paths_overlap(write_root, root) for root in protected_roots):
            raise KnowledgeError(
                "library_exec additional write permissions cannot overlap the "
                "library, PDF cache, or conversation environment; use a dedicated "
                "application tool for those writes"
            )
    return read_roots, write_roots, profile.network.enabled


def _paths_overlap(left: Path, right: Path) -> bool:
    try:
        left.relative_to(right)
        return True
    except ValueError:
        pass
    try:
        right.relative_to(left)
        return True
    except ValueError:
        return False


def _sandbox_policy_id(permissions: SandboxPermissions) -> str:
    if permissions == "use_default":
        return _SANDBOX_POLICY_ID
    if permissions == "with_additional_permissions":
        return _ADDITIONAL_SANDBOX_POLICY_ID
    return _ESCALATED_POLICY_ID


def _execution_cwd_id(permissions: SandboxPermissions) -> str:
    return "system-temp" if permissions == "require_escalated" else "workspace"


def _shell_command_segments(command: str) -> list[str]:
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    depth = 0
    index = 0
    while index < len(command):
        character = command[index]
        if escaped:
            current.append(character)
            escaped = False
            index += 1
            continue
        if character == "\\" and quote != "'":
            current.append(character)
            escaped = True
            index += 1
            continue
        if quote is not None:
            current.append(character)
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {"'", '"'}:
            current.append(character)
            quote = character
            index += 1
            continue
        if character == "(":
            depth += 1
            current.append(character)
            index += 1
            continue
        if character == ")" and depth > 0:
            depth -= 1
            current.append(character)
            index += 1
            continue
        operator_length = 0
        if depth == 0:
            if command[index : index + 2] in {"&&", "||"}:
                operator_length = 2
            elif character in {";", "|", "\n"}:
                operator_length = 1
        if operator_length:
            segment = "".join(current).strip()
            if segment:
                segments.append(segment)
            current.clear()
            index += operator_length
            continue
        current.append(character)
        index += 1
    segment = "".join(current).strip()
    if segment:
        segments.append(segment)
    return segments[:32]


def _resolve_external_commands() -> _ExternalCommandSet:
    commands: list[tuple[str, Path]] = []
    sandbox_files: set[Path] = set()
    sandbox_directories: set[Path] = set()
    readable_directories: set[Path] = set()
    denied_directories: set[Path] = set()
    for command_name in (
        "rg",
        "pdfinfo",
        "pdftotext",
        "pdftoppm",
        "python",
    ):
        executable = (
            find_poppler_executable(command_name)
            if command_name in {"pdfinfo", "pdftotext", "pdftoppm"}
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
    brew = _first_external_command_candidate("brew")
    if brew is not None:
        commands.append(("brew", brew))
        sandbox_files.update(_path_resolution_chain(brew))
        readable_directories.add(_homebrew_prefix(brew))
    return _ExternalCommandSet(
        commands=tuple(commands),
        sandbox_files=tuple(sorted(sandbox_files)),
        sandbox_directories=tuple(sorted(sandbox_directories)),
        readable_directories=tuple(sorted(readable_directories)),
        denied_directories=tuple(sorted(denied_directories)),
    )


def _homebrew_prefix(brew: Path) -> Path:
    for prefix in (Path("/opt/homebrew"), Path("/usr/local")):
        try:
            brew.relative_to(prefix)
            return prefix
        except ValueError:
            continue
    return brew.parent


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


def _intercept_paper_read(
    resolved_command: _ResolvedCommand,
) -> _PaperCommand | None:
    try:
        arguments = shlex.split(resolved_command.source_cmd, posix=True)
    except ValueError as error:
        if _PAPER_READ_COMMAND_PATTERN.search(resolved_command.source_cmd):
            raise KnowledgeError(
                f"invalid paper read/search command: {error}"
            ) from error
        return None
    if (
        len(arguments) < 2
        or arguments[0] != "paper"
        or arguments[1] not in {"read", "search"}
    ):
        if _PAPER_READ_COMMAND_PATTERN.search(resolved_command.source_cmd):
            raise KnowledgeError(
                "paper read/search must be the entire library_exec cmd; do not place it "
                "inside a pipeline, loop, chained command, substitution, or find -exec"
            )
        return None
    if arguments[1] == "read" and len(arguments) < 4:
        raise KnowledgeError("paper read requires a PDF path and page number")
    if arguments[1] == "search" and len(arguments) < 3:
        raise KnowledgeError("paper search requires a PDF path and query")
    return _PaperCommand(
        operation=arguments[1],
        arguments=tuple(arguments[2:]),
    )


async def _run_paper_read_command(
    command: _PaperCommand,
    *,
    resolved_command: _ResolvedCommand,
    args: LibraryExecInput,
    library_root: Path,
    cache_root: Path,
    research_manifest: Path | None,
) -> LibraryExecRun:
    started = time.monotonic()
    command_ref = _command_ref(resolved_command, _BROKER_POLICY_ID)
    cache = PdfTextCache(cache_root)
    exit_code: int | None = 0
    try:
        async with asyncio.timeout(_BROKER_TIMEOUT_SECONDS):
            match command.operation, command.arguments:
                case ("read", (relative_pdf, raw_page)):
                    try:
                        page_number = int(raw_page)
                    except ValueError as error:
                        raise KnowledgeError(
                            "paper read requires an integer page number"
                        ) from error
                    manifest_key = _manifest_key_for_path(
                        research_manifest,
                        relative_pdf,
                    )
                    pdf_path, source_locator = _resolve_library_pdf(
                        library_root,
                        relative_pdf,
                        require_file=manifest_key is None,
                    )
                    if not pdf_path.is_file():
                        if manifest_key is not None:
                            await cache.delete(manifest_key)
                        await cache.delete_by_source_locator(source_locator)
                        if manifest_key is not None:
                            raise KnowledgeError(
                                "PDF no longer exists in the library"
                            )
                        raise KnowledgeError(
                            "PDF not found in the authorized library"
                        )
                    payload = _model_visible_page(
                        await _cached_or_fresh_page(
                            cache,
                            pdf_path=pdf_path,
                            source_locator=source_locator,
                            manifest_key=manifest_key,
                            page=page_number,
                        )
                    )
                case ("search", (relative_pdf, query)):
                    manifest_key = _manifest_key_for_path(
                        research_manifest,
                        relative_pdf,
                    )
                    pdf_path, source_locator = _resolve_library_pdf(
                        library_root,
                        relative_pdf,
                        require_file=manifest_key is None,
                    )
                    if not pdf_path.is_file():
                        if manifest_key is not None:
                            await cache.delete(manifest_key)
                        await cache.delete_by_source_locator(source_locator)
                        if manifest_key is not None:
                            raise KnowledgeError(
                                "PDF no longer exists in the library"
                            )
                        raise KnowledgeError(
                            "PDF not found in the authorized library"
                        )
                    payload = await _cached_or_fresh_search(
                        cache,
                        pdf_path=pdf_path,
                        source_locator=source_locator,
                        manifest_key=manifest_key,
                        query=query,
                    )
                case _:
                    raise KnowledgeError(
                        "usage: paper read <relative-pdf> <page> | "
                        "paper search <relative-pdf> <query>"
                    )
        raw_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except TimeoutError:
        exit_code = None
        raw_text = (
            f"paper read/search timed out after {_BROKER_TIMEOUT_SECONDS} seconds"
        )
    except (PaperCopilotError, OSError, ValueError) as error:
        exit_code = 1
        raw_text = str(error)
    wall_time_seconds = time.monotonic() - started
    original_token_count = _approx_tokens_from_bytes(len(raw_text.encode("utf-8")))
    output = _truncate_for_token_budget(
        raw_text,
        args.max_output_tokens,
        original_token_count=original_token_count,
    )
    return LibraryExecRun(
        output=_model_output(
            output=output,
            exit_code=exit_code,
            timed_out=exit_code is None,
            wall_time_seconds=wall_time_seconds,
            session_id=None,
            chunk_id=command_ref[:16],
            original_token_count=original_token_count,
        ),
        trace_attributes={
            "library_exec_schema_version": _SCHEMA_VERSION,
            "command": args.cmd,
            "resolved_command": list(resolved_command.argv),
            "command_ref": command_ref,
            "cwd": "workspace",
            "sandbox_policy": _BROKER_POLICY_ID,
            "network_access": False,
            "exit_code": exit_code,
            "paper_cache_operation": command.operation,
        },
    )


def _resolve_library_pdf(
    library_root: Path,
    relative_pdf: str,
    *,
    require_file: bool = True,
) -> tuple[Path, str]:
    locator = Path(relative_pdf)
    if locator.is_absolute() or ".." in locator.parts:
        raise KnowledgeError(
            "paper read/search requires a PDF path relative to the authorized library"
        )
    if locator.parts[:1] == ("library",):
        locator = Path(*locator.parts[1:])
    if not locator.parts:
        raise KnowledgeError("paper read/search requires a PDF path")
    candidate = (library_root / locator).resolve()
    try:
        source_locator = candidate.relative_to(library_root).as_posix()
    except ValueError as error:
        raise KnowledgeError("PDF path resolves outside the authorized library") from error
    if candidate.suffix.lower() != ".pdf":
        raise KnowledgeError("paper read/search target must be an existing PDF")
    if require_file and not candidate.is_file():
        raise KnowledgeError("PDF not found in the authorized library")
    return candidate, source_locator


def _manifest_key_for_path(
    research_manifest: Path | None,
    relative_pdf: str,
) -> str | None:
    if research_manifest is None:
        return None
    try:
        lines = [
            line
            for line in research_manifest.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not lines:
            return None
        header = json.loads(lines[0])
        if header.get("record_type") != "research_manifest":
            return None
        locator = _normalized_locator(relative_pdf)
        for line in lines[1:]:
            record = json.loads(line)
            if record.get("record_type") != "paper":
                continue
            pdf_value = record.get("pdf")
            if not isinstance(pdf_value, str):
                continue
            if _normalized_locator(pdf_value) != locator:
                continue
            paper_id = record.get("paper_id")
            return paper_id if isinstance(paper_id, str) else None
        return None
    except (OSError, ValueError, TypeError):
        return None


def _model_visible_page(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip cache identity fields (hashes, revision) from the model-visible read output."""
    return {"page": payload["page"], "text": payload["text"]}


def _normalized_locator(value: str) -> str:
    path = Path(value)
    if path.parts[:1] == ("library",):
        path = Path(*path.parts[1:])
    return path.as_posix()


async def _cached_or_fresh_page(
    cache: PdfTextCache,
    *,
    pdf_path: Path,
    source_locator: str,
    manifest_key: str | None,
    page: int,
) -> dict[str, Any]:
    if manifest_key is not None:
        old_lookup = await cache.lookup_by_sha(manifest_key)
        if old_lookup.status == "hit" and old_lookup.cache_ref is not None:
            current = await cache.status(pdf_path)
            if (
                current.status == "hit"
                and current.cache_ref is not None
                and current.cache_ref.pdf_sha256 == manifest_key
            ):
                cached_page = await cache.page(old_lookup.cache_ref, page=page)
                return cached_page.model_dump(mode="json")
            await cache.delete(manifest_key)
            await cache.delete_by_source_locator(source_locator)
    fresh = await cache.page_for_pdf(
        pdf_path,
        source_locator=source_locator,
        page=page,
    )
    return fresh.model_dump(mode="json")


async def _cached_or_fresh_search(
    cache: PdfTextCache,
    *,
    pdf_path: Path,
    source_locator: str,
    manifest_key: str | None,
    query: str,
) -> dict[str, Any]:
    if manifest_key is not None:
        old_lookup = await cache.lookup_by_sha(manifest_key)
        if old_lookup.status == "hit" and old_lookup.cache_ref is not None:
            current = await cache.status(pdf_path)
            if (
                current.status == "hit"
                and current.cache_ref is not None
                and current.cache_ref.pdf_sha256 == manifest_key
            ):
                return await _search_cached(cache, old_lookup, query)
            await cache.delete(manifest_key)
            await cache.delete_by_source_locator(source_locator)
    lookup = await cache.ensure(pdf_path, source_locator=source_locator)
    if lookup.manifest is None or lookup.cache_ref is None:
        raise KnowledgeError("paper cache could not be prepared")
    current_lookup = await cache.status(pdf_path)
    if (
        current_lookup.cache_ref is None
        or current_lookup.cache_ref.pdf_sha256 != lookup.cache_ref.pdf_sha256
    ):
        raise KnowledgeError("PDF content changed before the cached text was searched")
    return await _search_cached(cache, lookup, query)


def _search_needle(query: str) -> tuple[str, str]:
    """Build (spaced, whitespace-stripped) NFKC-casefold needles.

    PDF text layers in CJK-heavy corpora frequently encode Latin terms as
    full-width characters and insert justification gaps, so ASCII queries
    must be compared against NFKC-normalized text.
    """
    normalized = unicodedata.normalize("NFKC", query.casefold())
    spaced = " ".join(normalized.split())
    if not spaced:
        raise KnowledgeError("paper search query is empty after normalization")
    return spaced, "".join(normalized.split())


def _line_matches(line: str, needle: tuple[str, str]) -> bool:
    spaced_needle, stripped_needle = needle
    normalized = unicodedata.normalize("NFKC", line.casefold())
    if spaced_needle in " ".join(normalized.split()):
        return True
    # Fall back to whitespace-free matching for justified text where gaps
    # split glyphs (e.g. "M a r k e t"); accept word-boundary overruns as
    # the lesser risk versus missing evidence entirely.
    return stripped_needle in "".join(normalized.split())


async def _search_cached(
    cache: PdfTextCache,
    lookup: PdfCacheLookup,
    query: str,
) -> dict[str, Any]:
    if lookup.manifest is None or lookup.cache_ref is None:
        raise KnowledgeError("paper cache could not be prepared")
    matches: list[dict[str, Any]] = []
    needle = _search_needle(query)
    for page_number in range(1, lookup.manifest.page_count + 1):
        cached_page = await cache.page(lookup.cache_ref, page=page_number)
        for line_number, line in enumerate(cached_page.text.splitlines(), start=1):
            if _line_matches(line, needle):
                matches.append(
                    {
                        "page": page_number,
                        "line": line_number,
                        "text": line[:500],
                    }
                )
                if len(matches) >= 100:
                    break
        if len(matches) >= 100:
            break
    return {
        "query": query,
        "matches": matches,
        "truncated": len(matches) >= 100,
    }


def _model_output(
    *,
    output: str,
    exit_code: int | None,
    timed_out: bool,
    wall_time_seconds: float,
    session_id: str | None,
    chunk_id: str,
    original_token_count: int,
) -> str:
    sections = [
        f"Chunk ID: {chunk_id}",
        f"Wall time: {wall_time_seconds:.4f} seconds",
    ]
    if exit_code is not None:
        sections.append(f"Process exited with code {exit_code}")
    if timed_out:
        sections.append("Process timed out and was terminated")
    if session_id is not None:
        sections.append(f"Process running with session ID {session_id}")
    sections.extend(
        (
            f"Original token count: {original_token_count}",
            "Output:",
            output,
        )
    )
    return "\n".join(sections)


def _bounded_process_output(
    process_output: LibraryProcessOutput,
    max_output_tokens: int,
) -> tuple[str, int]:
    raw_text = process_output.output.decode("utf-8", errors="replace")
    original_token_count = _approx_tokens_from_bytes(
        process_output.total_output_bytes
    )
    output_text = _truncate_for_token_budget(
        raw_text,
        max_output_tokens,
        original_token_count=original_token_count,
    )
    return output_text, original_token_count


def _sandbox_denial_detected(output: bytes) -> bool:
    normalized = output.lower()
    return any(
        marker in normalized
        for marker in (
            b"operation not permitted",
            b"sandbox-exec:",
            b"deny file-",
            b"deny network",
            b"could not resolve host",
            b"couldn't connect to server",
            b"network is unreachable",
        )
    )


def _truncate_for_token_budget(
    text: str,
    max_tokens: int,
    *,
    original_token_count: int,
) -> str:
    max_bytes = max_tokens * _APPROX_BYTES_PER_TOKEN
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    head_budget = max_bytes // 2
    tail_budget = max_bytes - head_budget
    head = encoded[:head_budget].decode("utf-8", errors="ignore")
    tail = encoded[-tail_budget:].decode("utf-8", errors="ignore")
    marker = (
        "Warning: truncated output "
        f"(original token count: {original_token_count})"
    )
    return f"{marker}\n\n{head}\n[... truncated middle output ...]\n{tail}"


def _approx_tokens_from_bytes(byte_count: int) -> int:
    return (byte_count + _APPROX_BYTES_PER_TOKEN - 1) // _APPROX_BYTES_PER_TOKEN


def _command_ref(
    resolved_command: _ResolvedCommand,
    sandbox_policy_id: str,
    *,
    cwd_id: str = "workspace",
) -> str:
    payload = json.dumps(
        {
            "schema_version": _SCHEMA_VERSION,
            "command": resolved_command.argv,
            "cwd": cwd_id,
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
