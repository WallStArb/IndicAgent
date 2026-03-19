"""Data quality Prometheus metrics — continuously updated by data_quality_check.py.

Metrics are module-level constants (prevent duplicate registration across imports).
All gauges are labeled by dimension (symbol, timeframe) for drill-down visibility.

Renaissance principle: "Instrument everything." Data quality is observable state,
not assumed correctness.
"""

from prometheus_client import Gauge

# --- NULL RATE METRICS ---

DQ_NULL_CIS_RATE = Gauge(
    "dq_null_cis_rate",
    "Fraction of signal_ledger rows with NULL cis_score (recoverable nulls only)",
    ["symbol"],
)

DQ_NULL_CONFIDENCE_RATE = Gauge(
    "dq_null_confidence_rate",
    "Fraction of signal_ledger rows with NULL confidence",
    ["symbol"],
)

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
