"""Atomic fixed-window quota; enabled limiters fail closed on Redis failure."""

from redis.exceptions import RedisError

from app.tools.base import ToolFailure

SCRIPT = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return n
"""


class RateLimiter:
    def __init__(self, client=None, limit=0, window=60):
        if limit < 0 or window <= 0 or (limit and client is None):
            raise ValueError("Enabled rate limiting needs Redis and positive window")
        self.client, self.limit, self.window = client, limit, window

    async def check(self, owner):
        if not self.limit:
            return
        if len(owner) != 64:
            raise PermissionError("Owner is required")
        try:
            count = await self.client.eval(
                SCRIPT, 1, f"voice:quota:{owner}", self.window
            )
        except RedisError:
            raise ToolFailure(
                "rate_limit_unavailable", "Please try again later"
            ) from None
        if count > self.limit:
            raise ToolFailure("rate_limited", "Tool request limit reached; try later")
