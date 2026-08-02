from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx


def _content_shape(value: object) -> object:
    if isinstance(value, str):
        return {"type": "string", "length": len(value)}
    if isinstance(value, list):
        return [_content_shape(item) for item in value]
    if isinstance(value, dict):
        shaped: dict[str, object] = {}
        for key, item in value.items():
            if key in {"text", "content", "input_text", "output_text"}:
                shaped[key] = _content_shape(item)
            elif key in {"role", "type", "name", "call_id", "id", "status"}:
                shaped[key] = item
        return shaped
    return {"type": type(value).__name__}


def _request_summary(payload: dict[str, Any]) -> dict[str, object]:
    tools: list[dict[str, object]] = []
    for tool in payload.get("tools", []):
        if not isinstance(tool, dict):
            tools.append({"type": type(tool).__name__})
            continue
        tools.append(
            {
                key: tool[key]
                for key in ("type", "name", "description", "parameters", "strict")
                if key in tool
            }
        )
    return {
        "model": payload.get("model"),
        "stream": payload.get("stream"),
        "tool_choice": payload.get("tool_choice", "<omitted>"),
        "parallel_tool_calls": payload.get("parallel_tool_calls", "<omitted>"),
        "tools": tools,
        "input_shape": _content_shape(payload.get("input")),
        "instructions_length": len(payload.get("instructions", "")),
    }


def _event_summary(event_name: str | None, data: str) -> dict[str, object]:
    summary: dict[str, object] = {
        "event": event_name or "<data-only>",
        "data_length": len(data),
    }
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return summary
    if isinstance(payload, dict):
        summary["payload_type"] = payload.get("type")
        item = payload.get("item")
        if isinstance(item, dict):
            summary["item"] = {
                key: item[key]
                for key in ("type", "name", "call_id", "id", "status")
                if key in item
            }
        response = payload.get("response")
        if isinstance(response, dict):
            output = response.get("output")
            if isinstance(output, list):
                summary["output"] = [
                    {
                        key: item[key]
                        for key in ("type", "name", "call_id", "id", "status")
                        if key in item
                    }
                    for item in output
                    if isinstance(item, dict)
                ]
    return summary


class TraceProxyHandler(BaseHTTPRequestHandler):
    server: "TraceProxyServer"

    def do_POST(self) -> None:
        content_length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(content_length)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self.send_error(400, "request body must be JSON")
            return
        if not isinstance(payload, dict):
            self.send_error(400, "request body must be a JSON object")
            return
        self.server.append_trace({"kind": "request", **_request_summary(payload)})

        if self.server.offline:
            response_body = b'{"error":{"message":"offline request capture"}}'
            self.send_response(400)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)
            return

        headers = {
            "authorization": self.headers.get("authorization", ""),
            "content-type": "application/json",
            "accept": self.headers.get("accept", "text/event-stream"),
        }
        upstream_url = f"{self.server.upstream_base}{self.path}"
        with httpx.Client(timeout=120.0) as client:
            with client.stream("POST", upstream_url, content=body, headers=headers) as response:
                self.send_response(response.status_code)
                content_type = response.headers.get("content-type", "application/octet-stream")
                self.send_header("content-type", content_type)
                self.end_headers()

                event_name: str | None = None
                data_lines: list[str] = []
                for line in response.iter_lines():
                    encoded = f"{line}\n".encode()
                    self.wfile.write(encoded)
                    self.wfile.flush()
                    if line.startswith("event:"):
                        event_name = line.removeprefix("event:").strip()
                    elif line.startswith("data:"):
                        data_lines.append(line.removeprefix("data:").strip())
                    elif line == "" and data_lines:
                        self.server.append_trace(
                            {
                                "kind": "sse",
                                **_event_summary(event_name, "\n".join(data_lines)),
                            }
                        )
                        event_name = None
                        data_lines.clear()

    def log_message(self, format: str, *args: object) -> None:
        return


class TraceProxyServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        trace_path: Path,
        *,
        offline: bool,
    ) -> None:
        super().__init__(address, TraceProxyHandler)
        self.trace_path = trace_path
        self.upstream_base = "https://api.deepseek.com"
        self.offline = offline

    def append_trace(self, entry: dict[str, object]) -> None:
        with self.trace_path.open("a", encoding="utf-8") as trace_file:
            trace_file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    args.trace.parent.mkdir(parents=True, exist_ok=True)
    server = TraceProxyServer(
        ("127.0.0.1", args.port),
        args.trace,
        offline=args.offline,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
