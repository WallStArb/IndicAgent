"""
DataProvider protocol and normalized wire models.

All data providers emit Tick and OHLCVBar instances — the pipeline
is completely unaware of which provider is active.

The batch history surface (HistoryProvider, HistoryRequest, FetchBudget,
NoDataVerdict, HistoryPage) is the vendor-leaf contract for windowed history
fetching per docs/plans/2026-10-09-provider-history-plane-unification-design.md:
caller-driven window-scoped pagination (never a long-lived cursor token), the
leaf's native rate-limit model behind a common budget interface, and a
normalized no-data verdict carrying per-vendor evidence. It sits alongside the
streaming DataProvider protocol, which it does not modify.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from src.core.models import Instrument
from src.core.schemas.bar_message import BarMessage
from src.observability.metrics import PROVIDER_ACTIVE_SUBSCRIPTIONS


class Tick(BaseModel):
    """Normalized real-time tick from any provider."""

    symbol: str
    timestamp: datetime
    price: float
    size: int | None = None
    bid: float | None = None
    ask: float | None = None
    bid_size: int | None = None
    ask_size: int | None = None
    source: str  # provider name: "ibkr", "alpaca", etc.


class OHLCVBar(BaseModel):
    """Normalized OHLCV bar from any provider."""

    symbol: str
    timeframe: str  # "1m", "5m", "15m", "1h"
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str


@runtime_checkable
class DataProvider(Protocol):
    """Protocol that every data provider must implement.

    Adding a new provider:
    1. Create src/providers/<name>.py
    2. Implement all methods below
    3. Pass instance to the daemon — nothing else changes.
    """

    name: str  # "ibkr", "alpaca", "tradestation"

    async def connect(self) -> bool:
        """Establish connection to the data source. Returns True on success."""
        ...

    async def disconnect(self) -> None:
        """Cleanly disconnect."""
        ...

    def is_connected(self) -> bool:
        """Return True if the connection is currently active."""
        ...

    async def resolve_instrument(self, query: str) -> Instrument | None:
        """Resolve a user-entered symbol string to a concrete Instrument.

        Each provider handles its own lookup (IBKR reqContractDetails,
        Alpaca assets API, etc.). Returns None if not found.
        """
        ...

    async def stream_ticks(self, symbols: list[str]) -> AsyncIterator[Tick]:
        """Async iterator that yields normalized Ticks as they arrive.

        Usage:
            async for tick in provider.stream_ticks(["ESH6", "NQH6"]):
                await publish(tick)
        """
        ...

    async def stream_real_time_bars(self, symbols: list[str]) -> AsyncIterator[tuple[str, object]]:
        """Async iterator yielding (symbol, RealTimeBar) tuples as 5-second bars arrive.

        RealTimeBar fields: time (UTC close time), open_, high, low, close, volume (float).
        Usage:
            async for symbol, bar in provider.stream_real_time_bars(["ES", "NQ"]):
                accumulate(symbol, bar)
        """
        ...

    async def fetch_historical_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[OHLCVBar]:
        """Fetch historical OHLCV bars. timeframe: '1m', '5m', '15m', '1h'."""
        ...


@runtime_checkable
class DataProviderAdapter(Protocol):
    """Provider-agnostic adapter contract for the Phase 54 abstraction layer.

    Any broker implementation (IBKR, Alpaca, Polygon, etc.) must satisfy
    this protocol to plug into the MergerAgent-based pipeline.

    Contrast with the existing DataProvider Protocol above (tick/RTB stream):
    - DataProvider: legacy low-level tick/RTB API (ib_async coupled)
    - DataProviderAdapter: new normalized bar-level API (BarMessage typed bus)

    provider_name must be a lower-case identifier used in topic keys,
    metric labels, and quality event payloads, e.g. "ibkr", "alpaca".
    """

    provider_name: str  # "ibkr", "alpaca", etc.

    async def connect(self) -> bool:
        """Establish connection to the data source. Returns True on success."""
        ...

    async def disconnect(self) -> None:
        """Cleanly disconnect."""
        ...

    def is_connected(self) -> bool:
        """Return True if the connection is currently active."""
        ...

    async def stream_bars(self, instruments: list[Instrument]) -> AsyncIterator[BarMessage]:
        """Async iterator yielding normalized BarMessage instances as they arrive.

        Each bar is published to the provider's raw topic before the merger
        routes it into the canonical market.bars stream.
        """
        ...

    async def fetch_historical(
        self,
        symbol: str,
        tf: str,
        start: datetime,
        end: datetime,
    ) -> list[BarMessage]:
        """Fetch historical bars as normalized BarMessage instances."""
        ...

    async def qualify_instrument(self, instrument: Instrument) -> Instrument:
        """Resolve/enrich instrument metadata using provider-specific lookup.

        Returns an updated Instrument with contract_details populated.
        Raises ValueError if the instrument cannot be qualified.
        """
        ...


#
# Batch history surface (phase 190, provider history plane unification).
# Design: docs/plans/2026-10-09-provider-history-plane-unification-design.md.
# A vendor leaf (src/providers/<vendor>.py) satisfies HistoryProvider; the batch
# fetcher dispatches through this protocol, never a concrete leaf.
#


@dataclass(frozen=True)
class HistoryRequest:
    """One window-scoped batch history request, conventions declared (phase 190).

    `start` and `end` are UTC datetimes bounding the half-open span (start, end].
    `adjustment` is the declared price convention, e.g. "none" or "split"; each
    leaf honors the subset its vendor can serve windowed and raises loudly on the
    rest (silent unadjusted-instead-of-adjusted answers are forbidden).
    `rth_only` is the declared session convention the leaf maps to its native knob
    (IBKR useRTH, Alpaca RTH-window aggregates).
    """

    symbol: str
    timeframe: str  # "1m", "5m", "15m", "1h", "1d"
    start: datetime
    end: datetime
    adjustment: str = "none"
    rth_only: bool = True


@dataclass(frozen=True)
class FetchBudget:
    """The planner's budget passed to a leaf with every request (phase 190).

    `deadline` bounds wall-clock time and `max_requests` bounds the vendor
    requests a leaf may issue; the leaf maps both onto its native pacing model
    (IBKR's sliding window, a REST vendor's leaky bucket). Frozen: a budget is a
    per-call input, not shared mutable state.
    """

    deadline: datetime
    max_requests: int


@dataclass(frozen=True)
class NoDataVerdict:
    """Normalized definitive no-data answer with per-vendor evidence (phase 190).

    Generalizes EmptyHistory (the IBKR backward-walk precedent above). Evidence
    fields do not collapse into each other: `n_confirming_chunks` carries IBKR's
    chunk-by-chunk confirmation count, `authoritative_empty` carries a REST
    vendor's single authoritative empty response; both may be set. The planner
    weights evidence per vendor and never infers one vendor's emptiness from
    another vendor's answer.
    """

    provider: str
    symbol: str
    timeframe: str
    empty_from: datetime
    empty_through: datetime
    reached_request_start: bool
    n_confirming_chunks: int = 0
    authoritative_empty: bool = False


@dataclass(frozen=True)
class HistoryPage:
    """One page of a caller-driven windowed history fetch (phase 190).

    `bars` are the page's normalized observations. `next_window_start` is the
    caller-driven in-span resume point: the caller issues the next request with
    `end` set to it; it is a plain datetime, never a long-lived cursor token
    (resumability comes from coverage, not tokens). `verdict` is set when the
    leaf received a definitive no-data answer for (part of) the window.
    """

    bars: tuple[OHLCVBar, ...]
    next_window_start: datetime | None
    verdict: NoDataVerdict | None = None


@runtime_checkable
class HistoryProvider(Protocol):
    """Batch history surface a vendor leaf implements (phase 190).

    Sits alongside DataProvider (the streaming protocol above), which it does
    not modify; a leaf may satisfy both. The batch fetcher dispatches through
    this protocol, never a concrete leaf (CI-enforced by
    tests/unit/test_provider_leaf_boundary.py).
    """

    async def fetch_ohlcv(self, request: HistoryRequest, budget: FetchBudget) -> HistoryPage:
        """Fetch one caller-driven window of (request.start, request.end].

        Returns the page's bars plus the resume point for the next call
        (None when the span is exhausted) and a NoDataVerdict on a definitive
        vendor no-data answer. Honors the declared adjustment/rth_only
        conventions and bounds its native pacing by the budget.
        """
        ...


# A venue's routing code mapped to the name IBKR reports as a contract's primaryExchange
# (ISLAND is Nasdaq's routing code). One definition for the provider's venue walk and for
# the D1-derived empty-history confirmation, which both need to know which route is the
# current primary.
VENUE_ROUTE_ALIASES: dict[str, str] = {"ISLAND": "NASDAQ"}


@dataclass(frozen=True)
class EmptyHistory:
    """A fetch's backward walk ended in IBKR's definitive "no data" answers.

    `verified_from`..`empty_through` is the span IBKR answered "no data" for, chunk by
    chunk (Error 162 "no data" attributed by reqId; timeouts and throttling
    cancellations never count). `n_confirming_chunks` is how many consecutive chunks
    answered. `reached_request_start` is False when the walk stopped early on the
    confirmation threshold, i.e. the range older than `verified_from` was never asked;
    the walk already treats it as empty (it stops there every time), and callers must
    record which part was verified and which was inferred.
    """

    verified_from: datetime
    empty_through: datetime
    n_confirming_chunks: int
    reached_request_start: bool


@dataclass(frozen=True)
class RequestRecord:
    """One provider historical-data request and how it was answered (phase 185 D-05).

    The capture half of D1: the provider reports every request it makes (SMART walk
    chunks, venue-routed requests, back-from-now requests) through on_request, and
    every bar any route answers through on_observation, without touching a database.
    Fields mirror one ohlcv_request row except caller and source, which are sink-level
    facts the campaign supplies. Route is "SMART" or the venue exchange code the
    request was routed to; ib_req_id is IBKR's reqId when the answer carried one.
    """

    request_id: str
    fetch_run_id: str
    symbol: str
    timeframe: str
    route: str
    what_to_show: str
    primary_exchange: str | None
    window_start: datetime | None
    window_end: datetime
    ib_req_id: int | None
    outcome: Literal["bars", "no_data", "timeout", "failed"]
    error_code: int | None
    error_text: str | None
    n_bars: int
    client_id: int | None
    requested_at: datetime
    answered_at: datetime


class SubscriptionLimitError(Exception):
    """Raised when a provider's subscription limit is reached."""


class SubscriptionManager:
    """Generic subscription slot tracker for data providers with hard limits.

    Provider-agnostic: IBKR, Alpaca, Polygon all have different limits.
    SubscriptionLimitError is raised before attempting the violating subscription
    so the caller can handle gracefully (log + skip vs raise).
    """

    def __init__(self, provider_name: str, max_subscriptions: int) -> None:
        self._provider_name = provider_name
        self._max = max_subscriptions
        self._active: set[str] = set()

        self._gauge = PROVIDER_ACTIVE_SUBSCRIPTIONS

    def subscribe(self, symbol: str) -> None:
        if symbol in self._active:
            return  # idempotent
        if len(self._active) >= self._max:
            raise SubscriptionLimitError(
                f"{self._provider_name}: subscription limit {self._max} reached "
                f"(attempted to add {symbol!r})"
            )
        self._active.add(symbol)
        if self._gauge:
            self._gauge.add(self.count, {"provider": self._provider_name})

    def unsubscribe(self, symbol: str) -> None:
        self._active.discard(symbol)
        if self._gauge:
            self._gauge.add(self.count, {"provider": self._provider_name})

    @property
    def count(self) -> int:
        return len(self._active)
