"""
DataProvider protocol and normalized wire models.

All data providers emit Tick and OHLCVBar instances — the pipeline
is completely unaware of which provider is active.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol, runtime_checkable

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
