"""Unit tests for fetch_htf_bars script."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest


def _make_1m_bar(symbol="ES", ts=None, o=5100.0, h=5102.0, lo=5098.0, c=5101.0, v=500):
    return {
        "symbol": symbol,
        "ts": (ts or datetime(2026, 4, 9, 14, 0, tzinfo=UTC)).isoformat(),
        "tf": "1m",
        "open": o,
        "high": h,
        "low": lo,
        "close": c,
        "volume": v,
        "session_type": "rth",
    }


class TestBackfillHtfBarsScript:
    def test_build_bar_message_from_row(self):
        """Query row dict → BarMessage parses correctly."""
        from scripts.infrastructure.backfill.infrastructure_fetch_htf_bars import (
            _row_to_bar_message,
        )
        from src.core.schemas.bar_message import BarMessage

        row = _make_1m_bar()
        msg = _row_to_bar_message(row)
        assert isinstance(msg, BarMessage)
        assert msg.symbol == "ES"
        assert msg.tf == "1m"

    def test_accumulator_receives_bars_in_order(self):
        """Bars fed in ts order produce HTF bars at period boundaries."""
        from scripts.infrastructure.backfill.infrastructure_fetch_htf_bars import _replay_bars
        from src.core.bar_accumulator import BarAccumulator

        acc = BarAccumulator()
        # 6 bars: 14:00-14:05. The 6th bar (14:05) crosses the 5m boundary,
        # triggering emission of the accumulated 14:00-14:04 window.
        bars = [_make_1m_bar(ts=datetime(2026, 4, 9, 14, i, tzinfo=UTC)) for i in range(6)]
        htf_bars = _replay_bars(acc, bars, tf_targets=("5m",))
        # 6 bars spanning one 5m boundary should produce exactly one 5m bar
        assert len([b for b in htf_bars if b.tf == "5m"]) == 1

    @pytest.mark.asyncio
    async def test_publish_calls_producer_publish(self):
        """Each completed HTF bar is published to the htf topic."""
        from scripts.infrastructure.backfill.infrastructure_fetch_htf_bars import _publish_htf_bars
        from src.core.schemas.bar_message import BarMessage

        producer = AsyncMock()
        producer.publish = AsyncMock()

        fake_bars = [
            BarMessage(
                symbol="ES",
                tf="5m",
                ts=datetime(2026, 4, 9, 14, 5, tzinfo=UTC),
                open=5100.0,
                high=5105.0,
                low=5098.0,
                close=5102.0,
                volume=2500,
                session_type="rth",
                source="ibkr_named",
            )
        ]
        await _publish_htf_bars(producer, fake_bars, topic="dev.market.bars.htf")
        producer.publish.assert_awaited_once()
