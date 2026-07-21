from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any


def compute_prompt_sha256(
    *,
    system: str | list[dict[str, Any]] | None,
    tools: list[dict[str, Any]],
    tool_choice: dict[str, Any] | None,
) -> str:
    """Exclude dynamic messages so the fingerprint identifies the instruction contract."""
    payload = {
        "system": system,
        "tools": tools,
        "tool_choice": tool_choice,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compute_prompt_bundle_sha256(
    component_prompts: Iterable[tuple[str, str]],
) -> str | None:
    prompts = sorted(set(component_prompts))
    if not prompts:
        return None
    encoded = json.dumps(
        prompts,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
