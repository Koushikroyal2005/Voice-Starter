"""Validated, backend-only telemetry and reliability controls."""

from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ObservabilitySettings:
    otlp_endpoint: str = ""
    prometheus_enabled: bool = False
    sentry_dsn: str = field(default="", repr=False)
    provider_retries: int = 2
    provider_timeout: float = 10

    @classmethod
    def from_env(cls, env):
        def number(key, default, low, high):
            try:
                value = float(env.get(key, default))
                if not low <= value <= high:
                    raise ValueError
                return value
            except ValueError:
                raise ValueError(f"Invalid {key}") from None

        endpoint = env.get("VOICE_OTLP_ENDPOINT", "").strip()
        if endpoint:
            try:
                url = urlsplit(endpoint)
                valid = (
                    url.scheme in {"http", "https"}
                    and url.hostname
                    and not url.username
                    and not url.password
                    and not url.query
                    and not url.fragment
                )
            except ValueError:
                valid = False
            if not valid:
                raise ValueError(
                    "VOICE_OTLP_ENDPOINT must be an HTTP URL without secrets"
                )
        flag = env.get("PROMETHEUS_ENABLED", "false").strip().lower()
        if flag not in {"true", "false"}:
            raise ValueError("PROMETHEUS_ENABLED must be true or false")
        dsn = env.get("SENTRY_DSN", "").strip()
        if dsn:
            try:
                parsed = urlsplit(dsn)
                valid = (
                    parsed.scheme in {"http", "https"}
                    and parsed.hostname
                    and parsed.username
                    and parsed.path.strip("/")
                    and not parsed.password
                    and not parsed.query
                    and not parsed.fragment
                )
            except ValueError:
                valid = False
            if not valid:
                raise ValueError(
                    "Invalid SENTRY_DSN; configure a public-key project DSN"
                )
        retries = number("PROVIDER_MAX_RETRIES", 2, 0, 3)
        if not retries.is_integer():
            raise ValueError("PROVIDER_MAX_RETRIES must be an integer")
        return cls(
            endpoint,
            flag == "true",
            dsn,
            int(retries),
            number("PROVIDER_TIMEOUT_SECONDS", 10, 1, 60),
        )
