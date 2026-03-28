"""IBKRAdapter — DataProviderAdapter implementation wrapping IBKRProvider.

Encapsulates all IBKR-specific logic (5s RTB aggregation state machine,
official bar reconciliation, provider_meta['ibkr'] key lookup) so that
BaseProviderAgent only sees the provider-agnostic DataProviderAdapter interface.

Swapping IBKR for another broker = one new adapter file. Everything downstream
(MergerAgent, FeatureComputeAgent, etc.) is untouched.

Phase 54-02 — Provider Abstraction Layer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

from src.core.bar_normalizer import SOURCE_IBKR_GENERIC, SOURCE_IBKR_NAMED
from src.core.models import Instrument
from src.core.schemas.bar_message import BarMessage, SessionType
from src.providers.base import OHLCVBar
from src.providers.ibkr import IBKRProvider

# Map Instrument.session_id → SessionType for bar emission.
# session_id is the trading calendar identifier; SessionType is the bar-level
# session classification used downstream by the feature pipeline.
_SESSION_ID_TO_TYPE: dict[str, SessionType] = {
    "crypto_24_7": SessionType.CRYPTO,
    "fx_24_5": SessionType.FX,
    "nyse": SessionType.RTH,
    "futures_24_5": SessionType.RTH,
}

_DEFAULT_SESSION_TYPE = SessionType.RTH

logger = logging.getLogger(__name__)

# Sentinel — distinguishes "no previous close stored yet" from close=0.0
_UNSET = object()


class IBKRAdapter:
    """DataProviderAdapter that wraps IBKRProvider and produces BarMessage directly.

    The 5s-RTB → 1m aggregation state machine lives here, not in
    DataProviderAgent. This makes the adapter independently testable and
    removes IBKR-specific logic from the agent layer.

    provider_name = 'ibkr' — matches the key used in provider_meta lookups,
    topic keys, and Prometheus metric labels.
    """

    provider_name: str = "ibkr"

    def __init__(self, host: str, port: int, client_id: int) -> None:
        self._provider = IBKRProvider(host=host, port=port, client_id=client_id)

        # RTB aggregation state: symbol → {bar_minute, open, high, low, close, volume, …}
        self._rtb_state: dict[str, dict[str, Any]] = {}

        # Official bar cache for reconciliation: symbol → {ts_iso → OHLCVBar}
        self._official_bars_cache: dict[str, dict[str, Any]] = defaultdict(dict)

        # Dedup guard: symbol → set of emitted ts ISO strings
        self._seen_ts: dict[str, set[str]] = defaultdict(set)
        self._seen_ts_order: dict[str, deque] = defaultdict(lambda: deque(maxlen=30))

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Establish connection to IBKR TWS."""
        return await self._provider.connect()

    async def disconnect(self) -> None:
        """Cleanly disconnect from IBKR TWS."""
        await self._provider.disconnect()

    def is_connected(self) -> bool:
        """Return True if the IBKR connection is currently active."""
        return self._provider.is_connected()

    # ------------------------------------------------------------------
    # stream_bars — core 5s RTB → 1m aggregation pipeline
    # ------------------------------------------------------------------

    async def stream_bars(
        self, instruments: list[Instrument]
    ) -> AsyncIterator[BarMessage]:
        """Async iterator yielding completed 1m BarMessage instances.

        Internally subscribes to IBKRProvider.stream_real_time_bars() and
        applies the 5s→1m OHLCV aggregation state machine. Each completed
        minute emits one BarMessage with source=SOURCE_IBKR_GENERIC.

        A background task subscribes to stream_official_bars() for
        reconciliation metadata (is_reconciled / drift_detected). Those
        fields are currently carried in the state dict but not exposed on
        BarMessage directly — they are available for callers that cast to
        a richer payload type.
        """
        symbols = [i.symbol for i in instruments]
        # Build symbol → instrument mapping for session_type derivation
        sym_to_instrument: dict[str, Instrument] = {i.symbol: i for i in instruments}

        def _init_state(minute: datetime | None = None, prev_close: Any = _UNSET) -> dict:
            return {
                "bar_minute": minute,
                "open": None,
                "high": None,
                "low": None,
                "close": None,
                "volume": 0.0,
                "last_update": time.monotonic(),
                "emitted": False,
                "prev_close": prev_close,
                # Reconciliation fields (populated by official bars background task)
                "is_reconciled": False,
                "drift_detected": False,
            }

        # Queue for completed BarMessage instances
        bar_queue: asyncio.Queue[BarMessage] = asyncio.Queue()

        # ----------------------------------------------------------------
        # Official bars background task for reconciliation
        # ----------------------------------------------------------------
        official_task: asyncio.Task | None = None

        async def _official_bars_background() -> None:
            try:
                async for sym, bar in self._provider.stream_official_bars(symbols):
                    ts_str = bar.timestamp.isoformat()
                    self._official_bars_cache[sym][ts_str] = bar
                    # Keep cache bounded (last 20 per symbol)
                    if len(self._official_bars_cache[sym]) > 20:
                        oldest = min(self._official_bars_cache[sym])
                        del self._official_bars_cache[sym][oldest]
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("official_bars_background error", exc_info=exc)

        # ----------------------------------------------------------------
        # Emit helper
        # ----------------------------------------------------------------
        async def _emit_bar(symbol: str, state: dict) -> None:
            """Publish completed 1m bar to the queue with dedup guard."""
            bar_minute = state["bar_minute"]
            if bar_minute is None:
                return

            ts_str = bar_minute.isoformat() if hasattr(bar_minute, "isoformat") else str(bar_minute)

            # Dedup guard
            seen = self._seen_ts[symbol]
            order = self._seen_ts_order[symbol]
            if ts_str in seen:
                return
            seen.add(ts_str)
            order.append(ts_str)  # deque(maxlen=30) auto-evicts

            # Reconciliation check
            official = self._official_bars_cache.get(symbol, {}).get(ts_str)
            if official:
                price_diff = abs(float(state["close"] or 0.0) - official.close)
                if price_diff > (official.close * 0.0001):
                    logger.warning(
                        "IBKRAdapter drift detected",
                        extra={
                            "symbol": symbol,
                            "ts": ts_str,
                            "derived": state["close"],
                            "official": official.close,
                            "diff": price_diff,
                        },
                    )

            # Flat bar if no 5s data arrived
            if state["open"] is None:
                if official:
                    state.update(
                        {
                            "open": official.open,
                            "high": official.high,
                            "low": official.low,
                            "close": official.close,
                            "volume": official.volume,
                        }
                    )
                else:
                    prev_close = state.get("prev_close", _UNSET)
                    if prev_close is _UNSET:
                        logger.warning(
                            "IBKRAdapter: no data for bar emission and no prev_close",
                            extra={"symbol": symbol, "ts": ts_str},
                        )
                        return
                    flat = float(prev_close)
                    bar_ts = (
                        bar_minute.replace(tzinfo=UTC)
                        if bar_minute.tzinfo is None
                        else bar_minute
                    )
                    instrument = sym_to_instrument.get(symbol)
                    session_type = _SESSION_ID_TO_TYPE.get(
                        instrument.session_id if instrument else "futures_24_5",
                        _DEFAULT_SESSION_TYPE,
                    )
                    bar_msg = BarMessage(
                        ts=bar_ts,
                        symbol=symbol,
                        tf="1m",
                        open=flat,
                        high=flat,
                        low=flat,
                        close=flat,
                        volume=0,
                        source=SOURCE_IBKR_GENERIC,
                        session_type=session_type,
                        gap_preceding=False,
                        is_flat_bar=True,
                    )
                    await bar_queue.put(bar_msg)
                    state["prev_close"] = flat
                    return

            # Normal bar
            bar_ts = bar_minute.replace(tzinfo=UTC) if bar_minute.tzinfo is None else bar_minute
            instrument = sym_to_instrument.get(symbol)
            session_type = _SESSION_ID_TO_TYPE.get(
                instrument.session_id if instrument else "futures_24_5",
                _DEFAULT_SESSION_TYPE,
            )

            bar_msg = BarMessage(
                ts=bar_ts,
                symbol=symbol,
                tf="1m",
                open=float(state["open"]),
                high=float(state["high"]),
                low=float(state["low"]),
                close=float(state["close"]),
                volume=int(state["volume"]),
                source=SOURCE_IBKR_GENERIC,
                session_type=session_type,
                gap_preceding=False,
                is_flat_bar=False,
            )
            state["prev_close"] = state["close"]
            await bar_queue.put(bar_msg)

        # ----------------------------------------------------------------
        # RTB aggregation loop — produces to bar_queue
        # ----------------------------------------------------------------
        async def _rtb_aggregation_loop() -> None:
            try:
                async for symbol, rtb in self._provider.stream_real_time_bars(symbols):
                    try:
                        # Ensure UTC-aware timestamp
                        rtb_time = rtb.time
                        if rtb_time.tzinfo is None:
                            rtb_time = rtb_time.replace(tzinfo=UTC)
                        bar_minute = rtb_time.replace(second=0, microsecond=0)

                        s = self._rtb_state.setdefault(symbol, _init_state(bar_minute))

                        # New minute arrived — the old bar should have been emitted already
                        if s["bar_minute"] is not None and bar_minute > s["bar_minute"]:
                            if not s["emitted"]:
                                await _emit_bar(symbol, s)
                            prev_close = s.get("prev_close", _UNSET)
                            s.update(_init_state(bar_minute, prev_close))

                        if s["bar_minute"] is None or bar_minute >= s["bar_minute"]:
                            if s["open"] is None:
                                s["open"] = rtb.open_
                            s["high"] = max(s["high"] or rtb.high, rtb.high)
                            s["low"] = min(s["low"] or rtb.low, rtb.low)
                            s["close"] = rtb.close
                            s["volume"] = (s["volume"] or 0.0) + rtb.volume
                            s["last_update"] = time.monotonic()

                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.warning(
                            "IBKRAdapter RTB loop error",
                            extra={"symbol": symbol, "error": str(exc)},
                            exc_info=exc,
                        )
            except asyncio.CancelledError:
                pass

        # ----------------------------------------------------------------
        # Heartbeat — deterministic 1m emission (61s after bar_minute)
        # ----------------------------------------------------------------
        async def _heartbeat_loop() -> None:
            running = True
            while running:
                try:
                    now = datetime.now(UTC)
                    for symbol, s in list(self._rtb_state.items()):
                        if not s or not s.get("bar_minute"):
                            continue
                        bm = s["bar_minute"]
                        if bm.tzinfo is None:
                            bm = bm.replace(tzinfo=UTC)
                        if now >= bm + timedelta(seconds=61) and not s["emitted"]:
                            await _emit_bar(symbol, s)
                            s["emitted"] = True
                    await asyncio.sleep(1)
                except asyncio.CancelledError:
                    running = False
                except Exception as exc:
                    logger.error("IBKRAdapter heartbeat error", exc_info=exc)
                    await asyncio.sleep(1)

        # Start background tasks
        official_task = asyncio.ensure_future(_official_bars_background())
        heartbeat_task = asyncio.ensure_future(_heartbeat_loop())
        rtb_task = asyncio.ensure_future(_rtb_aggregation_loop())

        try:
            while True:
                bar = await bar_queue.get()
                yield bar
        except asyncio.CancelledError:
            pass
        finally:
            for task in (official_task, heartbeat_task, rtb_task):
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

    # ------------------------------------------------------------------
    # fetch_historical
    # ------------------------------------------------------------------

    async def fetch_historical(
        self,
        symbol: str,
        tf: str,
        start: datetime,
        end: datetime,
    ) -> list[BarMessage]:
        """Fetch historical bars and convert each to BarMessage with SOURCE_IBKR_NAMED."""
        raw_bars: list[OHLCVBar] = await self._provider.fetch_historical_bars(
            symbol=symbol,
            timeframe=tf,
            start=start,
            end=end,
        )
        result: list[BarMessage] = []
        for bar in raw_bars:
            ts = bar.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            bar_msg = BarMessage(
                ts=ts,
                symbol=bar.symbol,
                tf=bar.timeframe,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=int(bar.volume),
                source=SOURCE_IBKR_NAMED,
                session_type=SessionType.RTH,
                gap_preceding=False,
                is_flat_bar=False,
            )
            result.append(bar_msg)
        return result

    # ------------------------------------------------------------------
    # qualify_instrument
    # ------------------------------------------------------------------

    async def qualify_instrument(self, instrument: Instrument) -> Instrument:
        """Resolve/enrich instrument metadata using IBKR-specific lookup.

        Reads provider_meta[self.provider_name] (i.e. provider_meta['ibkr'])
        for broker-specific overrides like trading_class.

        Returns the original Instrument (possibly enriched in-place by the
        underlying IBKRProvider). Raises ValueError if qualification fails.
        """
        # Extract IBKR-specific meta from the nested format
        ibkr_meta = instrument.provider_meta.get(self.provider_name, {})

        # Build an ephemeral Instrument copy with the flattened meta for
        # IBKRProvider.qualify_instrument() which reads flat provider_meta
        if ibkr_meta:
            flat_instrument = instrument.model_copy(update={"provider_meta": ibkr_meta})
        else:
            flat_instrument = instrument

        success = await self._provider.qualify_instrument(flat_instrument)
        if not success:
            raise ValueError(
                f"IBKRAdapter.qualify_instrument failed for {instrument.symbol!r}"
            )
        return instrument
