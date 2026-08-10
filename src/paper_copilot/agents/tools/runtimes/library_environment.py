from __future__ import annotations

import atexit
import asyncio
import hashlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from paper_copilot.shared.errors import KnowledgeError

_MAX_ACTIVE_PROCESSES = 16
_READ_CHUNK_BYTES = 8_192
_RAW_OUTPUT_MAX_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class LibraryProcessOutput:
    output: bytes
    session_id: str | None
    chunk_id: str
    exit_code: int | None
    wall_time_seconds: float
    output_omitted_bytes: int
    total_output_bytes: int
    timed_out: bool


@dataclass(frozen=True, slots=True)
class LibraryResearchPaper:
    alias: str | None
    source_locator: str
    paper_id: str
    text_source: Path | None
    page_count: int
    citation_base: str

    def manifest_payload(self) -> dict[str, str | int | bool | None]:
        return {
            "pdf": f"library/{self.source_locator}",
            "text": f"papers/{self.alias}" if self.alias is not None else None,
            "cached": self.text_source is not None,
            "paper_id": self.paper_id,
            "pages": self.page_count,
            "citation_base": self.citation_base,
        }


class _ChunkBuffer:
    def __init__(self, max_bytes: int) -> None:
        self._max_bytes = max_bytes
        self._head_budget = max_bytes // 2
        self._tail_budget = max_bytes - self._head_budget
        self._head = bytearray()
        self._tail: deque[int] = deque()
        self._omitted_bytes = 0
        self._total_bytes = 0

    def push(self, chunk: bytes) -> None:
        self._total_bytes += len(chunk)
        head_remaining = self._head_budget - len(self._head)
        head_length = min(head_remaining, len(chunk))
        self._head.extend(chunk[:head_length])
        self._tail.extend(chunk[head_length:])
        excess = len(self._tail) - self._tail_budget
        if excess > 0:
            for _ in range(excess):
                self._tail.popleft()
            self._omitted_bytes += excess

    def drain(self) -> tuple[bytes, int, int]:
        output = bytes(self._head)
        if self._omitted_bytes:
            output += f"\n... {self._omitted_bytes} bytes omitted ...\n".encode()
        output += bytes(self._tail)
        omitted = self._omitted_bytes
        total = self._total_bytes
        self._head.clear()
        self._tail.clear()
        self._omitted_bytes = 0
        self._total_bytes = 0
        return output, omitted, total


class _ManagedProcess:
    def __init__(
        self,
        *,
        process: subprocess.Popen[bytes],
        session_id: str,
        command: str,
        timeout_ms: int,
    ) -> None:
        self.process = process
        self.session_id = session_id
        self.command = command
        self.started = time.monotonic()
        self.deadline = self.started + timeout_ms / 1_000
        self.timed_out = False
        self.condition = threading.Condition()
        self.interaction_lock = threading.Lock()
        self.output = _ChunkBuffer(_RAW_OUTPUT_MAX_BYTES)
        self.reader = threading.Thread(
            target=self._read_output,
            name=f"paper-copilot-library-exec-{session_id}",
            daemon=True,
        )
        self.reader.start()
        self.timeout_watcher = threading.Thread(
            target=self._enforce_timeout,
            name=f"paper-copilot-library-timeout-{session_id}",
            daemon=True,
        )
        self.timeout_watcher.start()

    def _read_output(self) -> None:
        stream = self.process.stdout
        if stream is None:
            return
        while chunk := stream.read(_READ_CHUNK_BYTES):
            with self.condition:
                self.output.push(chunk)
                self.condition.notify_all()
        with self.condition:
            self.condition.notify_all()

    def _enforce_timeout(self) -> None:
        remaining = max(self.deadline - time.monotonic(), 0)
        try:
            self.process.wait(timeout=remaining)
            return
        except subprocess.TimeoutExpired:
            pass
        self.timed_out = True
        self.terminate()
        with self.condition:
            self.condition.notify_all()

    def collect(self, *, yield_time_ms: int) -> LibraryProcessOutput:
        yield_deadline = time.monotonic() + yield_time_ms / 1_000
        with self.condition:
            while self.process.poll() is None:
                now = time.monotonic()
                remaining = min(yield_deadline, self.deadline) - now
                if remaining <= 0:
                    break
                self.condition.wait(timeout=remaining)
        if self.process.poll() is None and time.monotonic() >= self.deadline:
            self.timed_out = True
            self.terminate()
            self.process.wait()
        exit_code = self.process.poll()
        if exit_code is not None:
            self.reader.join()
        with self.condition:
            output, omitted, total = self.output.drain()
        return LibraryProcessOutput(
            output=output,
            session_id=self.session_id if exit_code is None else None,
            chunk_id=uuid4().hex[:12],
            exit_code=exit_code,
            wall_time_seconds=time.monotonic() - self.started,
            output_omitted_bytes=omitted,
            total_output_bytes=total,
            timed_out=self.timed_out,
        )

    def terminate(self) -> None:
        if self.process.poll() is not None:
            return
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            self.process.wait(timeout=0.5)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return


class LibraryEnvironment:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.workspace = self.root / "workspace"
        self.scratch = self.root / "scratch"
        self.tool_bin = self.root / "bin"
        self.empty_cache = self.root / "empty-cache"
        self._configuration_lock = threading.Lock()
        self._process_lock = threading.Lock()
        self._processes: dict[str, _ManagedProcess] = {}
        self._configured_roots: tuple[Path, Path] | None = None
        self._temporary_directories: list[Path] = []

    def configure_research_view(
        self,
        papers: tuple[LibraryResearchPaper, ...],
        *,
        total_pdf_count: int,
        failures: tuple[dict[str, str], ...],
        truncated_by_paper_budget: bool,
    ) -> str:
        with self._configuration_lock:
            self._ensure_directory(self.root)
            self._ensure_directory(self.workspace)
            papers_directory = self.workspace / "papers"
            manifests_directory = self.workspace / "research-manifests"
            self._ensure_directory(papers_directory)
            self._ensure_directory(manifests_directory)
            for paper in papers:
                if paper.alias is not None and paper.text_source is not None:
                    self._ensure_symlink(
                        papers_directory / paper.alias,
                        paper.text_source,
                    )
            manifest_header = {
                "record_type": "research_manifest",
                "schema_version": 1,
                "total_pdf_count": total_pdf_count,
                "inventory_count": len(papers),
                "prepared_count": sum(
                    paper.text_source is not None for paper in papers
                ),
                "truncated_by_paper_budget": truncated_by_paper_budget,
                "failures": list(failures),
            }
            manifest = (
                json.dumps(
                    manifest_header,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
                + "".join(
                    json.dumps(
                        {
                            "record_type": "paper",
                            **paper.manifest_payload(),
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    + "\n"
                    for paper in papers
                )
            ).encode()
            manifest_digest = hashlib.sha256(manifest).hexdigest()[:16]
            manifest_path = (
                manifests_directory
                / f"manifest-{manifest_digest}.jsonl"
            )
            self._ensure_immutable_file(manifest_path, manifest)
            current_manifest_path = manifests_directory / "current.jsonl"
            self._ensure_current_symlink(current_manifest_path, manifest_path)
        return current_manifest_path.relative_to(self.workspace).as_posix()

    def configure(
        self,
        *,
        library_root: Path,
        cache_root: Path,
        external_commands: tuple[tuple[str, Path], ...],
    ) -> Path:
        library_root = library_root.expanduser().resolve()
        cache_root = cache_root.expanduser().resolve()
        with self._configuration_lock:
            if self._configured_roots is not None:
                if self._configured_roots != (library_root, cache_root):
                    raise KnowledgeError(
                        "library environment roots cannot change within a conversation"
                    )
                for command_name, executable in external_commands:
                    self._ensure_symlink(self.tool_bin / command_name, executable)
                return cache_root if cache_root.is_dir() else self.empty_cache
            self._ensure_directory(self.root)
            self._ensure_directory(self.workspace)
            self._ensure_directory(self.scratch)
            self._ensure_directory(self.tool_bin)
            self._ensure_directory(self.empty_cache)
            self._ensure_directory(cache_root)
            visible_cache = cache_root
            self._ensure_symlink(self.workspace / "library", library_root)
            self._ensure_symlink(self.workspace / "cache", visible_cache)
            self._ensure_symlink(self.workspace / "scratch", self.scratch)
            for command_name, executable in external_commands:
                self._ensure_symlink(self.tool_bin / command_name, executable)
            self._configured_roots = (library_root, cache_root)
            return visible_cache

    def administrator_askpass(self) -> Path:
        with self._configuration_lock:
            helper_directory = Path(
                tempfile.mkdtemp(prefix="paper-copilot-askpass-")
            )
            self._temporary_directories.append(helper_directory)
            helper = helper_directory / "askpass"
            content = """#!/bin/sh
parent_executable=$(/bin/ps -p \"$PPID\" -o comm= 2>/dev/null)
parent_command=$(/bin/ps -p \"$PPID\" -o command= 2>/dev/null)
case \"$parent_executable\" in
  /usr/bin/sudo|sudo) ;;
  *) exit 1 ;;
esac
case \"$parent_command\" in
  *"/usr/bin/sudo -A -v"|*"sudo -A -v") ;;
  *) exit 1 ;;
esac
exec /usr/bin/osascript \\
  -e 'display dialog "Paper Copilot 需要管理员权限来执行你刚批准的命令。请输入 Mac 登录密码；密码只会交给 sudo，且不会被保存。" default answer "" with hidden answer buttons {"取消", "继续"} default button "继续" with icon caution' \\
  -e 'text returned of result'
""".encode("utf-8")
            self._ensure_executable_file(helper, content)
            return helper

    async def exec(
        self,
        *,
        argv: tuple[str, ...],
        command: str,
        profile: str | None,
        env: dict[str, str],
        yield_time_ms: int,
        timeout_ms: int,
    ) -> LibraryProcessOutput:
        managed = await asyncio.to_thread(
            self._spawn,
            argv=argv,
            command=command,
            profile=profile,
            env=env,
            timeout_ms=timeout_ms,
        )
        try:
            output = await asyncio.to_thread(
                managed.collect,
                yield_time_ms=yield_time_ms,
            )
        except asyncio.CancelledError:
            managed.terminate()
            await asyncio.to_thread(managed.process.wait)
            self._remove(managed.session_id)
            raise
        if output.session_id is None:
            self._remove(managed.session_id)
        return output

    async def write_stdin(
        self,
        *,
        session_id: str,
        chars: str,
        yield_time_ms: int,
    ) -> LibraryProcessOutput:
        managed = self._get(session_id)
        try:
            return await asyncio.to_thread(
                self._interact,
                managed,
                chars=chars,
                yield_time_ms=yield_time_ms,
            )
        except asyncio.CancelledError:
            managed.terminate()
            await asyncio.to_thread(managed.process.wait)
            self._remove(session_id)
            raise

    def terminate_all(self) -> None:
        with self._process_lock:
            processes = tuple(self._processes.values())
            self._processes.clear()
        for managed in processes:
            managed.terminate()
        for managed in processes:
            try:
                managed.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                continue
        with self._configuration_lock:
            temporary_directories = tuple(self._temporary_directories)
            self._temporary_directories.clear()
        for directory in temporary_directories:
            shutil.rmtree(directory, ignore_errors=True)

    def _spawn(
        self,
        *,
        argv: tuple[str, ...],
        command: str,
        profile: str | None,
        env: dict[str, str],
        timeout_ms: int,
    ) -> _ManagedProcess:
        with self._process_lock:
            if len(self._processes) >= _MAX_ACTIVE_PROCESSES:
                raise KnowledgeError(
                    "library environment reached its active process limit"
                )
        execution_argv = (
            ["/usr/bin/sandbox-exec", "-p", profile, *argv]
            if profile is not None
            else list(argv)
        )
        process = subprocess.Popen(
            execution_argv,
            cwd=(self.workspace if profile is not None else Path("/private/tmp")),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        managed = _ManagedProcess(
            process=process,
            session_id=uuid4().hex,
            command=command,
            timeout_ms=timeout_ms,
        )
        with self._process_lock:
            self._processes[managed.session_id] = managed
        return managed

    def _interact(
        self,
        managed: _ManagedProcess,
        *,
        chars: str,
        yield_time_ms: int,
    ) -> LibraryProcessOutput:
        with managed.interaction_lock:
            if managed.process.poll() is not None:
                output = managed.collect(yield_time_ms=0)
                self._remove(managed.session_id)
                return output
            if chars:
                stdin = managed.process.stdin
                if stdin is None or stdin.closed:
                    raise KnowledgeError(
                        f"library process {managed.session_id} stdin is closed"
                    )
                try:
                    stdin.write(chars.encode())
                    stdin.flush()
                except BrokenPipeError as error:
                    raise KnowledgeError(
                        f"library process {managed.session_id} stdin is closed"
                    ) from error
            output = managed.collect(yield_time_ms=yield_time_ms)
            if output.session_id is None:
                self._remove(managed.session_id)
            return output

    def _get(self, session_id: str) -> _ManagedProcess:
        with self._process_lock:
            managed = self._processes.get(session_id)
        if managed is None:
            raise KnowledgeError(f"unknown library process session: {session_id}")
        return managed

    def _remove(self, session_id: str) -> None:
        with self._process_lock:
            self._processes.pop(session_id, None)

    @staticmethod
    def _ensure_symlink(link: Path, target: Path) -> None:
        if link.is_symlink():
            if link.resolve() != target.resolve():
                raise KnowledgeError(
                    f"library environment link target changed: {link.name}"
                )
            return
        if link.exists():
            raise KnowledgeError(
                f"library environment path is not a symlink: {link.name}"
            )
        link.symlink_to(target, target_is_directory=target.is_dir())

    @staticmethod
    def _ensure_current_symlink(link: Path, target: Path) -> None:
        if link.is_symlink():
            if link.resolve() == target.resolve():
                return
            link.unlink()
        elif link.exists():
            raise KnowledgeError(
                f"library environment current manifest is not a symlink: {link.name}"
            )
        link.symlink_to(target)

    @staticmethod
    def _ensure_immutable_file(path: Path, content: bytes) -> None:
        if path.is_symlink():
            raise KnowledgeError(
                f"library environment file must not be a symlink: {path.name}"
            )
        if path.exists():
            if not path.is_file() or path.read_bytes() != content:
                raise KnowledgeError(
                    f"library environment file content changed: {path.name}"
                )
            return
        with path.open("xb") as stream:
            stream.write(content)

    @staticmethod
    def _ensure_executable_file(path: Path, content: bytes) -> None:
        if path.is_symlink():
            raise KnowledgeError(
                f"library environment executable must not be a symlink: {path.name}"
            )
        if path.exists():
            if not path.is_file() or path.read_bytes() != content:
                raise KnowledgeError(
                    f"library environment executable content changed: {path.name}"
                )
        else:
            with path.open("xb") as stream:
                stream.write(content)
        path.chmod(0o700)

    @staticmethod
    def _ensure_directory(path: Path) -> None:
        if path.is_symlink():
            raise KnowledgeError(
                f"library environment directory must not be a symlink: {path.name}"
            )
        path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            raise KnowledgeError(
                f"library environment path is not a directory: {path.name}"
            )


_ENVIRONMENTS: dict[Path, LibraryEnvironment] = {}
_ENVIRONMENTS_LOCK = threading.Lock()


def get_library_environment(root: Path) -> LibraryEnvironment:
    resolved = root.expanduser().resolve()
    with _ENVIRONMENTS_LOCK:
        environment = _ENVIRONMENTS.get(resolved)
        if environment is None:
            environment = LibraryEnvironment(resolved)
            _ENVIRONMENTS[resolved] = environment
        return environment


def discard_library_environment(root: Path) -> None:
    resolved = root.expanduser().resolve()
    with _ENVIRONMENTS_LOCK:
        environment = _ENVIRONMENTS.pop(resolved, None)
    if environment is not None:
        environment.terminate_all()


def _terminate_registered_environments() -> None:
    with _ENVIRONMENTS_LOCK:
        environments = tuple(_ENVIRONMENTS.values())
        _ENVIRONMENTS.clear()
    for environment in environments:
        environment.terminate_all()


atexit.register(_terminate_registered_environments)
