"""Data quality Prometheus metrics — observability for the intelligence pipeline.

Null-rate metrics (DQ_NULL_CIS_RATE, DQ_NULL_CONFIDENCE_RATE) were removed in
Phase 61 — null CIS is now prevented by DB NOT NULL constraint (migration 057)
and source assertion in intelligence_pipeline_agent. Remaining metrics:
staleness, pipeline lag, OHLCV completeness, IC health.
"""

from prometheus_client import Gauge

# --- STALENESS METRICS ---

DQ_INTELLIGENCE_STALENESS_SECONDS = Gauge(
    "dq_intelligence_staleness_seconds",
    "Seconds since last intelligence_features row written per (symbol, timeframe)",
    ["symbol", "timeframe"],
)

DQ_SIGNAL_STALENESS_SECONDS = Gauge(
    "dq_signal_staleness_seconds",
    "Seconds since last signal_ledger row written per symbol",
    ["symbol"],
)

# --- PIPELINE LAG METRICS ---

DQ_PIPELINE_LAG_P50_MS = Gauge(
    "dq_pipeline_lag_p50_ms",
    "P50 pipeline_lag_ms from signal_ledger (feature_ts to signal_computed_at)",
    ["symbol", "timeframe"],
)

DQ_PIPELINE_LAG_P95_MS = Gauge(
    "dq_pipeline_lag_p95_ms",
    "P95 pipeline_lag_ms from signal_ledger — critical threshold 500ms",
    ["symbol", "timeframe"],
)

# --- OHLCV COMPLETENESS METRICS ---

DQ_OHLCV_MISSING_BARS_DAILY = Gauge(
    "dq_ohlcv_missing_bars_daily",
    "Count of missing expected 1m RTH bars in today's session per symbol",
    ["symbol"],
)

DQ_OHLCV_CHUNK_COUNT = Gauge(
    "dq_ohlcv_chunk_count",
    "Total chunk count in market_data_ohlcv hypertable (target < 200 after rebuild)",
    [],
)

# --- IC HEALTH METRICS ---

DQ_IC_SCORE = Gauge(
    "dq_ic_score",
    "Latest Information Coefficient per (setup_plugin, timeframe)",
    ["setup_plugin", "timeframe"],
)

DQ_IC_SIGNIFICANT_FRACTION = Gauge(
    "dq_ic_significant_fraction",
    "Fraction of plugins with N>=30 that have IC p-value < 0.05",
    [],
)
