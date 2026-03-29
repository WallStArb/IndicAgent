"""Kafka topic specifications for IndicAgent pipeline.

Each entry: (suffix, num_partitions, retention_ms)

suffix         — topic name after the env prefix (e.g. "market.bars" → "development.market.bars")
num_partitions — 1 for all topics (single-partition ordering guarantees per symbol)
retention_ms   — 7 days (604_800_000) for all topics; keeps a full trading week for replay

Used by pipeline_reset.py to delete + recreate all topics on a full reset.
"""

_SEVEN_DAYS_MS = 604_800_000

_TOPIC_SPECS: list[tuple[str, int, int]] = [
    # --- Market data ---
    ("market.ticks",               1, _SEVEN_DAYS_MS),
    ("market.bars",                1, _SEVEN_DAYS_MS),
    ("market.bars.htf",            1, _SEVEN_DAYS_MS),
    # market.bars.raw.<provider> entries are added dynamically via get_topic_specs()
    ("market.events.gap_requests", 1, _SEVEN_DAYS_MS),
    ("market.events.roll",         1, _SEVEN_DAYS_MS),
    ("market.data.quality",        1, _SEVEN_DAYS_MS),
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
    ("audit",                      1, _SEVEN_DAYS_MS),
    ("pipeline.data_quality",      1, _SEVEN_DAYS_MS),
]


def get_topic_specs(providers: list[str]) -> list[tuple[str, int, int]]:
    """Return full topic spec list, including one raw topic per provider.

    Args:
        providers: List of provider names from Settings.provider_raw_topics
                   (e.g. ["ibkr", "polygon"]).
    """
    raw_provider_specs = [
        (f"market.bars.raw.{provider}", 1, _SEVEN_DAYS_MS) for provider in providers
    ]
    # Insert raw provider topics immediately after market.bars.htf
    insert_after = next(i for i, t in enumerate(_TOPIC_SPECS) if t[0] == "market.bars.htf")
    return _TOPIC_SPECS[: insert_after + 1] + raw_provider_specs + _TOPIC_SPECS[insert_after + 1 :]
