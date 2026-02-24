"""
IBKRProvider — DataProvider implementation for Interactive Brokers (ib_insync).

Wraps all ib_insync logic. The daemon and backfill script interact only
with the DataProvider protocol — no ib_insync imports outside this file.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timedelta

import nest_asyncio
from ib_insync import IB, Future, Stock

nest_asyncio.apply()

from src.core.models import AssetClass, Instrument
from src.providers.base import OHLCVBar, Tick

logger = logging.getLogger(__name__)

# Map our timeframe strings to ib_insync barSizeSetting values
_TF_TO_IB: dict[str, str] = {
    "1m":  "1 min",
    "5m":  "5 mins",
    "15m": "15 mins",
    "1h":  "1 hour",
    "4h":  "4 hours",
    "1d":  "1 day",
}

# Max days per IBKR historical data request by bar size (conservative, under hard limits)
_MAX_CHUNK_DAYS: dict[str, int] = {
    "1m":  6,    # IBKR hard limit: 7 days
    "5m":  29,   # IBKR hard limit: 30 days
    "15m": 59,   # IBKR hard limit: 60 days
    "1h":  364,  # IBKR hard limit: 1 year
    "4h":  364,
    "1d":  364,
}


class IBKRProvider:
    """DataProvider implementation for Interactive Brokers via ib_insync."""

    name = "ibkr"

    def __init__(self, host: str, port: int, client_id: int, tick_queue_size: int = 5000):
        self._host = host
        self._port = port
        self._client_id = client_id
        self._tick_queue_size = tick_queue_size
        self._ib: IB | None = None
        self._tick_queue: asyncio.Queue[Tick] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._qualified_contracts: dict[str, object] = {}

    async def connect(self) -> bool:
        """Connect to TWS/Gateway. Returns True on success."""
        try:
            self._ib = IB()
            await self._ib.connectAsync(
                host=self._host,
                port=self._port,
                clientId=self._client_id,
                timeout=20,
                readonly=False,
            )
            connected = self._ib.isConnected()
            if connected:
                logger.info("IBKRProvider connected", extra={"host": self._host, "port": self._port})
            return connected
        except Exception as e:
            logger.error("IBKRProvider connect failed", extra={"error": str(e)})
            return False

    async def disconnect(self) -> None:
        """Disconnect from TWS."""
        if self._ib:
            self._ib.disconnect()
            logger.info("IBKRProvider disconnected")

    def is_connected(self) -> bool:
        return bool(self._ib and self._ib.isConnected())

    async def fetch_historical_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[OHLCVBar]:
        """Fetch historical OHLCV bars from IBKR.

        Automatically chunks long requests to stay within IBKR per-request
        duration limits (e.g. 6-day chunks for 1m bars). Chunks are fetched
        chronologically with a 10-second pause between requests for pacing.

        Requires the contract to be pre-qualified via qualify_instrument().
        """
        if timeframe not in _TF_TO_IB:
            raise ValueError(f"Unsupported timeframe '{timeframe}'. Valid: {list(_TF_TO_IB)}")

        if not self._ib:
            raise RuntimeError("Not connected. Call connect() first.")

        contract = self._qualified_contracts.get(symbol)
        if not contract:
            raise ValueError(f"Unknown symbol '{symbol}'. Call qualify_instrument() first.")

        chunk_days = _MAX_CHUNK_DAYS.get(timeframe, 6)
        all_bars: list[OHLCVBar] = []
        chunk_start = start
        first_chunk = True

        while chunk_start < end:
            if not first_chunk:
                await asyncio.sleep(10)  # IBKR pacing between chunk requests
            first_chunk = False

            chunk_end = min(chunk_start + timedelta(days=chunk_days - 1), end)
            duration = max(1, (chunk_end - chunk_start).days + 1)

            ib_bars = self._ib.reqHistoricalData(
                contract,
                endDateTime=chunk_end.strftime("%Y%m%d %H:%M:%S"),
                durationStr=f"{duration} D",
                barSizeSetting=_TF_TO_IB[timeframe],
                whatToShow="TRADES",
                useRTH=False,
                formatDate=1,
            )

            for bar in (ib_bars or []):
                all_bars.append(OHLCVBar(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=bar.date if isinstance(bar.date, datetime) else datetime.fromisoformat(str(bar.date)),
                    open=float(bar.open),
                    high=float(bar.high),
                    low=float(bar.low),
                    close=float(bar.close),
                    volume=int(bar.volume),
                    source="ibkr",
                ))

            chunk_start = chunk_end + timedelta(days=1)

        all_bars.sort(key=lambda b: b.timestamp)
        return all_bars

    async def qualify_instrument(self, instrument: Instrument) -> bool:
        """Qualify an instrument with IBKR and cache the contract.

        Must be called before fetch_historical_bars() or stream_ticks().
        Returns True if successfully qualified.
        """
        if not self._ib:
            return False
        try:
            if instrument.asset_class == AssetClass.FUTURES:
                contract = Future(
                    symbol=instrument.base or instrument.symbol,
                    lastTradeDateOrContractMonth=instrument.expiry,
                    exchange=instrument.exchange,
                )
            else:
                contract = Stock(symbol=instrument.symbol, exchange=instrument.exchange)

            details = self._ib.reqContractDetails(contract)
            if details:
                self._qualified_contracts[instrument.symbol] = details[0].contract
                return True
            return False
        except Exception as e:
            logger.warning("qualify_instrument failed", extra={"symbol": instrument.symbol, "error": str(e)})
            return False

    def _normalize_ticker(self, ticker) -> Tick | None:
        """Normalize an ib_insync Ticker to a Tick. Returns None if no valid price."""
        symbol = getattr(ticker.contract, "localSymbol", None)
        if not symbol:
            return None

        price = None
        for attr in ("last", "close", "bid", "ask"):
            val = getattr(ticker, attr, None)
            if isinstance(val, (int, float)) and val > 0:
                price = float(val)
                break
        if not price:
            return None

        def _pos_float(val) -> float | None:
            return float(val) if isinstance(val, (int, float)) and val > 0 else None

        def _pos_int(val) -> int | None:
            return int(val) if isinstance(val, (int, float)) and val > 0 else None

        from datetime import timezone
        return Tick(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            price=price,
            size=_pos_int(getattr(ticker, "lastSize", None)),
            bid=_pos_float(getattr(ticker, "bid", None)),
            ask=_pos_float(getattr(ticker, "ask", None)),
            bid_size=_pos_int(getattr(ticker, "bidSize", None)),
            ask_size=_pos_int(getattr(ticker, "askSize", None)),
            source="ibkr",
        )

    def _handle_pending_tickers(self, tickers) -> None:
        """ib_insync callback — runs on ib_insync's thread. Bridge to asyncio queue."""
        if not self._tick_queue or not self._loop:
            return
        for ticker in tickers:
            if ticker.contract.localSymbol not in self._qualified_contracts:
                continue
            tick = self._normalize_ticker(ticker)
            if tick:
                try:
                    self._loop.call_soon_threadsafe(self._tick_queue.put_nowait, tick)
                except Exception:
                    pass  # drop on full queue — backpressure

    async def stream_ticks(self, symbols: list[str]) -> AsyncIterator[Tick]:
        """Async iterator yielding normalized Ticks.

        Bridges ib_insync's sync callbacks to asyncio via a bounded Queue.
        Subscribes to all symbols via reqMktData on entry.
        """
        self._loop = asyncio.get_event_loop()
        self._tick_queue = asyncio.Queue(maxsize=self._tick_queue_size)

        # Register callback
        self._ib.pendingTickersEvent += self._handle_pending_tickers

        # Subscribe to market data for each symbol
        for symbol in symbols:
            contract = self._qualified_contracts.get(symbol)
            if contract and self._ib:
                self._ib.reqMktData(contract, genericTickList="233", snapshot=False)

        try:
            while True:
                tick = await self._tick_queue.get()
                yield tick
        finally:
            self._ib.pendingTickersEvent -= self._handle_pending_tickers

    async def resolve_instrument(self, query: str) -> Instrument | None:
        """Resolve a symbol query to an Instrument via IBKR contract details."""
        if not self._ib:
            return None
        try:
            # Try as futures first (most common for this platform)
            contract = Future(symbol=query)
            details = self._ib.reqContractDetails(contract)
            if details:
                d = details[0]
                c = d.contract
                return Instrument(
                    symbol=c.localSymbol or c.symbol,
                    name=getattr(d, "longName", ""),
                    asset_class=AssetClass.FUTURES,
                    exchange=c.exchange,
                    base=c.symbol,
                    expiry=c.lastTradeDateOrContractMonth,
                    tick_size=float(d.minTick),
                    point_value=float(c.multiplier or 0),
                    provider_meta={"con_id": c.conId},
                )
        except Exception as e:
            logger.debug("resolve_instrument futures lookup failed", extra={"query": query, "error": str(e)})
        return None
