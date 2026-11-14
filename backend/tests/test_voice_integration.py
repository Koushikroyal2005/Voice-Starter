"""Opt-in audio scenarios; absent consent or fixtures is a skip, not a benchmark."""

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.evaluation.run import SCENARIOS, run

SCENARIOS_DATA = json.loads(SCENARIOS.read_text(encoding="utf-8"))


@pytest.mark.skipif(
    os.getenv("RUN_REAL_VOICE_EVAL") != "true",
    reason="Real providers and consented WAV fixtures are opt-in",
)
@pytest.mark.parametrize(
    "scenario", [s["id"] for s in SCENARIOS_DATA if s["mode"] == "audio"]
)
def test_real_voice_scenario(scenario):
    if not os.getenv("VOICE_EVAL_FIXTURES"):
        pytest.skip("VOICE_EVAL_FIXTURES is required")
    fixtures = Path(os.environ["VOICE_EVAL_FIXTURES"])
    if not (fixtures / f"{scenario}.wav").is_file():
        pytest.skip("Missing scenario WAV fixture")
    report = asyncio.run(
        run(
            SimpleNamespace(
                list=False,
                fixtures=fixtures,
                reviews=None,
                concurrency=4,
                scenario=scenario,
            )
        )
    )
    assert all(r["status"] == "measured_server_replay" for r in report["results"])
    for result in report["results"]:
        assert result["scores"]["transcription"] is not None
        assert result["scores"]["first_audio_seconds"]
