"""Real, harmless MCP 2 server. Stdout is protocol-only in stdio mode."""

import argparse
from datetime import UTC, datetime

from mcp.server import MCPServer
from pydantic import BaseModel

server = MCPServer("voice-starter-clock")


class CurrentTime(BaseModel):
    iso_time: str


@server.tool()
def get_current_time() -> CurrentTime:
    """Get the current UTC time."""
    return CurrentTime(iso_time=datetime.now(UTC).isoformat())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--transport", choices=["stdio", "streamable-http"], default="stdio"
    )
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport="streamable-http", host="127.0.0.1", port=args.port)
