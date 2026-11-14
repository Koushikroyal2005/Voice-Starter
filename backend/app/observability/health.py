"""Dependency readiness; worker registration uses LiveKit's built-in HTTP probe."""

import asyncio
import json

from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.cache.redis_client import create_redis
from app.config.settings import load_settings
from app.database.connection import Database
from app.reliability.retry import retry_probe


async def check_readiness(settings):
    results = {"configuration": "ok"}
    config = settings.infrastructure
    if config.persistence_enabled:
        db = Database(config.database_url)

        async def probe():
            async with db.transaction() as session:
                revision = await session.scalar(
                    text("SELECT version_num FROM alembic_version")
                )
                if revision != "0001_voice":
                    raise ValueError("Migration required")

        try:
            await retry_probe(
                probe, retryable=(OperationalError, OSError, TimeoutError)
            )
            results["postgresql"] = "ok"
        except Exception:
            results["postgresql"] = "unavailable"
        finally:
            await db.close()
    else:
        results["postgresql"] = "disabled"
    client = create_redis(config)
    if client:
        try:
            await retry_probe(
                client.ping, retryable=(RedisError, OSError, TimeoutError)
            )
            results["redis"] = "ok"
        except Exception:
            results["redis"] = (
                "unavailable" if config.rate_limit else "degraded_optional_cache"
            )
        finally:
            await client.aclose()
    else:
        results["redis"] = "disabled"
    return results


def main():
    try:
        results = asyncio.run(check_readiness(load_settings()))
    except Exception:
        results = {"configuration": "invalid"}
    ready = all(v not in {"unavailable", "invalid"} for v in results.values())
    print(json.dumps({"ready": ready, "checks": results}))
    raise SystemExit(0 if ready else 1)


if __name__ == "__main__":
    main()
