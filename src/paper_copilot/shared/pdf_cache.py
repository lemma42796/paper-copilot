from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from paper_copilot.shared.errors import PdfCacheError
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

_SCHEMA_VERSION = 1
_LAYOUT_FILENAME = "layout.txt"
_MANIFEST_FILENAME = "manifest.json"
_CURRENT_FILENAME = "current.json"
_READ_CHUNK_BYTES = 1024 * 1024


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


class PdfCacheManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = _SCHEMA_VERSION
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
        revision_dir = self._revision_dir(cache_ref)
        manifest = await asyncio.to_thread(_read_manifest, revision_dir)
        if _cache_ref(manifest) != cache_ref:
            raise PdfCacheError("cache reference does not match the stored manifest")
        if page > manifest.page_count:
            raise PdfCacheError(
                f"page {page} exceeds cached page count {manifest.page_count}"
            )
        if not await asyncio.to_thread(_artifact_is_valid, revision_dir, manifest):
            raise PdfCacheError("cached text artifact failed its integrity check")
        boundary = manifest.page_boundaries[page - 1]
        text = await asyncio.to_thread(
            _read_text_range,
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
            layout_path = staging_path / _LAYOUT_FILENAME
            extraction = await self._extractor.extract(pdf_path, layout_path)
            if extraction.identity != identity:
                raise PdfCacheError("extractor identity changed during cache generation")
            current_pdf_sha256 = await asyncio.to_thread(_sha256_file, pdf_path)
            if current_pdf_sha256 != pdf_sha256:
                raise PdfCacheError("PDF content changed during cache generation")
            layout_bytes = await asyncio.to_thread(layout_path.read_bytes)
            page_boundaries = _page_boundaries(layout_bytes, extraction.page_count)
            artifact = TextArtifact(
                sha256=hashlib.sha256(layout_bytes).hexdigest(),
                byte_count=len(layout_bytes),
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
            )
            await asyncio.to_thread(
                _write_json,
                staging_path / _MANIFEST_FILENAME,
                manifest.model_dump(mode="json"),
            )
            revision_dir = revisions_dir / revision_id
            await asyncio.to_thread(os.replace, staging_path, revision_dir)
            await asyncio.to_thread(_publish_current, key_dir, revision_id)
            return PdfCacheLookup(
                status="hit",
                cache_ref=_cache_ref(manifest),
                manifest=manifest,
                reason="generated",
            )
        finally:
            if staging_path.exists():
                await asyncio.to_thread(shutil.rmtree, staging_path)

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


def _page_boundaries(layout_bytes: bytes, page_count: int) -> list[PageBoundary]:
    separator = b"\f"
    raw_pages = layout_bytes.split(separator)
    if raw_pages and raw_pages[-1] == b"":
        raw_pages.pop()
    if len(raw_pages) != page_count:
        raise PdfCacheError(
            "pdftotext page separators do not match pdfinfo page count: "
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
