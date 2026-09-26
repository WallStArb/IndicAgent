import asyncio
from datetime import UTC, datetime, timedelta
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

    @pytest.mark.asyncio
    async def test_chunk_over_365_days_uses_years_not_days(self, provider, mock_ib):
        """A chunk window over 365 days must format durationStr as 'N Y', not 'N D' --
        IBKR rejects day-unit durations past 365 days with Error 321 ("Historical data
        requests for durations longer than 365 days must be made in years"). The
        continuous-contract branch already handled this; the regular chunked branch
        (used by every real backfill) did not, because every prior _MAX_CHUNK_DAYS
        default stayed under 365 -- discovered 2026-08-06 via a chunk-size headroom
        probe that widened 1d to 1825 days."""
        from ib_async import BarDataList

        original_chunk_days = ibkr_module._MAX_CHUNK_DAYS["1d"]
        ibkr_module._MAX_CHUNK_DAYS["1d"] = 1825  # 5yr -- exercises the >365 branch
        captured_duration_strs: list[str] = []
        ibkr_module._no_data_req_ids.clear()
        calls = {"n": 0}

        async def fake_req(*args, **kwargs):
            # Must register the reqId in _no_data_req_ids before returning an empty
            # BarDataList -- see F3 2026-07-05 / the sibling no-data tests above:
            # without a matching reqId, the fast no-data-abort path never fires and
            # the retry loop falls through to real (unmocked) 65s/130s backoff sleeps,
            # taking ~10+ minutes to finish instead of running instantly.
            captured_duration_strs.append(kwargs["durationStr"])
            calls["n"] += 1
            req_id = 90200 + calls["n"]
            ibkr_module._no_data_req_ids.add(req_id)
            bars = BarDataList()
            bars.reqId = req_id
            return bars

        try:
            mock_ib.reqHistoricalDataAsync = AsyncMock(side_effect=fake_req)
            provider._ib = mock_ib
            provider._qualified_contracts["MSFT"] = MagicMock()

            await provider.fetch_historical_bars(
                "MSFT",
                "1d",
                datetime(2015, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 1, tzinfo=UTC),
            )
        finally:
            ibkr_module._MAX_CHUNK_DAYS["1d"] = original_chunk_days
            ibkr_module._no_data_req_ids.clear()

        assert captured_duration_strs, "no requests were made"
        for duration_str in captured_duration_strs:
            assert duration_str.endswith(" Y") or duration_str.endswith(" D"), duration_str
            if duration_str.endswith(" D"):
                days = int(duration_str.split()[0])
                assert days <= 365, f"day-unit duration must stay <=365 days, got {duration_str}"


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


class TestEmptyHistoryReport:
    """fetch_historical_bars(on_empty_history=) reports only a walk that ENDS in definitive
    Error 162 "no data" answers (migration 354's evidence). 1m chunks are 14 days."""

    @staticmethod
    def _bar(ts):
        bar = MagicMock()
        bar.date = ts
        bar.open, bar.high, bar.low, bar.close, bar.volume = 1.0, 1.0, 1.0, 1.0, 1
        return bar

    async def _walk(self, provider, mock_ib, answers, start, end):
        """answers: per-request 'data' | 'no_data' | 'timeout', newest chunk first."""
        from ib_async import BarDataList

        ibkr_module._no_data_req_ids.clear()
        calls = {"n": 0}

        async def fake_req(*args, **kwargs):
            answer = answers[calls["n"]]
            calls["n"] += 1
            if answer == "timeout":
                raise TimeoutError
            if answer == "data":
                return [self._bar(datetime(2026, 1, 20, tzinfo=UTC))]
            req_id = 91000 + calls["n"]
            ibkr_module._no_data_req_ids.add(req_id)
            result = BarDataList()
            result.reqId = req_id
            return result

        mock_ib.reqHistoricalDataAsync = AsyncMock(side_effect=fake_req)
        provider._ib = mock_ib
        provider._qualified_contracts["XYZ"] = MagicMock(secType="STK")
        reports = []
        with patch.object(ibkr_module, "_RETRY_COUNT", 1):
            await provider.fetch_historical_bars(
                "XYZ", "1m", start, end, on_empty_history=reports.append
            )
        ibkr_module._no_data_req_ids.clear()
        return reports, calls["n"]

    @pytest.mark.asyncio
    async def test_threshold_stop_reports_verified_span_and_inference(self, provider, mock_ib):
        start, end = datetime(2025, 11, 1, tzinfo=UTC), datetime(2026, 1, 25, tzinfo=UTC)
        reports, n = await self._walk(provider, mock_ib, ["no_data", "no_data"], start, end)
        assert n == 2
        (report,) = reports
        assert report.n_confirming_chunks == 2
        assert report.empty_through == end
        assert report.verified_from > start
        assert report.reached_request_start is False

    @pytest.mark.asyncio
    async def test_walk_reaching_start_in_no_data_is_fully_verified(self, provider, mock_ib):
        start, end = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 25, tzinfo=UTC)
        reports, n = await self._walk(provider, mock_ib, ["data", "no_data"], start, end)
        assert n == 2
        (report,) = reports
        assert report.n_confirming_chunks == 1
        assert report.verified_from == start
        assert report.empty_through < end
        assert report.reached_request_start is True

    @pytest.mark.asyncio
    async def test_walk_ending_in_data_reports_nothing(self, provider, mock_ib):
        start, end = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 25, tzinfo=UTC)
        reports, _ = await self._walk(provider, mock_ib, ["no_data", "data"], start, end)
        assert reports == []

    @pytest.mark.asyncio
    async def test_timeout_is_never_evidence_of_empty_history(self, provider, mock_ib):
        """A timed-out oldest chunk breaks the no-data run: nothing is reported."""
        start, end = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 25, tzinfo=UTC)
        reports, _ = await self._walk(provider, mock_ib, ["no_data", "timeout"], start, end)
        assert reports == []


def test_error_162_log_label_separates_no_data_from_throttling():
    """Both used to log as hist_pacing_error, which made a no-data answer look like
    throttling (the ODFL 2006-2024 window)."""
    ibkr_module._no_data_req_ids.clear()
    with patch.object(ibkr_module.logger, "warning") as warn:
        ibkr_module._on_ib_error(1, 162, "HMDS query returned no data: X@SMART Trades", None)
        ibkr_module._on_ib_error(2, 162, "API historical data query cancelled: 2", None)
    assert [c.args[0] for c in warn.call_args_list] == [
        "ibkr.hist_no_data",
        "ibkr.hist_pacing_error",
    ]
    assert ibkr_module._no_data_req_ids == {1}
    ibkr_module._no_data_req_ids.clear()


class TestGetHeadTimestamp:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("returned", "expected_head", "error_contains"),
        [
            (
                datetime(2024, 3, 27, 8, 0, tzinfo=UTC),
                datetime(2024, 3, 27, 8, 0, tzinfo=UTC),
                None,
            ),
            ("", None, "no head"),
            (RuntimeError("Query failed"), None, "Query failed"),
        ],
    )
    async def test_outcomes(self, provider, mock_ib, returned, expected_head, error_contains):
        if isinstance(returned, Exception):
            mock_ib.reqHeadTimeStampAsync = AsyncMock(side_effect=returned)
        else:
            mock_ib.reqHeadTimeStampAsync = AsyncMock(return_value=returned)
        provider._ib = mock_ib
        provider._qualified_contracts["GEV"] = MagicMock(secType="STK")
        head, error = await provider.get_head_timestamp("GEV")
        assert head == expected_head
        assert (error is None) if error_contains is None else (error_contains in error)
        if head is not None:
            assert mock_ib.reqHeadTimeStampAsync.call_args.kwargs["useRTH"] is False

    @pytest.mark.asyncio
    async def test_unqualified_symbol_is_no_floor(self, provider, mock_ib):
        provider._ib = mock_ib
        head, error = await provider.get_head_timestamp("NOPE")
        assert head is None and error


class TestPreMoveHistory:
    """1d fetches of a stock recover history from before a listing-venue move (todo 433):
    the SMART walk's uncovered head is asked of every candidate venue, and the venue with
    the most volume is kept under SOURCE_IBKR_VENUE."""

    START = datetime(2010, 1, 1, tzinfo=UTC)
    END = datetime(2026, 1, 30, tzinfo=UTC)

    @staticmethod
    def _bars(first, n, volume):
        out = []
        for i in range(n):
            bar = MagicMock()
            bar.date = first.replace(tzinfo=UTC) + timedelta(days=i)
            bar.open, bar.high, bar.low, bar.close, bar.volume = 1.0, 1.0, 1.0, 1.0, volume
            out.append(bar)
        return out

    async def _fetch(self, provider, mock_ib, answers, *, timeframe="1d", primary="NASDAQ"):
        """answers: routed exchange -> list of bars | 'no_data' | 'timeout'."""
        from ib_async import BarDataList, Stock

        ibkr_module._no_data_req_ids.clear()
        asked: list[str] = []
        req = {"n": 0}

        async def fake_req(contract, **kwargs):
            asked.append(contract.exchange)
            answer = answers.get(contract.exchange, "no_data")
            if answer == "timeout":
                raise TimeoutError
            if answer == "no_data":
                req["n"] += 1
                result = BarDataList()
                result.reqId = 92000 + req["n"]
                ibkr_module._no_data_req_ids.add(result.reqId)
                return result
            return answer

        mock_ib.reqHistoricalDataAsync = AsyncMock(side_effect=fake_req)
        provider._ib = mock_ib
        contract = Stock("XYZ", "SMART", "USD", primaryExchange=primary)
        contract.secType = "STK"
        provider._qualified_contracts["XYZ"] = contract
        reports, persisted = [], []

        async def on_chunk(bars):
            persisted.extend(bars)

        with patch.object(ibkr_module, "_RETRY_COUNT", 1):
            bars = await provider.fetch_historical_bars(
                "XYZ",
                timeframe,
                self.START,
                self.END,
                on_chunk=on_chunk,
                on_empty_history=reports.append,
            )
        ibkr_module._no_data_req_ids.clear()
        return bars, persisted, reports, asked

    @pytest.mark.asyncio
    async def test_keeps_highest_volume_venue_for_the_head(self, provider, mock_ib):
        from src.core.bar_normalizer import SOURCE_IBKR_VENUE

        smart = self._bars(datetime(2018, 9, 10), 5, 1000)
        nyse = self._bars(datetime(2012, 1, 3), 4, 400)
        arca = self._bars(datetime(2012, 1, 3), 4, 50)
        bars, persisted, reports, asked = await self._fetch(
            provider, mock_ib, {"SMART": smart, "NYSE": nyse, "ARCA": arca}
        )
        venue = [b for b in bars if b.source == SOURCE_IBKR_VENUE]
        assert len(venue) == 4 and all(b.volume == 400 for b in venue)
        assert [b for b in persisted if b.source == SOURCE_IBKR_VENUE] == venue
        assert reports == []
        assert "ISLAND" not in asked  # the current primary is never asked as a former venue
        assert bars == sorted(bars, key=lambda b: b.timestamp)

    @pytest.mark.asyncio
    async def test_head_empty_everywhere_is_recorded(self, provider, mock_ib):
        bars, _, reports, asked = await self._fetch(provider, mock_ib, {})
        assert bars == []
        (report,) = reports
        assert report.empty_through == self.END
        assert set(asked) == {"SMART", "NYSE", "ARCA", "AMEX", "BATS"}

    @pytest.mark.asyncio
    async def test_ambiguous_venue_answer_leaves_the_head_unverified(self, provider, mock_ib):
        bars, _, reports, _ = await self._fetch(provider, mock_ib, {"ARCA": "timeout"})
        assert bars == []
        assert reports == []

    @pytest.mark.asyncio
    async def test_history_starting_at_request_start_asks_no_venue(self, provider, mock_ib):
        smart = self._bars(datetime(2010, 1, 4), 5, 1000)
        _, _, _, asked = await self._fetch(provider, mock_ib, {"SMART": smart})
        assert asked == ["SMART"]

    @pytest.mark.asyncio
    async def test_intraday_timeframes_are_not_recovered(self, provider, mock_ib):
        smart = self._bars(datetime(2026, 1, 29), 1, 1000)
        with patch.object(ibkr_module, "_MAX_CHUNK_DAYS", {"1h": 7300}):
            _, _, _, asked = await self._fetch(provider, mock_ib, {"SMART": smart}, timeframe="1h")
        assert set(asked) == {"SMART"}
