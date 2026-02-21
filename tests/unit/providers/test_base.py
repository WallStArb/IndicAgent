import pytest
from datetime import datetime, timezone
from src.providers.base import Tick, OHLCVBar, DataProvider
from src.core.models import Instrument


class TestTick:
    def test_minimal_tick(self):
        tick = Tick(
            symbol="ESH6",
            timestamp=datetime(2026, 2, 21, 10, 0, tzinfo=timezone.utc),
            price=5100.25,
            source="ibkr",
        )
        assert tick.symbol == "ESH6"
        assert tick.bid is None
        assert tick.ask is None

    def test_full_tick(self):
        tick = Tick(
            symbol="ESH6",
            timestamp=datetime(2026, 2, 21, 10, 0, tzinfo=timezone.utc),
            price=5100.25,
            bid=5100.00,
            ask=5100.50,
            bid_size=10,
            ask_size=15,
            size=2,
            source="ibkr",
        )
        assert tick.bid == 5100.00
        assert tick.ask == 5100.50


class TestOHLCVBar:
    def test_bar_creation(self):
        bar = OHLCVBar(
            symbol="ESH6",
            timeframe="1m",
            timestamp=datetime(2026, 2, 21, 10, 0, tzinfo=timezone.utc),
            open=5100.0,
            high=5105.0,
            low=5098.0,
            close=5102.0,
            volume=1500,
            source="ibkr",
        )
        assert bar.timeframe == "1m"
        assert bar.high == 5105.0


class TestDataProviderProtocol:
    def test_protocol_is_runtime_checkable(self):
        # A class that doesn't implement the protocol should not be an instance
        class NotAProvider:
            pass
        assert not isinstance(NotAProvider(), DataProvider)

    def test_minimal_implementation_satisfies_protocol(self):
        from collections.abc import AsyncIterator

        class MinimalProvider:
            name = "test"
            async def connect(self) -> bool: return True
            async def disconnect(self) -> None: pass
            def is_connected(self) -> bool: return True
            async def resolve_instrument(self, query: str): return None
            async def stream_ticks(self, symbols): ...
            async def fetch_historical_bars(self, symbol, timeframe, start, end): return []

        assert isinstance(MinimalProvider(), DataProvider)
