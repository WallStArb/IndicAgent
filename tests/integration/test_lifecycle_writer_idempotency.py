"""Integration test for lifecycle writer idempotency.

Tests that two EXIT transitions for the same signal result in only the first
being written to the database. The second is a no-op due to the WHERE exit_at IS NULL
guard, and increments the LIFECYCLE_WRITER_IDEMPOTENT_SKIP_TOTAL counter.
"""

from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from src.config.settings import get_settings
from src.observability.metrics import LIFECYCLE_WRITER_IDEMPOTENT_SKIP_TOTAL

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.skip(reason="v2.x Signal Ledger Architecture, archived, no live consumer (CLAUDE.md)")
async def test_lifecycle_writer_idempotency_counter():
    """Test that second EXIT write is idempotent (no-op) and increments counter."""

    # Connect to database
    settings = get_settings()
    conn: asyncpg.Connection = await asyncpg.connect(settings.database_url)

    # Unique test signal_id to avoid collision
    test_signal_id = "p81-test-lifecycle-idempotency-001"

    try:
        # Clean up any existing test data
        await conn.execute(
            "DELETE FROM signal_ledger WHERE signal_id = $1",
            test_signal_id,
        )

        # Insert a v1 signal with exit_at=NULL (pending signal)
        timestamp = datetime.now(UTC) - timedelta(hours=1)
        await conn.execute(
            """
            INSERT INTO signal_ledger (
                signal_id, symbol, timeframe, timestamp, entry_price, stop_loss,
                direction, status, exit_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NULL)
            """,
            test_signal_id,
            "ES",
            "1m",
            timestamp,
            4000.0,
            3980.0,
            1,
            "active",
        )

        # Capture baseline counter value
        baseline_skip_count = LIFECYCLE_WRITER_IDEMPOTENT_SKIP_TOTAL._value.get()

        # First EXIT write
        first_exit_at = datetime.now(UTC)
        result1: str = await conn.execute(
            """
            UPDATE signal_ledger
               SET status = $1,
                   exit_at = $2,
                   exit_price = $3,
                   exit_reason = $4,
                   outcome = $5,
                   pnl_r = $6
             WHERE signal_id = $7
               AND exit_at IS NULL
            """,
            "stopped_in_trade",
            first_exit_at,
            3990.0,
            "stop_loss",
            "stopped_in_trade",
            -0.0025,
            test_signal_id,
        )

        # Assert first write succeeded (UPDATE 1)
        assert result1.endswith(" 1"), f"First write should succeed, got: {result1}"

        # Verify row now has exit_at set
        row = await conn.fetchrow(
            "SELECT exit_at, outcome, pnl_r FROM signal_ledger WHERE signal_id = $1",
            test_signal_id,
        )
        assert row["exit_at"] is not None
        assert row["outcome"] == "stopped_in_trade"
        assert row["pnl_r"] == -0.0025

        # Second EXIT write with different terminal values
        second_exit_at = datetime.now(UTC) + timedelta(seconds=1)
        result2: str = await conn.execute(
            """
            UPDATE signal_ledger
               SET status = $1,
                   exit_at = $2,
                   exit_price = $3,
                   exit_reason = $4,
                   outcome = $5,
                   pnl_r = $6
             WHERE signal_id = $7
               AND exit_at IS NULL
            """,
            "target_full",
            second_exit_at,
            4020.0,
            "target_hit",
            "target_full",
            0.0050,
            test_signal_id,
        )

        # Assert second write was no-op (UPDATE 0)
        assert result2.endswith(" 0"), f"Second write should be no-op, got: {result2}"

        # Verify row UNCHANGED from first write
        row2 = await conn.fetchrow(
            "SELECT exit_at, outcome, pnl_r FROM signal_ledger WHERE signal_id = $1",
            test_signal_id,
        )
        assert row2["exit_at"] == first_exit_at  # Still first exit_at
        assert row2["outcome"] == "stopped_in_trade"  # Still first outcome
        assert row2["pnl_r"] == -0.0025  # Still first pnl_r

        # Assert counter incremented by exactly 1
        skip_count = LIFECYCLE_WRITER_IDEMPOTENT_SKIP_TOTAL._value.get()
        assert skip_count == baseline_skip_count + 1, (
            f"Counter should increment by 1: baseline={baseline_skip_count}, "
            f"current={skip_count}"
        )

    finally:
        # Cleanup: DELETE test row
        await conn.execute(
            "DELETE FROM signal_ledger WHERE signal_id = $1",
            test_signal_id,
        )
        await conn.close()
