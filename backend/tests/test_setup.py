from app.check_setup import check_configuration


def configured():
    shared = {
        "LIVEKIT_URL": "wss://example.livekit.cloud",
        "LIVEKIT_API_KEY": "test-key",
        "LIVEKIT_API_SECRET": "test-secret",
        "AGENT_NAME": "voice-starter",
    }
    return shared, shared | {
        "DEEPGRAM_API_KEY": "test",
        "LLM_API_KEY": "test",
        "CARTESIA_API_KEY": "test",
    }


def test_matching_named_dispatch():
    assert check_configuration(*configured()) == []


def test_matching_automatic_dispatch():
    frontend, backend = configured()
    frontend["AGENT_NAME"] = backend["AGENT_NAME"] = ""
    assert check_configuration(frontend, backend) == []


def test_mismatches_do_not_print_secret_values():
    frontend, backend = configured()
    backend.update(
        LIVEKIT_URL="wss://other.livekit.cloud",
        LIVEKIT_API_SECRET="other-secret",
        AGENT_NAME="other-agent",
    )
    problems = check_configuration(frontend, backend)
    assert len(problems) == 3
    assert all("differs" in p for p in problems)
    assert "other-secret" not in str(problems)
    assert "test-secret" not in str(problems)


def test_missing_configuration_is_actionable():
    problems = check_configuration({}, {})
    assert any("Frontend missing LIVEKIT_URL" in p for p in problems)
    assert any("Backend: Missing required" in p for p in problems)
