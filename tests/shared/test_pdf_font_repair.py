from __future__ import annotations

from pathlib import Path
from typing import Any

from paper_copilot.shared.pdf_font_repair import (
    _CONTROL_REWRITE_SENTINEL,
    _CidToGidMap,
    _destination_codepoint,
    _expanded_to_unicode_mapping,
    _mapping_by_cid,
    _observed_symbol_mapping,
    _read_cid_to_gid_map,
    _readerex_control_mapping,
    _to_unicode_cmap_bytes,
)
from paper_copilot.shared.poppler import _strip_pdf_control_codepoints


class _FakeGlyph:
    def __init__(self, *, has_outline: bool) -> None:
        self._has_outline = has_outline

    def draw(self, pen: Any) -> None:
        if not self._has_outline:
            return
        pen.moveTo((0, 0))
        pen.lineTo((1, 0))
        pen.closePath()


class _FakeFont:
    def __init__(
        self,
        glyph_order: list[str],
        outlined: set[str] | None = None,
    ) -> None:
        self._glyph_order = glyph_order
        outlined = outlined or set()
        self._glyph_set = {
            name: _FakeGlyph(has_outline=name in outlined) for name in glyph_order
        }

    def getGlyphOrder(self) -> list[str]:
        return self._glyph_order

    def getGlyphSet(self) -> dict[str, _FakeGlyph]:
        return self._glyph_set


class _IndirectDescendantDocument:
    def xref_get_key(self, xref: int, key: str) -> tuple[str, str]:
        values = {
            (10, "DescendantFonts"): ("xref", "20 0 R"),
            (21, "Subtype"): ("name", "/CIDFontType2"),
            (21, "CIDToGIDMap"): ("name", "/Identity"),
        }
        return values[(xref, key)]

    def xref_object(self, xref: int) -> str:
        assert xref == 20
        return "[ 21 0 R ]"


def test_expanded_to_unicode_mapping_supports_bfchar_and_bfrange() -> None:
    cmap = b"""
2 beginbfchar
<0001> <F061>
<0002> <0041>
endbfchar
1 beginbfrange
<0003> <0004> <03B1>
endbfrange
1 beginbfrange
<0005> <0006> [<D835DC41> <002B>]
endbfrange
"""

    mapping = _expanded_to_unicode_mapping(cmap)

    assert mapping is not None
    assert {cid: _destination_codepoint(value) for cid, value in mapping.items()} == {
        1: 0xF061,
        2: ord("A"),
        3: ord("α"),
        4: ord("β"),
        5: 0x1D441,
        6: ord("+"),
    }


def test_expanded_to_unicode_mapping_rejects_conflicting_duplicate() -> None:
    cmap = b"""
1 beginbfchar
<0001> <0041>
endbfchar
1 beginbfrange
<0001> <0001> <0042>
endbfrange
"""

    assert _expanded_to_unicode_mapping(cmap) is None


def test_indirect_descendant_array_preserves_explicit_identity() -> None:
    result = _read_cid_to_gid_map(
        _IndirectDescendantDocument(),  # type: ignore[arg-type]
        10,
    )

    assert result == _CidToGidMap(source="identity")


def test_stream_cid_to_gid_mapping_uses_gids_not_cids() -> None:
    result = _mapping_by_cid(
        {1: ord("A"), 2: ord("B")},
        _CidToGidMap(source="stream", gids=(0, 2, 1)),
    )

    assert result == {1: ord("B"), 2: ord("A")}


def test_observed_symbol_mapping_requires_matching_actual_glyph() -> None:
    source = {
        4: chr(0xF061).encode("utf-16-be"),
        5: chr(0xF062).encode("utf-16-be"),
    }
    font = _FakeFont([".notdef", "uniF061", "wrongName"])

    mapping, changed_count, semantic_count = _observed_symbol_mapping(
        source,
        font,  # type: ignore[arg-type]
        {0xF061: 1, 0xF062: 2},
    )

    assert _destination_codepoint(mapping[4]) == ord("α")
    assert mapping[5] == source[5]
    assert changed_count == 1
    assert semantic_count == 1


def test_readerex_rewrites_only_verified_empty_glyph() -> None:
    source = {
        10: chr(0xE5CE).encode("utf-16-be"),
        11: chr(0xE5CF).encode("utf-16-be"),
    }
    font = _FakeFont([".notdef", "empty", "visible"], outlined={"visible"})

    mapping, replacement_count = _readerex_control_mapping(
        source,
        font,  # type: ignore[arg-type]
        _CidToGidMap(source="missing"),
        {0xE5CE: 1, 0xE5CF: 2},
    )

    assert _destination_codepoint(mapping[10]) == ord(_CONTROL_REWRITE_SENTINEL)
    assert mapping[11] == source[11]
    assert replacement_count == 1


def test_serialized_mapping_round_trips_utf16_destinations() -> None:
    source = {
        1: "A".encode("utf-16-be"),
        2: chr(0x1D441).encode("utf-16-be"),
    }

    assert _expanded_to_unicode_mapping(_to_unicode_cmap_bytes(source)) == source


def test_control_cleanup_preserves_surrounding_text_order(tmp_path: Path) -> None:
    output_path = tmp_path / "layout.txt"
    output_path.write_text("before\ue5ceinside\ue5cfafter", encoding="utf-8")

    _strip_pdf_control_codepoints(output_path, (0xE5CE, 0xE5CF))

    assert output_path.read_text(encoding="utf-8") == "beforeinsideafter"
