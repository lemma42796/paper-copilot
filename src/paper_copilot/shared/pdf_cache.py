from __future__ import annotations

import asyncio
import fcntl
import hashlib
import html as html_module
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from contextlib import contextmanager
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from paper_copilot.shared.errors import PdfCacheError
from paper_copilot.shared.logging import get_logger
from paper_copilot.shared.poppler import PopplerIdentity, PopplerTextExtractor

__all__ = [
    "PageBoundary",
    "PdfCacheLookup",
    "PdfCacheManifest",
    "PdfCachePage",
    "PdfCacheRef",
    "PdfTextCache",
    "TextArtifact",
]

_SCHEMA_VERSION = 2
_LAYOUT_FILENAME = "layout.txt"
_MANIFEST_FILENAME = "manifest.json"
_CURRENT_FILENAME = "current.json"
_READ_CHUNK_BYTES = 1024 * 1024
_OCR_START_TEMPLATE = "[[paper-copilot-ocr:start slot={slot} page={page}]]"
_OCR_END_TEMPLATE = "[[paper-copilot-ocr:end slot={slot}]]"
_REVISION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_SAFE_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_BBOX_WORD_PATTERN = re.compile(
    r'<word xMin="([0-9.]+)" yMin="([0-9.]+)" xMax="([0-9.]+)" yMax="([0-9.]+)">'
    r"(.*?)</word>",
    re.DOTALL,
)
_BBOX_PAGE_PATTERN = re.compile(
    r'<page width="([0-9.]+)" height="([0-9.]+)">'
)
_SLOT_BBOX_PATTERN = re.compile(
    r"\[\[paper-copilot-ocr:start slot=(page-[0-9]{4}-formula-[0-9]{4}) "
    r"page=([0-9]+) "
    r"bbox=([0-9.]+),([0-9.]+),([0-9.]+),([0-9.]+)\]\]"
)
# Display-formula glyphs split into several adjacent word clusters (operator
# halves, scripts, limits). Clusters closer than this multiple of their own
# height are merged into one formula group; vertically adjacent words inside
# the group's horizontal span (summation bounds, fraction rows) are absorbed.
_BBOX_CLUSTER_GAP_FACTOR = 1.5
_BBOX_ABSORB_PADDING_POINTS = 2.0
# Word boxes hug glyph edges exactly; anti-aliasing at the render boundary
# shaves edge strokes, so pad the normalized crop on all sides.
_BBOX_MARGIN_POINTS = 4.0
# One display formula can interleave clean extraction lines between its
# garbled rows (summation limits, fraction numerators). Garbled runs or
# clusters bridged by at most this many clean lines/clusters stay one
# formula; longer clean gaps mean separate formulas or prose. The same bound
# applies on both extraction passes so their group counts can align.
_MAX_INTRA_FORMULA_CLEAN_LINES = 2
_log = get_logger(__name__)


class PageBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    page: int = Field(ge=1)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    character_count: int = Field(ge=0)


class TextArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: Literal["layout.txt"] = _LAYOUT_FILENAME
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(ge=0)


class FormulaOCRRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    slot: str = Field(pattern=r"^page-[0-9]{4}-formula-[0-9]{4}$")
    page: int = Field(ge=1)
    region: dict[str, float]
    model: str = Field(min_length=1)
    render_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    latex_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime


class PdfCacheManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2] = _SCHEMA_VERSION
    revision_id: str
    pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_locator: str
    page_count: int = Field(ge=1)
    extractor_name: str
    extractor_version: str
    extractor_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction_mode: str
    extraction_parameters: dict[str, str]
    page_boundaries: list[PageBoundary]
    created_at: datetime
    status: Literal["complete", "partial", "failed"]
    unresolved_pages: list[int]
    artifact: TextArtifact
    formula_ocr_records: list[FormulaOCRRecord] = Field(default_factory=list)

    @field_validator("source_locator")
    @classmethod
    def _source_locator_is_safe(cls, value: str) -> str:
        stripped = value.strip()
        locator_path = Path(stripped)
        if not stripped:
            raise ValueError("source_locator must not be empty")
        if "\x00" in stripped:
            raise ValueError("source_locator must not contain NUL bytes")
        if locator_path.is_absolute() or ".." in locator_path.parts:
            raise ValueError("source_locator must be an authorized relative reference")
        return stripped


class PdfCacheRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extractor_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision_id: str


class PdfCacheLookup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["hit", "miss", "corrupt", "incompatible"]
    cache_ref: PdfCacheRef | None = None
    manifest: PdfCacheManifest | None = None
    reason: str | None = None


class PdfCachePage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cache_ref: PdfCacheRef
    paper_id: str
    page: int = Field(ge=1)
    text: str
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class _CurrentRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    revision_id: str


@dataclass(frozen=True, slots=True)
class _WordBox:
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    text: str


@dataclass(frozen=True, slots=True)
class _FormulaCluster:
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    garbled: bool


class PdfTextCache:
    def __init__(
        self,
        root: Path,
        *,
        extractor: PopplerTextExtractor | None = None,
    ) -> None:
        self._root = root.expanduser()
        self._extractor = extractor if extractor is not None else PopplerTextExtractor()
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def status(self, pdf_path: Path) -> PdfCacheLookup:
        pdf_sha256 = await asyncio.to_thread(_sha256_file, pdf_path)
        identity = await self._extractor.identity()
        return await asyncio.to_thread(self._lookup, pdf_sha256, identity)

    async def lookup_by_sha(self, pdf_sha256: str) -> PdfCacheLookup:
        identity = await self._extractor.identity()
        return await asyncio.to_thread(self._lookup, pdf_sha256, identity)

    async def delete(self, pdf_sha256: str) -> None:
        identity = await self._extractor.identity()
        key_dir = self._key_dir(pdf_sha256, identity.fingerprint)
        await asyncio.to_thread(self._delete_key, key_dir)

    async def delete_by_source_locator(self, source_locator: str) -> tuple[str, ...]:
        identity = await self._extractor.identity()
        return await asyncio.to_thread(
            self._delete_by_source_locator,
            source_locator,
            identity.fingerprint,
        )

    async def ensure(
        self,
        pdf_path: Path,
        *,
        source_locator: str,
    ) -> PdfCacheLookup:
        if not source_locator.strip():
            raise PdfCacheError("source_locator must not be empty")
        pdf_sha256 = await asyncio.to_thread(_sha256_file, pdf_path)
        identity = await self._extractor.identity()
        cache_key = f"{pdf_sha256}:{identity.fingerprint}"
        lock = await self._lock_for(cache_key)
        async with lock:
            existing = await asyncio.to_thread(self._lookup, pdf_sha256, identity)
            if existing.status == "hit":
                return existing
            return await self._build(
                pdf_path=pdf_path,
                source_locator=source_locator,
                pdf_sha256=pdf_sha256,
                identity=identity,
            )

    async def page(
        self,
        cache_ref: PdfCacheRef,
        *,
        page: int,
    ) -> PdfCachePage:
        if page < 1:
            raise PdfCacheError("page must be at least 1")
        return await asyncio.to_thread(self._read_page, cache_ref, page)

    def _read_page(self, cache_ref: PdfCacheRef, page: int) -> PdfCachePage:
        key_dir = self._key_dir(
            cache_ref.pdf_sha256,
            cache_ref.extractor_fingerprint,
        )
        with _paper_file_lock(key_dir, exclusive=False):
            revision_dir = self._revision_dir(cache_ref)
            manifest = _read_manifest(revision_dir)
            if _cache_ref(manifest) != cache_ref:
                raise PdfCacheError("cache reference does not match the stored manifest")
            if page > manifest.page_count:
                raise PdfCacheError(
                    f"page {page} exceeds cached page count {manifest.page_count}"
                )
            if not _artifact_is_valid(revision_dir, manifest):
                raise PdfCacheError("cached text artifact failed its integrity check")
            boundary = manifest.page_boundaries[page - 1]
            text = _read_text_range(
                revision_dir / manifest.artifact.filename,
                boundary.start_offset,
                boundary.end_offset,
            )
            return PdfCachePage(
                cache_ref=cache_ref,
                paper_id=cache_ref.pdf_sha256,
                page=page,
                text=text,
                artifact_sha256=manifest.artifact.sha256,
            )

    async def page_for_paper_id(
        self,
        paper_id: str,
        *,
        page: int,
    ) -> PdfCachePage:
        normalized_paper_id = paper_id.strip().lower()
        if len(normalized_paper_id) != 64 or any(
            character not in "0123456789abcdef"
            for character in normalized_paper_id
        ):
            raise PdfCacheError("paper_id must be a full PDF SHA-256")
        identity = await self._extractor.identity()
        lookup = await asyncio.to_thread(
            self._lookup,
            normalized_paper_id,
            identity,
        )
        if lookup.status != "hit" or lookup.cache_ref is None:
            reason = lookup.reason or "no compatible current revision"
            raise PdfCacheError(f"paper cache is unavailable: {reason}")
        return await self.page(lookup.cache_ref, page=page)

    async def page_for_pdf(
        self,
        pdf_path: Path,
        *,
        source_locator: str,
        page: int,
    ) -> PdfCachePage:
        """Read a page only after binding the cache to the PDF's current bytes."""
        lookup = await self.ensure(pdf_path, source_locator=source_locator)
        if lookup.cache_ref is None:
            raise PdfCacheError("paper cache could not be prepared")
        current_pdf_sha256 = await asyncio.to_thread(_sha256_file, pdf_path)
        if current_pdf_sha256 != lookup.cache_ref.pdf_sha256:
            raise PdfCacheError("PDF content changed before the cached page was read")
        return await self.page(lookup.cache_ref, page=page)

    async def prune_orphans(self, live_pdf_sha256: set[str]) -> tuple[str, ...]:
        """Remove content-addressed caches that no current library PDF references."""
        return await asyncio.to_thread(self._prune_orphans, live_pdf_sha256)

    async def record_formula_ocr(
        self,
        pdf_sha256: str,
        *,
        page: int,
        cache_slot: str,
        latex: str,
        region: dict[str, float],
        model: str,
        render_sha256: str,
        equation_label: str | None,
    ) -> PdfCacheLookup:
        identity = await self._extractor.identity()
        cache_key = f"{pdf_sha256}:{identity.fingerprint}"
        lock = await self._lock_for(cache_key)
        async with lock:
            return await asyncio.to_thread(
                self._record_formula_ocr,
                pdf_sha256,
                identity,
                page,
                cache_slot,
                latex,
                region,
                model,
                render_sha256,
                equation_label,
            )

    async def _build(
        self,
        *,
        pdf_path: Path,
        source_locator: str,
        pdf_sha256: str,
        identity: PopplerIdentity,
    ) -> PdfCacheLookup:
        key_dir = self._key_dir(pdf_sha256, identity.fingerprint)
        revisions_dir = key_dir / "revisions"
        await asyncio.to_thread(revisions_dir.mkdir, parents=True, exist_ok=True)
        staging_path = Path(
            await asyncio.to_thread(
                tempfile.mkdtemp,
                prefix=".staging-",
                dir=key_dir,
            )
        )
        revision_id = uuid4().hex
        try:
            raw_path = staging_path / "source-extraction"
            extraction = await self._extractor.extract(pdf_path, raw_path)
            if extraction.identity != identity:
                raise PdfCacheError("extractor identity changed during cache generation")
            current_pdf_sha256 = await asyncio.to_thread(_sha256_file, pdf_path)
            if current_pdf_sha256 != pdf_sha256:
                raise PdfCacheError("PDF content changed during cache generation")
            raw_bytes = await asyncio.to_thread(raw_path.read_bytes)
            slot_bboxes = await self._collect_slot_bboxes(pdf_path, raw_bytes)
            text_bytes, page_boundaries = _formula_aware_text(
                raw_bytes,
                extraction.page_count,
                slot_bboxes,
            )
            await asyncio.to_thread(raw_path.unlink)
            text_path = staging_path / _LAYOUT_FILENAME
            await asyncio.to_thread(text_path.write_bytes, text_bytes)
            artifact = TextArtifact(
                sha256=hashlib.sha256(text_bytes).hexdigest(),
                byte_count=len(text_bytes),
            )
            manifest = PdfCacheManifest(
                revision_id=revision_id,
                pdf_sha256=pdf_sha256,
                source_locator=source_locator,
                page_count=extraction.page_count,
                extractor_name=identity.name,
                extractor_version=identity.version,
                extractor_fingerprint=identity.fingerprint,
                extraction_mode=identity.mode,
                extraction_parameters=identity.parameters,
                page_boundaries=page_boundaries,
                created_at=datetime.now(UTC),
                status="complete",
                unresolved_pages=[],
                artifact=artifact,
                formula_ocr_records=[],
            )
            await asyncio.to_thread(
                _write_json,
                staging_path / _MANIFEST_FILENAME,
                manifest.model_dump(mode="json"),
            )
            await asyncio.to_thread(
                _publish_revision,
                staging_path,
                key_dir,
                revision_id,
            )
            return PdfCacheLookup(
                status="hit",
                cache_ref=_cache_ref(manifest),
                manifest=manifest,
                reason="generated",
            )
        finally:
            if staging_path.exists():
                await asyncio.to_thread(shutil.rmtree, staging_path)

    async def _collect_slot_bboxes(
        self,
        pdf_path: Path,
        raw_bytes: bytes,
    ) -> dict[int, tuple[tuple[float, float, float, float], ...]]:
        """Compute normalized formula bboxes for pages with garbled lines.

        A bbox failure degrades to a coordinate-less slot instead of failing
        the build: recognition keeps working through region/label inputs.
        """
        raw_pages = raw_bytes.split(b"\f")
        slot_bboxes: dict[int, tuple[tuple[float, float, float, float], ...]] = {}
        for page_number, raw_page in enumerate(raw_pages, start=1):
            if raw_page == b"":
                continue
            text = raw_page.decode("utf-8", errors="replace")
            slot_count = _slot_block_count(text)
            if slot_count == 0:
                continue
            try:
                bbox_html = await self._extractor.page_word_boxes(pdf_path, page_number)
            except PdfCacheError as error:
                _log.warning(
                    "pdf_cache.slot_bbox_extraction_failed",
                    page=page_number,
                    error_type=type(error).__name__,
                )
                continue
            result = _garbled_line_bboxes(bbox_html)
            if result is None:
                continue
            bboxes, garbled_cluster_count = result
            garbled_line_count = sum(
                1 for line in text.splitlines() if _contains_extraction_garble(line)
            )
            # Slots map to formula groups positionally, so both passes must
            # agree line by line (garbled totals) and group by group (block
            # totals); any disagreement makes the coordinates unreliable, so
            # they are dropped for the page.
            if (
                garbled_line_count == garbled_cluster_count
                and len(bboxes) == slot_count
            ):
                slot_bboxes[page_number] = bboxes
        return slot_bboxes

    async def slot_bbox(
        self,
        pdf_sha256: str,
        *,
        page: int,
        cache_slot: str,
    ) -> dict[str, float] | None:
        """Return the stored normalized crop for a garbled formula slot.

        None means the cache misses, the slot exists without coordinates, or
        the slot is unknown; callers fall back to explicit locators.
        """
        if page < 1:
            raise PdfCacheError("page must be at least 1")
        if re.fullmatch(r"page-[0-9]{4}-formula-[0-9]{4}", cache_slot) is None:
            raise PdfCacheError("cache_slot has an invalid slot identifier format")
        identity = await self._extractor.identity()
        return await asyncio.to_thread(
            self._slot_bbox,
            pdf_sha256,
            identity,
            page,
            cache_slot,
        )

    def _slot_bbox(
        self,
        pdf_sha256: str,
        identity: PopplerIdentity,
        page: int,
        cache_slot: str,
    ) -> dict[str, float] | None:
        key_dir = self._key_dir(pdf_sha256, identity.fingerprint)
        with _paper_file_lock(key_dir, exclusive=False):
            lookup = self._lookup_unlocked(pdf_sha256, identity)
            if lookup.status != "hit" or lookup.cache_ref is None or lookup.manifest is None:
                return None
            manifest = lookup.manifest
            if page > manifest.page_count:
                return None
            revision_dir = self._revision_dir(lookup.cache_ref)
            if not _artifact_is_valid(revision_dir, manifest):
                return None
            boundary = manifest.page_boundaries[page - 1]
            text = _read_text_range(
                revision_dir / manifest.artifact.filename,
                boundary.start_offset,
                boundary.end_offset,
            )
        for match in _SLOT_BBOX_PATTERN.finditer(text):
            if match.group(1) != cache_slot or int(match.group(2)) != page:
                continue
            x1, y1, x2, y2 = (float(match.group(index)) for index in range(3, 7))
            if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
                return None
            return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
        return None

    def _record_formula_ocr(
        self,
        pdf_sha256: str,
        identity: PopplerIdentity,
        page: int,
        cache_slot: str,
        latex: str,
        region: dict[str, float],
        model: str,
        render_sha256: str,
        equation_label: str | None,
    ) -> PdfCacheLookup:
        key_dir = self._key_dir(pdf_sha256, identity.fingerprint)
        with _paper_file_lock(key_dir, exclusive=True):
            return self._record_formula_ocr_locked(
                pdf_sha256,
                identity,
                page,
                cache_slot,
                latex,
                region,
                model,
                render_sha256,
                equation_label,
            )

    def _record_formula_ocr_locked(
        self,
        pdf_sha256: str,
        identity: PopplerIdentity,
        page: int,
        cache_slot: str,
        latex: str,
        region: dict[str, float],
        model: str,
        render_sha256: str,
        equation_label: str | None,
    ) -> PdfCacheLookup:
        lookup = self._lookup_unlocked(pdf_sha256, identity)
        if lookup.status != "hit" or lookup.cache_ref is None or lookup.manifest is None:
            raise PdfCacheError("formula-aware text cache is unavailable for formula OCR")
        manifest = lookup.manifest
        if page > manifest.page_count:
            raise PdfCacheError("formula OCR page exceeds the cached page count")
        revision_dir = self._revision_dir(lookup.cache_ref)
        source_path = revision_dir / manifest.artifact.filename
        text = source_path.read_text(encoding="utf-8")
        start_pattern = (
            r"\[\[paper-copilot-ocr:start slot="
            + re.escape(cache_slot)
            + r" page="
            + str(page)
            + r"[^\]]*\]\]"
        )
        end = _OCR_END_TEMPLATE.format(slot=cache_slot)
        pattern = re.compile(start_pattern + r".*?" + re.escape(end), re.DOTALL)
        if pattern.search(text) is None:
            raise PdfCacheError(
                f"formula OCR cache slot is unavailable on page {page}: {cache_slot}"
            )
        normalized_latex = latex.strip()
        label_token = _marker_label_token(equation_label)
        marker = (
            f"[[paper-copilot-ocr:recognized slot={cache_slot} page={page}"
            f"{label_token} model={model} render_sha256={render_sha256} verified=false]]"
        )
        replacement = (
            f"{marker}\n"
            f"$$\n{normalized_latex}\n$$"
        )
        updated = pattern.sub(lambda _: replacement, text, count=1)
        updated_bytes = updated.encode("utf-8")
        page_boundaries = _page_boundaries(updated_bytes, manifest.page_count)
        revision_id = uuid4().hex
        key_dir = self._key_dir(pdf_sha256, identity.fingerprint)
        staging_path = Path(tempfile.mkdtemp(prefix=".staging-", dir=key_dir))
        try:
            artifact = TextArtifact(
                sha256=hashlib.sha256(updated_bytes).hexdigest(),
                byte_count=len(updated_bytes),
            )
            record = FormulaOCRRecord(
                slot=cache_slot,
                page=page,
                region=region,
                model=model,
                render_sha256=render_sha256,
                latex_sha256=hashlib.sha256(normalized_latex.encode("utf-8")).hexdigest(),
                created_at=datetime.now(UTC),
            )
            derived = manifest.model_copy(
                update={
                    "revision_id": revision_id,
                    "page_boundaries": page_boundaries,
                    "created_at": datetime.now(UTC),
                    "artifact": artifact,
                    "formula_ocr_records": [*manifest.formula_ocr_records, record],
                }
            )
            (staging_path / _LAYOUT_FILENAME).write_bytes(updated_bytes)
            _write_json(
                staging_path / _MANIFEST_FILENAME,
                derived.model_dump(mode="json"),
            )
            _publish_revision_unlocked(staging_path, key_dir, revision_id)
            return PdfCacheLookup(
                status="hit",
                cache_ref=_cache_ref(derived),
                manifest=derived,
                reason="formula OCR recorded",
            )
        finally:
            if staging_path.exists():
                shutil.rmtree(staging_path)

    async def _lock_for(self, cache_key: str) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._locks.get(cache_key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[cache_key] = lock
            return lock

    def _lookup(
        self,
        pdf_sha256: str,
        identity: PopplerIdentity,
    ) -> PdfCacheLookup:
        key_dir = self._key_dir(pdf_sha256, identity.fingerprint)
        with _paper_file_lock(key_dir, exclusive=False):
            return self._lookup_unlocked(pdf_sha256, identity)

    def _lookup_unlocked(
        self,
        pdf_sha256: str,
        identity: PopplerIdentity,
    ) -> PdfCacheLookup:
        key_dir = self._key_dir(pdf_sha256, identity.fingerprint)
        current_path = key_dir / _CURRENT_FILENAME
        if not current_path.is_file():
            return PdfCacheLookup(status="miss", reason="no current revision")
        try:
            current = _CurrentRevision.model_validate_json(current_path.read_text())
            revision_dir = key_dir / "revisions" / current.revision_id
            manifest = _read_manifest(revision_dir)
        except (OSError, ValueError) as error:
            return PdfCacheLookup(status="corrupt", reason=str(error))
        if manifest.pdf_sha256 != pdf_sha256:
            return PdfCacheLookup(status="corrupt", reason="PDF hash mismatch")
        if manifest.extractor_fingerprint != identity.fingerprint:
            return PdfCacheLookup(
                status="incompatible",
                reason="extractor fingerprint mismatch",
            )
        if manifest.status != "complete":
            return PdfCacheLookup(
                status="incompatible",
                reason=f"revision status is {manifest.status}",
            )
        if len(manifest.page_boundaries) != manifest.page_count:
            return PdfCacheLookup(status="corrupt", reason="page boundary count mismatch")
        if not _artifact_is_valid(revision_dir, manifest):
            return PdfCacheLookup(status="corrupt", reason="artifact integrity check failed")
        return PdfCacheLookup(
            status="hit",
            cache_ref=_cache_ref(manifest),
            manifest=manifest,
        )

    def _key_dir(self, pdf_sha256: str, extractor_fingerprint: str) -> Path:
        return self._root / pdf_sha256 / extractor_fingerprint

    def _revision_dir(self, cache_ref: PdfCacheRef) -> Path:
        return (
            self._key_dir(cache_ref.pdf_sha256, cache_ref.extractor_fingerprint)
            / "revisions"
            / cache_ref.revision_id
        )

    def _prune_orphans(self, live_pdf_sha256: set[str]) -> tuple[str, ...]:
        if not self._root.is_dir():
            return ()
        removed: list[str] = []
        for candidate in self._root.iterdir():
            name = candidate.name.lower()
            if (
                candidate.is_dir()
                and len(name) == 64
                and all(character in "0123456789abcdef" for character in name)
                and name not in live_pdf_sha256
            ):
                with _paper_file_lock(candidate, exclusive=True):
                    if candidate.is_dir():
                        shutil.rmtree(candidate)
                        removed.append(name)
        return tuple(sorted(removed))

    def _delete_key(self, key_dir: Path) -> None:
        if not key_dir.is_dir():
            return
        with _paper_file_lock(key_dir, exclusive=True):
            if key_dir.is_dir():
                shutil.rmtree(key_dir)
        parent = key_dir.parent
        if parent != self._root and parent.is_dir():
            try:
                parent.rmdir()
            except OSError:
                # Another fingerprint directory (or writer) still occupies this
                # key; leaving the outer sha directory in place is correct.
                pass

    def _delete_by_source_locator(
        self,
        source_locator: str,
        fingerprint: str,
    ) -> tuple[str, ...]:
        if not self._root.is_dir():
            return ()
        removed: list[str] = []
        for candidate in self._root.iterdir():
            name = candidate.name.lower()
            if not (
                candidate.is_dir()
                and len(name) == 64
                and all(character in "0123456789abcdef" for character in name)
            ):
                continue
            key_dir = candidate / fingerprint
            try:
                current_path = key_dir / _CURRENT_FILENAME
                current = _CurrentRevision.model_validate_json(
                    current_path.read_text(encoding="utf-8")
                )
                manifest = _read_manifest(
                    key_dir / "revisions" / current.revision_id
                )
            except (OSError, ValueError):
                continue
            if manifest.source_locator != source_locator:
                continue
            self._delete_key(key_dir)
            removed.append(name)
        return tuple(sorted(removed))


def _page_boundaries(layout_bytes: bytes, page_count: int) -> list[PageBoundary]:
    separator = b"\f"
    raw_pages = layout_bytes.split(separator)
    if raw_pages and raw_pages[-1] == b"":
        raw_pages.pop()
    if len(raw_pages) != page_count:
        raise PdfCacheError(
            "text cache page separators do not match PDF page count: "
            f"{len(raw_pages)} != {page_count}"
        )
    boundaries: list[PageBoundary] = []
    offset = 0
    for page_number, page_bytes in enumerate(raw_pages, start=1):
        end_offset = offset + len(page_bytes)
        boundaries.append(
            PageBoundary(
                page=page_number,
                start_offset=offset,
                end_offset=end_offset,
                character_count=len(page_bytes.decode("utf-8", errors="replace")),
            )
        )
        offset = end_offset + len(separator)
    return boundaries


def _formula_aware_text(
    raw_bytes: bytes,
    page_count: int,
    slot_bboxes: dict[int, tuple[tuple[float, float, float, float], ...]] | None = None,
) -> tuple[bytes, list[PageBoundary]]:
    raw_pages = raw_bytes.split(b"\f")
    if raw_pages and raw_pages[-1] == b"":
        raw_pages.pop()
    if len(raw_pages) != page_count:
        raise PdfCacheError(
            "source extraction page separators do not match PDF page count: "
            f"{len(raw_pages)} != {page_count}"
        )
    rendered_pages: list[str] = []
    for page, raw_page in enumerate(raw_pages, start=1):
        text = raw_page.decode("utf-8", errors="replace")
        page_bboxes = (slot_bboxes or {}).get(page, ())
        rendered_pages.append(_render_text_page(text, page, page_bboxes))
    text_bytes = "\f".join(rendered_pages).encode("utf-8") + b"\f"
    return text_bytes, _page_boundaries(text_bytes, page_count)


def _garbled_flags(text: str) -> list[bool]:
    return [_contains_extraction_garble(line) for line in text.splitlines()]


def _slot_block_count(text: str) -> int:
    """Count slot blocks: garbled runs bridged by short clean gaps.

    Mirrors the bbox side's grouping so the two passes produce the same
    formula count and coordinates can attach positionally.
    """
    return len(_group_garbled_runs(_garbled_flags(text)))


def _group_garbled_runs(flags: Sequence[bool]) -> list[tuple[int, int]]:
    """Group garbled runs separated by at most the bridging gap of clean items.

    Returns half-open line ranges covering each block, including bridged
    clean lines. Trailing clean lines without a following garbled run stay
    outside any block.
    """
    blocks: list[tuple[int, int]] = []
    block_start: int | None = None
    last_garbled = -1
    for index, garbled in enumerate(flags):
        if not garbled:
            continue
        if block_start is None:
            block_start = index
        elif index - last_garbled - 1 > _MAX_INTRA_FORMULA_CLEAN_LINES:
            blocks.append((block_start, last_garbled + 1))
            block_start = index
        last_garbled = index
    if block_start is not None:
        blocks.append((block_start, last_garbled + 1))
    return blocks


def _render_text_page(
    text: str,
    page: int,
    slot_bboxes: Sequence[tuple[float, float, float, float]] = (),
) -> str:
    lines: list[str] = [f"[[paper-copilot-page:{page}]]", ""]
    slot_index = 0
    pending: list[str] = []
    pending_has_garble = False
    pending_clean_tail = 0

    def flush_pending() -> None:
        # One slot per formula block: a display formula spanning several
        # extraction lines (including interleaved clean limit rows) is one
        # physical formula, so its lines share one slot and one crop. Clean
        # lines held at the tail that never bridged to another garbled run
        # stay outside the slot.
        nonlocal slot_index, pending_has_garble, pending_clean_tail
        if not pending:
            return
        if not pending_has_garble:
            lines.extend(pending)
        else:
            body_end = len(pending) - pending_clean_tail
            slot_index += 1
            slot = f"page-{page:04d}-formula-{slot_index:04d}"
            bbox = (
                slot_bboxes[slot_index - 1] if slot_index - 1 < len(slot_bboxes) else None
            )
            lines.append(_ocr_start_marker(slot, page, bbox))
            lines.append(f"[公式 OCR 待识别；cache_slot={slot}]")
            lines.extend(f"原始提取：{line}" for line in pending[:body_end])
            lines.append(_OCR_END_TEMPLATE.format(slot=slot))
            lines.extend(pending[body_end:])
        pending.clear()
        pending_has_garble = False
        pending_clean_tail = 0

    for line in text.splitlines():
        if _contains_extraction_garble(line):
            pending.append(line)
            pending_has_garble = True
            pending_clean_tail = 0
            continue
        if pending_has_garble and pending_clean_tail < _MAX_INTRA_FORMULA_CLEAN_LINES:
            # Hold a short clean tail: a garbled line right after keeps it
            # inside the formula block; otherwise it is flushed as prose.
            pending.append(line)
            pending_clean_tail += 1
            continue
        flush_pending()
        lines.append(line)
    flush_pending()
    return "\n".join(lines).rstrip() + "\n"


def _ocr_start_marker(
    slot: str,
    page: int,
    bbox: tuple[float, float, float, float] | None,
) -> str:
    marker = _OCR_START_TEMPLATE.format(slot=slot, page=page)
    if bbox is None:
        return marker
    x1, y1, x2, y2 = bbox
    coordinates = ",".join(f"{value:.4f}" for value in (x1, y1, x2, y2))
    return marker[:-2] + f" bbox={coordinates}]]"


def _garbled_line_bboxes(
    bbox_html: str,
) -> tuple[tuple[tuple[float, float, float, float], ...], int] | None:
    """Compute one normalized bbox per formula group in reading order.

    Returns the boxes together with the garbled cluster total so callers can
    gate on both passes agreeing line by line and group by group. A display
    formula occupying several garbled text lines (with interleaved clean
    limit rows) yields a single box. Returns None when the bbox page cannot
    be parsed, so callers keep plain coordinate-less slots instead of
    writing misleading coordinates.
    """
    page_match = _BBOX_PAGE_PATTERN.search(bbox_html)
    if page_match is None:
        return None
    page_width = float(page_match.group(1))
    page_height = float(page_match.group(2))
    if page_width <= 0.0 or page_height <= 0.0:
        return None
    words: list[_WordBox] = []
    for match in _BBOX_WORD_PATTERN.finditer(bbox_html):
        x_min, y_min, x_max, y_max = (float(match.group(index)) for index in range(1, 5))
        if x_max <= x_min or y_max <= y_min:
            continue
        words.append(
            _WordBox(
                x_min=x_min,
                y_min=y_min,
                x_max=x_max,
                y_max=y_max,
                text=html_module.unescape(match.group(5)),
            )
        )
    if not words:
        return None
    clusters = _cluster_words_into_lines(words)
    garbled_cluster_count = sum(1 for cluster in clusters if cluster.garbled)
    groups = _formula_groups(clusters)
    if not groups:
        return ((), garbled_cluster_count)
    boxes: list[tuple[float, float, float, float]] = []
    for group in groups:
        box = _absorb_formula_neighbors(group, clusters)
        x1 = max(0.0, min(1.0, (box[0] - _BBOX_MARGIN_POINTS) / page_width))
        y1 = max(0.0, min(1.0, (box[1] - _BBOX_MARGIN_POINTS) / page_height))
        x2 = max(0.0, min(1.0, (box[2] + _BBOX_MARGIN_POINTS) / page_width))
        y2 = max(0.0, min(1.0, (box[3] + _BBOX_MARGIN_POINTS) / page_height))
        if x2 <= x1 or y2 <= y1:
            return None
        boxes.append((x1, y1, x2, y2))
    return (tuple(boxes), garbled_cluster_count)


def _cluster_words_into_lines(words: list[_WordBox]) -> list[_FormulaCluster]:
    ordered = sorted(words, key=lambda word: (word.y_min, word.x_min))
    clusters: list[list[_WordBox]] = []
    for word in ordered:
        if clusters and word.y_min <= max(member.y_max for member in clusters[-1]):
            clusters[-1].append(word)
        else:
            clusters.append([word])
    return [
        _FormulaCluster(
            x_min=min(word.x_min for word in members),
            y_min=min(word.y_min for word in members),
            x_max=max(word.x_max for word in members),
            y_max=max(word.y_max for word in members),
            garbled=any(_contains_extraction_garble(word.text) for word in members),
        )
        for members in clusters
    ]


def _formula_groups(
    clusters: list[_FormulaCluster],
) -> list[_FormulaCluster]:
    """Merge garbled clusters into one group per display formula.

    Two merge rules mirror the text-side slot blocks: garbled clusters with
    at most the bridging gap of clean clusters between them stay one formula
    (summation limits and fraction rows extract clean between garbled rows),
    and consecutive garbled clusters merge when geometrically adjacent (a
    gap below their own height), which keeps far-apart formulas separated
    even when no clean clusters sit between them.
    """
    group_members: list[list[_FormulaCluster]] = []
    pending_clean: list[_FormulaCluster] = []
    for cluster in clusters:
        if not cluster.garbled:
            if group_members:
                pending_clean.append(cluster)
            continue
        bridged = False
        if group_members:
            previous = group_members[-1]
            if pending_clean:
                bridged = len(pending_clean) <= _MAX_INTRA_FORMULA_CLEAN_LINES
            else:
                last = previous[-1]
                gap = cluster.y_min - last.y_max
                tolerance = _BBOX_CLUSTER_GAP_FACTOR * min(
                    last.y_max - last.y_min,
                    cluster.y_max - cluster.y_min,
                )
                bridged = gap <= tolerance
            if bridged:
                previous.extend(pending_clean)
                previous.append(cluster)
                pending_clean = []
                continue
        pending_clean = []
        group_members.append([cluster])
    return [_merge_cluster_boxes(members) for members in group_members]


def _merge_cluster_boxes(members: list[_FormulaCluster]) -> _FormulaCluster:
    return _FormulaCluster(
        x_min=min(member.x_min for member in members),
        y_min=min(member.y_min for member in members),
        x_max=max(member.x_max for member in members),
        y_max=max(member.y_max for member in members),
        garbled=True,
    )


def _absorb_formula_neighbors(
    group: _FormulaCluster,
    clusters: list[_FormulaCluster],
) -> tuple[float, float, float, float]:
    """Grow the group box to vertically adjacent clusters inside its span.

    Summation limits and fraction rows are not garbled themselves, but they
    sit just above or below the garbled band and inside its horizontal
    extent; prose lines outside the span stay excluded.
    """
    box = [group.x_min, group.y_min, group.x_max, group.y_max]
    changed = True
    while changed:
        changed = False
        for cluster in clusters:
            if cluster.garbled:
                continue
            if cluster.x_min < box[0] - _BBOX_ABSORB_PADDING_POINTS:
                continue
            if cluster.x_max > box[2] + _BBOX_ABSORB_PADDING_POINTS:
                continue
            above = box[1] - cluster.y_max
            below = cluster.y_min - box[3]
            gap = above if cluster.y_max <= box[1] else below if cluster.y_min >= box[3] else 0.0
            if gap > 8.0:
                continue
            grown = (
                cluster.x_min < box[0]
                or cluster.y_min < box[1]
                or cluster.x_max > box[2]
                or cluster.y_max > box[3]
            )
            box[0] = min(box[0], cluster.x_min)
            box[1] = min(box[1], cluster.y_min)
            box[2] = max(box[2], cluster.x_max)
            box[3] = max(box[3], cluster.y_max)
            changed = changed or grown
    return (box[0], box[1], box[2], box[3])


def _marker_label_token(equation_label: str | None) -> str:
    if equation_label is None or _SAFE_LABEL_PATTERN.fullmatch(equation_label) is None:
        return ""
    return f" label={equation_label}"


def _contains_extraction_garble(text: str) -> bool:
    return any(
        character == "\ufffd" or "\ue000" <= character <= "\uf8ff"
        for character in text
    )


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise PdfCacheError("PDF path does not identify a regular file")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as pdf_file:
            while chunk := pdf_file.read(_READ_CHUNK_BYTES):
                digest.update(chunk)
    except OSError as error:
        raise PdfCacheError("PDF could not be read") from error
    return digest.hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact_file:
        while chunk := artifact_file.read(_READ_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(revision_dir: Path) -> PdfCacheManifest:
    manifest_path = revision_dir / _MANIFEST_FILENAME
    return PdfCacheManifest.model_validate_json(manifest_path.read_text())


def _artifact_is_valid(revision_dir: Path, manifest: PdfCacheManifest) -> bool:
    artifact_path = revision_dir / manifest.artifact.filename
    try:
        stat = artifact_path.stat()
        return (
            stat.st_size == manifest.artifact.byte_count
            and _sha256_path(artifact_path) == manifest.artifact.sha256
        )
    except OSError:
        return False


def _cache_ref(manifest: PdfCacheManifest) -> PdfCacheRef:
    return PdfCacheRef(
        pdf_sha256=manifest.pdf_sha256,
        extractor_fingerprint=manifest.extractor_fingerprint,
        revision_id=manifest.revision_id,
    )


def _read_text_range(path: Path, start_offset: int, end_offset: int) -> str:
    with path.open("rb") as artifact_file:
        artifact_file.seek(start_offset)
        raw_text = artifact_file.read(end_offset - start_offset)
    return raw_text.decode("utf-8", errors="replace")


def _publish_revision(
    staging_path: Path,
    key_dir: Path,
    revision_id: str,
) -> None:
    with _paper_file_lock(key_dir, exclusive=True):
        _publish_revision_unlocked(staging_path, key_dir, revision_id)


def _publish_revision_unlocked(
    staging_path: Path,
    key_dir: Path,
    revision_id: str,
) -> None:
    revision_target = key_dir / "revisions" / revision_id
    os.replace(staging_path, revision_target)
    _publish_current(key_dir, revision_id)
    _delete_superseded_revisions(key_dir, keep_revision_id=revision_id)


@contextmanager
def _paper_file_lock(key_dir: Path, *, exclusive: bool) -> Iterator[None]:
    key_dir.mkdir(parents=True, exist_ok=True)
    lock_path = key_dir / ".paper.lock"
    with lock_path.open("a+b") as lock_file:
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(lock_file.fileno(), operation)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _publish_current(key_dir: Path, revision_id: str) -> None:
    current = _CurrentRevision(revision_id=revision_id)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=key_dir,
        prefix=".current-",
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
        temporary.write(current.model_dump_json())
        temporary.flush()
        os.fsync(temporary.fileno())
    try:
        os.replace(temporary_path, key_dir / _CURRENT_FILENAME)
    finally:
        temporary_path.unlink(missing_ok=True)


def _delete_superseded_revisions(
    key_dir: Path,
    *,
    keep_revision_id: str,
) -> None:
    revisions_dir = key_dir / "revisions"
    try:
        for candidate in revisions_dir.iterdir():
            if (
                candidate.name == keep_revision_id
                or _REVISION_ID_PATTERN.fullmatch(candidate.name) is None
                or not candidate.is_dir()
                or candidate.is_symlink()
            ):
                continue
            shutil.rmtree(candidate)
    except OSError as error:
        _log.warning(
            "pdf_cache.revision_cleanup_failed",
            current_revision_id=keep_revision_id,
            error_type=type(error).__name__,
        )


def _write_json(path: Path, payload: object) -> None:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    with path.open("w", encoding="utf-8") as manifest_file:
        manifest_file.write(encoded + "\n")
        manifest_file.flush()
        os.fsync(manifest_file.fileno())
