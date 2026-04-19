"""Structured logging for paper_copilot.

Two outputs from a single processor chain:

1. JSONL file at ``{log_dir}/{YYYY-MM-DD}.jsonl`` (machine-readable, for
   replay and downstream tooling).
2. Stderr with colored ``ConsoleRenderer`` (human-readable, for live work).

Implementation note: the JSONL file is written via a **side-effect
processor** that serializes ``event_dict`` to JSON and returns the dict
unchanged; the terminal ``ConsoleRenderer`` runs next and renders a string
for the ``PrintLoggerFactory``. No stdlib ``logging`` handlers are
installed — we only configure structlog itself.
"""

from __future__ import annotations

import json
import logging as _stdlib_logging
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import structlog

__all__ = ["configure_logging", "get_logger"]


_DEFAULT_LOG_DIR = Path.home() / ".paper-copilot" / "logs"


class _NullSink:
    """File-like sink that discards writes. Used when ``console=False``.

    We can't hand ``structlog.PrintLoggerFactory`` a context-managed
    ``open(os.devnull, "w")`` — the factory keeps the file alive for the
    life of the process. A tiny write/flush stub avoids the lint noise
    and the kernel fd that ``/dev/null`` would claim.
    """

    def write(self, _s: str) -> int:
        return 0

    def flush(self) -> None:
        pass


_METHOD_TO_LEVEL: dict[str, int] = {
    "debug": _stdlib_logging.DEBUG,
    "info": _stdlib_logging.INFO,
    "warning": _stdlib_logging.WARNING,
    "warn": _stdlib_logging.WARNING,
    "error": _stdlib_logging.ERROR,
    "exception": _stdlib_logging.ERROR,
    "critical": _stdlib_logging.CRITICAL,
    "fatal": _stdlib_logging.CRITICAL,
}


class _JsonlFileProcessor:
    """Side-effect processor: writes event_dict as one JSON line to a file."""

    def __init__(self, path: Path) -> None:
        self._file = path.open("a", encoding="utf-8")

    def __call__(
        self,
        _logger: Any,
        _method_name: str,
        event_dict: structlog.types.EventDict,
    ) -> structlog.types.EventDict:
        line = json.dumps(event_dict, ensure_ascii=False, default=str)
        self._file.write(line + "\n")
        self._file.flush()
        return event_dict

    def close(self) -> None:
        self._file.close()


def _make_level_filter(min_level: int) -> Callable[..., structlog.types.EventDict]:
    def processor(
        _logger: Any,
        method_name: str,
        event_dict: structlog.types.EventDict,
    ) -> structlog.types.EventDict:
        level = _METHOD_TO_LEVEL.get(method_name.lower(), _stdlib_logging.CRITICAL)
        if level < min_level:
            raise structlog.DropEvent
        return event_dict

    return processor


_configured: bool = False
_jsonl_processor: _JsonlFileProcessor | None = None


def configure_logging(
    *,
    log_dir: Path | None = None,
    level: str = "INFO",
    console: bool = True,
) -> None:
    """Configure structlog for the process. Idempotent: subsequent calls no-op.

    Resolution precedence is **asymmetric** between the two env-aware args,
    and this is intentional:

    - ``log_dir``:  arg > ``PAPER_COPILOT_LOG_DIR`` > ``~/.paper-copilot/logs``
      Tests pass an explicit ``tmp_path`` and must win over any env var the
      test runner happens to inherit.
    - ``level``:    ``PAPER_COPILOT_LOG_LEVEL`` > arg > ``"INFO"``
      Ops / debugging should be able to crank verbosity without code
      changes, so env overrides whatever the caller hard-coded.

    The resolved directory is created if missing (``mkdir(parents=True,
    exist_ok=True)``). File rotation is not performed here — the file is
    named after today's UTC date at configure time and stays open for the
    life of the process.
    """
    global _configured, _jsonl_processor
    if _configured:
        return

    if log_dir is not None:
        resolved_dir = log_dir
    elif env_dir := os.environ.get("PAPER_COPILOT_LOG_DIR"):
        resolved_dir = Path(env_dir)
    else:
        resolved_dir = _DEFAULT_LOG_DIR
    resolved_dir.mkdir(parents=True, exist_ok=True)

    env_level = os.environ.get("PAPER_COPILOT_LOG_LEVEL")
    resolved_level = (env_level or level).upper()
    level_int = _stdlib_logging.getLevelNamesMapping().get(resolved_level, _stdlib_logging.INFO)

    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    jsonl_path = resolved_dir / f"{date_str}.jsonl"
    _jsonl_processor = _JsonlFileProcessor(jsonl_path)

    processors: list[structlog.types.Processor] = [
        _make_level_filter(level_int),
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _jsonl_processor,
    ]

    factory_file: Any
    if console:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))
        factory_file = sys.stderr
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=False))
        factory_file = _NullSink()

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.PrintLoggerFactory(file=factory_file),
        cache_logger_on_first_use=False,
    )
    _configured = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger. Prefer ``get_logger(__name__)`` at module scope.

    The ``name`` is bound as the ``logger`` field on every event emitted
    through this logger, so JSONL consumers can trace origin without a
    separate processor.
    """
    return cast("structlog.stdlib.BoundLogger", structlog.get_logger(name).bind(logger=name))


def _reset_for_tests() -> None:
    global _configured, _jsonl_processor
    if _jsonl_processor is not None:
        _jsonl_processor.close()
        _jsonl_processor = None
    _configured = False
    structlog.reset_defaults()
