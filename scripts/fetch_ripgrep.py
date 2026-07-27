from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

DOWNLOAD_TIMEOUT_SECONDS = 60
PLATFORM = "macos-aarch64"


@dataclass(frozen=True, slots=True)
class RipgrepArtifact:
    size: int
    digest: str
    archive_member: str
    url: str


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    arguments = parser.parse_args()

    artifact = _load_artifact(arguments.manifest)
    archive_path = _cache_root() / _archive_filename(artifact.url)
    if not _archive_is_valid(archive_path, artifact):
        _download_archive(artifact.url, archive_path)
        try:
            _verify_archive(archive_path, artifact)
        except RuntimeError:
            archive_path.unlink(missing_ok=True)
            raise
    _extract_distribution_files(archive_path, artifact, arguments.destination)
    return 0


def _load_artifact(manifest_path: Path) -> RipgrepArtifact:
    manifest_text = manifest_path.read_text(encoding="utf-8")
    if manifest_text.startswith("#!"):
        manifest_text = "\n".join(manifest_text.splitlines()[1:])
    manifest: dict[str, Any] = json.loads(manifest_text)
    platform = manifest.get("platforms", {}).get(PLATFORM)
    if not isinstance(platform, dict):
        raise RuntimeError(
            f"ripgrep manifest {manifest_path} is missing platform {PLATFORM!r}"
        )
    if platform.get("hash") != "sha256":
        raise RuntimeError("ripgrep manifest hash must be sha256")
    if platform.get("format") != "tar.gz":
        raise RuntimeError("ripgrep manifest format must be tar.gz")
    providers = platform.get("providers")
    if not isinstance(providers, list) or not providers:
        raise RuntimeError("ripgrep manifest must contain a provider")
    provider = providers[0]
    if not isinstance(provider, dict) or not isinstance(provider.get("url"), str):
        raise RuntimeError("ripgrep manifest provider must contain a URL")
    return RipgrepArtifact(
        size=int(platform["size"]),
        digest=str(platform["digest"]),
        archive_member=str(platform["path"]),
        url=provider["url"],
    )


def _cache_root() -> Path:
    return Path(tempfile.gettempdir()) / "paper-copilot-package" / "macos-aarch64-rg"


def _archive_filename(url: str) -> str:
    filename = Path(urlparse(url).path).name
    if not filename:
        raise RuntimeError(f"unable to determine archive filename from {url}")
    return filename


def _archive_is_valid(
    archive_path: Path,
    artifact: RipgrepArtifact,
) -> bool:
    if not archive_path.is_file():
        return False
    try:
        _verify_archive(archive_path, artifact)
    except RuntimeError:
        archive_path.unlink(missing_ok=True)
        return False
    return True


def _verify_archive(
    archive_path: Path,
    artifact: RipgrepArtifact,
) -> None:
    actual_size = archive_path.stat().st_size
    if actual_size != artifact.size:
        raise RuntimeError(
            f"ripgrep archive {archive_path} has size {actual_size}, "
            f"expected {artifact.size}"
        )

    digest = hashlib.sha256()
    with archive_path.open("rb") as archive_file:
        for chunk in iter(lambda: archive_file.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_digest = digest.hexdigest()
    if actual_digest != artifact.digest:
        raise RuntimeError(
            f"ripgrep archive {archive_path} has sha256 {actual_digest}, "
            f"expected {artifact.digest}"
        )


def _download_archive(url: str, archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = archive_path.with_suffix(f"{archive_path.suffix}.tmp")
    temporary_path.unlink(missing_ok=True)
    try:
        with urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            with temporary_path.open("wb") as output_file:
                shutil.copyfileobj(response, output_file)
        temporary_path.replace(archive_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _extract_distribution_files(
    archive_path: Path,
    artifact: RipgrepArtifact,
    destination: Path,
) -> None:
    archive_root = Path(artifact.archive_member).parent
    members = {
        artifact.archive_member: destination / "bin" / "rg",
        str(archive_root / "COPYING"): destination / "licenses" / "ripgrep" / "COPYING",
        str(archive_root / "LICENSE-MIT"): (
            destination / "licenses" / "ripgrep" / "LICENSE-MIT"
        ),
        str(archive_root / "UNLICENSE"): (
            destination / "licenses" / "ripgrep" / "UNLICENSE"
        ),
    }
    with tarfile.open(archive_path, "r:gz") as archive:
        for member_name, output_path in members.items():
            try:
                member = archive.getmember(member_name)
            except KeyError as error:
                raise RuntimeError(
                    f"ripgrep archive {archive_path} is missing {member_name!r}"
                ) from error
            extracted = archive.extractfile(member)
            if extracted is None:
                raise RuntimeError(
                    f"ripgrep archive member {member_name!r} is not a file"
                )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.unlink(missing_ok=True)
            with extracted, output_path.open("wb") as output_file:
                shutil.copyfileobj(extracted, output_file)

    executable = destination / "bin" / "rg"
    executable.chmod(
        executable.stat().st_mode
        | stat.S_IXUSR
        | stat.S_IXGRP
        | stat.S_IXOTH
    )


if __name__ == "__main__":
    raise SystemExit(main())
