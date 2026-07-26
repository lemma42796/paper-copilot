from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from paper_copilot.shared.errors import KnowledgeError
from paper_copilot.shared.logging import get_logger

_SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
_SHELL = Path("/bin/zsh")
_COMMAND_MAX_CHARS = 8_000
_OUTPUT_MAX_BYTES = 64_000
_READ_CHUNK_BYTES = 8_192
_DEFAULT_TIMEOUT_MS = 15_000
_MAX_TIMEOUT_MS = 30_000
_CPU_LIMIT_SECONDS = 35
_FILE_SIZE_LIMIT = "64m"
_SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
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

    command: str = Field(
        min_length=1,
        max_length=_COMMAND_MAX_CHARS,
        description=(
            "Shell command to run read-only with the paper library as its fixed "
            "working directory. Use system commands such as find, grep, awk, sed, "
            "sort, uniq, wc, du, stat, shasum, and file. Library writes, network "
            "access, and reads outside the library are blocked by the OS sandbox."
        ),
    )
    timeout_ms: StrictInt = Field(
        default=_DEFAULT_TIMEOUT_MS,
        ge=1_000,
        le=_MAX_TIMEOUT_MS,
        description="Execution deadline in milliseconds.",
    )

    @field_validator("command")
    @classmethod
    def _command_has_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("command must contain a non-whitespace character")
        if "\x00" in value:
            raise ValueError("command must not contain NUL bytes")
        return value


@dataclass(frozen=True, slots=True)
class _CapturedStream:
    text: str
    bytes_seen: int
    truncated: bool


def library_exec_tool_description() -> str:
    return (
        "Run a bounded read-only shell command inside the configured paper library. "
        "Use it for exact or batch filesystem questions such as counting PDFs, "
        "listing titles, grouping filenames, measuring sizes, and finding duplicate "
        "file hashes. The working directory is fixed; the environment contains no "
        "user credentials; macOS sandboxing blocks network access, library writes, "
        "and reads outside the library. Only system executables are available. Use "
        "paper_search for semantic content discovery and library_edit for mkdir, "
        "copy, move, rename, trash, or restore operations."
    )


async def run_library_exec(
    args: LibraryExecInput,
    library_root: Path | None,
) -> dict[str, Any]:
    root = _resolve_library_root(library_root)
    _require_macos_sandbox()
    started = time.monotonic()
    _LOGGER.debug(
        "library_command_started",
        command_preview=args.command[:200],
        command_length=len(args.command),
        timeout_ms=args.timeout_ms,
    )
    with tempfile.TemporaryDirectory(prefix="paper-copilot-command-") as raw_scratch:
        scratch = Path(raw_scratch).resolve()
        profile = _sandbox_profile(root, scratch)
        process = await asyncio.create_subprocess_exec(
            str(_SANDBOX_EXEC),
            "-p",
            profile,
            str(_SHELL),
            "-f",
            "-c",
            _RESOURCE_WRAPPER,
            "--",
            args.command,
            cwd=root,
            env=_command_environment(scratch),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        if process.stdout is None or process.stderr is None:
            raise KnowledgeError("library command did not create output pipes")
        stdout_task = asyncio.create_task(_capture_stream(process.stdout))
        stderr_task = asyncio.create_task(_capture_stream(process.stderr))
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
            stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        finally:
            if process.returncode is None:
                os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
            if not stdout_task.done():
                stdout_task.cancel()
            if not stderr_task.done():
                stderr_task.cancel()
            await asyncio.gather(
                stdout_task,
                stderr_task,
                return_exceptions=True,
            )

    duration_ms = round((time.monotonic() - started) * 1_000)
    _LOGGER.debug(
        "library_command_finished",
        exit_code=exit_code,
        timed_out=timed_out,
        duration_ms=duration_ms,
        stdout_bytes=stdout.bytes_seen,
        stderr_bytes=stderr.bytes_seen,
    )
    return {
        "status": "timed_out" if timed_out else "completed",
        "sandbox": "macos_read_only",
        "cwd": str(root),
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "stdout": stdout.text,
        "stderr": stderr.text,
        "stdout_bytes": stdout.bytes_seen,
        "stderr_bytes": stderr.bytes_seen,
        "stdout_truncated": stdout.truncated,
        "stderr_truncated": stderr.truncated,
    }


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


def _command_environment(scratch: Path) -> dict[str, str]:
    return {
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
        "PATH": _SYSTEM_PATH,
        "TMPDIR": str(scratch),
    }


async def _capture_stream(
    stream: asyncio.StreamReader,
) -> _CapturedStream:
    chunks: list[bytes] = []
    bytes_seen = 0
    bytes_captured = 0
    while chunk := await stream.read(_READ_CHUNK_BYTES):
        bytes_seen += len(chunk)
        remaining = _OUTPUT_MAX_BYTES - bytes_captured
        if remaining > 0:
            captured = chunk[:remaining]
            chunks.append(captured)
            bytes_captured += len(captured)
    return _CapturedStream(
        text=b"".join(chunks).decode("utf-8", errors="replace"),
        bytes_seen=bytes_seen,
        truncated=bytes_seen > bytes_captured,
    )


def _sandbox_profile(library_root: Path, scratch: Path) -> str:
    root = _sandbox_string(library_root)
    scratch_path = _sandbox_string(scratch)
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
  (subpath {root})
  (subpath {scratch_path}))

(allow file-read-metadata file-test-existence
  (literal "/")
  (literal "/Users")
  (literal "/private")
  (literal "/private/var")
  (literal "/private/var/folders")
  (path-ancestors {root})
  (path-ancestors {scratch_path}))

(allow file-map-executable
  (subpath "/System")
  (subpath "/Library/Apple")
  (subpath "/usr/bin")
  (subpath "/usr/lib")
  (subpath "/usr/libexec")
  (subpath "/usr/sbin")
  (subpath "/bin")
  (subpath "/sbin"))

(allow file-read* file-test-existence file-write* file-ioctl
  (subpath {scratch_path})
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
"""


def _sandbox_string(path: Path) -> str:
    return json.dumps(str(path), ensure_ascii=True)
