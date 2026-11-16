"""Git privacy boundaries shared by local evaluation commands."""

import subprocess
from pathlib import Path


def require_ignored_file(path: Path):
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--", str(path.resolve())],
        capture_output=True,
        timeout=3,
    )
    if result.returncode != 0:
        raise ValueError("Use an ignored .local/ or evaluation.local/ directory")


def require_ignored(directory: Path):
    """Reject output directories that would expose common evaluation artifacts."""
    for name in ("probe.wav", "probe.onnx", "probe.json", "probe.part"):
        require_ignored_file(directory / name)
