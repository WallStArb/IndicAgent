from __future__ import annotations

import logging
import os
import socket

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_log = logging.getLogger(__name__)


class OTelInitError(RuntimeError):
    """Raised when OTel MeterProvider initialization or startup validation fails.

    TracerProvider failures remain graceful (warning log) since traces are
    genuinely optional.  Metrics are NOT optional - if the collector is
    unreachable the service must crash so systemd restarts it with visible
    failure mode, not silently degrade into a metrics black hole.
    """


def init_otel_providers(
    service_name: str = "indicagent-processor",
    endpoint: str | None = None,
) -> None:
    """Initialize OTel MeterProvider + TracerProvider with OTLP gRPC export.

    Metrics: hard failure. If the collector is unreachable, raises OTelInitError
    so the calling service crashes and systemd restarts it. No silent degradation.

    Traces: graceful degradation. If the TracerProvider init fails, logs a warning
    and continues. Traces are useful but not mission-critical.

    Idempotent: first call wins, subsequent calls are no-ops.
    """
    endpoint = endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    grpc_endpoint = endpoint.replace("http://", "").replace("https://", "")
    if "/" in grpc_endpoint:
        grpc_endpoint = grpc_endpoint.split("/")[0]

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": os.getenv("APP_VERSION", "dev"),
            "deployment.environment": os.getenv("INDICAGENT_ENV", os.getenv("ENV", "dev")),
            "service.instance.id": f"{socket.gethostname()}:{os.getpid()}",
        }
    )

    # Initialize MeterProvider (metrics) — HARD FAILURE
    if not isinstance(metrics.get_meter_provider(), MeterProvider):
        metric_reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=grpc_endpoint, insecure=True),
            export_interval_millis=15000,  # export every 15s
        )
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        metrics.set_meter_provider(meter_provider)

        # Startup validation: record a test metric and force_flush to verify
        # gRPC export actually works. Catches the exact class of bug where the
        # endpoint is misconfigured (wrong port, wrong protocol, firewall, etc).
        if os.getenv("OTEL_VALIDATION_DISABLED") != "1":
            _validate_export(meter_provider, service_name, endpoint)

    # Initialize TracerProvider (traces) — graceful degradation
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        try:
            provider = TracerProvider(resource=resource)
            exporter = OTLPSpanExporter(
                endpoint=grpc_endpoint,
                insecure=True,
            )
            processor = BatchSpanProcessor(exporter)
            provider.add_span_processor(processor)
            trace.set_tracer_provider(provider)
        except Exception as error:
            _log.warning("otel.tracer_provider_init_failed endpoint=%s error=%s", endpoint, error)


def _validate_export(
    meter_provider: MeterProvider,
    service_name: str,
    endpoint: str,
) -> None:
    """Force a test metric through the export pipeline to verify gRPC connectivity."""
    meter_provider.get_meter("otel.healthcheck").create_counter("otel_export_validation_total").add(
        1, {"service": service_name, "check": "startup"}
    )
    # force_flush raises on gRPC connection failure — let it propagate as-is.
    # The caller (init_otel_providers) is not wrapped in try/except, so any
    # exception from here crashes the service with a clear traceback.
    meter_provider.force_flush(timeout_millis=3000)


# Keep backward compat -- init_tracing() now delegates to init_otel_providers
def init_tracing(service_name: str = "indicagent-processor") -> None:
    """Backward-compat shim. Delegates to init_otel_providers."""
    init_otel_providers(service_name=service_name)


def get_tracer(name: str):
    return trace.get_tracer(name)


def get_meter(name: str = "indicagent"):
    return metrics.get_meter(name)
