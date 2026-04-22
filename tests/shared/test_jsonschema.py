from __future__ import annotations

import pytest

from paper_copilot.shared.errors import SchemaValidationError
from paper_copilot.shared.jsonschema import inline_refs


def test_inlines_simple_nested_ref() -> None:
    schema = {
        "$defs": {
            "Inner": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            }
        },
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "inner": {"$ref": "#/$defs/Inner"},
        },
        "required": ["label", "inner"],
    }

    result = inline_refs(schema)

    assert "$defs" not in result
    assert result["properties"]["inner"] == {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }
    assert result["properties"]["label"] == {"type": "string"}


def test_inlines_ref_inside_array_items() -> None:
    schema = {
        "$defs": {
            "Section": {
                "type": "object",
                "properties": {"title": {"type": "string"}},
                "required": ["title"],
            }
        },
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "items": {"$ref": "#/$defs/Section"},
            }
        },
    }

    result = inline_refs(schema)

    assert "$defs" not in result
    assert result["properties"]["sections"]["items"] == {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    }


def test_sibling_keys_override_target() -> None:
    schema = {
        "$defs": {
            "Inner": {
                "type": "object",
                "description": "target description (should lose)",
                "properties": {"value": {"type": "string"}},
            }
        },
        "type": "object",
        "properties": {
            "inner": {
                "$ref": "#/$defs/Inner",
                "description": "use-site description (should win)",
            }
        },
    }

    result = inline_refs(schema)

    assert result["properties"]["inner"]["description"] == "use-site description (should win)"
    # Non-overlapping keys from target survive.
    assert result["properties"]["inner"]["properties"] == {"value": {"type": "string"}}


def test_schema_without_refs_is_unchanged() -> None:
    schema = {
        "type": "object",
        "properties": {
            "a": {"type": "string"},
            "b": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["a"],
    }

    result = inline_refs(schema)

    assert result == schema
    assert result is not schema  # fresh dict


def test_non_local_ref_raises() -> None:
    schema = {
        "type": "object",
        "properties": {"x": {"$ref": "https://example.com/schema.json"}},
    }
    with pytest.raises(SchemaValidationError, match="only supports"):
        inline_refs(schema)


def test_cyclic_ref_raises() -> None:
    schema = {
        "$defs": {
            "A": {"type": "object", "properties": {"next": {"$ref": "#/$defs/A"}}},
        },
        "$ref": "#/$defs/A",
    }
    with pytest.raises(SchemaValidationError, match="exceeded max depth"):
        inline_refs(schema)
