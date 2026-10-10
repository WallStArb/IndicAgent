"""HistoryProvider protocol conformance suite (phase 190).

Pins the batch history surface defined in src/providers/base.py (the seam every
plan-190 dispatch goes through): verdict shape, observation shape, page
boundaries, and the budget interface. The same assertion functions run over
every conforming leaf; the fake leaf carries the behavioral cases (no vendor
access in unit tests), IBKRProvider carries the structure-level ones, and the
real IBKR fetch-path proof stays with tests/unit/scripts/test_history_fetch_item.py.

CI-clean: no DB, no network, no gateway connection.
"""

from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from src.providers.base import (
    DataProvider,
    FetchBudget,
    HistoryPage,
    HistoryProvider,
    HistoryRequest,
    NoDataVerdict,
    OHLCVBar,
)
from src.providers.ibkr import IBKRProvider


def _utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


@pytest.fixture
def provider() -> IBKRProvider:
    # Existing test convention (tests/unit/providers/test_ibkr_provider.py):
    # construct without connecting; isinstance checks never need a gateway.
    return IBKRProvider(host="127.0.0.1", port=7497, client_id=1)


class TestIbkrSatisfiesHistoryProvider:
    def test_isinstance_history_provider(self, provider: IBKRProvider) -> None:
        assert isinstance(provider, HistoryProvider)

    def test_fetch_ohlcv_is_async(self, provider: IBKRProvider) -> None:
        assert inspect.iscoroutinefunction(provider.fetch_ohlcv)

    def test_still_satisfies_streaming_data_provider(self, provider: IBKRProvider) -> None:
        # The streaming method set on DataProvider stays byte-identical this phase.
        assert isinstance(provider, DataProvider)

    def test_fetch_historical_bars_signature_unchanged(self, provider: IBKRProvider) -> None:
        params = inspect.signature(provider.fetch_historical_bars).parameters
        assert list(params) == [
            "symbol",
            "timeframe",
            "start",
            "end",
            "continuous",
            "on_chunk",
            "on_empty_history",
            "on_request",
            "on_observation",
            "fetch_run_id",
            "route",
        ]
        required = [params[name].default is inspect.Parameter.empty for name in params]
        assert required == [True, True, True, True] + [False] * 7


class TestHistoryRequest:
    def test_frozen(self) -> None:
        request = HistoryRequest(
            symbol="AAPL", timeframe="1d", start=_utc(2020, 1, 2), end=_utc(2020, 2, 3)
        )
        with pytest.raises(FrozenInstanceError):
            request.symbol = "MSFT"  # type: ignore[misc]

    def test_carries_declared_conventions(self) -> None:
        start, end = _utc(2020, 1, 2), _utc(2020, 2, 3)
        request = HistoryRequest(
            symbol="AAPL",
            timeframe="5m",
            start=start,
            end=end,
            adjustment="split",
            rth_only=False,
        )
        assert request.symbol == "AAPL"
        assert request.timeframe == "5m"
        assert request.start == start
        assert request.end == end
        assert request.adjustment == "split"
        assert request.rth_only is False


class TestFetchBudget:
    def test_frozen(self) -> None:
        budget = FetchBudget(deadline=_utc(2026, 10, 10), max_requests=5)
        with pytest.raises(FrozenInstanceError):
            budget.max_requests = 6  # type: ignore[misc]

    def test_carries_deadline_and_max_requests(self) -> None:
        deadline = _utc(2026, 10, 10)
        budget = FetchBudget(deadline=deadline, max_requests=5)
        assert budget.deadline == deadline
        assert budget.max_requests == 5


class TestNoDataVerdict:
    def test_frozen(self) -> None:
        verdict = NoDataVerdict(
            provider="ibkr",
            symbol="AAPL",
            timeframe="1d",
            empty_from=_utc(1998, 1, 2),
            empty_through=_utc(1999, 1, 5),
            reached_request_start=True,
        )
        with pytest.raises(FrozenInstanceError):
            verdict.symbol = "MSFT"  # type: ignore[misc]

    def test_ibkr_evidence_shape(self) -> None:
        verdict = NoDataVerdict(
            provider="ibkr",
            symbol="AAPL",
            timeframe="1d",
            empty_from=_utc(1998, 1, 2),
            empty_through=_utc(1999, 1, 5),
            reached_request_start=False,
            n_confirming_chunks=2,
        )
        assert verdict.provider == "ibkr"
        assert verdict.n_confirming_chunks == 2
        assert verdict.authoritative_empty is False

    def test_rest_evidence_shape(self) -> None:
        # A REST vendor's single authoritative empty; neither evidence field
        # collapses into the other (design: per-vendor evidence the planner weights).
        verdict = NoDataVerdict(
            provider="alpaca",
            symbol="AAPL",
            timeframe="5m",
            empty_from=_utc(2016, 1, 4),
            empty_through=_utc(2016, 2, 5),
            reached_request_start=True,
            authoritative_empty=True,
        )
        assert verdict.n_confirming_chunks == 0
        assert verdict.authoritative_empty is True

    def test_both_evidence_fields_may_coexist(self) -> None:
        verdict = NoDataVerdict(
            provider="ibkr",
            symbol="AAPL",
            timeframe="1d",
            empty_from=_utc(1998, 1, 2),
            empty_through=_utc(1999, 1, 5),
            reached_request_start=True,
            n_confirming_chunks=3,
            authoritative_empty=True,
        )
        assert verdict.n_confirming_chunks == 3
        assert verdict.authoritative_empty is True


class TestHistoryPage:
    def test_frozen(self) -> None:
        page = HistoryPage(bars=(), next_window_start=None, verdict=None)
        with pytest.raises(FrozenInstanceError):
            page.next_window_start = _utc(2020, 1, 2)  # type: ignore[misc]

    def test_carries_bars_resume_point_and_verdict(self) -> None:
        verdict = NoDataVerdict(
            provider="ibkr",
            symbol="AAPL",
            timeframe="1d",
            empty_from=_utc(1998, 1, 2),
            empty_through=_utc(1999, 1, 5),
            reached_request_start=True,
        )
        bar = OHLCVBar(
            symbol="AAPL",
            timeframe="1d",
            timestamp=_utc(2020, 1, 2),
            open=1.0,
            high=2.0,
            low=0.5,
            close=1.5,
            volume=100,
            source="ibkr",
        )
        page = HistoryPage(bars=(bar,), next_window_start=_utc(2019, 12, 2), verdict=verdict)
        assert page.bars == (bar,)
        assert page.next_window_start == _utc(2019, 12, 2)
        assert page.verdict == verdict
