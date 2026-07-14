"""Integration test for the north-star invariant: all v1 signals resolved.

Tests that after seeding N v1 signals with known OHLCV data and running
signal replay, all signals are resolved (exit_at IS NOT NULL). This proves
the two-path system (live tracker + replay auditor) produces complete
outcome labels for ML training.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import pytest

from services.signal_replay_auditor import SignalReplayAuditor
from src.config.settings import get_settings

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.skip(reason="v2.x Signal Ledger Architecture, archived, no live consumer (CLAUDE.md)")
async def test_all_signals_resolved():
    """North star test: seed signals + OHLCV, run replay, assert all resolved.

    This is the end-to-end proof that the replay system correctly recovers
    outcomes for signals the live tracker missed (e.g., due to restart).
    """

    settings = get_settings()
    conn: asyncpg.Connection = await asyncpg.connect(settings.database_url)

    # Unique signal_id prefix to avoid collision with live data
    signal_prefix = f"p81-test-resolved-{uuid4()}"

    # Timestamp for seeded signals (1 hour ago, so TTL has elapsed)
    signal_timestamp = datetime.now(UTC) - timedelta(hours=1)
    ttl_bars = 10
    timeframe = "1m"

    # Seed N=20 v1 signals
    n_signals = 20
    signal_ids = []

    try:
        # Clean up any existing test data with this prefix
        await conn.execute(
            "DELETE FROM signal_ledger WHERE signal_id LIKE $1",
            f"{signal_prefix}%",
        )

        # Insert 20 pending v1 signals
        for i in range(n_signals):
            signal_id = f"{signal_prefix}-{i:03d}"
            signal_ids.append(signal_id)

            # Alternate direction to test both long and short
            direction = 1 if i % 2 == 0 else -1
            entry_price = 4000.0 + (i * 10)

            await conn.execute(
                """
                INSERT INTO signal_ledger (
                    signal_id, symbol, timeframe, timestamp, entry_price, stop_loss,
                    direction, targets, status, ttl_bars,
                    exit_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NULL)
                """,
                signal_id,
                "ES",
                timeframe,
                signal_timestamp,
                entry_price,
                entry_price - (20 * direction),  # Stop loss 20 points away
                direction,
                [entry_price + (20 * direction), entry_price + (40 * direction)],
                "pending",
                ttl_bars,
            )

        # Seed OHLCV bars covering each signal's [T, T+10min] window
        # Engineered prices: all hit stop_loss (outcome = stopped_in_trade)
        for minute_offset in range(ttl_bars + 2):  # 0-11 minutes
            bar_ts = signal_timestamp + timedelta(minutes=minute_offset)

            for i in range(n_signals):
                direction = 1 if i % 2 == 0 else -1
                entry_price = 4000.0 + (i * 10)
                stop_price = entry_price - (20 * direction)

                # Bar OHLC: move toward stop, hitting it at minute 5
                if minute_offset < 5:
                    # Before stop hit: price moves toward stop
                    close = entry_price - (4 * direction * minute_offset)
                else:
                    # After stop hit: price continues past stop
                    close = stop_price - (2 * direction * (minute_offset - 5))

                high = max(entry_price, close) + 1
                low = min(close, stop_price) - 1
                open_price = close - (1 if direction > 0 else -1)

                await conn.execute(
                    """
                    INSERT INTO market_data_ohlcv (
                        timestamp, symbol, timeframe, open, high, low, close, volume, source
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    bar_ts,
                    "ES",
                    timeframe,
                    open_price,
                    high,
                    low,
                    close,
                    1000 + minute_offset,  # Volume
                    "test",
                )

        # Run one replay cycle
        agent = SignalReplayAuditor()
        await agent._setup()
        try:
            # Run single replay cycle
            await agent._cycle()
        finally:
            await agent._teardown()

        # Wait briefly for LifecycleWriter to apply transitions
        await asyncio.sleep(2)

        # Assert: zero unresolved v1 signals (north star invariant)
        unresolved_count = await conn.fetchval(
            """
            SELECT COUNT(*)
              FROM signal_ledger
             WHERE exit_at IS NULL
               AND entry_zone_low IS NOT NULL
               AND timestamp < NOW() - INTERVAL '2 minutes'
               AND signal_id LIKE $1
            """,
            f"{signal_prefix}%",
        )

        assert unresolved_count == 0, (
            f"North star invariant violated: {unresolved_count} v1 signals "
            f"still unresolved after replay"
        )

        # Verify all seeded signals have terminal outcomes
        resolved_with_outcome = await conn.fetchval(
            """
            SELECT COUNT(*)
              FROM signal_ledger
             WHERE signal_id LIKE $1
               AND outcome IS NOT NULL
               AND exit_at IS NOT NULL
            """,
            f"{signal_prefix}%",
        )

        assert (
            resolved_with_outcome == n_signals
        ), f"Expected {n_signals} resolved signals, got {resolved_with_outcome}"

    finally:
        # Cleanup all seeded rows
        await conn.execute(
            "DELETE FROM signal_ledger WHERE signal_id LIKE $1",
            f"{signal_prefix}%",
        )
        await conn.execute(
            "DELETE FROM market_data_ohlcv WHERE timestamp = $1 AND symbol = 'ES' AND timeframe = $2",
            signal_timestamp,
            timeframe,
        )
        await conn.close()
