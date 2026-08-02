from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def prepare_catalog(source: Path, destination: Path) -> None:
    payload: dict[str, Any] = json.loads(source.read_text(encoding="utf-8"))
    models = payload.get("models")
    if not isinstance(models, list):
        raise RuntimeError("model catalog must contain a models list")

    matched = 0
    for model in models:
        if isinstance(model, dict) and model.get("slug") == "deepseek-v4-flash":
            model["supports_search_tool"] = False
            matched += 1
    if matched != 1:
        raise RuntimeError(
            "model catalog must contain exactly one deepseek-v4-flash entry"
        )

    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    prepare_catalog(args.source, args.destination)


if __name__ == "__main__":
    main()
