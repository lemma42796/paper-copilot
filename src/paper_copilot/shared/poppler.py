from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from paper_copilot.shared.errors import PdfCacheError
from paper_copilot.shared.pdf_font_repair import (
    PDF_CONTROL_MARKER,
    repair_pdf_font_unicode_maps,
)

__all__ = [
    "PopplerExtraction",
    "PopplerIdentity",
    "PopplerTextExtractor",
    "find_poppler_executable",
]

_DEFAULT_TIMEOUT_SECONDS = 120.0
_EXTRACTION_MODE = "layout"
_EXTRACTION_PARAMETERS = {
    "encoding": "UTF-8",
    "eol": "unix",
    "page_breaks": "form_feed",
    # Drives the garbled-slot bbox marker format; bumping it retires caches
    # built before C0 control characters became garble signals rendered as
    # visible control pictures (silent math-glyph loss now opens slots).
    "slot_bbox_source": "pdftotext-bbox-v5",
    # Repair only deterministic embedded-font Unicode maps in a temporary PDF
    # copy before Poppler sees it. This changes cache content and therefore the
    # extractor fingerprint, without changing the public cache schema.
    "font_unicode_repair": "embedded-cmap-math-symbol-readerex-v2",
}
_MAX_BBOX_OUTPUT_BYTES = 64 * 1024 * 1024


def find_poppler_executable(name: str) -> Path | None:
    if name not in {"pdfinfo", "pdftotext", "pdftoppm"}:
        return None
    discovered = shutil.which(name)
    bundled_candidate = Path(sys.executable).resolve().parent / "bin" / name
    candidates = (
        Path(discovered) if discovered is not None else None,
        bundled_candidate,
        Path("/opt/homebrew/bin") / name,
        Path("/usr/local/bin") / name,
    )
    for candidate in candidates:
        if (
            candidate is not None
            and candidate.is_file()
            and os.access(candidate, os.X_OK)
        ):
            return candidate.resolve()
    return None


@dataclass(frozen=True, slots=True)
class PopplerIdentity:
    name: str
    version: str
    fingerprint: str
    mode: str
    parameters: dict[str, str]


@dataclass(frozen=True, slots=True)
class PopplerExtraction:
    page_count: int
    identity: PopplerIdentity


class PopplerTextExtractor:
    def __init__(
        self,
        *,
        pdfinfo_path: Path | None = None,
        pdftotext_path: Path | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._pdfinfo_path = pdfinfo_path
        self._pdftotext_path = pdftotext_path
        self._timeout_seconds = timeout_seconds
        self._identity: PopplerIdentity | None = None
        self._identity_lock = asyncio.Lock()

    async def identity(self) -> PopplerIdentity:
        if self._identity is not None:
            return self._identity
        async with self._identity_lock:
            if self._identity is not None:
                return self._identity
            pdfinfo_path = self._resolve_executable(self._pdfinfo_path, "pdfinfo")
            pdftotext_path = self._resolve_executable(self._pdftotext_path, "pdftotext")
            pdfinfo_version = await self._read_version(pdfinfo_path)
            pdftotext_version = await self._read_version(pdftotext_path)
            if pdfinfo_version != pdftotext_version:
                raise PdfCacheError(
                    "pdfinfo and pdftotext versions do not match: "
                    f"{pdfinfo_version!r} != {pdftotext_version!r}"
                )
            fingerprint_payload = {
                "name": "poppler",
                "version": pdftotext_version,
                "mode": _EXTRACTION_MODE,
                "parameters": _EXTRACTION_PARAMETERS,
            }
            canonical = json.dumps(
                fingerprint_payload,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            self._identity = PopplerIdentity(
                name="poppler",
                version=pdftotext_version,
                fingerprint=hashlib.sha256(canonical).hexdigest(),
                mode=_EXTRACTION_MODE,
                parameters=dict(_EXTRACTION_PARAMETERS),
            )
            return self._identity

    async def extract(self, pdf_path: Path, output_path: Path) -> PopplerExtraction:
        identity = await self.identity()
        pdfinfo_path = self._resolve_executable(self._pdfinfo_path, "pdfinfo")
        pdftotext_path = self._resolve_executable(self._pdftotext_path, "pdftotext")
        page_count = await self._page_count(pdfinfo_path, pdf_path)
        repaired_pdf_path = output_path.with_name(
            f".{output_path.name}.unicode-repaired.pdf"
        )
        try:
            repair = await asyncio.to_thread(
                repair_pdf_font_unicode_maps,
                pdf_path,
                repaired_pdf_path,
            )
            extraction_pdf_path = repaired_pdf_path if repair.modified else pdf_path
            await self._run(
                pdftotext_path,
                "-layout",
                "-enc",
                _EXTRACTION_PARAMETERS["encoding"],
                "-eol",
                _EXTRACTION_PARAMETERS["eol"],
                str(extraction_pdf_path),
                str(output_path),
            )
            if repair.removed_control_mapping_count > 0:
                await asyncio.to_thread(_strip_pdf_control_markers, output_path)
        finally:
            with suppress(FileNotFoundError):
                repaired_pdf_path.unlink()
        if not output_path.is_file():
            raise PdfCacheError("pdftotext completed without producing its output artifact")
        return PopplerExtraction(page_count=page_count, identity=identity)

    async def page_word_boxes(self, pdf_path: Path, page: int) -> str:
        """Return raw `pdftotext -bbox` XHTML for one page.

        The bbox pass shares the layout pass's text engine, so garbled glyphs
        surface with the same code points plus per-word coordinates.
        """
        if page < 1:
            raise PdfCacheError("page must be at least 1")
        pdftotext_path = self._resolve_executable(self._pdftotext_path, "pdftotext")
        stdout, _stderr = await self._run(
            pdftotext_path,
            "-bbox",
            "-enc",
            _EXTRACTION_PARAMETERS["encoding"],
            "-f",
            str(page),
            "-l",
            str(page),
            str(pdf_path),
            "-",
        )
        if len(stdout) > _MAX_BBOX_OUTPUT_BYTES:
            raise PdfCacheError("pdftotext -bbox output exceeded the size limit")
        return stdout

    @staticmethod
    def _resolve_executable(configured_path: Path | None, name: str) -> Path:
        if configured_path is not None:
            candidate = configured_path.expanduser().resolve()
            if candidate.is_file():
                return candidate
            raise PdfCacheError(f"configured {name} executable does not exist")
        if name not in {"pdfinfo", "pdftotext"}:
            raise PdfCacheError(f"unsupported Poppler executable: {name}")
        discovered = find_poppler_executable(name)
        if discovered is None:
            raise PdfCacheError(f"{name} is not available to the runtime")
        return discovered

    async def _read_version(self, executable: Path) -> str:
        _stdout, stderr = await self._run(executable, "-v")
        first_line = stderr.splitlines()[0].strip() if stderr else ""
        marker = " version "
        if marker not in first_line:
            raise PdfCacheError(f"could not parse {executable.name} version")
        version = first_line.rsplit(marker, maxsplit=1)[1].strip()
        if not version:
            raise PdfCacheError(f"could not parse {executable.name} version")
        return version

    async def _page_count(self, executable: Path, pdf_path: Path) -> int:
        stdout, _stderr = await self._run(executable, str(pdf_path))
        for line in stdout.splitlines():
            field, separator, raw_value = line.partition(":")
            if separator and field.strip() == "Pages":
                try:
                    page_count = int(raw_value.strip())
                except ValueError as error:
                    raise PdfCacheError("pdfinfo returned an invalid page count") from error
                if page_count < 1:
                    raise PdfCacheError("pdfinfo returned a non-positive page count")
                return page_count
        raise PdfCacheError("pdfinfo output did not contain a page count")

    async def _run(self, executable: Path, *arguments: str) -> tuple[str, str]:
        try:
            process = await asyncio.create_subprocess_exec(
                str(executable),
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            raise PdfCacheError(f"could not start {executable.name}") from error
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise PdfCacheError(
                f"{executable.name} exceeded the extraction deadline"
            ) from error
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        if process.returncode != 0:
            message = stderr.strip() or stdout.strip() or "no diagnostic output"
            raise PdfCacheError(
                f"{executable.name} failed with exit code {process.returncode}: {message[:500]}"
            )
        return stdout, stderr


def _strip_pdf_control_markers(output_path: Path) -> None:
    marker = PDF_CONTROL_MARKER.encode("utf-8")
    output_bytes = output_path.read_bytes()
    if marker in output_bytes:
        output_path.write_bytes(output_bytes.replace(marker, b""))
