from datetime import UTC, datetime

import pytest

from src.providers.base import DataProvider, OHLCVBar, Tick


class TestTick:
    def test_minimal_tick(self):
        tick = Tick(
            symbol="ESH6",
            timestamp=datetime(2026, 2, 21, 10, 0, tzinfo=UTC),
            price=5100.25,
            source="ibkr",
        )
        assert tick.symbol == "ESH6"
        assert tick.bid is None
        assert tick.ask is None

    def test_full_tick(self):
        tick = Tick(
            symbol="ESH6",
            timestamp=datetime(2026, 2, 21, 10, 0, tzinfo=UTC),
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
            timestamp=datetime(2026, 2, 21, 10, 0, tzinfo=UTC),
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

        class MinimalProvider:
            name = "test"

            async def connect(self) -> bool:
                return True

            async def disconnect(self) -> None:
                pass

            def is_connected(self) -> bool:
                return True

            async def resolve_instrument(self, query: str):
                return None

            async def stream_ticks(self, symbols): ...
            async def fetch_historical_bars(self, symbol, timeframe, start, end):
                return []

        assert isinstance(MinimalProvider(), DataProvider)


from src.providers.base import SubscriptionLimitError, SubscriptionManager


class TestSubscriptionManager:
    def test_subscribe_increments_count(self):
        mgr = SubscriptionManager("test_provider", max_subscriptions=10)
        mgr.subscribe("AAPL")
        assert mgr.count == 1

    def test_subscribe_twice_same_symbol_no_duplicate(self):
        mgr = SubscriptionManager("test_provider", max_subscriptions=10)
        mgr.subscribe("AAPL")
        mgr.subscribe("AAPL")  # set semantics — no duplicate
        assert mgr.count == 1

    def test_unsubscribe_decrements_count(self):
        mgr = SubscriptionManager("test_provider", max_subscriptions=10)
        mgr.subscribe("AAPL")
        mgr.unsubscribe("AAPL")
        assert mgr.count == 0

    def test_unsubscribe_unknown_symbol_no_error(self):
        mgr = SubscriptionManager("test_provider", max_subscriptions=10)
        mgr.unsubscribe("UNKNOWN")  # discard — no exception
        assert mgr.count == 0

    def test_raises_when_limit_reached(self):
        mgr = SubscriptionManager("test_provider", max_subscriptions=2)
        mgr.subscribe("AAPL")
        mgr.subscribe("MSFT")
        with pytest.raises(SubscriptionLimitError, match="test_provider"):
            mgr.subscribe("GOOG")

    def test_error_message_contains_symbol(self):
        mgr = SubscriptionManager("ibkr", max_subscriptions=1)
        mgr.subscribe("SPY")
        with pytest.raises(SubscriptionLimitError, match="AAPL"):
            mgr.subscribe("AAPL")

    def test_after_unsubscribe_can_subscribe_again(self):
        mgr = SubscriptionManager("test_provider", max_subscriptions=2)
        mgr.subscribe("AAPL")
        mgr.subscribe("MSFT")
        mgr.unsubscribe("AAPL")
        mgr.subscribe("GOOG")  # should succeed — count is 2 again
        assert mgr.count == 2
