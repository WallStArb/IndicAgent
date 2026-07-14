"""Integration test for is_backfill roundtrip from publisher to database.

Tests that when a signal is published with is_backfill=True (computed by the
publisher when bar_ts is more than tf_seconds in the past), the is_backfill
flag is correctly persisted to signal_ledger and excluded from ML training queries.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from aiokafka import AIOKafkaProducer

from src.config.settings import get_settings
from src.core.stream_keys import topic_intelligence_i7_signals

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.skip(reason="v2.x Signal Ledger Architecture, archived, no live consumer (CLAUDE.md)")
async def test_is_backfill_roundtrip():
    """Test that is_backfill=True signal persists correctly and is excluded from ML filter."""

    settings = get_settings()

    # Connect to database
    conn: asyncpg.Connection = await asyncpg.connect(settings.database_url)

    # Unique test signal_id
    test_signal_id = "p81-test-backfill-roundtrip-001"

    # Use old bar timestamp to trigger is_backfill=True in publisher
    # For 1m timeframe, any bar > 60 seconds in the past should be backfill
    old_bar_ts = datetime.now(UTC) - timedelta(hours=2)

    try:
        # Clean up any existing test data
        await conn.execute(
            "DELETE FROM signal_ledger WHERE signal_id = $1",
            test_signal_id,
        )

        # Publish signal payload through Kafka
        producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            client_id="test_backfill_producer",
        )
        await producer.start()

        # Signal payload with old timestamp (publisher computes is_backfill=True)
        signal_payload = {
            "signal_id": test_signal_id,
            "symbol": "ES",
            "timeframe": "1m",
            "timestamp": old_bar_ts.isoformat(),
            "entry_price": 4000.0,
            "stop_loss": 3980.0,
            "targets": [4020.0, 4040.0],
            "direction": 1,
            "setup_plugin": "MomentumBreakout",
            "regime_eligible": True,
            "confidence": 0.75,
            "composite_rank": 0.8,
            "adjusted_rank": 0.85,
            "ttl_bars": 10,
            "is_backfill": True,  # Explicitly set for test (publisher would compute this)
            "status": "pending",
            "exit_at": None,
            "activated_at": None,
        }

        # Publish to intelligence.i7.signals topic
        topic = topic_intelligence_i7_signals(settings.env_name)
        await producer.send_and_wait(
            topic,
            key=test_signal_id.encode(),
            value=signal_payload,
        )
        await producer.stop()

        # Wait for downstream writer to persist (poll with retry/backoff up to 30s)
        max_wait = timedelta(seconds=30)
        poll_interval = timedelta(seconds=0.5)
        start = datetime.now(UTC)

        row = None
        while (datetime.now(UTC) - start) < max_wait:
            row = await conn.fetchrow(
                "SELECT is_backfill FROM signal_ledger WHERE signal_id = $1",
                test_signal_id,
            )
            if row is not None:
                break
            await asyncio.sleep(poll_interval.total_seconds())

        assert row is not None, "Signal was not persisted within 30 seconds"

        # Assert is_backfill is True
        assert row["is_backfill"] is True, f"Expected is_backfill=True, got {row['is_backfill']}"

        # Run ML filter query: is_backfill signals should be excluded
        ml_training_count = await conn.fetchval(
            """
            SELECT COUNT(*)
              FROM signal_ledger
             WHERE signal_id = $1
               AND is_backfill = FALSE
            """,
            test_signal_id,
        )

        # Assert 0 rows returned (correctly excluded from ML training set)
        assert ml_training_count == 0, (
            f"is_backfill=True signals should be excluded from ML filter; "
            f"found {ml_training_count} rows"
        )

    finally:
        # Cleanup
        await conn.execute(
            "DELETE FROM signal_ledger WHERE signal_id = $1",
            test_signal_id,
        )
        await conn.close()
