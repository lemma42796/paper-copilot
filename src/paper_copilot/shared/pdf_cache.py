from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pymupdf
from pydantic import BaseModel, ConfigDict, Field, field_validator

from paper_copilot.shared.errors import PdfCacheError
from paper_copilot.shared.logging import get_logger
from paper_copilot.shared.poppler import PopplerIdentity, PopplerTextExtractor

__all__ = [
    "PageBoundary",
    "FormulaTargetSnapshot",
    "PdfCacheLookup",
    "PdfCacheManifest",
    "PdfCachePage",
    "PdfCacheRef",
    "PdfTextCache",
    "TextArtifact",
]

_SCHEMA_VERSION = 3
_LAYOUT_FILENAME = "layout.txt"
_MANIFEST_FILENAME = "manifest.json"
_CURRENT_FILENAME = "current.json"
_READ_CHUNK_BYTES = 1024 * 1024
_REPAIR_START_TEMPLATE = (
    "[[paper-copilot-formula:repair-start id={repair_span_id} page={page}]]"
)
_REPAIR_END_TEMPLATE = (
    "[[paper-copilot-formula:repair-end id={repair_span_id}]]"
)
_REVISION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
# One display formula can interleave clean extraction lines between its
# garbled rows (summation limits, fraction numerators). Garbled runs or
# clusters bridged by at most this many clean lines/clusters stay one
# formula; longer clean gaps mean separate formulas or prose. The same bound
# applies on both extraction passes so their group counts can align.
_MAX_INTRA_FORMULA_CLEAN_LINES = 2
_ENGLISH_PROSE_WORD_PATTERN = re.compile(r"[A-Za-z]{2,}")
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

    target_kind: Literal["repair_span", "replacement_text"]
    repair_span_id: str | None = Field(
        default=None,
        pattern=r"^page-[0-9]{4}-repair-[0-9]{4}$",
    )
    target_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page: int = Field(ge=1)
    region: dict[str, float]
    model: str = Field(min_length=1)
    render_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    latex_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Set only when the published LaTeX was model-refined before caching; the
    # raw OCR output hash keeps the audit chain intact (full OCR text remains
    # in the append-only session history).
    refined: bool = False
    ocr_latex_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    created_at: datetime


class PdfCacheManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[3] = _SCHEMA_VERSION
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
class FormulaTargetSnapshot:
    target_kind: Literal["repair_span", "replacement_text"]
    target_sha256: str
    cache_revision_id: str
    cache_artifact_sha256: str


@dataclass(frozen=True, slots=True)
class _FormulaHint:
    start_bbox: tuple[float, float, float, float]
    end_bbox: tuple[float, float, float, float]
    line_count: int


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

    async def snapshot_formula_target(
        self,
        pdf_sha256: str,
        *,
        page: int,
        repair_span_id: str | None,
        replacement_text: str | None,
    ) -> FormulaTargetSnapshot:
        identity = await self._extractor.identity()
        return await asyncio.to_thread(
            self._snapshot_formula_target,
            pdf_sha256,
            identity,
            page,
            repair_span_id,
            replacement_text,
        )

    async def record_formula_latex(
        self,
        pdf_sha256: str,
        *,
        page: int,
        repair_span_id: str | None,
        replacement_text: str | None,
        expected_target_sha256: str,
        latex: str,
        ocr_latex: str,
        region: dict[str, float],
        model: str,
        render_sha256: str,
    ) -> PdfCacheLookup:
        identity = await self._extractor.identity()
        cache_key = f"{pdf_sha256}:{identity.fingerprint}"
        lock = await self._lock_for(cache_key)
        async with lock:
            return await asyncio.to_thread(
                self._record_formula_latex,
                pdf_sha256,
                identity,
                page,
                repair_span_id,
                replacement_text,
                expected_target_sha256,
                latex,
                ocr_latex,
                region,
                model,
                render_sha256,
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
            formula_hints = await self._collect_formula_hints(pdf_path, raw_bytes)
            text_bytes, page_boundaries = _formula_aware_text(
                raw_bytes,
                extraction.page_count,
                formula_hints,
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

    async def _collect_formula_hints(
        self,
        pdf_path: Path,
        raw_bytes: bytes,
    ) -> dict[int, tuple[_FormulaHint, ...]]:
        """Pre-embed advisory endpoints only for damaged non-prose line runs."""
        raw_pages = raw_bytes.split(b"\f")
        formula_hints: dict[int, tuple[_FormulaHint, ...]] = {}
        for page_number, raw_page in enumerate(raw_pages, start=1):
            if raw_page == b"":
                continue
            text = raw_page.decode("utf-8", errors="replace")
            if not any(
                _contains_extraction_garble(line) and not _line_has_prose(line)
                for line in text.splitlines()
            ):
                continue
            try:
                hints = await asyncio.to_thread(
                    _page_formula_hints,
                    pdf_path,
                    page_number,
                )
            except (OSError, RuntimeError, ValueError) as error:
                _log.warning(
                    "pdf_cache.formula_hint_extraction_failed",
                    page=page_number,
                    error_type=type(error).__name__,
                )
                continue
            if hints:
                formula_hints[page_number] = hints
        return formula_hints

    def _snapshot_formula_target(
        self,
        pdf_sha256: str,
        identity: PopplerIdentity,
        page: int,
        repair_span_id: str | None,
        replacement_text: str | None,
    ) -> FormulaTargetSnapshot:
        key_dir = self._key_dir(pdf_sha256, identity.fingerprint)
        with _paper_file_lock(key_dir, exclusive=False):
            lookup = self._lookup_unlocked(pdf_sha256, identity)
            if (
                lookup.status != "hit"
                or lookup.cache_ref is None
                or lookup.manifest is None
            ):
                raise PdfCacheError(
                    "formula-aware text cache is unavailable for formula targeting"
                )
            manifest = lookup.manifest
            if page > manifest.page_count:
                raise PdfCacheError("formula target page exceeds the cached page count")
            revision_dir = self._revision_dir(lookup.cache_ref)
            boundary = manifest.page_boundaries[page - 1]
            page_text = _read_text_range(
                revision_dir / manifest.artifact.filename,
                boundary.start_offset,
                boundary.end_offset,
            )
            target_kind, target_text, _start, _end = _resolve_formula_target(
                page_text,
                page=page,
                repair_span_id=repair_span_id,
                replacement_text=replacement_text,
            )
            return FormulaTargetSnapshot(
                target_kind=target_kind,
                target_sha256=hashlib.sha256(target_text.encode("utf-8")).hexdigest(),
                cache_revision_id=manifest.revision_id,
                cache_artifact_sha256=manifest.artifact.sha256,
            )

    def _record_formula_latex(
        self,
        pdf_sha256: str,
        identity: PopplerIdentity,
        page: int,
        repair_span_id: str | None,
        replacement_text: str | None,
        expected_target_sha256: str,
        latex: str,
        ocr_latex: str,
        region: dict[str, float],
        model: str,
        render_sha256: str,
    ) -> PdfCacheLookup:
        key_dir = self._key_dir(pdf_sha256, identity.fingerprint)
        with _paper_file_lock(key_dir, exclusive=True):
            return self._record_formula_latex_locked(
                pdf_sha256,
                identity,
                page,
                repair_span_id,
                replacement_text,
                expected_target_sha256,
                latex,
                ocr_latex,
                region,
                model,
                render_sha256,
            )

    def _record_formula_latex_locked(
        self,
        pdf_sha256: str,
        identity: PopplerIdentity,
        page: int,
        repair_span_id: str | None,
        replacement_text: str | None,
        expected_target_sha256: str,
        latex: str,
        ocr_latex: str,
        region: dict[str, float],
        model: str,
        render_sha256: str,
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
        pages = text.split("\f")
        if pages and pages[-1] == "":
            pages.pop()
        if len(pages) != manifest.page_count:
            raise PdfCacheError("cached formula text has invalid page separators")
        target_kind, target_text, start, end = _resolve_formula_target(
            pages[page - 1],
            page=page,
            repair_span_id=repair_span_id,
            replacement_text=replacement_text,
        )
        actual_target_sha256 = hashlib.sha256(target_text.encode("utf-8")).hexdigest()
        if actual_target_sha256 != expected_target_sha256:
            raise PdfCacheError(
                "formula replacement target changed after recognition; recognize again"
            )
        normalized_latex = latex.strip()
        normalized_ocr_latex = ocr_latex.strip()
        refined = normalized_latex != normalized_ocr_latex
        refined_token = " refined=true" if refined else ""
        target_token = (
            repair_span_id
            if repair_span_id is not None
            else f"text-{actual_target_sha256[:16]}"
        )
        marker = (
            f"[[paper-copilot-formula:latex target={target_token} page={page}"
            f" model={model} render_sha256={render_sha256}"
            f"{refined_token} verified=false]]"
        )
        replacement = f"{marker}\n$$\n{normalized_latex}\n$$"
        page_text = pages[page - 1]
        pages[page - 1] = page_text[:start] + replacement + page_text[end:]
        updated = "\f".join(pages) + "\f"
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
                target_kind=target_kind,
                repair_span_id=repair_span_id,
                target_sha256=actual_target_sha256,
                page=page,
                region=region,
                model=model,
                render_sha256=render_sha256,
                latex_sha256=hashlib.sha256(normalized_latex.encode("utf-8")).hexdigest(),
                refined=refined,
                ocr_latex_sha256=(
                    hashlib.sha256(normalized_ocr_latex.encode("utf-8")).hexdigest()
                    if refined
                    else None
                ),
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
    formula_hints: dict[int, tuple[_FormulaHint, ...]] | None = None,
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
        page_hints = (formula_hints or {}).get(page, ())
        rendered_pages.append(_render_text_page(text, page, page_hints))
    text_bytes = "\f".join(rendered_pages).encode("utf-8") + b"\f"
    return text_bytes, _page_boundaries(text_bytes, page_count)


def _repair_flags(text: str) -> list[bool]:
    return [
        _contains_extraction_garble(line) and not _line_has_prose(line)
        for line in text.splitlines()
    ]


def _repair_span_count(text: str) -> int:
    """Count stable cache replacement spans without inferring OCR crops."""
    return len(_repair_blocks(text))


def _repair_blocks(text: str) -> list[tuple[int, int]]:
    """Return damaged non-prose runs, bridging only short formula-like gaps."""
    lines = text.splitlines()
    repair_flags = _repair_flags(text)
    blocks: list[tuple[int, int]] = []
    block_start: int | None = None
    last_garbled = -1
    for index, (line, garbled) in enumerate(
        zip(lines, repair_flags, strict=True)
    ):
        if garbled:
            if block_start is None:
                block_start = index
            elif index - last_garbled - 1 > _MAX_INTRA_FORMULA_CLEAN_LINES:
                blocks.append((block_start, last_garbled + 1))
                block_start = index
            last_garbled = index
            continue
        if block_start is not None and (
            _line_has_prose(line)
            or index - last_garbled > _MAX_INTRA_FORMULA_CLEAN_LINES
        ):
            blocks.append((block_start, last_garbled + 1))
            block_start = None
    if block_start is not None:
        blocks.append((block_start, last_garbled + 1))
    return blocks


def _render_text_page(
    text: str,
    page: int,
    formula_hints: Sequence[_FormulaHint] = (),
) -> str:
    # Repair eligibility must run on raw text: mixed prose lines stay outside
    # automatic replacement spans even when they contain damaged characters.
    repair_blocks = _repair_blocks(text)
    # Control characters are invisible to models; render them as Unicode
    # control pictures so extraction damage like math glyphs mapped to C0
    # codes becomes visible in the cached text.
    text = _visualize_control_characters(text)
    lines: list[str] = [f"[[paper-copilot-page:{page}]]"]
    for hint_index, hint in enumerate(formula_hints, start=1):
        lines.append(_formula_hint_marker(page, hint_index, hint))
    lines.append("")
    rendered_source_lines = text.splitlines()
    block_by_start = {start: end for start, end in repair_blocks}
    source_index = 0
    repair_index = 0
    while source_index < len(rendered_source_lines):
        block_end = block_by_start.get(source_index)
        if block_end is None:
            lines.append(rendered_source_lines[source_index])
            source_index += 1
            continue
        repair_index += 1
        repair_span_id = f"page-{page:04d}-repair-{repair_index:04d}"
        lines.append(
            _REPAIR_START_TEMPLATE.format(
                repair_span_id=repair_span_id,
                page=page,
            )
        )
        lines.append(f"[公式文本待恢复；repair_span_id={repair_span_id}]")
        lines.extend(
            f"原始提取：{line}"
            for line in rendered_source_lines[source_index:block_end]
        )
        lines.append(_REPAIR_END_TEMPLATE.format(repair_span_id=repair_span_id))
        source_index = block_end
    return "\n".join(lines).rstrip() + "\n"


def _formula_hint_marker(page: int, index: int, hint: _FormulaHint) -> str:
    start = ",".join(f"{value:.4f}" for value in hint.start_bbox)
    end = ",".join(f"{value:.4f}" for value in hint.end_bbox)
    return (
        f"[[paper-copilot-formula:hint id=page-{page:04d}-hint-{index:04d} "
        f"page={page} start_bbox={start} end_bbox={end} "
        f"line_count={hint.line_count} advisory=true]]"
    )


def _page_formula_hints(
    pdf_path: Path,
    page_number: int,
) -> tuple[_FormulaHint, ...]:
    document = pymupdf.open(pdf_path)
    try:
        if page_number > document.page_count:
            return ()
        page = document.load_page(page_number - 1)
        page_rect = page.rect
        if page_rect.width <= 0.0 or page_rect.height <= 0.0:
            return ()
        raw = page.get_text("rawdict")
        runs: list[
            list[tuple[list[tuple[str, pymupdf.Rect]], pymupdf.Rect]]
        ] = []
        current_run: list[
            tuple[list[tuple[str, pymupdf.Rect]], pymupdf.Rect]
        ] = []
        for block in raw.get("blocks", []):
            if not isinstance(block, dict):
                continue
            for line in block.get("lines", []):
                characters: list[tuple[str, pymupdf.Rect]] = []
                if isinstance(line, dict):
                    for span in line.get("spans", []):
                        if not isinstance(span, dict):
                            continue
                        for character in span.get("chars", []):
                            if not isinstance(character, dict):
                                continue
                            value = character.get("c")
                            bbox = character.get("bbox")
                            if (
                                isinstance(value, str)
                                and value
                                and _valid_character_bbox(bbox)
                            ):
                                characters.append((value, pymupdf.Rect(bbox)))
                line_text = "".join(value for value, _bbox in characters)
                line_bbox = _union_character_boxes(characters)
                garbled = [
                    item
                    for item in characters
                    if any(
                        _is_extraction_garble_character(char)
                        for char in item[0]
                    )
                ]
                if garbled and not _line_has_prose(line_text) and line_bbox is not None:
                    if current_run and not _visual_lines_are_consecutive(
                        current_run[-1][1],
                        line_bbox,
                    ):
                        runs.append(current_run)
                        current_run = []
                    current_run.append((garbled, line_bbox))
                    continue
                if current_run:
                    runs.append(current_run)
                    current_run = []
        if current_run:
            runs.append(current_run)
        return tuple(
            _FormulaHint(
                start_bbox=_normalize_pdf_rect(run[0][0][0][1], page_rect),
                end_bbox=_normalize_pdf_rect(run[-1][0][-1][1], page_rect),
                line_count=len(run),
            )
            for run in runs
        )
    finally:
        document.close()


def _valid_character_bbox(value: object) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 4
        and all(isinstance(item, (int, float)) for item in value)
        and float(value[2]) > float(value[0])
        and float(value[3]) > float(value[1])
    )


def _union_character_boxes(
    characters: list[tuple[str, pymupdf.Rect]],
) -> pymupdf.Rect | None:
    if not characters:
        return None
    bbox = pymupdf.Rect(characters[0][1])
    for _text, character_bbox in characters[1:]:
        bbox |= character_bbox
    return bbox


def _visual_lines_are_consecutive(
    previous: pymupdf.Rect,
    current: pymupdf.Rect,
) -> bool:
    if current.y0 < previous.y0:
        return False
    vertical_gap = max(0.0, current.y0 - previous.y1)
    max_gap = 1.75 * max(previous.height, current.height)
    horizontal_overlap = min(previous.x1, current.x1) - max(
        previous.x0,
        current.x0,
    )
    return vertical_gap <= max_gap and horizontal_overlap >= -2.0


def _normalize_pdf_rect(
    rect: pymupdf.Rect,
    page_rect: pymupdf.Rect,
) -> tuple[float, float, float, float]:
    def clamp(value: float) -> float:
        return max(0.0, min(1.0, round(value, 4)))

    return (
        clamp((rect.x0 - page_rect.x0) / page_rect.width),
        clamp((rect.y0 - page_rect.y0) / page_rect.height),
        clamp((rect.x1 - page_rect.x0) / page_rect.width),
        clamp((rect.y1 - page_rect.y0) / page_rect.height),
    )


def _line_has_prose(text: str) -> bool:
    return any("\u3400" <= character <= "\u9fff" for character in text) or bool(
        _ENGLISH_PROSE_WORD_PATTERN.search(text)
    )


def _resolve_formula_target(
    page_text: str,
    *,
    page: int,
    repair_span_id: str | None,
    replacement_text: str | None,
) -> tuple[Literal["repair_span", "replacement_text"], str, int, int]:
    if (repair_span_id is None) == (replacement_text is None):
        raise PdfCacheError(
            "formula target requires exactly one of repair_span_id or replacement_text"
        )
    if repair_span_id is not None:
        if re.fullmatch(r"page-[0-9]{4}-repair-[0-9]{4}", repair_span_id) is None:
            raise PdfCacheError("repair_span_id has an invalid format")
        start = _REPAIR_START_TEMPLATE.format(
            repair_span_id=repair_span_id,
            page=page,
        )
        end = _REPAIR_END_TEMPLATE.format(repair_span_id=repair_span_id)
        pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
        matches = list(pattern.finditer(page_text))
        if len(matches) != 1:
            raise PdfCacheError(
                f"formula repair span is unavailable on page {page}: {repair_span_id}"
            )
        match = matches[0]
        return "repair_span", match.group(0), match.start(), match.end()
    assert replacement_text is not None
    if not replacement_text.strip():
        raise PdfCacheError("replacement_text must not be empty")
    if "[[" in replacement_text or "\f" in replacement_text:
        raise PdfCacheError("replacement_text must not contain cache markers")
    if page_text.count(replacement_text) != 1:
        raise PdfCacheError(
            "replacement_text must match exactly one whole formula on the cached page"
        )
    start = page_text.index(replacement_text)
    return (
        "replacement_text",
        replacement_text,
        start,
        start + len(replacement_text),
    )


def _contains_extraction_garble(text: str) -> bool:
    return any(_is_extraction_garble_character(character) for character in text)


def _is_extraction_garble_character(character: str) -> bool:
    # Three damage signatures seen from incomplete ToUnicode mappings: FFFD,
    # private-use-area codes, and C0 control codes (math glyphs mapped to raw
    # glyph indices, for example U+000F). Legitimate layout whitespace
    # (tab/newline/CR) is not damage.
    if character == "\ufffd" or "\ue000" <= character <= "\uf8ff":
        return True
    return (
        "\x00" <= character <= "\x1f"
        and character not in "\t\n\r"
    ) or character == "\x7f"


def _visualize_control_characters(text: str) -> str:
    # Characters str.splitlines() treats as line breaks must survive the
    # substitution, otherwise raw-text and rendered-text line counts diverge.
    line_break_like = "\t\n\r\x0b\x0c\x1c\x1d\x1e"

    def visualize(character: str) -> str:
        if character in line_break_like:
            return character
        code = ord(character)
        if code <= 0x1F:
            return chr(0x2400 + code)
        if code == 0x7F:
            return "\u2421"
        return character

    return "".join(visualize(character) for character in text)


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
