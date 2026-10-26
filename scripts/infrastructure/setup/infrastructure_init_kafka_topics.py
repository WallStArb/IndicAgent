#!/usr/bin/env python3
"""
infrastructure_init_kafka_topics.py — canonical Kafka topic specifications for IndicAgent pipeline

Defines topic suffixes, partition counts, retention policies, and cleanup rules;
provides get_topic_specs() helper for topic creation and retention enforcement.
Retention tiers: buffer (1d), htf (3d), compact (infinite). DLQ topics are created, at 7 days,
by infrastructure_ensure_topics.sh, the one owner of the DLQ list and its retention.
Imported by infrastructure_enforce_topic_retention.py and pipeline reset scripts.
No standalone execution — module-only specification library.
"""

# ---------------------------------------------------------------------------
# Retention tiers (milliseconds)
# ---------------------------------------------------------------------------
_BUFFER_MS: int = 86_400_000  # 1 day   — standard restart catch-up
_HTF_MS: int = 259_200_000  # 3 days  — HTF bar accumulation window

# ---------------------------------------------------------------------------
# Topic specifications
# ---------------------------------------------------------------------------
# (suffix, num_partitions, retention_ms, cleanup_policy)
_TOPIC_SPECS: list[tuple[str, int, int, str]] = [
    # --- Market data ---
    ("market.bars", 1, _BUFFER_MS, "delete"),
    ("market.bars.htf", 1, _HTF_MS, "delete"),
    # market.bars.raw.<provider> entries are added dynamically via get_topic_specs()
    ("market.events.gap_requests", 1, _BUFFER_MS, "delete"),
    ("market.data.quality", 1, _BUFFER_MS, "delete"),
    # --- Read by the dashboard SSE route; kept until todo 509 item 2 decides that surface ---
    ("intelligence", 1, _BUFFER_MS, "delete"),
    ("intelligence.journal", 1, _BUFFER_MS, "delete"),
    ("signals.aggregated", 1, _BUFFER_MS, "delete"),
    # --- Cross-asset (published by cross_asset_analyzer) ---
    ("cross_asset", 1, _BUFFER_MS, "delete"),
    # --- Macro factors (persisted by macro_compute_agent → macro_features) ---
    ("macro_signals", 1, _BUFFER_MS, "delete"),
    # --- System ---
    ("system.events", 1, _BUFFER_MS, "delete"),
    ("system.health.events", 1, _BUFFER_MS, "delete"),
    # --- Alerting ---
    ("alert.requests", 1, _BUFFER_MS, "delete"),
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
