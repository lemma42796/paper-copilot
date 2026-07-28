from __future__ import annotations

import asyncio
import base64
import hashlib
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from paper_copilot.agents.loop import ToolResultImage
from paper_copilot.session.paths import compute_paper_id
from paper_copilot.shared.errors import KnowledgeError
from paper_copilot.shared.poppler import find_poppler_executable

__all__ = [
    "InspectPageInput",
    "InspectPageRegion",
    "InspectPageRun",
    "configured_input_modalities",
    "inspect_page_tool_description",
    "run_inspect_page",
]

_DEFAULT_INPUT_MODALITIES = frozenset({"text", "image"})
_RENDER_MAX_DIMENSION = 1_800
_RENDER_MAX_BYTES = 8_000_000
_INTERMEDIATE_MAX_BYTES = 16_000_000
_RENDER_TIMEOUT_SECONDS = 20.0
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_SCHEMA_VERSION = 1


class InspectPageRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x1: float = Field(ge=0.0, le=1.0)
    y1: float = Field(ge=0.0, le=1.0)
    x2: float = Field(ge=0.0, le=1.0)
    y2: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _has_positive_area(self) -> InspectPageRegion:
        if self.x2 <= self.x1:
            raise ValueError("region.x2 must be greater than region.x1")
        if self.y2 <= self.y1:
            raise ValueError("region.y2 must be greater than region.y1")
        return self


class InspectPageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str = Field(
        min_length=12,
        max_length=64,
        pattern=r"^(?:[0-9a-f]{12}|[0-9a-f]{64})$",
        description=(
            "Full PDF SHA-256 returned by paper-cache or paper_set. Legacy "
            "12-character Paper Copilot IDs remain accepted."
        ),
    )
    page: int = Field(
        ge=1,
        description="One-based PDF page number to inspect.",
    )
    region: InspectPageRegion | None = Field(
        default=None,
        description=(
            "Optional normalized page crop with x1/y1 at the top-left and x2/y2 "
            "at the bottom-right."
        ),
    )
    purpose: str = Field(
        min_length=1,
        max_length=500,
        description="Specific visual fact that needs verification on this page.",
    )


@dataclass(frozen=True, slots=True)
class InspectPageRun:
    output: dict[str, Any]
    images: tuple[ToolResultImage, ...]
    trace_attributes: dict[str, Any]


def configured_input_modalities() -> frozenset[str]:
    configured = os.environ.get("LLM_INPUT_MODALITIES")
    if configured is None:
        return _DEFAULT_INPUT_MODALITIES
    modalities = frozenset(
        value.strip().lower() for value in configured.split(",") if value.strip()
    )
    unsupported = modalities - {"text", "image", "audio"}
    if unsupported:
        raise KnowledgeError(
            "LLM_INPUT_MODALITIES contains unsupported values: "
            + ", ".join(sorted(unsupported))
        )
    if "text" not in modalities:
        raise KnowledgeError("LLM_INPUT_MODALITIES must include text")
    return modalities


def inspect_page_tool_description() -> str:
    return (
        "Visually inspect one page or normalized region of an authorized local PDF. "
        "Use this only after another tool has identified the full PDF SHA-256 "
        "(preferred) or a legacy 12-character paper_id, plus the exact PDF page. "
        "Do not truncate a SHA-256. The Runtime renders a bounded PNG with Poppler "
        "and binds it to the PDF hash, page, region, and render hash. The configured "
        "model must support image inputs. This tool does not perform OCR or "
        "whole-document ingestion."
    )


async def run_inspect_page(
    args: InspectPageInput,
    library_root: Path | None,
    *,
    input_modalities: frozenset[str] | None = None,
) -> InspectPageRun:
    modalities = (
        configured_input_modalities()
        if input_modalities is None
        else input_modalities
    )
    if "image" not in modalities:
        raise KnowledgeError(
            "inspect_page is not allowed because you do not support image inputs"
        )
    root = _resolve_library_root(library_root)
    pdf_path = await asyncio.to_thread(_resolve_paper_path, args.paper_id, root)
    pdftoppm_path = _resolve_poppler_executable("pdftoppm")
    pdfinfo_path = _resolve_poppler_executable("pdfinfo")
    page_count = await _page_count(pdfinfo_path, pdf_path)
    if args.page > page_count:
        raise KnowledgeError(
            f"page {args.page} is outside the PDF page range 1-{page_count}"
        )
    pdf_sha256 = await asyncio.to_thread(_sha256_file, pdf_path)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="paper-copilot-inspect-page-") as raw_dir:
        render_dir = Path(raw_dir)
        render_path = await _render_page(
            pdftoppm_path,
            pdf_path,
            page=args.page,
            region=args.region,
            render_dir=render_dir,
        )
        if render_path.stat().st_size > _RENDER_MAX_BYTES:
            raise KnowledgeError(
                "inspect_page render exceeded the model input byte limit "
                f"({_RENDER_MAX_BYTES} bytes)"
            )
        image_bytes = await asyncio.to_thread(render_path.read_bytes)
    current_pdf_sha256 = await asyncio.to_thread(_sha256_file, pdf_path)
    if current_pdf_sha256 != pdf_sha256:
        raise KnowledgeError("PDF changed while inspect_page was rendering it")
    width, height = _png_dimensions(image_bytes)
    render_sha256 = hashlib.sha256(image_bytes).hexdigest()
    region_payload = (
        args.region.model_dump(mode="json") if args.region is not None else None
    )
    evidence = {
        "source_kind": "pdf_page_render",
        "paper_id": args.paper_id,
        "pdf_sha256": pdf_sha256,
        "page": args.page,
        "region": region_payload,
        "artifact_hash": render_sha256,
    }
    output = {
        "status": "ok",
        "paper_id": args.paper_id,
        "page": args.page,
        "purpose": args.purpose,
        "evidence": [evidence],
        "visual": {
            "delivered_to_model": True,
            "mime_type": "image/png",
            "width": width,
            "height": height,
            "bytes": len(image_bytes),
            "render_hash": render_sha256,
        },
        "unresolved": [],
    }
    data_url = (
        "data:image/png;base64,"
        + base64.b64encode(image_bytes).decode("ascii")
    )
    return InspectPageRun(
        output=output,
        images=(ToolResultImage(data_url=data_url),),
        trace_attributes={
            "inspect_page_schema_version": _SCHEMA_VERSION,
            "paper_id": args.paper_id,
            "pdf_sha256": pdf_sha256,
            "page": args.page,
            "region": region_payload,
            "render_sha256": render_sha256,
            "render_width": width,
            "render_height": height,
            "render_bytes": len(image_bytes),
            "wall_time_seconds": round(time.monotonic() - started, 3),
        },
    )


def _resolve_library_root(library_root: Path | None) -> Path:
    if library_root is None:
        raise KnowledgeError("inspect_page requires a configured PDF library")
    root = library_root.expanduser().resolve()
    if not root.is_dir():
        raise KnowledgeError("configured PDF library is not available")
    return root


def _resolve_paper_path(paper_id: str, library_root: Path) -> Path:
    matches: list[Path] = []
    for path in sorted(library_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue
        resolved_path = path.resolve()
        try:
            resolved_path.relative_to(library_root)
        except ValueError:
            continue
        resolved_paper_id = (
            _sha256_file(resolved_path)
            if len(paper_id) == 64
            else compute_paper_id(resolved_path)
        )
        if resolved_paper_id == paper_id:
            matches.append(resolved_path)
    if not matches:
        raise KnowledgeError(f"no authorized PDF matched paper_id {paper_id}")
    if len(matches) > 1:
        raise KnowledgeError(
            f"paper_id {paper_id} matched more than one authorized PDF"
        )
    return matches[0]


def _resolve_poppler_executable(name: str) -> Path:
    if name not in {"pdfinfo", "pdftoppm"}:
        raise KnowledgeError(f"unsupported inspect_page Poppler command: {name}")
    executable = find_poppler_executable(name)
    if executable is not None:
        return executable
    raise KnowledgeError(
        f"{name} is unavailable; inspect_page requires a user-installed Poppler"
    )


async def _page_count(pdfinfo_path: Path, pdf_path: Path) -> int:
    stdout, _stderr = await _run_process(pdfinfo_path, str(pdf_path))
    for line in stdout.splitlines():
        field, separator, raw_value = line.partition(":")
        if separator and field.strip() == "Pages":
            try:
                page_count = int(raw_value.strip())
            except ValueError as error:
                raise KnowledgeError("pdfinfo returned an invalid page count") from error
            if page_count < 1:
                raise KnowledgeError("pdfinfo returned a non-positive page count")
            return page_count
    raise KnowledgeError("pdfinfo output did not contain a page count")


async def _render_page(
    pdftoppm_path: Path,
    pdf_path: Path,
    *,
    page: int,
    region: InspectPageRegion | None,
    render_dir: Path,
) -> Path:
    full_prefix = render_dir / "full"
    await _run_process(
        pdftoppm_path,
        "-f",
        str(page),
        "-l",
        str(page),
        "-singlefile",
        "-png",
        "-scale-to",
        str(_RENDER_MAX_DIMENSION),
        str(pdf_path),
        str(full_prefix),
    )
    full_path = full_prefix.with_suffix(".png")
    if not full_path.is_file():
        raise KnowledgeError("pdftoppm completed without producing a PNG")
    if region is None:
        return full_path
    if full_path.stat().st_size > _INTERMEDIATE_MAX_BYTES:
        raise KnowledgeError("pdftoppm intermediate render exceeded the byte limit")
    full_bytes = await asyncio.to_thread(full_path.read_bytes)
    width, height = _png_dimensions(full_bytes)
    x = int(region.x1 * width)
    y = int(region.y1 * height)
    crop_width = max(1, int(region.x2 * width) - x)
    crop_height = max(1, int(region.y2 * height) - y)
    crop_prefix = render_dir / "region"
    await _run_process(
        pdftoppm_path,
        "-f",
        str(page),
        "-l",
        str(page),
        "-singlefile",
        "-png",
        "-scale-to",
        str(_RENDER_MAX_DIMENSION),
        "-x",
        str(x),
        "-y",
        str(y),
        "-W",
        str(crop_width),
        "-H",
        str(crop_height),
        str(pdf_path),
        str(crop_prefix),
    )
    crop_path = crop_prefix.with_suffix(".png")
    if not crop_path.is_file():
        raise KnowledgeError("pdftoppm completed without producing a cropped PNG")
    return crop_path


async def _run_process(executable: Path, *arguments: str) -> tuple[str, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            str(executable),
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as error:
        raise KnowledgeError(f"could not start {executable.name}") from error
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(),
            timeout=_RENDER_TIMEOUT_SECONDS,
        )
    except TimeoutError as error:
        process.kill()
        await process.wait()
        raise KnowledgeError(
            f"{executable.name} exceeded the page inspection deadline"
        ) from error
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    if process.returncode != 0:
        diagnostic = stderr.strip() or stdout.strip() or "no diagnostic output"
        raise KnowledgeError(
            f"{executable.name} failed with exit code {process.returncode}: "
            f"{diagnostic[:500]}"
        )
    return stdout, stderr


def _png_dimensions(image_bytes: bytes) -> tuple[int, int]:
    if len(image_bytes) < 24 or image_bytes[:8] != _PNG_SIGNATURE:
        raise KnowledgeError("pdftoppm output is not a valid PNG")
    width = int.from_bytes(image_bytes[16:20], "big")
    height = int.from_bytes(image_bytes[20:24], "big")
    if width < 1 or height < 1:
        raise KnowledgeError("pdftoppm output has invalid dimensions")
    if width > _RENDER_MAX_DIMENSION or height > _RENDER_MAX_DIMENSION:
        raise KnowledgeError("pdftoppm output exceeded the render dimension limit")
    return width, height


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
