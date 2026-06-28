"""Kafka topic specifications for IndicAgent pipeline.

Version: 1.0
Status: current
Last Updated: 2026-06-12

Each entry: (suffix, num_partitions, retention_ms, cleanup_policy)

Retention tiers:
  hot      — 2h (7,200,000ms)     Real-time transport, consumed within seconds
  buffer   — 1d (86,400,000ms)    Standard buffer — all data persisted to TimescaleDB
  htf      — 3d (259,200,000ms)   HTF bars need accumulation window for 4h/1d catch-up
  compact  — compacted topic, no time-based retention

Rationale: Redpanda is a transport layer, not storage. Once consumed and
persisted to TimescaleDB, Kafka data is redundant. Retention is sized for
restart catch-up only — ground truth lives in the DB. At 55 symbols, even
1 day of 1m bars is ~76K messages; 7 days of intelligence output was 89 GB.

Used by pipeline_reset.py to delete + recreate all topics on a full reset.
"""

# ---------------------------------------------------------------------------
# Retention tiers (milliseconds)
# ---------------------------------------------------------------------------
_HOT_MS: int = 7_200_000  # 2 hours — ticks, sub-minute transport
_BUFFER_MS: int = 86_400_000  # 1 day   — standard restart catch-up
_HTF_MS: int = 259_200_000  # 3 days  — HTF bar accumulation window

# ---------------------------------------------------------------------------
# Topic specifications
# ---------------------------------------------------------------------------
# (suffix, num_partitions, retention_ms, cleanup_policy)
_TOPIC_SPECS: list[tuple[str, int, int, str]] = [
    # --- Market data ---
    ("market.ticks", 1, _HOT_MS, "delete"),
    ("market.bars", 1, _BUFFER_MS, "delete"),
    ("market.bars.htf", 1, _HTF_MS, "delete"),
    # market.bars.raw.<provider> entries are added dynamically via get_topic_specs()
    ("market.events.gap_requests", 1, _BUFFER_MS, "delete"),
    ("market.events.roll", 1, _BUFFER_MS, "delete"),
    ("market.data.quality", 1, _BUFFER_MS, "delete"),
    # --- Intelligence pipeline (all persisted by feature_writer → intelligence_features) ---
    ("intelligence", 1, _BUFFER_MS, "delete"),
    ("intelligence.i8", 1, _BUFFER_MS, "delete"),
    ("intelligence.journal", 1, _BUFFER_MS, "delete"),
    ("intelligence.i7.signals", 1, _BUFFER_MS, "delete"),
    ("intelligence.signal_metrics", 1, _BUFFER_MS, "delete"),
    ("intelligence.signal.audit", 1, _BUFFER_MS, "delete"),
    ("intelligence.service_auditor.journal.dlq", 1, _BUFFER_MS, "delete"),
    # --- Signals (persisted by signal_writer → signal_ledger) ---
    ("signals.aggregated", 1, _BUFFER_MS, "delete"),
    # --- LLM (persisted by llm_writer → llm_calls) ---
    ("llm.calls", 1, _BUFFER_MS, "delete"),
    ("llm.outcomes", 1, _BUFFER_MS, "delete"),
    # --- Narratives (consumed by dashboard SSE) ---
    ("narratives", 1, _BUFFER_MS, "delete"),
    ("narratives.group", 1, _BUFFER_MS, "delete"),
    # --- Cross-asset (consumed in real-time by pipeline) ---
    ("cross_asset", 1, _BUFFER_MS, "delete"),
    # --- Macro factors (persisted by macro_compute_agent → macro_features) ---
    ("macro_signals", 1, _BUFFER_MS, "delete"),
    # --- Lifecycle (persisted by lifecycle_writer) ---
    ("lifecycle.transitions", 1, _BUFFER_MS, "delete"),
    # --- Alpha swarm (AlphaSwarmComputeAgent → persisted to alpha_multiplier_shadow) ---
    ("swarm.alpha", 1, _BUFFER_MS, "delete"),
    # --- Signal lineage (LineageWriterAgent → signal_lineage hypertable) ---
    ("intelligence.signal_lineage", 1, _BUFFER_MS, "delete"),
    ("intelligence.signal_lineage.dlq", 1, _BUFFER_MS, "delete"),
    # --- Transform graduation (Phase 72) ---
    ("intelligence.transform.graduation", 1, _BUFFER_MS, "delete"),
    ("intelligence.transform.graduation.dlq", 1, _BUFFER_MS, "delete"),
    # --- System ---
    ("system.events", 1, _BUFFER_MS, "delete"),
    ("system.health.events", 1, _BUFFER_MS, "delete"),
    ("pipeline.data_quality", 1, _BUFFER_MS, "delete"),
    # --- Alerting ---
    ("alert.requests", 1, _BUFFER_MS, "delete"),
    # --- DLQs ---
    ("gap_fill.dlq", 1, _BUFFER_MS, "delete"),
]

# Compacted topics (state snapshots — key-based retention)
_COMPACTED_TOPICS: list[tuple[str, int]] = [
    # (suffix, num_partitions)
    ("bar.aggregator.state", 1),  # Phase 74: BarAggregator state checkpoints
    ("market.events.contract_update", 1),
]


def get_topic_specs(providers: list[str]) -> list[tuple[str, int, int, str]]:
    """Return full topic spec list, including one raw topic per provider.

    Args:
        providers: List of provider names from Settings.provider_raw_topics
                   (e.g. ["ibkr", "polygon"]).
    """
    raw_provider_specs = [
        (f"market.bars.raw.{provider}", 1, _BUFFER_MS, "delete") for provider in providers
    ]
    # Insert raw provider topics immediately after market.bars.htf
    insert_after = next(i for i, t in enumerate(_TOPIC_SPECS) if t[0] == "market.bars.htf")
    return _TOPIC_SPECS[: insert_after + 1] + raw_provider_specs + _TOPIC_SPECS[insert_after + 1 :]
