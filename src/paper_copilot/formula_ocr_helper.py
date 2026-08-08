from __future__ import annotations

import argparse
import json
import os
import selectors
import sys
from pathlib import Path
from typing import Any

_MODEL_NAME = "PP-FormulaNet_plus-M"
_SCHEMA_VERSION = 1
_DEFAULT_IDLE_TIMEOUT_SECONDS = 60.0 * 60.0
_MAX_REQUEST_BYTES = 16_000


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--image", type=Path)
    mode.add_argument("--serve", action="store_true")
    parser.add_argument(
        "--idle-timeout-seconds",
        type=_positive_float,
        default=_DEFAULT_IDLE_TIMEOUT_SECONDS,
    )
    arguments = parser.parse_args()
    if arguments.serve:
        return _serve(arguments.idle_timeout_seconds)
    assert arguments.image is not None
    image_path = arguments.image.expanduser().resolve()
    if not image_path.is_file():
        sys.stderr.write("formula image does not exist\n")
        return 2
    model_dir = _model_dir()
    if not model_dir.is_dir():
        sys.stderr.write("formula model directory is missing\n")
        return 2
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    try:
        model = _load_model(model_dir)
        latex = _recognize(image_path, model)
    except Exception as error:
        sys.stderr.write(f"formula recognition failed: {_error_chain(error)}\n")
        return 1
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "model": _MODEL_NAME,
        "latex": latex,
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    sys.stdout.flush()
    return 0


def _positive_float(raw: str) -> float:
    value = float(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("idle timeout must be positive")
    return value


def _serve(idle_timeout_seconds: float) -> int:
    model_dir = _model_dir()
    if not model_dir.is_dir():
        sys.stderr.write("formula model directory is missing\n")
        return 2
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    model: Any | None = None
    selector = selectors.DefaultSelector()
    selector.register(sys.stdin.buffer, selectors.EVENT_READ)
    try:
        while selector.select(timeout=idle_timeout_seconds):
            request_line = sys.stdin.buffer.readline(_MAX_REQUEST_BYTES + 1)
            if not request_line:
                return 0
            if len(request_line) > _MAX_REQUEST_BYTES or not request_line.endswith(b"\n"):
                _write_server_error(None, "formula OCR request is oversized")
                continue
            request_id: str | None = None
            try:
                request = json.loads(request_line)
                request_id, image_path = _parse_request(request)
                if model is None:
                    model = _load_model(model_dir)
                latex = _recognize(image_path, model)
            except Exception as error:
                _write_server_error(request_id, _error_chain(error))
                continue
            _write_payload(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "request_id": request_id,
                    "model": _MODEL_NAME,
                    "latex": latex,
                }
            )
    finally:
        selector.close()
    return 0


def _parse_request(request: Any) -> tuple[str, Path]:
    if not isinstance(request, dict) or request.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("unsupported formula OCR request schema")
    if set(request) != {"schema_version", "request_id", "image"}:
        raise ValueError("invalid formula OCR request fields")
    request_id = request.get("request_id")
    if not isinstance(request_id, str) or not request_id or len(request_id) > 64:
        raise ValueError("invalid formula OCR request id")
    image_raw = request.get("image")
    if not isinstance(image_raw, str) or not image_raw:
        raise ValueError("formula OCR request image is missing")
    image_path = Path(image_raw).expanduser().resolve()
    if not image_path.is_file():
        raise ValueError("formula image does not exist")
    return request_id, image_path


def _write_server_error(request_id: str | None, message: str) -> None:
    _write_payload(
        {
            "schema_version": _SCHEMA_VERSION,
            "request_id": request_id,
            "error": message[:500] or "formula recognition failed",
        }
    )


def _write_payload(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _model_dir() -> Path:
    configured = os.environ.get("PAPER_COPILOT_FORMULA_OCR_MODEL_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    executable = Path(sys.executable).resolve()
    return executable.parent / "models" / _MODEL_NAME


def _load_model(model_dir: Path) -> Any:
    from paddleocr import FormulaRecognition

    return FormulaRecognition(
        model_name=_MODEL_NAME,
        model_dir=str(model_dir),
        device="cpu",
    )


def _recognize(image_path: Path, model: Any) -> str:
    results: list[Any] = list(model.predict(str(image_path), batch_size=1))
    if len(results) != 1:
        raise RuntimeError("formula recognizer did not return exactly one result")
    raw = results[0].json
    latex = raw.get("res", {}).get("rec_formula")
    if not isinstance(latex, str) or not latex.strip():
        raise RuntimeError("formula recognizer returned empty LaTeX")
    return latex


def _error_chain(error: Exception) -> str:
    messages: list[str] = []
    current: BaseException | None = error
    while current is not None and len(messages) < 4:
        message = " ".join(str(current).split())[:400]
        if message and message not in messages:
            messages.append(message)
        current = current.__cause__
    return " caused by: ".join(messages) or type(error).__name__


if __name__ == "__main__":
    raise SystemExit(main())
