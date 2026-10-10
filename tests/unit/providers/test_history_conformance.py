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
from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from typing import Any

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


# ---------------------------------------------------------------------------
# FakeHistoryLeaf: the behavioral fixture. Modeled on the provider_factory /
# fetch_fn seam style of tests/unit/scripts/test_ohlcv_history_fetcher.py: the
# contract assertions below are written once and run against any conforming
# leaf; the fake makes the page-boundary, budget and verdict cases runnable
# without vendor access (IBKRProvider's fetch-path proof stays with
# tests/unit/scripts/test_history_fetch_item.py).
# ---------------------------------------------------------------------------


class FakeHistoryLeaf:
    """A stateless-per-call HistoryProvider fake driven by scenario config.

    The window (start, end] is divided into equal `window_span_days` pages.
    Each call fetches exactly one page, and each fetched page costs one vendor
    "request". The budget interface is honored per native request: the leaf
    checks the deadline and its remaining request allowance (tracked across
    calls in `requests_issued`, since FetchBudget itself is frozen per-call
    state) before issuing each request and stops mid-call when exhausted,
    returning what it has with the resume point intact.
    """

    name = "fake"

    def __init__(
        self,
        *,
        window_span_days: int = 30,
        empty_windows: int = 0,
        provider: str = "fake",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._window_span_days = window_span_days
        # The oldest `empty_windows` pages of the span answer definitive no-data
        # instead of bars (the backward walk runs newest page first).
        self._empty_windows = empty_windows
        self._provider = provider
        self._clock = clock or (lambda: datetime.now(UTC))
        self.requests_issued = 0

    async def fetch_ohlcv(self, request: HistoryRequest, budget: FetchBudget) -> HistoryPage:
        if request.start >= request.end:
            raise ValueError(f"Empty window: start {request.start} >= end {request.end}")

        span_days = (request.end - request.start).days
        window_start = max(request.start, request.end - timedelta(days=self._window_span_days))
        next_window_start = window_start if window_start > request.start else None

        # Budget honored per native request: deadline first, then the request
        # allowance. A blocked request yields an empty page with the resume
        # point unchanged; the caller decides whether to stop.
        if budget.max_requests - self.requests_issued <= 0 or self._clock() >= budget.deadline:
            return HistoryPage(bars=(), next_window_start=next_window_start, verdict=None)

        self.requests_issued += 1

        if self._empty_windows and span_days <= self._window_span_days * self._empty_windows:
            empty_from = max(request.start, request.end - timedelta(days=self._window_span_days))
            verdict = NoDataVerdict(
                provider=self._provider,
                symbol=request.symbol,
                timeframe=request.timeframe,
                empty_from=empty_from,
                empty_through=request.end,
                reached_request_start=request.start >= empty_from - timedelta(seconds=1),
                n_confirming_chunks=2,
            )
            return HistoryPage(bars=(), next_window_start=next_window_start, verdict=verdict)

        return HistoryPage(
            bars=(_fake_bar(request.symbol, request.timeframe, request.end - timedelta(days=1)),),
            next_window_start=next_window_start,
            verdict=None,
        )


def _fake_bar(symbol: str, timeframe: str, timestamp: datetime) -> OHLCVBar:
    return OHLCVBar(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=timestamp,
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=100,
        source="fake",
    )


@pytest.fixture
def fake_leaf() -> FakeHistoryLeaf:
    return FakeHistoryLeaf(window_span_days=30)


CONFORMANCE_LEAVES = [
    FakeHistoryLeaf(window_span_days=30),
    IBKRProvider(host="127.0.0.1", port=7497, client_id=1),
]
CONFORMANCE_LEAF_IDS = ["fake", "ibkr-structure"]


@pytest.fixture(params=CONFORMANCE_LEAVES, ids=CONFORMANCE_LEAF_IDS)
def conforming_leaf(request: pytest.FixtureRequest) -> Any:
    return request.param


# --- Shared assertion functions: the contract, written once -----------------


def assert_observation_shape(bars: tuple[OHLCVBar, ...]) -> None:
    """Every observation is a fully populated OHLCVBar (the capture contract's field set)."""
    for bar in bars:
        assert isinstance(bar, OHLCVBar)
        for field in (
            "symbol",
            "timeframe",
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "source",
        ):
            value = getattr(bar, field)
            assert value is not None, f"{field} is None on {bar}"
        assert bar.volume >= 0


def assert_page_chain_within_span(pages: list[HistoryPage], request: HistoryRequest) -> None:
    """A fully driven fetch chains monotonically inside (start, end] and ends closed."""
    previous_end = request.end
    for page in pages[:-1]:
        resume = page.next_window_start
        assert resume is not None, "only the final page may close the span"
        assert request.start < resume < previous_end
        previous_end = resume
    assert pages[-1].next_window_start is None, "the final page must close the span"


# --- Type and structure conformance: every conforming leaf ------------------


class TestLeafConformance:
    @pytest.mark.parametrize(
        ("leaf",), [(leaf,) for leaf in CONFORMANCE_LEAVES], ids=CONFORMANCE_LEAF_IDS
    )
    def test_satisfies_history_provider(self, leaf: Any) -> None:
        assert isinstance(leaf, HistoryProvider)

    @pytest.mark.parametrize(
        ("leaf",), [(leaf,) for leaf in CONFORMANCE_LEAVES], ids=CONFORMANCE_LEAF_IDS
    )
    def test_fetch_ohlcv_is_async(self, leaf: Any) -> None:
        assert inspect.iscoroutinefunction(leaf.fetch_ohlcv)


# --- Behavioral cases: the fake leaf carries them ---------------------------


class TestPageBoundaries:
    async def test_n_page_request_yields_n_chained_pages(self, fake_leaf: FakeHistoryLeaf) -> None:
        # A 90-day span over 30-day windows: three pages, chained, closed.
        request = HistoryRequest(
            symbol="AAPL", timeframe="1d", start=_utc(2020, 1, 2), end=_utc(2020, 4, 1)
        )
        budget = FetchBudget(deadline=datetime.now(UTC) + timedelta(seconds=30), max_requests=10)
        pages: list[HistoryPage] = []
        end = request.end
        while True:
            page = await fake_leaf.fetch_ohlcv(
                replace(request, end=end),
                budget,
            )
            pages.append(page)
            assert_observation_shape(page.bars)
            if page.next_window_start is None:
                break
            end = page.next_window_start
        assert len(pages) == 3
        assert_page_chain_within_span(pages, request)

    async def test_single_page_span_closes_immediately(self, fake_leaf: FakeHistoryLeaf) -> None:
        request = HistoryRequest(
            symbol="AAPL", timeframe="1d", start=_utc(2020, 3, 15), end=_utc(2020, 4, 1)
        )
        budget = FetchBudget(deadline=datetime.now(UTC) + timedelta(seconds=30), max_requests=10)
        page = await fake_leaf.fetch_ohlcv(request, budget)
        assert page.next_window_start is None
        assert_observation_shape(page.bars)


class TestBudgetInterface:
    async def test_stops_issuing_requests_once_max_requests_exhausted(
        self, fake_leaf: FakeHistoryLeaf
    ) -> None:
        request = HistoryRequest(
            symbol="AAPL", timeframe="1d", start=_utc(2020, 1, 2), end=_utc(2020, 4, 1)
        )
        budget = FetchBudget(deadline=datetime.now(UTC) + timedelta(seconds=30), max_requests=1)
        # The first page fetches normally (one request) and hands back a mid-span
        # resume point; the second call is budget-blocked and must leave it intact.
        first = await fake_leaf.fetch_ohlcv(request, budget)
        assert fake_leaf.requests_issued == 1
        assert first.bars
        assert first.next_window_start is not None
        end = first.next_window_start
        blocked = await fake_leaf.fetch_ohlcv(replace(request, end=end), budget)
        assert fake_leaf.requests_issued == 1, "exhausted budget must not issue more requests"
        assert blocked.bars == ()
        # The blocked page returns the resume point of the window it was asked
        # for (mid-span, not None), so the caller can retry it under fresh budget.
        assert blocked.next_window_start == end - timedelta(days=30)

    async def test_never_returns_bars_past_deadline(self, fake_leaf: FakeHistoryLeaf) -> None:
        request = HistoryRequest(
            symbol="AAPL", timeframe="1d", start=_utc(2020, 1, 2), end=_utc(2020, 4, 1)
        )
        expired = FetchBudget(deadline=_utc(2020, 1, 2), max_requests=5)
        page = await fake_leaf.fetch_ohlcv(request, expired)
        assert page.bars == (), "an expired deadline must not produce bars"
        assert fake_leaf.requests_issued == 0


class TestVerdictEmission:
    async def test_no_data_window_returns_empty_page_with_intact_verdict(
        self, fake_leaf: FakeHistoryLeaf
    ) -> None:
        leaf = FakeHistoryLeaf(window_span_days=30, empty_windows=1, provider="fake")
        request = HistoryRequest(
            symbol="AAPL", timeframe="1d", start=_utc(2020, 1, 2), end=_utc(2020, 4, 1)
        )
        budget = FetchBudget(deadline=datetime.now(UTC) + timedelta(seconds=30), max_requests=10)
        pages: list[HistoryPage] = []
        end = request.end
        while True:
            page = await leaf.fetch_ohlcv(replace(request, end=end), budget)
            pages.append(page)
            if page.next_window_start is None:
                break
            end = page.next_window_start
        # The oldest page (the empty_windows window) carries the verdict.
        final = pages[-1]
        assert final.bars == ()
        assert final.verdict is not None
        assert final.verdict.provider == "fake"
        assert final.verdict.symbol == "AAPL"
        assert final.verdict.timeframe == "1d"
        assert final.verdict.n_confirming_chunks == 2
        assert final.verdict.authoritative_empty is False
        assert final.verdict.reached_request_start is True
        # Evidence survives the page round-trip untouched (frozen dataclass).
        assert_page_chain_within_span(pages, request)

    async def test_data_window_carries_no_verdict(self, fake_leaf: FakeHistoryLeaf) -> None:
        request = HistoryRequest(
            symbol="AAPL", timeframe="1d", start=_utc(2020, 3, 15), end=_utc(2020, 4, 1)
        )
        budget = FetchBudget(deadline=datetime.now(UTC) + timedelta(seconds=30), max_requests=10)
        page = await fake_leaf.fetch_ohlcv(request, budget)
        assert page.bars
        assert page.verdict is None


class TestObservationShape:
    async def test_every_bar_is_a_complete_ohlcvbar(self, fake_leaf: FakeHistoryLeaf) -> None:
        request = HistoryRequest(
            symbol="AAPL", timeframe="1d", start=_utc(2020, 3, 15), end=_utc(2020, 4, 1)
        )
        budget = FetchBudget(deadline=datetime.now(UTC) + timedelta(seconds=30), max_requests=10)
        page = await fake_leaf.fetch_ohlcv(request, budget)
        assert_observation_shape(page.bars)
