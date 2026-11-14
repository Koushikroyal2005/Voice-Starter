"""Per-server serialized sessions, bounded requests and background reconnects."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.mcp.client import LiveKitMCPClient
from app.mcp.config import ServerConfig
from app.tools.base import ToolFailure

logger = logging.getLogger("voice-starter.mcp")


class ConnectionManager:
    def __init__(self, configs: list[ServerConfig]):
        self.configs = {config.id: config for config in configs}
        self.clients = {config.id: LiveKitMCPClient(config) for config in configs}
        self.locks = {config.id: asyncio.Lock() for config in configs}
        self.wake = {config.id: asyncio.Event() for config in configs}
        self.tasks: list[asyncio.Task] = []
        self.closed = False
        self.on_available: Callable[[str, set[str]], Awaitable[None]] | None = None

    def start(self, callback: Callable[[str, set[str]], Awaitable[None]]):
        if self.tasks:
            return
        self.on_available = callback
        self.tasks = [
            asyncio.create_task(self.monitor(server_id)) for server_id in self.clients
        ]

    async def close_client(self, server_id: str):
        try:
            async with asyncio.timeout(5):
                await self.clients[server_id].aclose()
        except Exception:
            logger.warning("MCP cleanup failed", extra={"server_id": server_id})

    async def discover(self, server_id: str) -> set[str]:
        config = self.configs[server_id]
        async with self.locks[server_id]:
            try:
                async with asyncio.timeout(config.connect_timeout_seconds):
                    return await self.clients[server_id].discover()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                await self.close_client(server_id)
                logger.warning(
                    "MCP unavailable (%s); approved tools remain disabled",
                    type(error).__name__,
                    extra={"server_id": server_id},
                )
                return set()

    async def monitor(self, server_id: str):
        config = self.configs[server_id]
        while not self.closed:
            self.wake[server_id].clear()
            available = await self.discover(server_id)
            try:
                await self.on_available(server_id, available)
            except Exception:
                logger.warning(
                    "MCP tool availability update failed",
                    extra={"server_id": server_id},
                )
            interval = (
                config.health_interval_seconds
                if available
                else config.reconnect_interval_seconds
            )
            try:
                await asyncio.wait_for(self.wake[server_id].wait(), interval)
            except TimeoutError:
                pass

    async def call(self, server_id: str, alias: str, arguments: dict):
        if self.closed or server_id not in self.clients:
            raise ToolFailure("mcp_unavailable", "External tool server is unavailable.")
        config = self.configs[server_id]
        invoked = False
        async with self.locks[server_id]:
            try:
                async with asyncio.timeout(config.request_timeout_seconds):
                    # Re-discover before invocation; schemas must still match.
                    available = await self.clients[server_id].discover()
                    if alias not in available:
                        raise ToolFailure(
                            "mcp_not_approved",
                            "External action is unavailable or its schema changed.",
                        )
                    invoked = True
                    return await self.clients[server_id].call(alias, arguments)
            except asyncio.CancelledError:
                # SDK 2 sends cancellation; side effects may not roll back.
                self.wake[server_id].set()
                raise
            except Exception:
                await self.close_client(server_id)
                self.wake[server_id].set()
                raise ToolFailure(
                    "mcp_operation_failed",
                    "External tool failed or returned unapproved data. "
                    "No action was replayed.",
                    outcome_unknown=invoked,
                ) from None

    async def aclose(self):
        self.closed = True
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        for server_id in self.clients:
            async with self.locks[server_id]:
                await self.close_client(server_id)
        self.tasks.clear()
