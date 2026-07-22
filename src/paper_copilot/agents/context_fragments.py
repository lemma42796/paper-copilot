from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

ContextSource = Literal[
    "runtime",
    "conversation",
    "pdf",
    "retrieval",
    "tool",
    "validation",
]


@dataclass(frozen=True, slots=True)
class TrustedRuntimeContext:
    payload: dict[str, Any]

    def render(self) -> str:
        return (
            "<runtime_context>\n"
            f"{json.dumps(self.payload, ensure_ascii=False, indent=2)}\n"
            "</runtime_context>"
        )


@dataclass(frozen=True, slots=True)
class UntrustedSource:
    source: ContextSource
    text: str

    def render(self) -> str:
        return (
            f"<untrusted_source kind=\"{self.source}\">\n"
            f"{self.text}\n"
            "</untrusted_source>"
        )
