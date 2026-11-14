"""Application JSON logs deliberately exclude arbitrary extras and exception text."""

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

from opentelemetry import trace

correlation = ContextVar("voice_correlation", default=None)


class CorrelationFilter(logging.Filter):
    def filter(self, record):
        for key, value in (correlation.get() or {}).items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


FIELDS = (
    "session_id",
    "turn_id",
    "tool_call_id",
    "request_id",
    "stage",
    "duration_seconds",
    "status",
    "category",
    "provider",
    "recoverable",
    "metric_port",
)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(
            {key: getattr(record, key) for key in FIELDS if hasattr(record, key)}
        )
        context = trace.get_current_span().get_span_context()
        if context.is_valid:
            payload["trace_id"] = format(context.trace_id, "032x")
        return json.dumps(payload, ensure_ascii=False)


def configure_logging():
    logger = logging.getLogger("voice-starter")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(getattr(handler, "voice_json", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.voice_json = True
        handler.addFilter(CorrelationFilter())
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
