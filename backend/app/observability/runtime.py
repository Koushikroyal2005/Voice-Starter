"""Metadata-only custom spans; no conversation, tool payload or exception export."""

import logging
import math

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import StatusCode

from app.observability.logging import configure_logging

logger = logging.getLogger("voice-starter.telemetry")


class Telemetry:
    def __init__(self, session_id, config, provider=None, request_id=None):
        configure_logging()
        self.session_id = session_id
        self.request_id = request_id or session_id
        self.closed = False
        self.provider = provider or TracerProvider(
            resource=Resource.create({"service.name": "voice-starter-worker"})
        )
        if config.otlp_endpoint and provider is None:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            self.provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=config.otlp_endpoint, timeout=3),
                    max_queue_size=512,
                    max_export_batch_size=64,
                )
            )
        self.tracer = self.provider.get_tracer("voice-starter")
        self.session_span = self.tracer.start_span(
            "voice.session", attributes={"session_id": session_id}
        )
        self.context = trace.set_span_in_context(self.session_span)
        self.histogram = self.counter = self.http = self.sentry = None
        if config.prometheus_enabled:
            try:
                from prometheus_client import (
                    CollectorRegistry,
                    Counter,
                    Histogram,
                    start_http_server,
                )
            except ImportError:
                raise ValueError(
                    "PROMETHEUS_ENABLED requires uv sync --extra telemetry"
                ) from None
            registry = CollectorRegistry()
            self.histogram = Histogram(
                "voice_stage_seconds",
                "Measured server latency",
                ["stage"],
                registry=registry,
                buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
            )
            self.counter = Counter(
                "voice_events",
                "Voice lifecycle events",
                ["stage", "status"],
                registry=registry,
            )
            self.http, _ = start_http_server(0, addr="127.0.0.1", registry=registry)
            logger.info(
                "Per-job metrics endpoint listening",
                extra={"session_id": session_id, "metric_port": self.http.server_port},
            )
        if config.sentry_dsn:
            try:
                import sentry_sdk
            except ImportError:
                raise ValueError(
                    "SENTRY_DSN requires uv sync --extra telemetry"
                ) from None
            # Dedicated client: no automatic breadcrumbs, HTTP payloads or exceptions.
            self.sentry = sentry_sdk.Client(
                dsn=config.sentry_dsn,
                default_integrations=False,
                auto_enabling_integrations=False,
                send_default_pii=False,
                max_breadcrumbs=0,
                traces_sample_rate=0,
            )

    def event(
        self,
        stage,
        *,
        turn_id=None,
        tool_call_id=None,
        duration=None,
        status="ok",
        category=None,
        provider=None,
        recoverable=None,
    ):
        if self.closed:
            return
        attributes = {
            "session_id": self.session_id,
            "request_id": self.request_id,
            "stage": stage,
            "status": status,
        }
        for key, value in (
            ("turn_id", turn_id),
            ("tool_call_id", tool_call_id),
            ("category", category),
            ("provider", provider),
            ("recoverable", recoverable),
        ):
            if value is not None:
                attributes[key] = value
        if duration is not None:
            if not math.isfinite(duration) or duration < 0:
                return  # Missing/invalid SDK values are not measured zeroes.
            attributes["duration_seconds"] = duration
            if self.histogram:
                self.histogram.labels(stage=stage).observe(duration)
        with self.tracer.start_as_current_span(
            f"voice.{stage}", context=self.context, attributes=attributes
        ) as span:
            if status in {"error", "failed", "timeout", "unknown"}:
                span.set_status(StatusCode.ERROR)
            logger.info("Voice telemetry", extra=attributes)
        if self.counter:
            self.counter.labels(stage=stage, status=status).inc()
        if self.sentry and status == "error":
            self.sentry.capture_event(
                {
                    "message": f"Voice {stage} failed",
                    "level": "error",
                    "tags": attributes,
                }
            )

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.session_span.end()
        self.provider.shutdown()
        if self.http:
            self.http.shutdown()
            self.http.server_close()
        if self.sentry:
            self.sentry.close(timeout=2)
