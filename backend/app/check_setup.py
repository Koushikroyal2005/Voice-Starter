"""Compare local frontend/backend configuration without printing secret values."""

import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values

from app.config.settings import ConfigurationError, Settings, validate_url

ROOT = Path(__file__).resolve().parents[2]


def check_configuration(
    frontend: Mapping[str, str], backend: Mapping[str, str]
) -> list[str]:
    problems = []
    shared = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
    for key in shared:
        if not frontend.get(key, "").strip():
            problems.append(f"Frontend missing {key}: set root .env.local")
    try:
        Settings.from_env(backend)
    except ConfigurationError as error:
        problems.append(f"Backend: {error}")
    if frontend.get("LIVEKIT_URL", "").strip():
        try:
            validate_url("LIVEKIT_URL", frontend["LIVEKIT_URL"].strip(), {"ws", "wss"})
        except ConfigurationError as error:
            problems.append(f"Frontend: {error}")
    for key in (*shared, "AGENT_NAME"):
        left, right = frontend.get(key, "").strip(), backend.get(key, "").strip()
        if key == "LIVEKIT_URL":
            left, right = left.rstrip("/"), right.rstrip("/")
        if left != right:
            problems.append(
                f"{key} differs between frontend and backend; use matching values"
            )
    return problems


def read_environment(paths: list[Path]) -> dict[str, str]:
    values = {}
    for path in paths:
        values.update({k: v for k, v in dotenv_values(path).items() if v is not None})
    values.update(os.environ)
    return values


if __name__ == "__main__":
    # Next.js development precedence, from lowest to highest priority.
    frontend = read_environment(
        [
            ROOT / ".env",
            ROOT / ".env.development",
            ROOT / ".env.local",
            ROOT / ".env.development.local",
        ]
    )
    backend = read_environment([ROOT / "backend" / ".env"])
    errors = check_configuration(frontend, backend)
    if errors:
        print("Voice setup is incomplete:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print(
        "Local configuration matches. This does not test credentials or connectivity."
    )
    print(
        "Dispatch: named"
        if backend.get("AGENT_NAME", "").strip()
        else "Dispatch: automatic"
    )
