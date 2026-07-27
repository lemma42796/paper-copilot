from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from paper_copilot.shared.errors import PdfCacheError

__all__ = [
    "PopplerExtraction",
    "PopplerIdentity",
    "PopplerTextExtractor",
]

_DEFAULT_TIMEOUT_SECONDS = 120.0
_EXTRACTION_MODE = "layout"
_EXTRACTION_PARAMETERS = {
    "encoding": "UTF-8",
    "eol": "unix",
    "page_breaks": "form_feed",
}


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
        await self._run(
            pdftotext_path,
            "-layout",
            "-enc",
            _EXTRACTION_PARAMETERS["encoding"],
            "-eol",
            _EXTRACTION_PARAMETERS["eol"],
            str(pdf_path),
            str(output_path),
        )
        if not output_path.is_file():
            raise PdfCacheError("pdftotext completed without producing its output artifact")
        return PopplerExtraction(page_count=page_count, identity=identity)

    @staticmethod
    def _resolve_executable(configured_path: Path | None, name: str) -> Path:
        if configured_path is not None:
            candidate = configured_path.expanduser().resolve()
            if candidate.is_file():
                return candidate
            raise PdfCacheError(f"configured {name} executable does not exist")
        discovered = shutil.which(name)
        if discovered is None:
            raise PdfCacheError(f"{name} is not available on the runtime PATH")
        return Path(discovered).resolve()

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
