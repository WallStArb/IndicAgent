"""Integration test for market entry track completeness.

Tests that signals with market_entry_price set (i.e., activated signals)
get complete market_entry_outcome labels after replay. The market entry
track is independent of the zone track and must also be fully resolved.
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
async def test_market_entry_completeness():
    """Test that activated signals get complete market entry outcomes after replay."""

    settings = get_settings()
    conn: asyncpg.Connection = await asyncpg.connect(settings.database_url)

    # Unique signal_id prefix
    signal_prefix = f"p81-test-market-entry-{uuid4()}"

    # Timestamp for seeded signals (1 hour ago, TTL elapsed)
    signal_timestamp = datetime.now(UTC) - timedelta(hours=1)
    ttl_bars = 10
    timeframe = "1m"

    try:
        # Clean up any existing test data
        await conn.execute(
            "DELETE FROM signal_ledger WHERE signal_id LIKE $1",
            f"{signal_prefix}%",
        )

        # Seed signals with market_entry_price set (activated signals)
        n_signals = 10
        signal_ids = []

        for i in range(n_signals):
            signal_id = f"{signal_prefix}-{i:03d}"
            signal_ids.append(signal_id)

            direction = 1 if i % 2 == 0 else -1
            entry_price = 4000.0 + (i * 10)
            market_entry_price = entry_price + (5 * direction)  # Market entry 5 points away

            await conn.execute(
                """
                INSERT INTO signal_ledger (
                    signal_id, symbol, timeframe, timestamp, entry_price, stop_loss,
                    direction, targets, status, ttl_bars,
                    exit_at, market_entry_price, market_entry_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NULL, $11, $12)
                """,
                signal_id,
                "ES",
                timeframe,
                signal_timestamp,
                entry_price,
                entry_price - (20 * direction),
                direction,
                [entry_price + (20 * direction), entry_price + (40 * direction)],
                "active",
                ttl_bars,
                market_entry_price,
                signal_timestamp + timedelta(seconds=30),  # Activated 30s after fire
            )

        # Seed OHLCV bars to drive market entry track to known outcome
        # All signals hit their stop (market_entry_outcome = stopped_in_trade)
        for minute_offset in range(ttl_bars + 2):
            bar_ts = signal_timestamp + timedelta(minutes=minute_offset)

            for i in range(n_signals):
                direction = 1 if i % 2 == 0 else -1
                entry_price = 4000.0 + (i * 10)
                market_entry_price = entry_price + (5 * direction)
                stop_price = entry_price - (20 * direction)

                # Bar OHLC: from market_entry, move toward stop
                if minute_offset == 0:
                    # First bar: between entry and market_entry
                    close = entry_price + (2 * direction)
                elif minute_offset < 6:
                    # Bars 1-5: move from market_entry toward stop
                    close = market_entry_price - (3 * direction * minute_offset)
                else:
                    # After stop hit: continue past stop
                    close = stop_price - (2 * direction * (minute_offset - 6))

                high = max(market_entry_price, close) + 1
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
                    1000 + minute_offset,
                    "test",
                )

        # Run replay cycle
        agent = SignalReplayAuditor()
        await agent._setup()
        try:
            await agent._cycle()
        finally:
            await agent._teardown()

        # Wait for LifecycleWriter to apply transitions
        await asyncio.sleep(2)

        # Assert: every seeded signal has market_entry_outcome IS NOT NULL
        signals_without_outcome = await conn.fetchval(
            """
            SELECT COUNT(*)
              FROM signal_ledger
             WHERE signal_id LIKE $1
               AND market_entry_price IS NOT NULL
               AND market_entry_outcome IS NULL
            """,
            f"{signal_prefix}%",
        )

        assert (
            signals_without_outcome == 0
        ), f"Expected 0 signals without market_entry_outcome, got {signals_without_outcome}"

        # Verify all signals have both zone and market entry outcomes
        complete_signals = await conn.fetchval(
            """
            SELECT COUNT(*)
              FROM signal_ledger
             WHERE signal_id LIKE $1
               AND outcome IS NOT NULL
               AND exit_at IS NOT NULL
               AND market_entry_outcome IS NOT NULL
            """,
            f"{signal_prefix}%",
        )

        assert (
            complete_signals == n_signals
        ), f"Expected {n_signals} complete signals, got {complete_signals}"

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
