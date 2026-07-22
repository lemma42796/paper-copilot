from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from paper_copilot.observability.reducer import reduce_trace_bundle
from paper_copilot.observability.types import TraceManifest
from paper_copilot.shared.errors import TraceIntegrityError

PayloadPolicyClassification = Literal["local_safe_v1", "legacy_unclassified"]

_PAYLOAD_ID_RE = re.compile(r"^payload-[0-9a-f]{32}$")
_TOMBSTONE_MARKER = "payload_tombstone"


class PayloadRetentionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    bundle_relpath: str
    job_id: str
    attempt: int = Field(ge=1)
    payload_id: str
    kind: str
    payload_policy: PayloadPolicyClassification
    original_bytes: int = Field(ge=1)
    original_file_sha256: str
    original_value_sha256: str


class PayloadRetentionReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generated_at: str
    cutoff_at: str
    retention_days: int = Field(ge=1)
    bundle_count: int = Field(ge=0)
    legacy_bundle_count: int = Field(ge=0)
    active_payload_count: int = Field(ge=0)
    tombstoned_payload_count: int = Field(ge=0)
    active_payload_bytes: int = Field(ge=0)
    legacy_active_payload_count: int = Field(ge=0)
    legacy_active_payload_bytes: int = Field(ge=0)
    expired_running_payload_count: int = Field(ge=0)
    candidates: list[PayloadRetentionCandidate]


class PayloadRetentionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    applied_at: str
    rewritten_payload_count: int = Field(ge=0)
    released_bytes: int = Field(ge=0)
    tombstone_bytes: int = Field(ge=0)


def scan_payload_retention(
    root: Path,
    *,
    retention_days: int = 30,
    now: datetime | None = None,
) -> PayloadRetentionReport:
    if retention_days < 1:
        raise ValueError("retention_days must be at least 1")
    generated_at = now or datetime.now(UTC)
    if generated_at.tzinfo is None:
        raise ValueError("now must include timezone information")
    cutoff_at = generated_at - timedelta(days=retention_days)
    jobs_dir = root / "jobs"
    manifest_paths = sorted(jobs_dir.glob("*/attempts/*/manifest.json"))

    legacy_bundle_count = 0
    active_payload_count = 0
    tombstoned_payload_count = 0
    active_payload_bytes = 0
    legacy_active_payload_count = 0
    legacy_active_payload_bytes = 0
    expired_running_payload_count = 0
    candidates: list[PayloadRetentionCandidate] = []

    for manifest_path in manifest_paths:
        bundle_dir = manifest_path.parent
        raw_manifest = _read_json_object(manifest_path)
        manifest = TraceManifest.model_validate(raw_manifest)
        policy = _classify_policy(raw_manifest)
        if policy == "legacy_unclassified":
            legacy_bundle_count += 1
        state = reduce_trace_bundle(bundle_dir, write_state=False)
        expired = _parse_timestamp(manifest.started_at) <= cutoff_at
        bundle_relpath = str(bundle_dir.relative_to(jobs_dir))

        for payload_path in sorted((bundle_dir / "payloads").glob("payload-*.json")):
            raw_bytes = payload_path.read_bytes()
            payload = _validate_payload_file(payload_path, raw_bytes)
            value = payload["value"]
            if _is_tombstone(value):
                tombstoned_payload_count += 1
                continue

            payload_bytes = len(raw_bytes)
            active_payload_count += 1
            active_payload_bytes += payload_bytes
            if policy == "legacy_unclassified":
                legacy_active_payload_count += 1
                legacy_active_payload_bytes += payload_bytes
            if not expired:
                continue
            if state.status == "running":
                expired_running_payload_count += 1
                continue

            payload_id = str(payload["payload_id"])
            candidates.append(
                PayloadRetentionCandidate(
                    bundle_relpath=bundle_relpath,
                    job_id=manifest.job_id,
                    attempt=manifest.attempt,
                    payload_id=payload_id,
                    kind=str(payload["kind"]),
                    payload_policy=policy,
                    original_bytes=payload_bytes,
                    original_file_sha256=hashlib.sha256(raw_bytes).hexdigest(),
                    original_value_sha256=_value_sha256(value),
                )
            )

    return PayloadRetentionReport(
        generated_at=generated_at.isoformat(),
        cutoff_at=cutoff_at.isoformat(),
        retention_days=retention_days,
        bundle_count=len(manifest_paths),
        legacy_bundle_count=legacy_bundle_count,
        active_payload_count=active_payload_count,
        tombstoned_payload_count=tombstoned_payload_count,
        active_payload_bytes=active_payload_bytes,
        legacy_active_payload_count=legacy_active_payload_count,
        legacy_active_payload_bytes=legacy_active_payload_bytes,
        expired_running_payload_count=expired_running_payload_count,
        candidates=candidates,
    )


def apply_payload_retention(
    root: Path,
    report: PayloadRetentionReport,
    *,
    now: datetime | None = None,
) -> PayloadRetentionResult:
    applied_at = now or datetime.now(UTC)
    if applied_at.tzinfo is None:
        raise ValueError("now must include timezone information")
    jobs_dir = (root / "jobs").resolve()
    released_bytes = 0
    tombstone_bytes = 0

    for candidate in report.candidates:
        bundle_dir = _resolve_bundle_dir(jobs_dir, candidate.bundle_relpath)
        manifest = TraceManifest.model_validate(
            _read_json_object(bundle_dir / "manifest.json")
        )
        if manifest.job_id != candidate.job_id or manifest.attempt != candidate.attempt:
            raise TraceIntegrityError(
                f"retention candidate identity does not match {candidate.bundle_relpath}"
            )
        payload_path = bundle_dir / "payloads" / f"{candidate.payload_id}.json"
        raw_bytes = payload_path.read_bytes()
        if hashlib.sha256(raw_bytes).hexdigest() != candidate.original_file_sha256:
            raise TraceIntegrityError(
                f"payload changed after retention scan: {candidate.payload_id}"
            )
        payload = _validate_payload_file(payload_path, raw_bytes)
        if payload["payload_id"] != candidate.payload_id or payload["kind"] != candidate.kind:
            raise TraceIntegrityError(
                f"payload identity changed after retention scan: {candidate.payload_id}"
            )
        if _value_sha256(payload["value"]) != candidate.original_value_sha256:
            raise TraceIntegrityError(
                f"payload value changed after retention scan: {candidate.payload_id}"
            )

        tombstone = {
            "payload_id": candidate.payload_id,
            "kind": candidate.kind,
            "value": {
                "_trace_value": _TOMBSTONE_MARKER,
                "reason": "retention",
                "removed_at": applied_at.isoformat(),
                "payload_policy": candidate.payload_policy,
                "original_bytes": candidate.original_bytes,
                "original_file_sha256": candidate.original_file_sha256,
                "original_value_sha256": candidate.original_value_sha256,
            },
        }
        rewritten_bytes = _replace_json_file(payload_path, tombstone)
        released_bytes += max(candidate.original_bytes - rewritten_bytes, 0)
        tombstone_bytes += rewritten_bytes

    return PayloadRetentionResult(
        applied_at=applied_at.isoformat(),
        rewritten_payload_count=len(report.candidates),
        released_bytes=released_bytes,
        tombstone_bytes=tombstone_bytes,
    )


def tombstone_value_sha256(value: object) -> str | None:
    if not isinstance(value, dict) or value.get("_trace_value") != _TOMBSTONE_MARKER:
        return None
    sha256 = value.get("original_value_sha256")
    return sha256 if isinstance(sha256, str) else None


def _read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TraceIntegrityError(f"expected JSON object in {path}")
    return value


def _validate_payload_file(path: Path, raw_bytes: bytes) -> dict[str, Any]:
    value = json.loads(raw_bytes)
    if not isinstance(value, dict):
        raise TraceIntegrityError(f"expected payload object in {path}")
    payload_id = value.get("payload_id")
    if not isinstance(payload_id, str) or _PAYLOAD_ID_RE.fullmatch(payload_id) is None:
        raise TraceIntegrityError(f"invalid payload id in {path}")
    if path.stem != payload_id:
        raise TraceIntegrityError(f"payload filename does not match id in {path}")
    if not isinstance(value.get("kind"), str) or "value" not in value:
        raise TraceIntegrityError(f"invalid payload envelope in {path}")
    return value


def _classify_policy(raw_manifest: dict[str, Any]) -> PayloadPolicyClassification:
    return (
        "local_safe_v1"
        if raw_manifest.get("payload_policy") == "local_safe_v1"
        else "legacy_unclassified"
    )


def _parse_timestamp(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        raise TraceIntegrityError(f"trace timestamp lacks timezone: {value}")
    return timestamp


def _value_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _is_tombstone(value: object) -> bool:
    return tombstone_value_sha256(value) is not None


def _resolve_bundle_dir(jobs_dir: Path, bundle_relpath: str) -> Path:
    relative = Path(bundle_relpath)
    if relative.is_absolute() or len(relative.parts) != 3 or relative.parts[1] != "attempts":
        raise TraceIntegrityError(f"invalid retention bundle path: {bundle_relpath}")
    resolved = (jobs_dir / relative).resolve()
    if not resolved.is_relative_to(jobs_dir):
        raise TraceIntegrityError(f"retention bundle escapes jobs directory: {bundle_relpath}")
    return resolved


def _replace_json_file(path: Path, value: dict[str, Any]) -> int:
    encoded = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    with temp_path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp_path, path)
    return len(encoded)
