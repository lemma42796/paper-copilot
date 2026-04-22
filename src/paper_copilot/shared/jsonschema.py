"""JSON Schema utilities.

`inline_refs` exists because some LLM endpoints (notably Dashscope's
qwen3.6-flash Anthropic-compatible gateway) accept a schema containing
`$defs` + `$ref` but then emit stringified JSON for the referenced
nested fields instead of real nested objects. Inlining every `$ref` into
its target produces a flat schema the model handles correctly.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, cast

from paper_copilot.shared.errors import SchemaValidationError

__all__ = ["inline_refs"]

_MAX_DEPTH = 20
_LOCAL_PREFIX = "#/$defs/"


def inline_refs(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Return `schema` with every `#/$defs/*` $ref replaced by the inlined target.

    `$defs` is dropped from the result. Non-local refs and cycles deeper
    than 20 levels raise `SchemaValidationError`. Sibling keys at a $ref
    use-site (e.g. a `description` alongside `$ref`) override the target's
    corresponding keys.
    """
    defs = schema.get("$defs", {})
    body = {k: v for k, v in schema.items() if k != "$defs"}
    return cast("dict[str, Any]", _walk(body, defs, depth=0))


def _walk(node: Any, defs: Mapping[str, Any], depth: int) -> Any:
    if depth > _MAX_DEPTH:
        raise SchemaValidationError(
            f"inline_refs exceeded max depth {_MAX_DEPTH} — cyclic $ref?"
        )
    if isinstance(node, Mapping):
        if "$ref" in node:
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith(_LOCAL_PREFIX):
                raise SchemaValidationError(
                    f"inline_refs only supports '{_LOCAL_PREFIX}*' refs, got {ref!r}"
                )
            name = ref.removeprefix(_LOCAL_PREFIX)
            if name not in defs:
                raise SchemaValidationError(
                    f"inline_refs: $ref '{ref}' not found in $defs"
                )
            target = copy.deepcopy(defs[name])
            siblings = {k: v for k, v in node.items() if k != "$ref"}
            merged = {**target, **siblings}
            return _walk(merged, defs, depth + 1)
        return {k: _walk(v, defs, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk(item, defs, depth + 1) for item in node]
    return node
