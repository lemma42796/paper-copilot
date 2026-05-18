from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console

from paper_copilot.api.http import serve_http_api


def serve(
    host: Annotated[
        str,
        typer.Option("--host", help="HTTP bind host."),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", help="HTTP bind port."),
    ] = 8765,
) -> None:
    """Serve the chat-first HTTP API."""
    if port <= 0 or port > 65535:
        raise typer.BadParameter("--port must be between 1 and 65535")

    Console().print(f"[green]serving[/green] http://{host}:{port}")
    serve_http_api(host=host, port=port)
