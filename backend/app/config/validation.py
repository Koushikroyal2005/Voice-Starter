"""Shared, secret-safe configuration errors and scalar validation."""

from collections.abc import Mapping
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    """Invalid or missing environment configuration."""


def require_credentials(missing: list[str]) -> None:
    if missing:
        raise ConfigurationError(
            "Missing required environment variables: " + ", ".join(missing)
        )


def validate_url(name: str, value: str, schemes: set[str]) -> None:
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in schemes
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
        )
        _ = parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ConfigurationError(
            f"{name} must be a valid URL without credentials/query"
        )


def boolean(values: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = values.get(name, "").strip().lower()
    if not raw:
        return default
    if raw not in ("true", "false"):
        raise ConfigurationError(f"{name} must be true or false")
    return raw == "true"
