import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.bar_normalizer import SOURCE_IBKR_NAMED
from src.providers import ibkr as ibkr_module
from src.providers.base import DataProvider
from src.providers.ibkr import IBKRProvider


@pytest.fixture
def mock_ib():
    """Mock ib_async.IB instance."""
    ib = MagicMock()
    ib.isConnected.return_value = True
    ib.pendingTickersEvent = MagicMock()
    return ib


@pytest.fixture
def provider():
    return IBKRProvider(host="127.0.0.1", port=7497, client_id=1)


class TestIBKRProviderProtocol:
    def test_satisfies_data_provider_protocol(self, provider):
        assert isinstance(provider, DataProvider)

    def test_name(self, provider):
        assert provider.name == "ibkr"


class TestConnect:
    @pytest.mark.asyncio
    async def test_connect_success(self, provider, mock_ib):
        with patch("src.providers.ibkr.IB", return_value=mock_ib):
            mock_ib.connectAsync = AsyncMock(return_value=None)
            mock_ib.isConnected.return_value = True
            result = await provider.connect()
        assert result is True
        assert provider.is_connected()

    @pytest.mark.asyncio
    async def test_connect_failure_returns_false(self, provider, mock_ib):
        with patch("src.providers.ibkr.IB", return_value=mock_ib):
            mock_ib.connect.side_effect = Exception("connection refused")
            result = await provider.connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect_calls_ib_disconnect(self, provider, mock_ib):
        provider._ib = mock_ib
        await provider.disconnect()
        mock_ib.disconnect.assert_called_once()

    def test_is_connected_false_before_connect(self, provider):
        assert provider.is_connected() is False


class TestFetchHistoricalBars:
    @pytest.mark.asyncio
    async def test_returns_ohlcv_bars(self, provider, mock_ib):
        """fetch_historical_bars maps ib_async BarData to OHLCVBar list."""

        mock_bar = MagicMock()
        mock_bar.date = datetime(2026, 2, 1, 9, 30, tzinfo=UTC)
        mock_bar.open = 5100.0
        mock_bar.high = 5105.0
        mock_bar.low = 5098.0
        mock_bar.close = 5102.0
        mock_bar.volume = 1500

        mock_ib.reqHistoricalDataAsync = AsyncMock(return_value=[mock_bar])
        provider._ib = mock_ib

        mock_contract = MagicMock()
        provider._qualified_contracts["ESH6"] = mock_contract

        bars = await provider.fetch_historical_bars(
            symbol="ESH6",
            timeframe="1m",
            start=datetime(2026, 2, 1, tzinfo=UTC),
            end=datetime(2026, 2, 2, tzinfo=UTC),
        )

        assert len(bars) == 1
        assert bars[0].symbol == "ESH6"
        assert bars[0].timeframe == "1m"
        assert bars[0].open == 5100.0
        assert bars[0].high == 5105.0
        assert bars[0].source == SOURCE_IBKR_NAMED

    @pytest.mark.asyncio
    async def test_unknown_timeframe_raises(self, provider, mock_ib):
        provider._ib = mock_ib
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            await provider.fetch_historical_bars(
                "ESH6", "3m", datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 2, 2, tzinfo=UTC)
            )

    @pytest.mark.asyncio
    async def test_returns_empty_on_no_data(self, provider, mock_ib):
        """A bare empty return (no matching reqId in _no_data_req_ids) is treated as
        an AMBIGUOUS result, not a confirmed no-data signal -- it falls through to
        the real 65s/130s exponential-backoff retry path (see F3 2026-07-05 /
        test_two_consecutive_no_data_chunks_aborts_backfill's comment below for the
        full mechanics). A plain `[]` mock here previously made this "returns empty"
        test spend ~195s in real asyncio.sleep() before its assertion ever ran.
        Registering the reqId in _no_data_req_ids simulates the confirmed-no-data
        signal so the fast path fires instead, matching how the codebase's other
        no-data tests are already written.
        """
        from ib_async import BarDataList

        ibkr_module._no_data_req_ids.clear()
        req_id = 90200

        async def fake_req(*args, **kwargs):
            ibkr_module._no_data_req_ids.add(req_id)
            bars = BarDataList()
            bars.reqId = req_id
            return bars

        mock_ib.reqHistoricalDataAsync = AsyncMock(side_effect=fake_req)
        provider._ib = mock_ib
        provider._qualified_contracts["ESH6"] = MagicMock()
        bars = await provider.fetch_historical_bars(
            "ESH6",
            "1m",
            datetime(2026, 2, 1, tzinfo=UTC),
            datetime(2026, 2, 2, tzinfo=UTC),
        )
        assert bars == []
        ibkr_module._no_data_req_ids.clear()

    @pytest.mark.asyncio
    async def test_single_no_data_chunk_does_not_abort_backfill(self, provider, mock_ib):
        """A single confirmed Error 162 chunk must not truncate the walk (todo 049):
        it can be a transient pacing/permission hiccup, not proof of a pre-listing date.

        The confirmed-no-data fast path only fires when the returned result's own
        .reqId matches an entry in _no_data_req_ids -- a bare `[]` (no .reqId
        attribute, getattr(..., "reqId", None) is always None) never matches,
        which silently falls through to the AMBIGUOUS-result retry path (real
        65s/130s asyncio.sleep() backoff) instead of the fast no-data break this
        test means to exercise. Previously passed anyway (retry attempt 2 happens
        to return real_bar, satisfying the assertions) but only after ~65s of real
        sleep, and without ever actually exercising todo 049's fast-path logic.
        """
        ibkr_module._no_data_req_ids.clear()
        real_bar = MagicMock()
        real_bar.date = datetime(2026, 1, 10, 9, 30, tzinfo=UTC)
        real_bar.open, real_bar.high, real_bar.low, real_bar.close, real_bar.volume = (
            100.0,
            101.0,
            99.0,
            100.5,
            1000,
        )
        calls = {"n": 0}

        async def fake_req(*args, **kwargs):
            from ib_async import BarDataList

            calls["n"] += 1
            if calls["n"] == 1:
                req_id = 90000 + calls["n"]
                ibkr_module._no_data_req_ids.add(req_id)
                no_data = BarDataList()
                no_data.reqId = req_id
                return no_data
            return [real_bar]

        mock_ib.reqHistoricalDataAsync = AsyncMock(side_effect=fake_req)
        provider._ib = mock_ib
        provider._qualified_contracts["ESH6"] = MagicMock()

        bars = await provider.fetch_historical_bars(
            "ESH6",
            "1m",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 25, tzinfo=UTC),  # 24 days -> multiple 6-day chunks
        )

        assert calls["n"] >= 2, "walk must continue past a single no-data chunk"
        assert len(bars) >= 1
        ibkr_module._no_data_req_ids.clear()

    @pytest.mark.asyncio
    async def test_two_consecutive_no_data_chunks_aborts_backfill(self, provider, mock_ib):
        """Two CONSECUTIVE confirmed Error 162 chunks are strong enough evidence to
        stop the backward walk (todo 049 confirmation threshold)."""
        # Local import: src.providers.ibkr (imported at module level above) applies
        # a Python 3.14 event-loop workaround before eventkit/ib_async get pulled
        # in transitively -- importing ib_async directly at module level here,
        # ahead of that workaround, would trip the same failure.
        from ib_async import BarDataList

        ibkr_module._no_data_req_ids.clear()
        calls = {"n": 0}

        async def fake_req(*args, **kwargs):
            # Real ib_async.reqHistoricalDataAsync always returns a BarDataList
            # with .reqId set (even when empty) -- see F3 2026-07-05: the provider
            # now matches Error 162 callbacks to this exact reqId instead of a
            # global snapshot-diff, so the mock must carry a real reqId for the
            # no-data detection path to fire (otherwise it falls through to real
            # 65s/130s backoff sleeps instead of the fast no-data abort this test
            # is meant to verify).
            calls["n"] += 1
            req_id = 90100 + calls["n"]
            ibkr_module._no_data_req_ids.add(req_id)
            bars = BarDataList()
            bars.reqId = req_id
            return bars

        mock_ib.reqHistoricalDataAsync = AsyncMock(side_effect=fake_req)
        provider._ib = mock_ib
        provider._qualified_contracts["ESH6"] = MagicMock()

        bars = await provider.fetch_historical_bars(
            "ESH6",
            "1m",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 25, tzinfo=UTC),
        )

        assert bars == []
        assert calls["n"] == 2, "must stop after exactly 2 consecutive no-data chunks"
        ibkr_module._no_data_req_ids.clear()


class TestStreamTicks:
    @pytest.mark.asyncio
    async def test_stream_ticks_yields_normalized_ticks(self, provider, mock_ib):
        """Ticks pushed to the queue appear in the async iterator."""
        provider._ib = mock_ib
        provider._qualified_contracts["ESH6"] = MagicMock()

        mock_ticker = MagicMock()
        mock_ticker.contract.localSymbol = "ESH6"
        mock_ticker.last = 5100.25
        mock_ticker.lastSize = 2
        mock_ticker.bid = 5100.0
        mock_ticker.ask = 5100.5
        mock_ticker.bidSize = 10
        mock_ticker.askSize = 15

        collected = []

        async def collect_one():
            async for tick in provider.stream_ticks(["ESH6"]):
                collected.append(tick)
                break  # stop after first tick

        task = asyncio.create_task(collect_one())
        await asyncio.sleep(0)  # let stream_ticks initialize queue + loop

        # Simulate ib_async callback firing
        provider._handle_pending_tickers([mock_ticker])
        await asyncio.wait_for(task, timeout=2.0)

        assert len(collected) == 1
        assert collected[0].symbol == "ESH6"
        assert collected[0].price == 5100.25
        assert collected[0].source == "ibkr"

    @pytest.mark.asyncio
    async def test_normalize_ticker_skips_zero_price(self, provider):
        mock_ticker = MagicMock()
        mock_ticker.contract.localSymbol = "ESH6"
        mock_ticker.last = 0.0
        mock_ticker.bid = None
        mock_ticker.ask = None
        tick = provider._normalize_ticker(mock_ticker)
        assert tick is None


class TestResolveInstrument:
    @pytest.mark.asyncio
    async def test_resolves_futures_contract(self, provider, mock_ib):
        from src.core.models import AssetClass

        mock_detail = MagicMock()
        mock_detail.contract.localSymbol = "ESH6"
        mock_detail.longName = "E-mini S&P 500"
        mock_detail.contract.exchange = "CME"
        mock_detail.contract.symbol = "ES"
        mock_detail.contract.lastTradeDateOrContractMonth = "20260320"
        mock_detail.minTick = 0.25
        mock_detail.contract.multiplier = "50"

        mock_ib.reqContractDetailsAsync = AsyncMock(return_value=[mock_detail])
        provider._ib = mock_ib

        instrument = await provider.resolve_instrument("ES")

        assert instrument is not None
        assert instrument.symbol == "ESH6"
        assert instrument.asset_class == AssetClass.FUTURES
        assert instrument.tick_size == 0.25

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_symbol(self, provider, mock_ib):
        mock_ib.reqContractDetailsAsync = AsyncMock(return_value=[])
        provider._ib = mock_ib
        result = await provider.resolve_instrument("XXXXXX")
        assert result is None
