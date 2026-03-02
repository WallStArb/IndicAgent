"""
TimeframeBuilder — 1m OHLCV bar aggregator for higher timeframes.

Consumes 1m bars from the market:SYMBOL:1m Redis stream and emits
5m, 15m, 1h, 4h, and 1d bars to market:SYMBOL:{TF} streams.

Version: 1.1.0
Last Updated: 2026-02-26
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog

from src.config.settings import Settings
from src.core.stream_keys import get_stream_maxlen, market

logger = structlog.get_logger(__name__)

# Target timeframes and their period length in minutes
_TARGET_TIMEFRAMES: dict[str, int] = {
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


# ---------------------------------------------------------------------------
# Pure functions (no I/O — easy to unit test)
# ---------------------------------------------------------------------------

def _floor_to_period(ts_seconds: int, tf_minutes: int) -> int:
    """Return the period-start timestamp (seconds) for a given bar timestamp.

    Args:
        ts_seconds: Bar open timestamp in Unix seconds.
        tf_minutes: Timeframe period in minutes (5, 15, 60, 240, 1440).

    Returns:
        Floored timestamp in seconds (start of the containing period).
    """
    period_seconds = tf_minutes * 60
    return (ts_seconds // period_seconds) * period_seconds


def _update_accumulator(
    acc: dict[str, Any] | None,
    bar: dict[str, Any],
    period_ts: int,
) -> dict[str, Any]:
    """Update or create an OHLCV accumulator for the given period.

    Args:
        acc: Existing accumulator dict or None if this is the first bar.
        bar: Incoming bar with open/high/low/close/volume/period_ts fields.
        period_ts: Period start timestamp in seconds.

    Returns:
        Updated accumulator dict.
    """
    if acc is None:
        return {
            "open": bar["open"],
            "high": bar["high"],
            "low": bar["low"],
            "close": bar["close"],
            "volume": bar["volume"],
            "period_ts": period_ts,
        }

    return {
        "open": acc["open"],  # keep first bar's open
        "high": max(acc["high"], bar["high"]),
        "low": min(acc["low"], bar["low"]),
        "close": bar["close"],  # latest bar's close
        "volume": acc["volume"] + bar["volume"],
        "period_ts": period_ts,
    }


def _parse_ts(ts_raw: str) -> int:
    """Parse a timestamp string (Unix seconds or ISO 8601) to Unix seconds int."""
    try:
        return int(float(ts_raw))
    except ValueError:
        dt = datetime.fromisoformat(str(ts_raw))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return int(dt.timestamp())


# ---------------------------------------------------------------------------
# TimeframeBuilder class
# ---------------------------------------------------------------------------

class TimeframeBuilder:
    """Aggregates 1m OHLCV bars into 5m/15m/1h/4h/1d bars.

    Usage (as called by timeframes_builder_service.py):
        builder = TimeframeBuilder(streams_manager)
        await builder.start()
        await builder.subscribe_to_symbols(["ESH6", "NQH6"])
        # ... service runs processing loop ...
        await builder.stop()
    """

    def __init__(self, streams_manager: Any) -> None:
        self._streams_manager = streams_manager
        self._symbols: set[str] = set()
        self._running: bool = False
        self._task: asyncio.Task | None = None

        # Accumulators: {symbol: {timeframe: accumulator_dict | None}}
        self._accumulators: dict[str, dict[str, dict[str, Any] | None]] = {}

        # Per-stream cursor for xread — avoids resetting to "$" every iteration
        # which would skip bars published between two loop iterations.
        self._last_ids: dict[str, str] = {}

        # Tracks the last period_ts emitted per (symbol, tf) — prevents
        # re-emitting the same period after a service restart.
        self._last_emitted: dict[str, dict[str, int]] = {}

        # Metrics counters
        self._bars_1m_processed: int = 0
        self._bars_built: dict[str, int] = {tf: 0 for tf in _TARGET_TIMEFRAMES}

        # Settings for env prefix
        try:
            _settings = Settings()
            self._env_prefix = f"{_settings.env_name}:" if _settings.env_name else ""
        except Exception:
            self._env_prefix = ""

        self._logger = structlog.get_logger(__name__)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialize accumulators and start the processing loop."""
        self._running = True
        self._task = asyncio.create_task(self._processing_loop())
        self._logger.info("TimeframeBuilder started")

    async def stop(self) -> None:
        """Cancel the processing loop and flush any pending accumulators."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._logger.info("TimeframeBuilder stopped")

    async def subscribe_to_symbols(self, symbols: list[str]) -> None:
        """Register symbols to watch for incoming 1m bars.

        Initialises per-symbol accumulators for all target timeframes.
        """
        for sym in symbols:
            if sym not in self._symbols:
                self._symbols.add(sym)
                self._accumulators[sym] = {tf: None for tf in _TARGET_TIMEFRAMES}
                self._logger.debug("Subscribed to symbol", symbol=sym)

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def get_metrics(self) -> dict[str, Any]:
        """Return current processing metrics.

        Returns a dict with keys:
          bars_1m_processed, bars_5m_built, bars_15m_built,
          bars_1h_built, bars_4h_built, bars_1d_built, symbols_active.
        """
        return {
            "bars_1m_processed": self._bars_1m_processed,
            "bars_5m_built": self._bars_built.get("5m", 0),
            "bars_15m_built": self._bars_built.get("15m", 0),
            "bars_1h_built": self._bars_built.get("1h", 0),
            "bars_4h_built": self._bars_built.get("4h", 0),
            "bars_1d_built": self._bars_built.get("1d", 0),
            "symbols_active": set(self._symbols),
        }

    # ------------------------------------------------------------------
    # Startup initialization
    # ------------------------------------------------------------------

    async def _initialize(self, redis: Any) -> None:
        """One-time startup: restore last_emitted + warm up accumulators + set cursors.

        Called from _processing_loop after symbols are subscribed.
        """
        self._logger.info("Initializing TimeframeBuilder state", symbols=list(self._symbols))

        # Step 1: Restore _last_emitted from the last bar in each output stream.
        # This prevents re-emitting periods that were already written before restart.
        for sym in list(self._symbols):
            for tf, tf_minutes in _TARGET_TIMEFRAMES.items():
                stream_key = market(self._env_prefix, sym, tf)
                try:
                    entries = await redis.xrevrange(stream_key, count=1)
                    if not entries:
                        continue
                    _msg_id, fields = entries[0]
                    decoded = _decode_fields(fields)
                    ts_raw = decoded.get("timestamp", "0")
                    period_ts = _floor_to_period(_parse_ts(ts_raw), tf_minutes)
                    self._last_emitted.setdefault(sym, {})[tf] = period_ts
                except Exception as e:
                    self._logger.warning(
                        "Could not restore last_emitted",
                        symbol=sym, timeframe=tf, error=str(e),
                    )

        # Step 2: Warm up in-progress accumulators from recent 1m history.
        # We read enough bars to cover the longest period (1d = 1440 bars).
        # Bars are processed WITHOUT emitting — they just rebuild accumulator state
        # so the first live bar can correctly complete a partial period.
        for sym in list(self._symbols):
            stream_key_1m = market(self._env_prefix, sym, "1m")
            try:
                recent_bars = await redis.xrevrange(stream_key_1m, count=1440)
                if not recent_bars:
                    continue
                recent_bars.reverse()  # oldest first (chronological)

                for _msg_id, fields in recent_bars:
                    decoded = _decode_fields(fields)
                    ts_raw = decoded.get("timestamp", "0")
                    try:
                        ts_seconds = _parse_ts(ts_raw)
                    except Exception:
                        continue
                    try:
                        bar_data = {
                            "open": float(decoded.get("open", 0)),
                            "high": float(decoded.get("high", 0)),
                            "low": float(decoded.get("low", 0)),
                            "close": float(decoded.get("close", 0)),
                            "volume": int(float(decoded.get("volume", 0))),
                        }
                    except (ValueError, TypeError):
                        continue

                    for tf, tf_minutes in _TARGET_TIMEFRAMES.items():
                        period_ts = _floor_to_period(ts_seconds, tf_minutes)
                        acc = self._accumulators[sym][tf]
                        if acc is not None and acc["period_ts"] != period_ts:
                            # Period boundary during warmup — reset without emitting
                            acc = None
                        self._accumulators[sym][tf] = _update_accumulator(
                            acc, bar_data, period_ts
                        )
            except Exception as e:
                self._logger.warning("Warmup failed", symbol=sym, error=str(e))

        # Step 3: Set _last_ids cursors to the current stream tail.
        # We start from the last existing message ID so we don't re-process
        # bars that arrived before the service started.
        for sym in list(self._symbols):
            stream_key = market(self._env_prefix, sym, "1m")
            try:
                entries = await redis.xrevrange(stream_key, count=1)
                if entries:
                    msg_id, _ = entries[0]
                    if isinstance(msg_id, bytes):
                        msg_id = msg_id.decode()
                    self._last_ids[stream_key] = msg_id
                else:
                    self._last_ids[stream_key] = "0"
            except Exception:
                self._last_ids[stream_key] = "0"

        self._logger.info("TimeframeBuilder initialization complete", symbols=list(self._symbols))

    # ------------------------------------------------------------------
    # Processing loop
    # ------------------------------------------------------------------

    async def _processing_loop(self) -> None:
        """Main loop: xread from market:SYMBOL:1m streams, process each bar."""
        redis = self._streams_manager.redis_client

        # Wait for symbols to be subscribed before initializing
        while self._running and not self._symbols:
            await asyncio.sleep(0.1)

        if not self._running:
            return

        await self._initialize(redis)

        while self._running:
            try:
                if not self._symbols:
                    await asyncio.sleep(1.0)
                    continue

                # Ensure any symbols added after init have a cursor
                for sym in list(self._symbols):
                    stream_key = market(self._env_prefix, sym, "1m")
                    if stream_key not in self._last_ids:
                        self._last_ids[stream_key] = "$"

                # XREAD with tracked cursors — never resets to "$" per iteration
                # Pass cursor dict directly (xread expects dict as first positional arg)
                messages = await redis.xread(self._last_ids, block=1000, count=100)

                for stream_key, msgs in (messages or []):
                    # Resolve symbol from stream key: env:market:SYMBOL:1m
                    key_str = stream_key.decode() if isinstance(stream_key, bytes) else stream_key
                    parts = key_str.split(":")
                    try:
                        market_idx = parts.index("market")
                        symbol = parts[market_idx + 1]
                    except (ValueError, IndexError):
                        self._logger.warning("Unexpected stream key format", key=key_str)
                        continue

                    if symbol not in self._symbols:
                        continue

                    for msg_id, fields in msgs:
                        # Advance cursor so we never re-read this message
                        decoded_id = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
                        self._last_ids[key_str] = decoded_id

                        bar = _decode_fields(fields)
                        await self._process_bar(symbol, bar)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error("Error in processing loop", error=str(e))
                await asyncio.sleep(1.0)

    async def _process_bar(self, symbol: str, fields: dict[str, str]) -> None:
        """Process a single decoded 1m bar and update all timeframe accumulators.

        Emits a completed bar when a period boundary is crossed for any timeframe.

        Args:
            symbol: Contract symbol (e.g. "ESH6").
            fields: Decoded bar fields with string values.
        """
        try:
            ts_raw = fields.get("timestamp", "0")
            ts_seconds = _parse_ts(ts_raw)
            open_ = float(fields.get("open", 0))
            high = float(fields.get("high", 0))
            low = float(fields.get("low", 0))
            close = float(fields.get("close", 0))
            volume = int(float(fields.get("volume", 0)))
        except (ValueError, TypeError) as e:
            self._logger.warning("Bad bar fields", symbol=symbol, error=str(e))
            return

        self._bars_1m_processed += 1

        if symbol not in self._accumulators:
            self._accumulators[symbol] = {tf: None for tf in _TARGET_TIMEFRAMES}

        for tf, tf_minutes in _TARGET_TIMEFRAMES.items():
            # Skip 5m/15m/1h/4h/1d aggregation when input 1m bar has no volume
            # This prevents empty bars from non-trading hours propagating upward
            # Allow volume=0 for crypto paper trading (IBKR returns volume=0 with real prices)
            if volume == 0 and close == 0.0:
                continue

            new_period_ts = _floor_to_period(ts_seconds, tf_minutes)
            acc = self._accumulators[symbol][tf]

            if acc is not None and acc["period_ts"] != new_period_ts:
                # Period boundary crossed — emit the completed accumulator
                await self._emit_bar(symbol, tf, acc)
                acc = None  # Reset accumulator

            # Update accumulator with current bar
            bar_data: dict[str, Any] = {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "period_ts": new_period_ts,
            }
            self._accumulators[symbol][tf] = _update_accumulator(acc, bar_data, new_period_ts)

    async def _emit_bar(self, symbol: str, timeframe: str, acc: dict[str, Any]) -> None:
        """Publish a completed aggregated bar to the market:SYMBOL:TF Redis stream.

        Skips emission if this period was already emitted (prevents duplicates
        across service restarts).

        Args:
            symbol: Contract symbol.
            timeframe: Target timeframe string (e.g. "5m").
            acc: Completed accumulator dict.
        """
        period_ts = acc["period_ts"]

        # Dedup: skip if we already emitted a bar for this period
        last = self._last_emitted.get(symbol, {}).get(timeframe)
        if last is not None and period_ts <= last:
            self._logger.debug(
                "Skipping duplicate bar",
                symbol=symbol, timeframe=timeframe, period_ts=period_ts,
            )
            return

        redis = self._streams_manager.redis_client
        stream_key = market(self._env_prefix, symbol, timeframe)
        maxlen = get_stream_maxlen(timeframe, "market")

        payload = {
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": datetime.fromtimestamp(period_ts, tz=UTC).isoformat(),
            "open": str(acc["open"]),
            "high": str(acc["high"]),
            "low": str(acc["low"]),
            "close": str(acc["close"]),
            "volume": str(acc["volume"]),
            "source": "timeframe_builder",
        }

        try:
            await redis.xadd(stream_key, payload, maxlen=maxlen, approximate=True)
            self._bars_built[timeframe] = self._bars_built.get(timeframe, 0) + 1
            self._last_emitted.setdefault(symbol, {})[timeframe] = period_ts
            self._logger.debug(
                "Emitted aggregated bar",
                symbol=symbol,
                timeframe=timeframe,
                period_ts=period_ts,
            )
        except Exception as e:
            self._logger.error(
                "Failed to emit bar",
                symbol=symbol,
                timeframe=timeframe,
                error=str(e),
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_fields(fields: dict) -> dict[str, str]:
    """Decode byte-keyed Redis stream fields to str:str dict."""
    result = {}
    for k, v in fields.items():
        key = k.decode() if isinstance(k, bytes) else str(k)
        val = v.decode() if isinstance(v, bytes) else str(v)
        result[key] = val
    return result
