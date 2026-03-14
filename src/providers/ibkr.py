"""
IBKRProvider — DataProvider implementation for Interactive Brokers (ib_insync).

Wraps all ib_insync logic. The daemon and backfill script interact only
with the DataProvider protocol — no ib_insync imports outside this file.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import nest_asyncio
from ib_insync import IB, ContFuture, Contract, Forex, Future, Stock

nest_asyncio.apply()

from src.config.settings import Settings  # noqa: E402
from src.core.models import AssetClass, Instrument  # noqa: E402

# Circuit breaker and retry
from src.core.plugin_circuit_breaker import (  # noqa: E402
    CircuitBreakerConfig,
    CircuitState,
    PluginCircuitBreaker,
)
from src.core.retry_utils import retry_with_backoff  # noqa: E402

# Circuit breaker metrics
from src.observability.metrics import (  # noqa: E402
    CIRCUIT_BREAKER_FAILURES_TOTAL,
    CIRCUIT_BREAKER_OPEN_SECONDS,
    CIRCUIT_BREAKER_SUCCESSES_TOTAL,
    CIRCUIT_BREAKER_TRANSITIONS_TOTAL,
)
from src.providers.base import OHLCVBar, Tick  # noqa: E402

logger = logging.getLogger(__name__)

# Map our timeframe strings to ib_insync barSizeSetting values
_TF_TO_IB: dict[str, str] = {
    "1m": "1 min",
    "5m": "5 mins",
    "15m": "15 mins",
    "1h": "1 hour",
    "4h": "4 hours",
    "1d": "1 day",
}

# RTVolume generic tick type — required for futures, not supported on other asset classes
_FUT_TICK_LIST = "233"

# Max days per IBKR historical data request by bar size (conservative, under hard limits)
_MAX_CHUNK_DAYS: dict[str, int] = {
    "1m": 6,  # IBKR hard limit: 7 days
    "5m": 29,  # IBKR hard limit: 30 days
    "15m": 59,  # IBKR hard limit: 60 days
    "1h": 364,  # IBKR hard limit: 1 year
    "4h": 364,
    "1d": 364,
}

# Circuit breaker for IBKR connection attempts
_ibkr_circuit_breaker = PluginCircuitBreaker(
    config=CircuitBreakerConfig(
        failure_threshold=3,
        recovery_timeout=180,  # 3 minutes (IBKR reconnection typically faster)
        success_threshold=2,
        max_half_open_calls=2,
        failure_window=120,  # Track failures over 2 minutes
        performance_threshold_ms=20000.0,  # 20s default timeout
    )
)

# Track when IBKR circuit breaker entered OPEN — used to observe duration on recovery.
_ibkr_open_since: float | None = None


async def _connect_with_circuit_breaker(
    host: str, port: int, client_id: int, timeout: float
) -> IB | None:
    """Connect to IBKR with circuit breaker tracking and metrics."""
    global _ibkr_open_since
    provider_id = "ibkr:connection"
    plugin_state = _ibkr_circuit_breaker.plugin_states[provider_id]
    previous_state = plugin_state.state

    async def _try_connect() -> IB:
        """Single connection attempt."""
        ib_instance = IB()
        await ib_instance.connectAsync(
            host=host,
            port=port,
            clientId=client_id,
            timeout=timeout,
            readonly=False,
        )
        if not ib_instance.isConnected():
            raise ConnectionError("IBKR connection established but not connected")
        return ib_instance

    try:
        # Use retry_with_backoff for exponential backoff + jitter
        ib_instance = await retry_with_backoff(
            _try_connect,
            max_attempts=3,
            base_delay=2.0,  # Longer base for IBKR
            max_delay=15.0,
            jitter_factor=0.5,
        )

        # Record success metrics
        CIRCUIT_BREAKER_SUCCESSES_TOTAL.labels(plugin_name=provider_id).inc()

        # Record success in circuit breaker
        plugin_state.success_count += 1
        plugin_state.last_success_time = datetime.now()
        plugin_state.total_calls += 1

        # Record state transition if recovered from non-closed state
        if plugin_state.state != previous_state and previous_state != CircuitState.CLOSED:
            CIRCUIT_BREAKER_TRANSITIONS_TOTAL.labels(
                plugin_name=provider_id,
                from_state=previous_state.name.lower(),
                to_state="closed",
            ).inc()
            # Observe how long the circuit was OPEN before recovery
            if _ibkr_open_since is not None:
                CIRCUIT_BREAKER_OPEN_SECONDS.labels(plugin_name=provider_id).observe(
                    time.monotonic() - _ibkr_open_since
                )
                _ibkr_open_since = None

        logger.info(
            "IBKR connected",
            extra={"host": host, "port": port, "client_id": client_id},
        )
        return ib_instance

    except Exception as exc:
        # Record failure metrics
        CIRCUIT_BREAKER_FAILURES_TOTAL.labels(
            plugin_name=provider_id,
            error_type=type(exc).__name__,
        ).inc()

        # Record failure in circuit breaker
        plugin_state.failure_count += 1
        plugin_state.last_failure_time = datetime.now()
        plugin_state.total_calls += 1

        # Record state transition if tripped to OPEN
        if plugin_state.state == CircuitState.OPEN and previous_state != CircuitState.OPEN:
            CIRCUIT_BREAKER_TRANSITIONS_TOTAL.labels(
                plugin_name=provider_id,
                from_state=previous_state.name.lower(),
                to_state="open",
            ).inc()
            # Start timing how long the circuit stays OPEN
            _ibkr_open_since = time.monotonic()

        logger.error(
            "IBKR connect failed",
            extra={"host": host, "port": port, "client_id": client_id, "error": str(exc)},
        )
        return None


def _is_circuit_breaker_open() -> bool:
    """Check if IBKR circuit breaker is OPEN."""
    state = _ibkr_circuit_breaker.plugin_states["ibkr:connection"].state
    return state == CircuitState.OPEN


async def reset_circuit_breaker() -> bool:
    """Force reset IBKR circuit breaker state."""

    provider_id = "ibkr:connection"
    plugin_state = _ibkr_circuit_breaker.plugin_states[provider_id]
    previous_state = plugin_state.state

    result = await _ibkr_circuit_breaker.force_reset_plugin(provider_id)

    # Record manual reset transition
    if result and previous_state != CircuitState.CLOSED:
        CIRCUIT_BREAKER_TRANSITIONS_TOTAL.labels(
            plugin_name=provider_id,
            from_state=previous_state.name.lower(),
            to_state="closed",
        ).inc()

    return result


class IBKRProvider:
    """DataProvider implementation for Interactive Brokers via ib_insync."""

    name = "ibkr"

    def __init__(
        self,
        host: str,
        port: int,
        client_id: int,
        tick_queue_size: int = 5000,
        settings: Settings | None = None,
    ):
        self._host = host
        self._port = port
        self._client_id = client_id
        self._tick_queue_size = tick_queue_size
        self._settings = settings or Settings()
        self._ib: IB | None = None
        self._tick_queue: asyncio.Queue[Tick] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._qualified_contracts: dict[str, object] = {}
        self._local_to_canonical: dict[str, str] = {}  # IBKR localSymbol -> instrument.symbol

    async def connect(self) -> bool:
        """Connect to TWS/Gateway. Returns True on success."""
        # Check circuit breaker state first
        if _is_circuit_breaker_open():
            logger.warning(
                "IBKR circuit breaker OPEN, skipping connection attempt",
                extra={"host": self._host, "port": self._port},
            )
            return False

        # Use circuit breaker for connection attempt
        self._ib = await _connect_with_circuit_breaker(
            host=self._host,
            port=self._port,
            client_id=self._client_id,
            timeout=self._settings.ib_timeout_sec,
        )
        return self._ib is not None

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
            logger.warning(
                "fetch_historical_bars: symbol not qualified",
                symbol=symbol,
                qualified_symbols=list(self._qualified_contracts.keys())[:5],
            )
            raise ValueError(f"Unknown symbol '{symbol}'. Call qualify_instrument() first.")

        if continuous:
            base = getattr(named_contract, "symbol", symbol)
            exchange = getattr(named_contract, "exchange", "CME")
            contract = ContFuture(symbol=base, exchange=exchange)
            what_to_show = "ADJUSTED_LAST"
            source_tag = "ibkr_continuous_adj"
            use_rth = False
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
            use_rth = sec_type == "STK"

        all_bars: list[OHLCVBar] = []

        if continuous:
            # ContFuture + ADJUSTED_LAST: IBKR prohibits setting endDateTime.
            # Fetch in a single request from now backwards by total duration.
            total_days = max(1, (end - start).days + 1)
            if total_days > 365:
                duration_str = f"{round(total_days / 365)} Y"
            else:
                duration_str = f"{total_days} D"
            ib_bars = await self._ib.reqHistoricalDataAsync(
                contract,
                endDateTime="",  # must be empty for ContFuture
                durationStr=duration_str,
                barSizeSetting=_TF_TO_IB[timeframe],
                whatToShow=what_to_show,
                useRTH=False,
                formatDate=1,
            )
            for bar in ib_bars or []:
                bar_ts = (
                    bar.date
                    if isinstance(bar.date, datetime)
                    else datetime.fromisoformat(str(bar.date))
                )
                if bar_ts.tzinfo is None:
                    bar_ts = bar_ts.replace(tzinfo=UTC)
                all_bars.append(
                    OHLCVBar(
                        symbol=symbol,
                        timeframe=timeframe,
                        timestamp=bar_ts,
                        open=float(bar.open),
                        high=float(bar.high),
                        low=float(bar.low),
                        close=float(bar.close),
                        volume=int(bar.volume),
                        source=source_tag,
                    )
                )
        else:
            chunk_days = _MAX_CHUNK_DAYS.get(timeframe, 6)
            chunk_start = start
            first_chunk = True

            while chunk_start < end:
                if not first_chunk:
                    await asyncio.sleep(10)  # IBKR pacing between chunk requests
                first_chunk = False

                chunk_end = min(chunk_start + timedelta(days=chunk_days - 1), end)
                window_seconds = int((chunk_end - chunk_start).total_seconds())
                if window_seconds < 86400:
                    duration_str = f"{max(120, window_seconds + 60)} S"
                else:
                    duration_str = f"{max(1, (chunk_end - chunk_start).days + 1)} D"

                ib_bars = await self._ib.reqHistoricalDataAsync(
                    contract,
                    endDateTime=chunk_end.strftime("%Y%m%d %H:%M:%S"),
                    durationStr=duration_str,
                    barSizeSetting=_TF_TO_IB[timeframe],
                    whatToShow=what_to_show,
                    useRTH=use_rth,
                    formatDate=1,
                )

                for bar in ib_bars or []:
                    bar_ts = (
                        bar.date
                        if isinstance(bar.date, datetime)
                        else datetime.fromisoformat(str(bar.date))
                    )
                    if bar_ts.tzinfo is None:
                        bar_ts = bar_ts.replace(tzinfo=UTC)
                    all_bars.append(
                        OHLCVBar(
                            symbol=symbol,
                            timeframe=timeframe,
                            timestamp=bar_ts,
                            open=float(bar.open),
                            high=float(bar.high),
                            low=float(bar.low),
                            close=float(bar.close),
                            volume=int(bar.volume),
                            source=source_tag,
                        )
                    )

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
            elif instrument.asset_class == AssetClass.EQUITY:
                contract = Stock(
                    symbol=instrument.symbol,
                    exchange=instrument.exchange or "SMART",
                    currency="USD",
                )
            else:
                contract = Stock(symbol=instrument.symbol, exchange=instrument.exchange)

            details = await self._ib.reqContractDetailsAsync(contract)
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
                extra={
                    "symbol": instrument.symbol,
                    "base": instrument.base,
                    "exchange": instrument.exchange,
                    "expiry": instrument.expiry,
                },
            )
            return False
        except Exception as e:
            logger.warning(
                "qualify_instrument failed", extra={"symbol": instrument.symbol, "error": str(e)}
            )
            return False

    async def get_quote(self, symbol: str, timeout_sec: float | None = None) -> dict | None:
        """Request a one-off snapshot quote for a pre-qualified symbol.

        Sleeps for timeout_sec to allow IBKR to fill the snapshot, then returns
        a dict with bid, ask, last (and optionally lastSize), or None if no data arrived.

        If not provided, uses Settings.ib_timeout_sec as default.

        Returns None if circuit breaker is OPEN or quote fails.
        """
        # Check circuit breaker state
        if _is_circuit_breaker_open():
            logger.warning(
                "IBKR circuit breaker OPEN, skipping quote request",
                extra={"symbol": symbol},
            )
            return None

        if not self._ib:
            return None
        contract = self._qualified_contracts.get(symbol)
        if not contract:
            logger.warning("get_quote: symbol not qualified", extra={"symbol": symbol})
            return None
        sec_type = getattr(contract, "secType", "")
        tick_list = _FUT_TICK_LIST if sec_type == "FUT" else ""
        ticker = self._ib.reqMktData(contract, genericTickList=tick_list, snapshot=True)
        actual_timeout = timeout_sec or self._settings.ib_timeout_sec
        try:
            await asyncio.sleep(actual_timeout)
            bid = getattr(ticker, "bid", None)
            ask = getattr(ticker, "ask", None)
            last = getattr(ticker, "last", None) or getattr(ticker, "close", None)
            last_size = getattr(ticker, "lastSize", None)
            result = {}
            if isinstance(bid, (int, float)) and bid > 0:
                result["bid"] = float(bid)
            if isinstance(ask, (int, float)) and ask > 0:
                result["ask"] = float(ask)
            if isinstance(last, (int, float)) and last > 0:
                result["last"] = float(last)
            if isinstance(last_size, (int, float)) and last_size > 0:
                result["lastSize"] = int(last_size)
            return result if result else None
        finally:
            self._ib.cancelMktData(contract)

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
                # RTVolume is futures-only; FX (CASH) uses basic bid/ask/last
                sec_type = getattr(contract, "secType", "")
                tick_list = _FUT_TICK_LIST if sec_type == "FUT" else ""
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
            details = await self._ib.reqContractDetailsAsync(contract)
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
            logger.debug(
                "resolve_instrument futures lookup failed", extra={"query": query, "error": str(e)}
            )
        return None
