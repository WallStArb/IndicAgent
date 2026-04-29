from __future__ import annotations

import os

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def init_otel_providers(
    service_name: str = "indicagent-processor",
    endpoint: str | None = None,
) -> None:
    """Initialize OTel MeterProvider + TracerProvider with OTLP gRPC export.

    Graceful degradation: wraps in try/except. If Collector is unreachable,
    falls back to no-op providers. Agents still run; metrics/traces just drop.
    Idempotent: first call wins, subsequent calls are no-ops.
    """
    endpoint = endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    # OTLP gRPC endpoint uses :4317 (not :4318/v1/traces)
    grpc_endpoint = endpoint.replace("http://", "").replace("https://", "")
    # Remove any trailing path (e.g. /v1/traces) for gRPC
    if "/" in grpc_endpoint:
        grpc_endpoint = grpc_endpoint.split("/")[0]

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": os.getenv("APP_VERSION", "dev"),
            "deployment.environment": os.getenv("INDICAGENT_ENV", os.getenv("ENV", "dev")),
        }
    )

    # Initialize MeterProvider (metrics)
    if metrics.get_meter_provider().__class__.__name__ == "ProxyMeterProvider":
        try:
            metric_reader = PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=grpc_endpoint, insecure=True),
                export_interval_millis=15000,  # export every 15s
            )
            meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
            metrics.set_meter_provider(meter_provider)
        except Exception:
            pass  # Graceful degradation -- agents run without metrics export

    # Initialize TracerProvider (traces) -- replaces init_tracing()
    if trace.get_tracer_provider().__class__.__name__ == "ProxyTracerProvider":
        try:
            provider = TracerProvider(resource=resource)
            exporter = OTLPSpanExporter(
                endpoint=f"http://{grpc_endpoint}/v1/traces",
            )
            processor = BatchSpanProcessor(exporter)
            provider.add_span_processor(processor)
            trace.set_tracer_provider(provider)
        except Exception:
            pass  # Graceful degradation


# Keep backward compat -- init_tracing() now delegates to init_otel_providers
def init_tracing(service_name: str = "indicagent-processor") -> None:
    """Backward-compat shim. Delegates to init_otel_providers."""
    init_otel_providers(service_name=service_name)


def get_tracer(name: str):
    return trace.get_tracer(name)


def get_meter(name: str = "indicagent"):
    return metrics.get_meter(name)
