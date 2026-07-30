from __future__ import annotations

import atexit
import asyncio
import os
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from paper_copilot.shared.errors import KnowledgeError

_MAX_ACTIVE_PROCESSES = 16
_READ_CHUNK_BYTES = 8_192
_RAW_OUTPUT_MAX_BYTES = 64_000


@dataclass(frozen=True, slots=True)
class LibraryProcessOutput:
    output: bytes
    session_id: str | None
    chunk_id: str
    exit_code: int | None
    wall_time_seconds: float
    output_omitted_bytes: int
    total_output_bytes: int


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
    ) -> None:
        self.process = process
        self.session_id = session_id
        self.command = command
        self.started = time.monotonic()
        self.condition = threading.Condition()
        self.interaction_lock = threading.Lock()
        self.output = _ChunkBuffer(_RAW_OUTPUT_MAX_BYTES)
        self.reader = threading.Thread(
            target=self._read_output,
            name=f"paper-copilot-library-exec-{session_id}",
            daemon=True,
        )
        self.reader.start()

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

    def collect(self, *, yield_time_ms: int) -> LibraryProcessOutput:
        deadline = time.monotonic() + yield_time_ms / 1_000
        with self.condition:
            while self.process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.condition.wait(timeout=remaining)
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
        )

    def terminate(self) -> None:
        if self.process.poll() is not None:
            return
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
                return (
                    cache_root if cache_root.is_dir() else self.empty_cache
                )
            self._ensure_directory(self.root)
            self._ensure_directory(self.workspace)
            self._ensure_directory(self.scratch)
            self._ensure_directory(self.tool_bin)
            self._ensure_directory(self.empty_cache)
            visible_cache = cache_root if cache_root.is_dir() else self.empty_cache
            self._ensure_symlink(self.workspace / "library", library_root)
            self._ensure_symlink(self.workspace / "cache", visible_cache)
            self._ensure_symlink(self.workspace / "scratch", self.scratch)
            for command_name, executable in external_commands:
                self._ensure_symlink(self.tool_bin / command_name, executable)
            self._configured_roots = (library_root, cache_root)
            return visible_cache

    async def exec(
        self,
        *,
        argv: tuple[str, ...],
        command: str,
        profile: str,
        env: dict[str, str],
        yield_time_ms: int,
    ) -> LibraryProcessOutput:
        managed = await asyncio.to_thread(
            self._spawn,
            argv=argv,
            command=command,
            profile=profile,
            env=env,
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

    def _spawn(
        self,
        *,
        argv: tuple[str, ...],
        command: str,
        profile: str,
        env: dict[str, str],
    ) -> _ManagedProcess:
        with self._process_lock:
            if len(self._processes) >= _MAX_ACTIVE_PROCESSES:
                raise KnowledgeError(
                    "library environment reached its active process limit"
                )
        process = subprocess.Popen(
            ["/usr/bin/sandbox-exec", "-p", profile, *argv],
            cwd=self.workspace,
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
