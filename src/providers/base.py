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
    timeframe: str   # "1m", "5m", "15m", "1h"
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

    async def fetch_historical_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[OHLCVBar]:
        """Fetch historical OHLCV bars. timeframe: '1m', '5m', '15m', '1h'."""
        ...
