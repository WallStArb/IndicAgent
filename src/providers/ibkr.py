"""
IBKRProvider — DataProvider implementation for Interactive Brokers (ib_insync).

Wraps all ib_insync logic. The daemon and backfill script interact only
with the DataProvider protocol — no ib_insync imports outside this file.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import nest_asyncio
from ib_insync import IB, ContFuture, Contract, Forex, Future, Stock

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
        self._local_to_canonical: dict[str, str] = {}  # IBKR localSymbol -> instrument.symbol

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
        continuous: bool = False,
    ) -> list[OHLCVBar]:
        """Fetch historical OHLCV bars from IBKR.

        Automatically chunks long requests to stay within IBKR per-request
        duration limits (e.g. 6-day chunks for 1m bars). Chunks are fetched
        chronologically with a 10-second pause between requests for pacing.

        Requires the contract to be pre-qualified via qualify_instrument().

        Args:
            continuous: If True, fetch back-adjusted continuous contract data
                (ContFuture + ADJUSTED_LAST) instead of the named contract.
                Use for multi-year history that spans contract rolls. The named
                contract must still be pre-qualified so the base symbol and
                exchange can be resolved.
        """
        if timeframe not in _TF_TO_IB:
            raise ValueError(f"Unsupported timeframe '{timeframe}'. Valid: {list(_TF_TO_IB)}")

        if not self._ib:
            raise RuntimeError("Not connected. Call connect() first.")

        named_contract = self._qualified_contracts.get(symbol)
        if not named_contract:
            raise ValueError(f"Unknown symbol '{symbol}'. Call qualify_instrument() first.")

        if continuous:
            base = getattr(named_contract, "symbol", symbol)
            exchange = getattr(named_contract, "exchange", "CME")
            contract = ContFuture(symbol=base, exchange=exchange)
            what_to_show = "ADJUSTED_LAST"
            source_tag = "ibkr_continuous_adj"
        else:
            contract = named_contract
            sec_type = getattr(named_contract, "secType", "")
            if sec_type == "CASH":
                what_to_show = "MIDPOINT"
            elif sec_type == "CRYPTO":
                what_to_show = "AGGTRADES"
            else:
                what_to_show = "TRADES"
            source_tag = "ibkr_named"

        chunk_days = _MAX_CHUNK_DAYS.get(timeframe, 6)
        all_bars: list[OHLCVBar] = []
        chunk_start = start
        first_chunk = True

        while chunk_start < end:
            if not first_chunk:
                await asyncio.sleep(10)  # IBKR pacing between chunk requests
            first_chunk = False

            chunk_end = min(chunk_start + timedelta(days=chunk_days - 1), end)
            window_seconds = int((chunk_end - chunk_start).total_seconds())
            if window_seconds < 86400:
                # Sub-day window: use seconds-based duration to avoid fetching a full day
                duration_str = f"{max(120, window_seconds + 60)} S"
            else:
                duration_str = f"{max(1, (chunk_end - chunk_start).days + 1)} D"

            ib_bars = self._ib.reqHistoricalData(
                contract,
                endDateTime=chunk_end.strftime("%Y%m%d %H:%M:%S"),
                durationStr=duration_str,
                barSizeSetting=_TF_TO_IB[timeframe],
                whatToShow=what_to_show,
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
                    source=source_tag,
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
                trading_class = instrument.provider_meta.get("trading_class", "")
                contract = Future(
                    symbol=instrument.base or instrument.symbol,
                    lastTradeDateOrContractMonth=instrument.expiry,
                    exchange=instrument.exchange,
                    currency="USD",
                    **({"tradingClass": trading_class} if trading_class else {}),
                )
            elif instrument.asset_class == AssetClass.FX:
                contract = Forex(pair=instrument.symbol)
            elif instrument.asset_class == AssetClass.CRYPTO:
                contract = Contract(secType="CRYPTO", symbol=instrument.base, currency="USD")
            else:
                contract = Stock(symbol=instrument.symbol, exchange=instrument.exchange)

            details = self._ib.reqContractDetails(contract)
            if details:
                qualified = details[0].contract
                self._qualified_contracts[instrument.symbol] = qualified
                # Store reverse mapping for localSymbol → canonical (e.g. "EUR.USD" → "EURUSD")
                local_sym = getattr(qualified, "localSymbol", None)
                if local_sym and local_sym != instrument.symbol:
                    self._local_to_canonical[local_sym] = instrument.symbol
                    self._qualified_contracts[local_sym] = qualified
                return True
            logger.warning(
                "qualify_instrument: no contract details returned",
                extra={"symbol": instrument.symbol, "base": instrument.base, "exchange": instrument.exchange, "expiry": instrument.expiry},
            )
            return False
        except Exception as e:
            logger.warning("qualify_instrument failed", extra={"symbol": instrument.symbol, "error": str(e)})
            return False

    def _normalize_ticker(self, ticker) -> Tick | None:
        """Normalize an ib_insync Ticker to a Tick. Returns None if no valid price."""
        symbol = getattr(ticker.contract, "localSymbol", None)
        if not symbol:
            return None
        symbol = self._local_to_canonical.get(symbol, symbol)

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

        return Tick(
            symbol=symbol,
            timestamp=datetime.now(UTC),
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
                # RTVolume (233) is futures-only; FX (CASH) uses basic bid/ask/last
                sec_type = getattr(contract, "secType", "")
                tick_list = "233" if sec_type == "FUT" else ""
                self._ib.reqMktData(contract, genericTickList=tick_list, snapshot=False)

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
