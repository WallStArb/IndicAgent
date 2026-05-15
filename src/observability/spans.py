from contextlib import asynccontextmanager

from opentelemetry import trace
from opentelemetry.trace import StatusCode

# Standard attribute keys — used by all span sites to ensure consistent naming
ATTR_SYMBOL = "symbol"
ATTR_TF = "tf"
ATTR_PLUGIN = "plugin_name"
ATTR_TIER = "intelligence_tier"
ATTR_AGENT_ID = "agent_id"
ATTR_SIGNAL_ID = "signal_id"
ATTR_GROUP_ID = "group_id"
ATTR_BATCH_SZ = "batch_size"
ATTR_FLUSH_MS = "flush_ms"


@asynccontextmanager
async def observed_span(name: str, tracer=None, **attrs):
    """Async context manager: creates a span, records exceptions, sets ERROR status.

    For use only in the two pipeline span sites in intelligence_pipeline_agent.py.
    All other spans are owned by base classes.
    """
    _tracer = tracer or trace.get_tracer("indicagent")
    with _tracer.start_as_current_span(name, attributes=attrs) as span:
        try:
            yield span
        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise
