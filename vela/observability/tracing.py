"""OpenTelemetry distributed tracing setup."""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_OTEL_AVAILABLE = False
_tracer = None

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.resources import Resource
    _OTEL_AVAILABLE = True
except ImportError:
    logger.info("opentelemetry packages not installed; tracing is a no-op")


def configure_tracing(
    service_name: str = "vela-api",
    otlp_endpoint: str | None = None,
    console_export: bool = False,
) -> Any:
    """
    Initialize OpenTelemetry tracing.
    If OTLP endpoint is set, exports spans to an OTel collector (Jaeger/Tempo).
    Falls back to console exporter in dev mode.
    """
    global _tracer

    if not _OTEL_AVAILABLE:
        return None

    endpoint = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    resource = Resource.create({"service.name": service_name, "deployment.environment": os.getenv("VELA_ENV", "dev")})
    provider = TracerProvider(resource=resource)

    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            exporter = OTLPSpanExporter(endpoint=endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("OTLP tracing configured: endpoint=%s", endpoint)
        except ImportError:
            logger.warning("OTLP exporter not installed; falling back to console")
            console_export = True

    if console_export or not endpoint:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(service_name)
    logger.info("OpenTelemetry tracing initialized for service '%s'", service_name)
    return _tracer


def get_tracer(name: str = "vela") -> Any:
    """Return the configured tracer, or a no-op tracer if OTel is not available."""
    if not _OTEL_AVAILABLE:
        return _NoOpTracer()
    from opentelemetry import trace as _trace
    return _trace.get_tracer(name)


class _NoOpSpan:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def set_attribute(self, key: str, value: Any) -> None:
        pass
    def record_exception(self, exc: Exception) -> None:
        pass
    def set_status(self, status: Any) -> None:
        pass


class _NoOpTracer:
    def start_as_current_span(self, name: str, **kwargs) -> _NoOpSpan:
        return _NoOpSpan()

    def start_span(self, name: str, **kwargs) -> _NoOpSpan:
        return _NoOpSpan()


def trace_function(span_name: str):
    """Decorator that wraps a function in an OTel span."""
    import functools
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            tracer = get_tracer()
            with tracer.start_as_current_span(span_name):
                return func(*args, **kwargs)
        return wrapper
    return decorator
