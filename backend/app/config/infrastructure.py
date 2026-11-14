"""Infrastructure configuration does not require voice-provider credentials."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from sqlalchemy.engine import make_url


@dataclass(frozen=True)
class InfrastructureSettings:
    persistence_enabled: bool = False
    transcripts_enabled: bool = False
    database_url: str = field(default="", repr=False)
    redaction_key: str = field(default="", repr=False)
    owner_namespace: str = ""
    redis_enabled: bool = False
    redis_url: str = field(default="", repr=False)
    cache_ttl: int = 300
    rate_limit: int = 0
    rate_window: int = 60

    @classmethod
    def from_env(cls, env: Mapping[str, str]):
        def flag(key):
            raw = env.get(key, "false").lower().strip()
            if raw not in {"true", "false"}:
                raise ValueError(f"{key} must be true or false")
            return raw == "true"

        def number(key, default, minimum):
            try:
                value = int(env.get(key, str(default)))
                if value < minimum or value > 86400:
                    raise ValueError
                return value
            except ValueError:
                raise ValueError(f"{key} is outside its supported range") from None

        config = cls(
            persistence_enabled=flag("PERSISTENCE_ENABLED"),
            transcripts_enabled=flag("PERSIST_TRANSCRIPTS"),
            database_url=env.get("DATABASE_URL", ""),
            redaction_key=env.get("DATA_REDACTION_KEY", ""),
            owner_namespace=env.get("PERSISTENCE_OWNER_NAMESPACE", ""),
            redis_enabled=flag("REDIS_ENABLED"),
            redis_url=env.get("REDIS_URL", ""),
            cache_ttl=number("SESSION_CACHE_TTL_SECONDS", 300, 1),
            rate_limit=number("TOOL_RATE_LIMIT", 0, 0),
            rate_window=number("RATE_LIMIT_WINDOW_SECONDS", 60, 1),
        )
        if config.transcripts_enabled and not config.persistence_enabled:
            raise ValueError("PERSIST_TRANSCRIPTS requires PERSISTENCE_ENABLED")
        if config.persistence_enabled:
            try:
                url = make_url(config.database_url)
                valid = url.drivername == "postgresql+asyncpg" and url.database
            except Exception:
                valid = False
            if not valid:
                raise ValueError("DATABASE_URL must use postgresql+asyncpg")
        if config.persistence_enabled or config.redis_enabled:
            if len(config.redaction_key) < 32 or not config.owner_namespace.strip():
                raise ValueError(
                    "Set DATA_REDACTION_KEY (32+ characters) and "
                    "PERSISTENCE_OWNER_NAMESPACE"
                )
        if config.redis_enabled:
            try:
                url = make_url(config.redis_url)
                valid = url.drivername in {"redis", "rediss"} and url.host
            except Exception:
                valid = False
            if not valid:
                raise ValueError("REDIS_URL must use redis:// or rediss://")
        if config.rate_limit and not config.redis_enabled:
            raise ValueError("TOOL_RATE_LIMIT requires REDIS_ENABLED")
        return config
