from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from paper_copilot.observability.retention import (
    apply_payload_retention,
    scan_payload_retention,
)
from paper_copilot.session.paths import default_root


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan trace payload risk and optionally apply retention tombstones."
    )
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--retention-days", type=_positive_int, default=30)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Atomically replace eligible payload values with tombstones.",
    )
    args = parser.parse_args()
    root = args.root.expanduser() if args.root is not None else default_root()
    report = scan_payload_retention(root, retention_days=args.retention_days)
    output: dict[str, object] = {"scan": report.model_dump(mode="json")}
    if args.apply:
        output["apply"] = apply_payload_retention(root, report).model_dump(mode="json")
    sys.stdout.write(json.dumps(output, ensure_ascii=False, indent=2) + "\n")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


if __name__ == "__main__":
    main()
