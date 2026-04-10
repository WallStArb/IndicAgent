"""Kafka topic specifications for IndicAgent pipeline.

Each entry: (suffix, num_partitions, retention_ms, cleanup_policy)

Retention tiers:
  hot      — 2h (7,200,000ms)     Real-time transport, consumed within seconds
  pipeline — 4h (14,400,000ms)    Audit snapshots, replay buffer for restarts
  output   — 24h (86,400,000ms)   Output buffer for lagging consumers
  compact  — compacted topic, no time-based retention

Rationale: Redpanda is a transport layer, not storage. Once consumed and
persisted to TimescaleDB, Kafka data is redundant. Retention matches the
SLA of the slowest consumer, not "just in case." Ground truth is in the DB.

Used by pipeline_reset.py to delete + recreate all topics on a full reset.
"""

# ---------------------------------------------------------------------------
# Retention tiers (milliseconds)
# ---------------------------------------------------------------------------
_HOT_MS: int = 7_200_000          # 2 hours
_PIPELINE_MS: int = 14_400_000    # 4 hours
_OUTPUT_MS: int = 86_400_000      # 24 hours

# ---------------------------------------------------------------------------
# Topic specifications
# ---------------------------------------------------------------------------
# (suffix, num_partitions, retention_ms, cleanup_policy)
_TOPIC_SPECS: list[tuple[str, int, int, str]] = [
    # --- Market data (hot — consumed in real-time by pipeline services) ---
    ("market.ticks",               1, _HOT_MS,      "delete"),
    ("market.bars",                1, _HOT_MS,      "delete"),
    ("market.bars.htf",            1, _HOT_MS,      "delete"),
    # market.bars.raw.<provider> entries are added dynamically via get_topic_specs()
    ("market.events.gap_requests", 1, _PIPELINE_MS, "delete"),
    ("market.events.roll",         1, _PIPELINE_MS, "delete"),
    ("market.data.quality",        1, _OUTPUT_MS,   "delete"),
    # --- Intelligence pipeline (pipeline — audit snapshots, replay buffer) ---
    ("indicators",                 1, _PIPELINE_MS, "delete"),
    ("intelligence",               1, _PIPELINE_MS, "delete"),
    ("intelligence.i8",            1, _PIPELINE_MS, "delete"),
    ("intelligence.journal",       1, _OUTPUT_MS,   "delete"),
    ("intelligence.record",        1, _PIPELINE_MS, "delete"),
    # --- Signal pipeline stages (pipeline — consumed within seconds) ---
    ("pipeline.quality_gated",     1, _PIPELINE_MS, "delete"),
    ("pipeline.regime_gated",      1, _PIPELINE_MS, "delete"),
    ("pipeline.tod_adjusted",      1, _PIPELINE_MS, "delete"),
    ("pipeline.calibrated",        1, _PIPELINE_MS, "delete"),
    ("pipeline.ranked",            1, _PIPELINE_MS, "delete"),
    # --- Signals (output — consumed by tracker/narrative, buffer for restart) ---
    ("signals",                    1, _PIPELINE_MS, "delete"),
    ("signals.aggregated",         1, _OUTPUT_MS,   "delete"),
    # --- LLM (output — audit trail, consumed by writer) ---
    ("llm.calls",                  1, _OUTPUT_MS,   "delete"),
    ("llm.outcomes",               1, _OUTPUT_MS,   "delete"),
    # --- Narratives (output — consumed by dashboard SSE) ---
    ("narratives",                 1, _OUTPUT_MS,   "delete"),
    ("narratives.group",           1, _OUTPUT_MS,   "delete"),
    # --- Cross-asset (pipeline — consumed by pipeline in real-time) ---
    ("cross_asset",                1, _PIPELINE_MS, "delete"),
    # --- System (compact — state + events, low volume) ---
    ("system.events",              1, _PIPELINE_MS, "delete"),
    ("audit",                      1, _OUTPUT_MS,   "delete"),
    ("pipeline.data_quality",      1, _PIPELINE_MS, "delete"),
]

# Compacted topics (state snapshots — key-based retention)
_COMPACTED_TOPICS: list[tuple[str, int]] = [
    # (suffix, num_partitions)
    ("intelligence.pipeline.state", 1),
    ("market.events.contract_update", 1),
]


def get_topic_specs(providers: list[str]) -> list[tuple[str, int, int, str]]:
    """Return full topic spec list, including one raw topic per provider.

    Args:
        providers: List of provider names from Settings.provider_raw_topics
                   (e.g. ["ibkr", "polygon"]).
    """
    raw_provider_specs = [
        (f"market.bars.raw.{provider}", 1, _HOT_MS, "delete") for provider in providers
    ]
    # Insert raw provider topics immediately after market.bars.htf
    insert_after = next(i for i, t in enumerate(_TOPIC_SPECS) if t[0] == "market.bars.htf")
    return _TOPIC_SPECS[: insert_after + 1] + raw_provider_specs + _TOPIC_SPECS[insert_after + 1 :]
