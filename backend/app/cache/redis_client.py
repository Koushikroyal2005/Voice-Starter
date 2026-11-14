"""Redis is an optional, disposable cache, never a database fallback."""

from redis.asyncio import Redis


def create_redis(settings):
    if not settings.redis_enabled:
        return None
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        max_connections=10,
    )
