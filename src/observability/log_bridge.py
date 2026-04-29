"""OTLP Log Bridge -- forwards structlog output to OTel Collector.

Additive to existing file-based logging. OTLP export is non-blocking and
best-effort; failures are silently dropped to avoid impacting the pipeline.
"""

from __future__ import annotations

import logging
from typing import Optional

from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggingHandler, LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource


def setup_otlp_logging(
    service_name: str = "indicagent",
    endpoint: str | None = None,
) -> Optional[LoggerProvider]:
    """Set up OTLP log export alongside existing file logging.

    Returns LoggerProvider if successful, None if Collector unreachable.
    Non-blocking: failures silently degrade to file-only logging.
    """
    import os

    try:
        endpoint = endpoint or os.getenv(
            "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"
        )
        grpc_endpoint = endpoint.replace("http://", "").replace("https://", "")
        if "/" in grpc_endpoint:
            grpc_endpoint = grpc_endpoint.split("/")[0]

        resource = Resource.create(
            {
                "service.name": service_name,
                "service.version": os.getenv("APP_VERSION", "dev"),
                "deployment.environment": os.getenv(
                    "INDICAGENT_ENV", os.getenv("ENV", "dev")
                ),
            }
        )

        logger_provider = LoggerProvider(resource=resource)
        exporter = OTLPLogExporter(endpoint=grpc_endpoint, insecure=True)
        processor = BatchLogRecordProcessor(exporter)
        logger_provider.add_log_record_processor(processor)

        handler = LoggingHandler(logger_provider=logger_provider)
        handler.setLevel(logging.WARNING)
        logging.getLogger().addHandler(handler)

        return logger_provider
    except Exception:
        return None
