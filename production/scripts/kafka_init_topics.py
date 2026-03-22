"""
Kafka topic initialisation script for IndicAgent.

Version: 1.0.0
Last Updated: 2026-03-14
Status: Current ✅

Creates all 24 Redpanda/Kafka topics idempotently. Run once at startup (or
whenever a new environment is provisioned). Topic names are prefixed by
env_name (e.g. "dev.market.ticks" for env_name="dev"; "market.ticks" for
env_name="" in production).

Usage:
    python -m production.scripts.kafka_init_topics [env_name]

    env_name defaults to "dev" when not provided.

Retention periods:
    - High-volume enrichment (i7/i8): 1 day (86400000 ms)
    - All other topics: 7 days (604800000 ms)
"""

from __future__ import annotations

import asyncio
import sys

from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError

# (suffix, partitions, retention_ms)
_TOPIC_SPECS = [
    ("market.ticks", 1, "604800000"),
    ("market.bars", 1, "604800000"),
    ("market.bars.htf", 1, "604800000"),
    ("indicators", 1, "604800000"),
    ("intelligence", 1, "604800000"),
    ("intelligence.i7", 1, "86400000"),
    ("intelligence.i8", 1, "86400000"),
    ("signals", 1, "604800000"),
    ("signals.aggregated", 1, "604800000"),
    ("narratives", 1, "604800000"),
    ("narratives.group", 1, "604800000"),
    ("llm.calls", 1, "86400000"),
    ("llm.outcomes", 1, "86400000"),
    ("system.events", 1, "604800000"),
    ("cross_asset", 1, "604800000"),
    ("pipeline.attribution", 1, "604800000"),
    ("pipeline.quality_gated", 1, "604800000"),
    ("pipeline.regime_gated", 1, "604800000"),
    ("pipeline.tod_adjusted", 1, "604800000"),
    ("pipeline.calibrated", 1, "604800000"),
    ("pipeline.ranked", 1, "604800000"),
    ("pipeline.winner", 1, "604800000"),
    ("pipeline.data_quality", 1, "604800000"),
    ("intelligence.record", 1, "604800000"),
]


async def create_topics(bootstrap_servers: str, env_name: str = "dev") -> None:
    """Create all 24 IndicAgent topics idempotently.

    Args:
        bootstrap_servers: Kafka/Redpanda bootstrap address (e.g. "localhost:19092").
        env_name: Environment name used as topic prefix (e.g. "dev"). Pass "" for no prefix.
    """
    prefix = f"{env_name}." if env_name else ""
    new_topics = [
        NewTopic(
            name=f"{prefix}{suffix}",
            num_partitions=partitions,
            replication_factor=1,
            topic_configs={"retention.ms": retention_ms},
        )
        for suffix, partitions, retention_ms in _TOPIC_SPECS
    ]

    client = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    await client.start()
    try:
        # Create topics one-by-one so a pre-existing topic doesn't silently
        # prevent new topics from being created (batch failure is all-or-nothing).
        for topic in new_topics:
            try:
                await client.create_topics([topic])
            except TopicAlreadyExistsError:
                pass
            except Exception as e:
                if "already exists" in str(e).lower():
                    pass
                else:
                    raise
    finally:
        await client.close()


if __name__ == "__main__":
    env_name = sys.argv[1] if len(sys.argv) > 1 else "dev"
    bootstrap = "localhost:19092"
    asyncio.run(create_topics(bootstrap, env_name=env_name))
