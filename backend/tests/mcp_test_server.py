"""Real MCP transport test fixture; never registered in the application demo."""

import asyncio
import os

from mcp.server import MCPServer

server = MCPServer("test-fixture")


@server.tool()
def broken() -> dict:
    return {"private": "not-in-the-reviewed-output-contract"}


@server.tool()
def leak() -> dict:
    return {"safe": os.environ.get("TEST_ONLY_TOKEN", "not-configured")}


@server.tool()
def hidden() -> dict:
    return {"hidden": True}


@server.tool()
async def slow() -> dict:
    await asyncio.sleep(30)
    return {"done": True}


if __name__ == "__main__":
    server.run(transport="stdio")
