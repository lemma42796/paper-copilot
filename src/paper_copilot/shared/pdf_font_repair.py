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
_BFRANGE_BLOCK = re.compile(
    rb"(?P<prefix>\b[0-9]+\s+beginbfrange\b)"
    rb"(?P<body>.*?)"
    rb"(?P<suffix>\bendbfrange\b)",
    re.DOTALL,
)
_CMAP_PAIR = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
_CMAP_RANGE = re.compile(
    rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*"
    rb"(?:<([0-9A-Fa-f]+)>|\[([^]]+)\])",
    re.DOTALL,
)
_SYMBOL_PRIVATE_GLYPH = re.compile(r"^uniF0([0-9A-Fa-f]{2})$")
_FontRepairKind = Literal["cambria_math", "symbol", "readerex_controls"]
_CidToGidSource = Literal["identity", "stream", "missing"]

# This internal value marks verified ReaderEx mappings while the original CMap
# is analyzed. It is never written to the PDF or extracted text.
_CONTROL_REWRITE_SENTINEL = "\U0010fff0"


@dataclass(frozen=True, slots=True)
class _CidToGidMap:
    source: _CidToGidSource
    gids: tuple[int, ...] = ()

    def glyph_id(self, cid: int) -> int | None:
        if not 0 <= cid <= _MAX_CID:
            return None
        if self.source == "identity":
            return cid
        if self.source == "stream" and cid < len(self.gids):
            return self.gids[cid]
        return None


@dataclass(frozen=True, slots=True)
class _FontResource:
    xref: int
    base_font: str
    kind: _FontRepairKind
    pages: tuple[int, ...]
    cid_to_gid: _CidToGidMap


@dataclass(frozen=True, slots=True)
class PdfFontRepairResult:
    repaired_font_count: int
    unicode_mapping_count: int
    removed_control_mapping_count: int
    repaired_pdf_created: bool
    removed_control_codepoints: tuple[int, ...]

    @property
    def modified(self) -> bool:
        return self.repaired_font_count > 0


def repair_pdf_font_unicode_maps(
    source_pdf: Path,
    repaired_pdf: Path,
) -> PdfFontRepairResult:
    """Repair safe embedded-font Unicode extraction without changing the source.

    Repairs are limited to embedded Type0 fonts whose character-code-to-glyph
    relationship is explicit or independently verified from rendered glyph IDs.
    Cambria Math uses its own cmap and MATH tables; Symbol uses the standard
    Adobe Symbol encoding; ReaderEx controls are removed only when a private-use
    mapping resolves to an empty embedded glyph. Rebuilt maps use a temporary PDF;
    verified ReaderEx control codepoints are returned for post-extraction cleanup.
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
    repaired_pdf_created = False
    removed_control_codepoints: set[int] = set()
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
                    source_cmap_bytes = _read_to_unicode(document, resource.xref)
                    source_cmap = _expanded_to_unicode_mapping(source_cmap_bytes)
                    if source_cmap is None:
                        continue
                    observed_gids = (
                        _observed_glyph_ids(document, resource, source_cmap)
                        if resource.cid_to_gid.source == "missing"
                        else {}
                    )
                    rewritten, mapping_count = _readerex_control_mapping(
                        source_cmap,
                        font,
                        resource.cid_to_gid,
                        observed_gids,
                    )
                    if mapping_count == 0:
                        continue
                    control_codepoints = _globally_removable_control_codepoints(
                        document,
                        resource,
                        source_cmap,
                        rewritten,
                    )
                    if not control_codepoints:
                        continue
                    removed_mapping_count = sum(
                        1
                        for cid, destination in source_cmap.items()
                        if _destination_codepoint(destination) in control_codepoints
                        and rewritten.get(cid) != destination
                    )
                    repaired_font_count += 1
                    unicode_mapping_count += removed_mapping_count
                    removed_control_mapping_count += removed_mapping_count
                    removed_control_codepoints.update(control_codepoints)
                    continue
                else:
                    if (
                        resource.kind == "symbol"
                        and resource.cid_to_gid.source == "missing"
                    ):
                        source_cmap = _expanded_to_unicode_mapping(
                            _read_to_unicode(document, resource.xref)
                        )
                        if source_cmap is None:
                            continue
                        observed_gids = _observed_glyph_ids(
                            document,
                            resource,
                            source_cmap,
                        )
                        mapping, changed_count, semantic_count = (
                            _observed_symbol_mapping(
                                source_cmap,
                                font,
                                observed_gids,
                            )
                        )
                        if changed_count == 0 or semantic_count == 0:
                            continue
                        cmap_bytes = _to_unicode_cmap_bytes(mapping)
                        mapping_count = len(mapping)
                        _attach_to_unicode(document, resource.xref, cmap_bytes)
                        repaired_pdf_created = True
                        repaired_font_count += 1
                        unicode_mapping_count += mapping_count
                        continue
                    glyph_mapping = (
                        _unicode_mapping(font)
                        if resource.kind == "cambria_math"
                        else _symbol_unicode_mapping(font)
                    )
                    mapping = _mapping_by_cid(glyph_mapping, resource.cid_to_gid)
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
            repaired_pdf_created = True
            repaired_font_count += 1
            unicode_mapping_count += mapping_count

        if repaired_pdf_created:
            try:
                document.save(repaired_pdf, garbage=4, deflate=True)
            except Exception as error:
                raise PdfCacheError(
                    "could not save temporary Unicode-repaired PDF"
                ) from error
    finally:
        document.close()

    return PdfFontRepairResult(
        repaired_font_count=repaired_font_count,
        unicode_mapping_count=unicode_mapping_count,
        removed_control_mapping_count=removed_control_mapping_count,
        repaired_pdf_created=repaired_pdf_created,
        removed_control_codepoints=tuple(sorted(removed_control_codepoints)),
    )


def _eligible_fonts(document: pymupdf.Document) -> tuple[_FontResource, ...]:
    font_details: dict[int, tuple[str, str, str]] = {}
    pages_by_xref: dict[int, set[int]] = defaultdict(set)
    for page_number in range(document.page_count):
        for resource in document.get_page_fonts(page_number, full=True):
            font_xref = int(resource[0])
            font_type = str(resource[2])
            base_font = str(resource[3])
            encoding = str(resource[5])
            font_details.setdefault(font_xref, (base_font, font_type, encoding))
            pages_by_xref[font_xref].add(page_number)

    fonts: dict[int, _FontResource] = {}
    for font_xref, (base_font, font_type, encoding) in font_details.items():
        if font_type != "Type0" or encoding != "Identity-H":
            continue
        cid_to_gid = _read_cid_to_gid_map(document, font_xref)
        if cid_to_gid is None:
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
        if kind is None or (
            kind == "cambria_math" and cid_to_gid.source == "missing"
        ):
            continue
        fonts[font_xref] = _FontResource(
            xref=font_xref,
            base_font=base_font,
            kind=kind,
            pages=tuple(sorted(pages_by_xref[font_xref])),
            cid_to_gid=cid_to_gid,
        )
    return tuple(fonts[xref] for xref in sorted(fonts))


def _read_cid_to_gid_map(
    document: pymupdf.Document,
    font_xref: int,
) -> _CidToGidMap | None:
    descendant_type, descendant_value = document.xref_get_key(
        font_xref,
        "DescendantFonts",
    )
    descendant_xref = _descendant_font_xref(
        document,
        descendant_type,
        descendant_value,
    )
    if descendant_xref is None:
        return None
    subtype_type, subtype_value = document.xref_get_key(descendant_xref, "Subtype")
    if subtype_type != "name" or subtype_value != "/CIDFontType2":
        return None
    map_type, map_value = document.xref_get_key(descendant_xref, "CIDToGIDMap")
    if map_type == "name" and map_value == "/Identity":
        return _CidToGidMap(source="identity")
    if map_type == "null":
        return _CidToGidMap(source="missing")
    if map_type != "xref":
        return None
    try:
        stream = document.xref_stream(int(map_value.split()[0]))
    except Exception:
        return None
    if not stream or len(stream) % 2 != 0 or len(stream) > 2 * (_MAX_CID + 1):
        return None
    gids = tuple(
        int.from_bytes(stream[index : index + 2], "big")
        for index in range(0, len(stream), 2)
    )
    return _CidToGidMap(source="stream", gids=gids)


def _descendant_font_xref(
    document: pymupdf.Document,
    value_type: str,
    value: str,
) -> int | None:
    if value_type == "array":
        match = re.fullmatch(r"\[\s*([0-9]+)\s+0\s+R\s*\]", value)
        return int(match.group(1)) if match is not None else None
    if value_type != "xref":
        return None
    match = re.fullmatch(r"([0-9]+)\s+0\s+R", value)
    if match is None:
        return None
    referenced_xref = int(match.group(1))
    try:
        referenced_object = document.xref_object(referenced_xref).strip()
    except Exception:
        return None
    if not referenced_object.startswith("["):
        return referenced_xref
    array_match = re.fullmatch(
        r"\[\s*([0-9]+)\s+0\s+R\s*\]",
        referenced_object,
    )
    return int(array_match.group(1)) if array_match is not None else None


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
    mapping = _expanded_to_unicode_mapping(cmap_bytes)
    if mapping is None:
        return False
    for destination in mapping.values():
        codepoint = _destination_codepoint(destination)
        if codepoint is None:
            continue
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
    mapping = _expanded_to_unicode_mapping(cmap_bytes)
    if mapping is None:
        return False
    return any(
        codepoint is not None and 0xE000 <= codepoint <= 0xF8FF
        for destination in mapping.values()
        if (codepoint := _destination_codepoint(destination)) is not None
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


def _mapping_by_cid(
    glyph_mapping: dict[int, int],
    cid_to_gid: _CidToGidMap,
) -> dict[int, int]:
    if cid_to_gid.source == "identity":
        return dict(glyph_mapping)
    if cid_to_gid.source != "stream":
        return {}
    return {
        cid: glyph_mapping.get(glyph_id, _REPLACEMENT_CHARACTER)
        for cid, glyph_id in enumerate(cid_to_gid.gids)
        if cid <= _MAX_CID and glyph_id != 0
    }


def _observed_glyph_ids(
    document: pymupdf.Document,
    resource: _FontResource,
    source_cmap: dict[int, bytes],
) -> dict[int, int]:
    wanted_codepoints = {
        codepoint
        for destination in source_cmap.values()
        if (codepoint := _destination_codepoint(destination)) is not None
        and 0xE000 <= codepoint <= 0xF8FF
    }
    if not wanted_codepoints:
        return {}

    trace_names = _font_trace_names(resource.base_font)
    observed: dict[int, set[int]] = defaultdict(set)
    try:
        for page_number in resource.pages:
            matching_xrefs = {
                int(font[0])
                for font in document.get_page_fonts(page_number, full=True)
                if _font_trace_names(str(font[3])).intersection(trace_names)
            }
            if matching_xrefs != {resource.xref}:
                return {}
            for span in document[page_number].get_texttrace():
                if _normalized_font_name(str(span.get("font", ""))) not in trace_names:
                    continue
                for character in span.get("chars", ()):
                    if len(character) < 2:
                        continue
                    codepoint = int(character[0])
                    glyph_id = int(character[1])
                    if codepoint in wanted_codepoints and 0 <= glyph_id <= _MAX_CID:
                        observed[codepoint].add(glyph_id)
    except Exception:
        return {}
    return {
        codepoint: next(iter(glyph_ids))
        for codepoint, glyph_ids in observed.items()
        if len(glyph_ids) == 1
    }


def _font_trace_names(base_font: str) -> set[str]:
    names = {_normalized_font_name(base_font)}
    if "+" in base_font:
        names.add(_normalized_font_name(base_font.rsplit("+", 1)[1]))
    return names


def _observed_symbol_mapping(
    source_cmap: dict[int, bytes],
    font: TTFont,
    observed_gids: dict[int, int],
) -> tuple[dict[int, bytes], int, int]:
    mapping = dict(source_cmap)
    glyph_order = font.getGlyphOrder()
    changed_count = 0
    semantic_count = 0
    for cid, destination in source_cmap.items():
        codepoint = _destination_codepoint(destination)
        if codepoint is None or not 0xF000 <= codepoint <= 0xF0FF:
            continue
        glyph_id = observed_gids.get(codepoint)
        if glyph_id is None or glyph_id >= len(glyph_order):
            continue
        expected_name = f"uniF0{codepoint & 0xFF:02X}"
        if glyph_order[glyph_id].upper() != expected_name.upper():
            continue
        encoding_name = symbol_glyph_name(codepoint & 0xFF)
        semantic = _single_semantic_codepoint(agl.toUnicode(encoding_name or ""))
        replacement = semantic if semantic is not None else _REPLACEMENT_CHARACTER
        mapping[cid] = chr(replacement).encode("utf-16-be")
        changed_count += 1
        if semantic is not None:
            semantic_count += 1
    return mapping, changed_count, semantic_count


def _readerex_control_mapping(
    source_cmap: dict[int, bytes],
    font: TTFont,
    cid_to_gid: _CidToGidMap,
    observed_gids: dict[int, int],
) -> tuple[dict[int, bytes], int]:
    mapping = dict(source_cmap)
    glyph_order = font.getGlyphOrder()
    glyph_set = font.getGlyphSet()
    outline_cache: dict[int, bool] = {}
    replacement_count = 0
    for cid, destination in source_cmap.items():
        codepoint = _destination_codepoint(destination)
        if codepoint is None or not 0xE000 <= codepoint <= 0xF8FF:
            continue
        glyph_id = cid_to_gid.glyph_id(cid)
        if glyph_id is None:
            glyph_id = observed_gids.get(codepoint)
        if glyph_id is None or glyph_id >= len(glyph_order):
            continue
        has_outline = outline_cache.get(glyph_id)
        if has_outline is None:
            pen = DecomposingRecordingPen(glyph_set)
            glyph_set[glyph_order[glyph_id]].draw(pen)
            has_outline = bool(pen.value)
            outline_cache[glyph_id] = has_outline
        if has_outline:
            continue
        mapping[cid] = _CONTROL_REWRITE_SENTINEL.encode("utf-16-be")
        replacement_count += 1
    return mapping, replacement_count


def _globally_removable_control_codepoints(
    document: pymupdf.Document,
    resource: _FontResource,
    source_cmap: dict[int, bytes],
    rewritten: dict[int, bytes],
) -> set[int]:
    cids_by_codepoint: dict[int, set[int]] = defaultdict(set)
    for cid, destination in source_cmap.items():
        codepoint = _destination_codepoint(destination)
        if codepoint is not None and 0xE000 <= codepoint <= 0xF8FF:
            cids_by_codepoint[codepoint].add(cid)
    candidates = {
        codepoint
        for codepoint, cids in cids_by_codepoint.items()
        if cids
        and all(rewritten.get(cid) != source_cmap[cid] for cid in cids)
    }
    if not candidates:
        return set()

    trace_names = _font_trace_names(resource.base_font)
    observed: set[int] = set()
    unsafe: set[int] = set()
    try:
        for page_number in range(document.page_count):
            matching_xrefs = {
                int(font[0])
                for font in document.get_page_fonts(page_number, full=True)
                if _font_trace_names(str(font[3])).intersection(trace_names)
            }
            for span in document[page_number].get_texttrace():
                span_name = _normalized_font_name(str(span.get("font", "")))
                for character in span.get("chars", ()):
                    if not character:
                        continue
                    codepoint = int(character[0])
                    if codepoint not in candidates:
                        continue
                    observed.add(codepoint)
                    if (
                        span_name not in trace_names
                        or matching_xrefs != {resource.xref}
                    ):
                        unsafe.add(codepoint)
    except Exception:
        return set()
    return candidates.intersection(observed).difference(unsafe)


def _expanded_to_unicode_mapping(cmap_bytes: bytes) -> dict[int, bytes] | None:
    mapping: dict[int, bytes] = {}
    for block in _BFCHAR_BLOCK.finditer(cmap_bytes):
        pairs = tuple(_CMAP_PAIR.finditer(block.group("body")))
        if len(pairs) != _declared_cmap_count(block.group("prefix")):
            return None
        if not _fully_parsed_cmap_body(block.group("body"), pairs):
            return None
        for pair in pairs:
            source = _hex_bytes(pair.group(1))
            destination = _hex_bytes(pair.group(2))
            if source is None or len(source) != 2 or not destination:
                return None
            cid = int.from_bytes(source, "big")
            if not _add_cmap_entry(mapping, cid, destination):
                return None

    for block in _BFRANGE_BLOCK.finditer(cmap_bytes):
        ranges = tuple(_CMAP_RANGE.finditer(block.group("body")))
        if len(ranges) != _declared_cmap_count(block.group("prefix")):
            return None
        if not _fully_parsed_cmap_body(block.group("body"), ranges):
            return None
        for cmap_range in ranges:
            start_bytes = _hex_bytes(cmap_range.group(1))
            end_bytes = _hex_bytes(cmap_range.group(2))
            if (
                start_bytes is None
                or end_bytes is None
                or len(start_bytes) != 2
                or len(end_bytes) != 2
            ):
                return None
            start = int.from_bytes(start_bytes, "big")
            end = int.from_bytes(end_bytes, "big")
            if start > end:
                return None
            length = end - start + 1
            sequential = cmap_range.group(3)
            array = cmap_range.group(4)
            if sequential is not None:
                initial = _hex_bytes(sequential)
                if initial is None or not initial:
                    return None
                initial_value = int.from_bytes(initial, "big")
                maximum_value = (1 << (8 * len(initial))) - 1
                if initial_value + length - 1 > maximum_value:
                    return None
                destinations = tuple(
                    (initial_value + offset).to_bytes(len(initial), "big")
                    for offset in range(length)
                )
            else:
                if array is None:
                    return None
                destination_matches = tuple(
                    re.finditer(rb"<([0-9A-Fa-f]+)>", array)
                )
                if len(destination_matches) != length or not _fully_parsed_cmap_body(
                    array,
                    destination_matches,
                ):
                    return None
                parsed = tuple(
                    _hex_bytes(match.group(1)) for match in destination_matches
                )
                if any(not destination for destination in parsed):
                    return None
                destinations = tuple(
                    destination for destination in parsed if destination is not None
                )
            for offset, destination in enumerate(destinations):
                if not _add_cmap_entry(mapping, start + offset, destination):
                    return None
    return mapping or None


def _declared_cmap_count(prefix: bytes) -> int:
    match = re.match(rb"\s*([0-9]+)", prefix)
    return int(match.group(1)) if match is not None else -1


def _fully_parsed_cmap_body(
    body: bytes,
    matches: tuple[re.Match[bytes], ...],
) -> bool:
    cursor = 0
    for match in matches:
        if not _only_cmap_space_and_comments(body[cursor : match.start()]):
            return False
        cursor = match.end()
    return _only_cmap_space_and_comments(body[cursor:])


def _only_cmap_space_and_comments(value: bytes) -> bool:
    return re.fullmatch(rb"(?:\s|%[^\r\n]*(?:\r?\n|$))*", value) is not None


def _hex_bytes(value: bytes) -> bytes | None:
    if len(value) % 2 != 0:
        return None
    try:
        return bytes.fromhex(value.decode("ascii"))
    except ValueError:
        return None


def _add_cmap_entry(mapping: dict[int, bytes], cid: int, destination: bytes) -> bool:
    if not 0 <= cid <= _MAX_CID or len(destination) % 2 != 0:
        return False
    existing = mapping.get(cid)
    if existing is not None and existing != destination:
        return False
    mapping[cid] = destination
    return True


def _destination_codepoint(destination: bytes) -> int | None:
    if not destination or len(destination) % 2 != 0:
        return None
    try:
        text = destination.decode("utf-16-be")
    except UnicodeDecodeError:
        return None
    if len(text) != 1:
        return None
    codepoint = ord(text)
    return codepoint if _is_unicode_scalar(codepoint) else None


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
    byte_mapping = {
        cid: chr(codepoint).encode("utf-16-be")
        for cid, codepoint in mapping.items()
        if 0 <= cid <= _MAX_CID and _is_unicode_scalar(codepoint)
    }
    return _to_unicode_cmap_bytes(byte_mapping)


def _to_unicode_cmap_bytes(mapping: dict[int, bytes]) -> bytes:
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
            f"<{cid:04X}> <{destination.hex().upper()}>"
            for cid, destination in chunk
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


def _normalized_font_name(name: str) -> str:
    family = _SUBSET_PREFIX.sub("", name)
    return "".join(character for character in family.lower() if character.isalnum())


def _is_unicode_scalar(codepoint: Any) -> bool:
    return (
        isinstance(codepoint, int)
        and 0 <= codepoint <= 0x10FFFF
        and not 0xD800 <= codepoint <= 0xDFFF
    )
