"""Kafka topic specifications for IndicAgent pipeline.

Each entry: (suffix, num_partitions, retention_ms)

suffix         — topic name after the env prefix (e.g. "market.bars" → "development.market.bars")
num_partitions — 1 for all topics (single-partition ordering guarantees per symbol)
retention_ms   — 7 days (604_800_000) for all topics; keeps a full trading week for replay

Used by pipeline_reset.py to delete + recreate all topics on a full reset.
"""

_SEVEN_DAYS_MS = 604_800_000

# (suffix, partitions, retention_ms)
_TOPIC_SPECS: list[tuple[str, int, int]] = [
    # --- Market data ---
    ("market.ticks",               1, _SEVEN_DAYS_MS),
    ("market.bars",                1, _SEVEN_DAYS_MS),
    ("market.bars.htf",            1, _SEVEN_DAYS_MS),
    ("market.bars.raw.ibkr",       1, _SEVEN_DAYS_MS),  # Phase 54: per-provider raw feed
    ("market.events.gap_requests", 1, _SEVEN_DAYS_MS),
    ("market.data.quality",        1, _SEVEN_DAYS_MS),  # Phase 54: ProviderQualityEvent
    # --- Intelligence pipeline ---
    ("indicators",                 1, _SEVEN_DAYS_MS),
    ("intelligence",               1, _SEVEN_DAYS_MS),
    ("intelligence.i8",            1, _SEVEN_DAYS_MS),
    ("intelligence.journal",       1, _SEVEN_DAYS_MS),
    ("intelligence.record",        1, _SEVEN_DAYS_MS),
    # --- Signal pipeline stages ---
    ("pipeline.quality_gated",     1, _SEVEN_DAYS_MS),
    ("pipeline.regime_gated",      1, _SEVEN_DAYS_MS),
    ("pipeline.tod_adjusted",      1, _SEVEN_DAYS_MS),
    ("pipeline.calibrated",        1, _SEVEN_DAYS_MS),
    ("pipeline.ranked",            1, _SEVEN_DAYS_MS),
    # --- Signals ---
    ("signals",                    1, _SEVEN_DAYS_MS),
    ("signals.aggregated",         1, _SEVEN_DAYS_MS),
    # --- LLM ---
    ("llm.calls",                  1, _SEVEN_DAYS_MS),
    ("llm.outcomes",               1, _SEVEN_DAYS_MS),
    # --- Narratives ---
    ("narratives",                 1, _SEVEN_DAYS_MS),
    ("narratives.group",           1, _SEVEN_DAYS_MS),
    # --- Cross-asset ---
    ("cross_asset",                1, _SEVEN_DAYS_MS),
    # --- System ---
    ("system.events",              1, _SEVEN_DAYS_MS),
]
