"""SwarmMetrics — Golden Signal Prometheus metrics for swarm services.

Creates metrics via src/observability/metrics.py to prevent duplicate registration.
Label convention: agent_id (not agent=).
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# Traffic
SWARM_SIGNALS_PROCESSED = Counter(
    "swarm_signals_processed_total",
    "Signals processed by SwarmOrchestratorComputeAgent",
    ["symbol", "timeframe"],
)

# Latency
SWARM_AGENT_LATENCY = Histogram(
    "swarm_agent_latency_seconds",
    "Per-agent compute latency",
    ["agent_id", "path"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
)

# Errors
SWARM_AGENT_ERRORS = Counter(
    "swarm_agent_errors_total",
    "Agent computation failures (timeout or exception)",
    ["agent_id", "error_type"],
)

# Saturation
SWARM_CONTEXT_CACHE_SIZE = Gauge(
    "swarm_context_cache_size",
    "Number of entries in SwarmContextCache",
)

SWARM_SHADOW_PREDICTIONS = Counter(
    "shadow_predictions_total",
    "Shadow multiplier predictions recorded",
    ["agent_id", "path"],
)

AGENT_INFERENCE_LATENCY = Histogram(
    "agent_inference_latency_seconds",
    "Per-agent inference latency (SwarmBaseAgent.compute)",
    ["agent_id"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
)
