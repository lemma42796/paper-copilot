"""Prompt-cache layer helpers for Anthropic-compatible `cache_control`.

Three wrappers translate the raw strings each agent already holds
(system prompt, tool schema, user message) into the content-block shapes
that accept an ``ephemeral`` cache marker. M9 uses a three-break-point
layout (tools / system / user-with-PDF); the helpers keep agents free of
dict plumbing.

Must not import the ``anthropic`` SDK — ``shared/`` sits below the SDK
boundary (see ARCHITECTURE.md "模块依赖方向").
"""

from __future__ import annotations

from typing import Any, Final

__all__ = [
    "CACHE_CONTROL_EPHEMERAL",
    "cached_system",
    "cached_user_text",
    "mark_tools_cached",
]

CACHE_CONTROL_EPHEMERAL: Final[dict[str, str]] = {"type": "ephemeral"}


def cached_system(text: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": text, "cache_control": CACHE_CONTROL_EPHEMERAL}]


def mark_tools_cached(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not tools:
        return tools
    out = [dict(t) for t in tools]
    out[-1] = {**out[-1], "cache_control": CACHE_CONTROL_EPHEMERAL}
    return out


def cached_user_text(text: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": text, "cache_control": CACHE_CONTROL_EPHEMERAL}]
