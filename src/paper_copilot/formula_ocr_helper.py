from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_MODEL_NAME = "PP-FormulaNet_plus-S"
_SCHEMA_VERSION = 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, required=True)
    arguments = parser.parse_args()
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
        latex = _recognize(image_path, model_dir)
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


def _model_dir() -> Path:
    configured = os.environ.get("PAPER_COPILOT_FORMULA_OCR_MODEL_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    executable = Path(sys.executable).resolve()
    return executable.parent / "models" / _MODEL_NAME


def _recognize(image_path: Path, model_dir: Path) -> str:
    from paddleocr import FormulaRecognition

    model = FormulaRecognition(
        model_name=_MODEL_NAME,
        model_dir=str(model_dir),
        device="cpu",
    )
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
