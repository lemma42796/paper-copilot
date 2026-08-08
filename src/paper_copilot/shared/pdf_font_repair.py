from __future__ import annotations

import io
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pymupdf
from fontTools import agl
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTCollection, TTFont

from paper_copilot.shared.adobe_symbol_encoding import symbol_glyph_name
from paper_copilot.shared.errors import PdfCacheError

__all__ = [
    "PDF_CONTROL_MARKER",
    "PdfFontRepairResult",
    "repair_pdf_font_unicode_maps",
]

_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
_CAMBRIA_MATH_FAMILY = "cambriamath"
_SYMBOL_FAMILY = "symbolmt"
_READEREX_SIMSUN_BASE_FONT = "B3+SimSun"
_REPLACEMENT_CHARACTER = 0xFFFD
_MAX_CID = 0xFFFF
_BFCHAR_BLOCK = re.compile(
    rb"(?P<prefix>\b[0-9]+\s+beginbfchar\b)"
    rb"(?P<body>.*?)"
    rb"(?P<suffix>\bendbfchar\b)",
    re.DOTALL,
)
_CMAP_PAIR = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
_SYMBOL_PRIVATE_GLYPH = re.compile(r"^uniF0([0-9A-Fa-f]{2})$")
_FontRepairKind = Literal["cambria_math", "symbol", "readerex_controls"]

# A Unicode noncharacter used only inside the temporary repaired PDF. Poppler
# emits it into the temporary text artifact, where the adapter removes it
# before cache generation. It cannot collide with meaningful document text.
PDF_CONTROL_MARKER = "\ufdd0"
_PDF_CONTROL_MARKER_HEX = (
    PDF_CONTROL_MARKER.encode("utf-16-be").hex().upper().encode("ascii")
)


@dataclass(frozen=True, slots=True)
class _FontResource:
    xref: int
    base_font: str
    kind: _FontRepairKind


@dataclass(frozen=True, slots=True)
class PdfFontRepairResult:
    repaired_font_count: int
    unicode_mapping_count: int
    removed_control_mapping_count: int

    @property
    def modified(self) -> bool:
        return self.repaired_font_count > 0


def repair_pdf_font_unicode_maps(
    source_pdf: Path,
    repaired_pdf: Path,
) -> PdfFontRepairResult:
    """Rebuild safe Unicode maps in a temporary PDF copy.

    Repairs are limited to embedded Type0 fonts whose character code, CID, and
    GID are identical. Cambria Math uses its own cmap and MATH tables; Symbol
    uses the standard Adobe Symbol encoding; ReaderEx controls are removed only
    when a private-use mapping points to an empty embedded glyph. The source PDF
    is never modified.
    """
    if not source_pdf.is_file():
        raise PdfCacheError("PDF path does not identify a regular file")
    if repaired_pdf.exists():
        raise PdfCacheError("temporary repaired PDF path already exists")

    try:
        document = pymupdf.open(source_pdf)
    except Exception as error:
        raise PdfCacheError("could not open PDF for font Unicode repair") from error

    repaired_font_count = 0
    unicode_mapping_count = 0
    removed_control_mapping_count = 0
    try:
        for resource in _eligible_fonts(document):
            accepted_names = _accepted_font_names(resource.kind)
            font = _embedded_font(
                document,
                resource.xref,
                accepted_names=accepted_names,
            )
            if font is None:
                continue
            try:
                if resource.kind == "readerex_controls":
                    cmap_bytes, mapping_count = _readerex_control_cmap(
                        _read_to_unicode(document, resource.xref),
                        font,
                    )
                    if mapping_count == 0:
                        continue
                    removed_control_mapping_count += mapping_count
                else:
                    mapping = (
                        _unicode_mapping(font)
                        if resource.kind == "cambria_math"
                        else _symbol_unicode_mapping(font)
                    )
                    if not any(
                        codepoint != _REPLACEMENT_CHARACTER
                        for codepoint in mapping.values()
                    ):
                        raise PdfCacheError(
                            f"embedded {resource.base_font} font has no recoverable "
                            "Unicode map"
                        )
                    cmap_bytes = _to_unicode_cmap(mapping)
                    mapping_count = len(mapping)
            finally:
                font.close()
            _attach_to_unicode(document, resource.xref, cmap_bytes)
            repaired_font_count += 1
            unicode_mapping_count += mapping_count

        if repaired_font_count > 0:
            try:
                document.save(repaired_pdf, garbage=4, deflate=True)
            except Exception as error:
                raise PdfCacheError("could not save temporary Unicode-repaired PDF") from error
    finally:
        document.close()

    return PdfFontRepairResult(
        repaired_font_count=repaired_font_count,
        unicode_mapping_count=unicode_mapping_count,
        removed_control_mapping_count=removed_control_mapping_count,
    )


def _eligible_fonts(document: pymupdf.Document) -> tuple[_FontResource, ...]:
    fonts: dict[int, _FontResource] = {}
    for page_number in range(document.page_count):
        for resource in document.get_page_fonts(page_number, full=True):
            font_xref = int(resource[0])
            font_type = str(resource[2])
            base_font = str(resource[3])
            encoding = str(resource[5])
            if font_type != "Type0" or encoding != "Identity-H":
                continue
            if not _has_identity_cid_to_gid_map(document, font_xref):
                continue
            family = _normalized_font_name(base_font)
            kind: _FontRepairKind | None = None
            if family == _CAMBRIA_MATH_FAMILY and _has_damaged_to_unicode(
                document,
                font_xref,
            ):
                kind = "cambria_math"
            elif family == _SYMBOL_FAMILY and _has_damaged_to_unicode(
                document,
                font_xref,
            ):
                kind = "symbol"
            elif (
                base_font == _READEREX_SIMSUN_BASE_FONT
                and _has_private_use_mapping(document, font_xref)
            ):
                kind = "readerex_controls"
            if kind is not None:
                fonts.setdefault(
                    font_xref,
                    _FontResource(xref=font_xref, base_font=base_font, kind=kind),
                )
    return tuple(fonts[xref] for xref in sorted(fonts))


def _has_identity_cid_to_gid_map(
    document: pymupdf.Document,
    font_xref: int,
) -> bool:
    descendant_type, descendant_value = document.xref_get_key(
        font_xref,
        "DescendantFonts",
    )
    if descendant_type not in {"array", "xref"}:
        return False
    match = re.fullmatch(
        r"(?:\[\s*)?([0-9]+)\s+0\s+R(?:\s*\])?",
        descendant_value,
    )
    if match is None:
        return False
    descendant_xref = int(match.group(1))
    map_type, map_value = document.xref_get_key(descendant_xref, "CIDToGIDMap")
    return map_type == "name" and map_value == "/Identity"


def _has_damaged_to_unicode(
    document: pymupdf.Document,
    font_xref: int,
) -> bool:
    map_type, map_value = document.xref_get_key(font_xref, "ToUnicode")
    if map_type == "null":
        return True
    if map_type != "xref":
        return False
    try:
        cmap_bytes = document.xref_stream(int(map_value.split()[0]))
    except Exception as error:
        raise PdfCacheError("could not read embedded font ToUnicode map") from error
    for _source, destination in _direct_cmap_pairs(cmap_bytes):
        if len(destination) != 4:
            continue
        codepoint = int(destination, 16)
        if (
            codepoint == 0
            or 0xD800 <= codepoint <= 0xDFFF
            or 0xE000 <= codepoint <= 0xF8FF
        ):
            return True
    return False


def _has_private_use_mapping(
    document: pymupdf.Document,
    font_xref: int,
) -> bool:
    try:
        cmap_bytes = _read_to_unicode(document, font_xref)
    except PdfCacheError:
        return False
    return any(
        len(destination) == 4
        and 0xE000 <= int(destination, 16) <= 0xF8FF
        for _source, destination in _direct_cmap_pairs(cmap_bytes)
    )


def _read_to_unicode(document: pymupdf.Document, font_xref: int) -> bytes:
    map_type, map_value = document.xref_get_key(font_xref, "ToUnicode")
    if map_type != "xref":
        raise PdfCacheError("embedded font has no readable ToUnicode stream")
    try:
        return document.xref_stream(int(map_value.split()[0]))
    except Exception as error:
        raise PdfCacheError("could not read embedded font ToUnicode stream") from error


def _embedded_font(
    document: pymupdf.Document,
    font_xref: int,
    *,
    accepted_names: set[str] | None,
) -> TTFont | None:
    try:
        extracted = document.extract_font(font_xref)
    except Exception as error:
        raise PdfCacheError("could not extract embedded font") from error
    font_bytes = extracted[3]
    if not font_bytes:
        return None

    if not font_bytes.startswith(b"ttcf"):
        try:
            font = TTFont(io.BytesIO(font_bytes), lazy=False)
        except Exception as error:
            raise PdfCacheError("could not parse embedded font") from error
        if accepted_names is not None and not accepted_names.intersection(
            _font_names(font)
        ):
            font.close()
            raise PdfCacheError("embedded font program identity does not match PDF font")
        return font

    try:
        collection = TTCollection(io.BytesIO(font_bytes), lazy=False)
    except Exception as error:
        raise PdfCacheError("could not parse embedded font collection") from error
    selected_index: int | None = None
    for index, candidate in enumerate(collection.fonts):
        if accepted_names is None or accepted_names.intersection(_font_names(candidate)):
            selected_index = index
            break
    collection.close()
    if selected_index is None:
        raise PdfCacheError("embedded font collection has no matching face")

    try:
        return TTFont(
            io.BytesIO(font_bytes),
            fontNumber=selected_index,
            lazy=False,
        )
    except Exception as error:
        raise PdfCacheError("could not reopen embedded font face") from error


def _accepted_font_names(kind: _FontRepairKind) -> set[str] | None:
    if kind == "cambria_math":
        return {_CAMBRIA_MATH_FAMILY}
    if kind == "symbol":
        return {_SYMBOL_FAMILY, "symbol"}
    return None


def _font_names(font: TTFont) -> set[str]:
    if "name" not in font:
        return set()
    names: set[str] = set()
    for record in font["name"].names:
        if record.nameID not in {1, 4, 6}:
            continue
        try:
            names.add(_normalized_font_name(record.toUnicode()))
        except Exception:
            continue
    return names


def _unicode_mapping(font: TTFont) -> dict[int, int]:
    glyph_to_codepoints: dict[str, set[int]] = defaultdict(set)
    if "cmap" in font:
        for table in font["cmap"].tables:
            if not table.isUnicode():
                continue
            for codepoint, glyph_name in table.cmap.items():
                if _is_unicode_scalar(codepoint):
                    glyph_to_codepoints[glyph_name].add(codepoint)

    variant_codepoints, assembly_glyphs = _math_variants(
        font,
        glyph_to_codepoints,
    )
    mapping: dict[int, int] = {}
    for glyph_id, glyph_name in enumerate(font.getGlyphOrder()):
        if glyph_id > _MAX_CID:
            break
        candidates = glyph_to_codepoints.get(glyph_name, set())
        if candidates:
            mapping[glyph_id] = min(candidates)
            continue
        variant_candidates = variant_codepoints.get(glyph_name, set())
        if len(variant_candidates) == 1:
            mapping[glyph_id] = next(iter(variant_candidates))
            continue
        # Assembly pieces and unknown glyphs are not complete characters.
        # Keep them visibly unresolved so downstream evidence code cannot
        # mistake silent omission for successful text recovery.
        if glyph_name in assembly_glyphs or glyph_id != 0:
            mapping[glyph_id] = _REPLACEMENT_CHARACTER
    return mapping


def _symbol_unicode_mapping(font: TTFont) -> dict[int, int]:
    mapping: dict[int, int] = {}
    for glyph_id, glyph_name in enumerate(font.getGlyphOrder()):
        if glyph_id > _MAX_CID:
            break
        match = _SYMBOL_PRIVATE_GLYPH.fullmatch(glyph_name)
        if match is None:
            if glyph_id != 0:
                mapping[glyph_id] = _REPLACEMENT_CHARACTER
            continue
        encoding_name = symbol_glyph_name(int(match.group(1), 16))
        semantic = agl.toUnicode(encoding_name or "")
        codepoint = _single_semantic_codepoint(semantic)
        mapping[glyph_id] = (
            codepoint if codepoint is not None else _REPLACEMENT_CHARACTER
        )
    return mapping


def _readerex_control_cmap(
    cmap_bytes: bytes,
    font: TTFont,
) -> tuple[bytes, int]:
    glyph_order = font.getGlyphOrder()
    glyph_set = font.getGlyphSet()
    outline_cache: dict[int, bool] = {}
    replacement_count = 0

    def replace(match: re.Match[bytes]) -> bytes:
        nonlocal replacement_count
        source = match.group(1)
        destination = match.group(2)
        if len(source) != 4 or len(destination) != 4:
            return match.group(0)
        codepoint = int(destination, 16)
        if not 0xE000 <= codepoint <= 0xF8FF:
            return match.group(0)
        glyph_id = int(source, 16)
        if glyph_id >= len(glyph_order):
            return match.group(0)
        has_outline = outline_cache.get(glyph_id)
        if has_outline is None:
            pen = DecomposingRecordingPen(glyph_set)
            glyph_set[glyph_order[glyph_id]].draw(pen)
            has_outline = bool(pen.value)
            outline_cache[glyph_id] = has_outline
        if has_outline:
            return match.group(0)
        replacement_count += 1
        return b"<" + source.upper() + b"> <" + _PDF_CONTROL_MARKER_HEX + b">"

    def replace_block(match: re.Match[bytes]) -> bytes:
        return (
            match.group("prefix")
            + _CMAP_PAIR.sub(replace, match.group("body"))
            + match.group("suffix")
        )

    return _BFCHAR_BLOCK.sub(replace_block, cmap_bytes), replacement_count


def _direct_cmap_pairs(cmap_bytes: bytes) -> tuple[tuple[bytes, bytes], ...]:
    pairs: list[tuple[bytes, bytes]] = []
    for block in _BFCHAR_BLOCK.finditer(cmap_bytes):
        pairs.extend(_CMAP_PAIR.findall(block.group("body")))
    return tuple(pairs)


def _single_semantic_codepoint(text: str) -> int | None:
    if len(text) != 1:
        return None
    codepoint = ord(text)
    if not _is_unicode_scalar(codepoint):
        return None
    if codepoint < 0x20 or 0x7F <= codepoint <= 0x9F:
        return None
    if 0xE000 <= codepoint <= 0xF8FF:
        return None
    return codepoint


def _math_variants(
    font: TTFont,
    glyph_to_codepoints: dict[str, set[int]],
) -> tuple[dict[str, set[int]], set[str]]:
    variants: dict[str, set[int]] = defaultdict(set)
    assembly_glyphs: set[str] = set()
    if "MATH" not in font:
        return {}, assembly_glyphs

    math_variants = font["MATH"].table.MathVariants
    if math_variants is None:
        return {}, assembly_glyphs
    for axis in ("Vert", "Horiz"):
        coverage = getattr(math_variants, f"{axis}GlyphCoverage", None)
        constructions = getattr(math_variants, f"{axis}GlyphConstruction", None)
        if coverage is None or constructions is None:
            continue
        for base_glyph, construction in zip(
            coverage.glyphs,
            constructions,
            strict=True,
        ):
            base_codepoints = set(glyph_to_codepoints.get(base_glyph, set()))
            records = construction.MathGlyphVariantRecord or []
            if not base_codepoints and records:
                base_codepoints.update(
                    glyph_to_codepoints.get(records[0].VariantGlyph, set())
                )
            for record in records:
                variants[record.VariantGlyph].update(base_codepoints)
            assembly = construction.GlyphAssembly
            if assembly is not None:
                assembly_glyphs.update(part.glyph for part in assembly.PartRecords)
    return dict(variants), assembly_glyphs


def _attach_to_unicode(
    document: pymupdf.Document,
    font_xref: int,
    cmap_bytes: bytes,
) -> None:
    to_unicode_xref = document.get_new_xref()
    document.update_object(to_unicode_xref, "<<>>")
    document.update_stream(to_unicode_xref, cmap_bytes)
    document.xref_set_key(font_xref, "ToUnicode", f"{to_unicode_xref} 0 R")


def _to_unicode_cmap(mapping: dict[int, int]) -> bytes:
    lines = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /PaperCopilot-Recovered-UCS def",
        "/CMapType 2 def",
        "1 begincodespacerange",
        "<0000> <FFFF>",
        "endcodespacerange",
    ]
    entries = sorted(mapping.items())
    for start in range(0, len(entries), 100):
        chunk = entries[start : start + 100]
        lines.append(f"{len(chunk)} beginbfchar")
        lines.extend(
            f"<{cid:04X}> <{_utf16_hex(codepoint)}>"
            for cid, codepoint in chunk
        )
        lines.append("endbfchar")
    lines.extend(
        [
            "endcmap",
            "CMapName currentdict /CMap defineresource pop",
            "end",
            "end",
        ]
    )
    return ("\n".join(lines) + "\n").encode("ascii")


def _utf16_hex(codepoint: int) -> str:
    return chr(codepoint).encode("utf-16-be").hex().upper()


def _normalized_font_name(name: str) -> str:
    family = _SUBSET_PREFIX.sub("", name)
    return "".join(character for character in family.lower() if character.isalnum())


def _is_unicode_scalar(codepoint: Any) -> bool:
    return (
        isinstance(codepoint, int)
        and 0 <= codepoint <= 0x10FFFF
        and not 0xD800 <= codepoint <= 0xDFFF
    )
