"""OTLP Log Bridge -- forwards structlog output to OTel Collector.

Additive to existing file-based logging. OTLP export is non-blocking and
best-effort; failures are silently dropped to avoid impacting the pipeline.
"""

from __future__ import annotations

import logging

from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource


def setup_otlp_logging(
    service_name: str = "indicagent",
    endpoint: str | None = None,
) -> LoggerProvider | None:
    """Set up OTLP log export alongside existing file logging.

    Returns LoggerProvider if successful, None if Collector unreachable.
    Non-blocking: failures silently degrade to file-only logging.
    """
    import os

    # Suppress noisy OTel exporter retry/reconnect logs.
    logging.getLogger("opentelemetry.exporter.otlp.proto.grpc.exporter").setLevel(logging.CRITICAL)
    logging.getLogger("opentelemetry.sdk._logs.export").setLevel(logging.CRITICAL)

    try:
        endpoint = endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        grpc_endpoint = endpoint.replace("http://", "").replace("https://", "")
        if "/" in grpc_endpoint:
            grpc_endpoint = grpc_endpoint.split("/")[0]

        resource = Resource.create(
            {
                "service.name": service_name,
                "service.version": os.getenv("APP_VERSION", "dev"),
                "deployment.environment": os.getenv("INDICAGENT_ENV", os.getenv("ENV", "dev")),
            }
        )

        logger_provider = LoggerProvider(resource=resource)

        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

        exporter = OTLPLogExporter(endpoint=grpc_endpoint, insecure=True)
        processor = BatchLogRecordProcessor(
            exporter,
            max_queue_size=2048,
            schedule_delay_millis=5000,
            max_export_batch_size=512,
        )
        logger_provider.add_log_record_processor(processor)

        # Set as global provider so LoggingInstrumentor picks it up
        from opentelemetry._logs import set_logger_provider

        set_logger_provider(logger_provider)
        LoggingInstrumentor().instrument(set_logging_format=False)

        return logger_provider
    except Exception:
        return None
