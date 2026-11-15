"""Local provider diagnostics: offline by default, inference only with --live."""

import argparse
import asyncio
import json
import logging
import re
from pathlib import Path

from app.config.validation import ConfigurationError


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Backend provider configuration doctor"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    providers = commands.add_parser("providers")
    actions = providers.add_subparsers(dest="action", required=True)
    doctor = actions.add_parser("doctor")
    mode = doctor.add_mutually_exclusive_group()
    mode.add_argument(
        "--offline", action="store_true", help="No network requests (default)"
    )
    mode.add_argument(
        "--live", action="store_true", help="Opt in to billable inference"
    )
    doctor.add_argument(
        "--wav", type=Path, help="Consented <=15s mono 16-bit 16kHz WAV"
    )
    args = parser.parse_args(argv)
    if args.wav and not args.live:
        parser.error("--wav requires --live")
    # Vendor SDKs can log private provider bodies. The doctor only prints its own
    # fixed, sanitized report, never SDK logs, exception strings or transcripts.
    previous_logging_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        from app.config.settings import load_settings
        from app.providers.doctor import live_report, offline_report

        settings = load_settings()
        report = (
            asyncio.run(live_report(settings, wav=args.wav))
            if args.live
            else offline_report(settings)
        )
    except ConfigurationError as error:
        message = str(error)
        reason = "invalid_configuration"
        for term, label in (
            ("Missing required", "missing_credentials"),
            ("conflicts", "configuration_conflict"),
            ("unsupported provider", "unsupported_provider"),
            ("MODEL is unsupported", "unsupported_model"),
            ("Unsupported", "unsupported_provider"),
            ("unsupported", "unsupported_model_or_option"),
            ("interim", "capability_mismatch"),
            ("Batch STT", "capability_mismatch"),
        ):
            if term in message:
                reason = label
                break
        # Configuration exceptions are sanitized by the resolver; do not print
        # arbitrary Pydantic/provider errors here.
        report = {"result": "not_ready", "failure": reason}
        if reason == "missing_credentials":
            report["required_variables"] = sorted(
                set(re.findall(r"\b[A-Z][A-Z0-9_]*(?:_KEY|_SECRET|_URL)\b", message))
            )
    except Exception:
        report = {"result": "not_ready", "failure": "invalid_sample_or_configuration"}
    logging.disable(previous_logging_disable)
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return (
        0
        if report["result"]
        in ("ready_for_browser_testing", "configuration_valid_inference_not_tested")
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
