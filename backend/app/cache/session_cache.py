"""Owner-scoped ephemeral status only: no transcript, secrets or tool arguments."""

import json

from redis.exceptions import RedisError


class SessionCache:
    def __init__(self, client=None, ttl=300):
        if ttl <= 0:
            raise ValueError("Cache TTL must be positive")
        self.client, self.ttl = client, ttl

    def key(self, owner, conversation):
        if len(owner) != 64 or not conversation:
            raise PermissionError("Owner and conversation are required")
        return f"voice:session:{owner}:{conversation}"

    async def put(self, owner, conversation, status):
        if status not in {"active", "closed"}:
            raise ValueError("Only session status may be cached")
        if self.client is not None:
            try:
                await self.client.set(
                    self.key(owner, conversation),
                    json.dumps({"status": status}),
                    ex=self.ttl,
                )
            except RedisError:
                pass  # Cache misses/outages never replace durable storage.

    async def get(self, owner, conversation):
        if self.client is None:
            return None
        try:
            value = await self.client.get(self.key(owner, conversation))
            return json.loads(value) if value else None
        except (RedisError, ValueError):
            return None
