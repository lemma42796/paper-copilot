from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from types import FrameType

from paper_copilot.api.http import serve_http_api
from paper_copilot.shared.logging import configure_logging

_HOST = "127.0.0.1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exit-on-stdin-eof", action="store_true")
    arguments = parser.parse_args()

    configure_logging()
    shutdown_event = threading.Event()

    def request_shutdown(_signum: int, _frame: FrameType | None) -> None:
        shutdown_event.set()

    def announce_ready(host: str, port: int) -> None:
        payload = {
            "status": "ready",
            "http_url": f"http://{host}:{port}",
        }
        sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
        sys.stdout.flush()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    if arguments.exit_on_stdin_eof:
        stdin_watcher = threading.Thread(
            target=_shutdown_on_stdin_eof,
            args=(shutdown_event,),
            name="paper-copilot-parent-watch",
            daemon=True,
        )
        stdin_watcher.start()
    serve_http_api(
        host=_HOST,
        port=0,
        websocket_port=0,
        shutdown_event=shutdown_event,
        ready_callback=announce_ready,
    )
    return 0


def _shutdown_on_stdin_eof(shutdown_event: threading.Event) -> None:
    while sys.stdin.buffer.read(1):
        pass
    shutdown_event.set()


if __name__ == "__main__":
    raise SystemExit(main())
