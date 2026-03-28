#!/usr/bin/env python3
"""
DataProviderAgent - Kafka-native bar and tick publisher

Dual-stream architecture from IBKR:
  - 5s RealTimeBars → aggregated 1m OHLCV → market.bars (published)
  - Official 1m bars (keepUpToDate) → reconciliation check (drift logging)
  - Each 5s close → market.ticks for live dashboard pricing

Reconciliation compares 5s-derived vs official close; logs drift if >0.01%.

Metrics:
  - indicagent_bars_total: 1m bars published
  - indicagent_ticks_total: 5s price updates
  - indicagent_bar_drift_total: reconciliation drift events
  - indicagent_ibkr_connected: connection status gauge

Version: 1.2.0
Last Updated: 2026-03-28
Status: Current
"""

from __future__ import annotations

import asyncio
import random
import signal
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from zoneinfo import ZoneInfo

import structlog
from prometheus_client import Counter as _Counter
from prometheus_client import start_http_server

from src.config.settings import Settings, get_active_contracts
from src.core.kafka_utils import KafkaProducerClient
from src.core.stream_keys import (
    message_key,
    topic_market_bars,
    topic_market_ticks,
)
from src.observability.metrics import counter as prom_counter
from src.observability.metrics import gauge as prom_gauge
from src.providers import IBKRProvider

logger = structlog.get_logger(__name__)

# Simplified tick types for futures - avoid Error 321
FUTURES_TICK_TYPES = {
    "essential": "",
    "volume": "233",
    "all": "233",
}

class DataProviderAgent:
    """Kafka-native data provider agent: publishes bars to market.bars and ticks to market.ticks."""

    def __init__(
        self, host: str | None = None, port: int | None = None, client_id: int | None = None
    ):
        self.settings = Settings()
        self.host = host or self.settings.ib_host
        self.port = port or self.settings.ib_port
        self.client_id = client_id or self.settings.ib_client_id

        self.provider: IBKRProvider | None = None

        self.running = False
        self.connected = False

        # High-frequency metrics
        self.ticks_processed = 0
        self.bars_processed = 0
        self.dropped_ticks = 0
        self.start_time: datetime | None = None
        self.last_health_check = 0
        self.reconnects = 0

        self.contracts = [c.model_dump() for c in get_active_contracts(self.settings)]
        self._symbol_to_base: dict[str, str] = {
            c["symbol"]: c.get("base", c["symbol"]) for c in self.contracts
        }
        self.health_check_interval = 30

        # Stream namespacing by environment (e.g., dev, prod)
        self.env_name = self.settings.env_name.strip()

        # Market hours
        self.market_hours = MarketHoursManager()
        self.current_mode: str | None = None
        self.mode_check_interval = 60
        self.last_mode_check_ts = 0.0

        # Seen bar dedup (last 30 bars per symbol)
        self.seen_bar_timestamps: dict[str, set[str]] = defaultdict(set)
        self.seen_bar_timestamps_order: dict[str, deque] = defaultdict(lambda: deque(maxlen=30))

        # Metrics
        self.metrics_port = int(self.settings.metrics_port)
        self.m_ticks = prom_counter("indicagent_ticks_total", "Total ticks processed")
        self.m_dropped = prom_counter(
            "indicagent_ticks_dropped_total", "Dropped ticks due to backpressure"
        )
        self.m_dropped_by_reason = _Counter(
            "indicagent_tws_ticks_dropped_reason_total",
            "Dropped ticks by reason",
            labelnames=("reason",),
        )
        self.m_bars = prom_counter("indicagent_bars_total", "Total bars processed")
        self.m_reconnects = prom_counter("indicagent_ibkr_reconnects_total", "IBKR reconnects")
        self.m_drift = prom_counter(
            "indicagent_bar_drift_total", "Discrepancies between 5s-derived and official bars"
        )
        self.g_connected = prom_gauge("indicagent_ibkr_connected", "1 when connected")
        self.g_tick_queue = prom_gauge("indicagent_tick_queue_size", "Async tick queue depth")

        # Kafka producer (replaces async_redis XADD calls)
        self._kafka_producer: KafkaProducerClient = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers
        )

        # Async loop (for tick loop + bar polling)
        self.use_async_publish = bool(self.settings.hf_async_publish)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.loop_thread: threading.Thread | None = None
        self._reconnect_delay = 1.0
        self._rtb_task: asyncio.Future | None = None
        self._official_task: asyncio.Future | None = None
        self._heartbeat_task: asyncio.Future | None = None

        # Per-symbol RTB state: symbol -> {open, high, low, close, volume, bar_minute, emitted}
        self._rtb_state: dict[str, dict] = {}
        # Reconciliation state: symbol -> {ts: OHLCVBar}
        self._official_bars_cache: dict[str, dict[str, Any]] = defaultdict(dict)
        # Sentinel for unset prev_close (distinguishes None from 0.0 price)
        self._UNSET = object()

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info(
            "DataProviderAgent (Kafka) initialized",
            host=host,
            port=port,
            client_id=client_id,
            target_contracts=len(self.contracts),
        )

    def _signal_handler(self, signum, frame):
        logger.info("Shutdown signal received", signal=signum)
        self.running = False

    def connect_tws(self) -> bool:
        try:
            self.provider = IBKRProvider(host=self.host, port=self.port, client_id=self.client_id)
            if self.loop:
                fut = asyncio.run_coroutine_threadsafe(self.provider.connect(), self.loop)
                connected = fut.result(timeout=30)
            else:
                connected = asyncio.run(self.provider.connect())

            if connected:
                self.connected = True
                self.g_connected.set(1)
                self.current_mode = self.market_hours.get_mode(datetime.now(UTC))
                self._qualify_all_instruments()
                logger.info("Connected to TWS via IBKRProvider")
                return True
            else:
                logger.error("TWS connection failed")
                return False
        except Exception as e:
            logger.error("TWS connection error", error=str(e))
            return False

    def _qualify_all_instruments(self) -> None:
        if not self.provider:
            return
        for instrument in get_active_contracts(self.settings):
            try:
                if self.loop:
                    fut = asyncio.run_coroutine_threadsafe(
                        self.provider.qualify_instrument(instrument), self.loop
                    )
                    fut.result(timeout=10)
                else:
                    asyncio.run(self.provider.qualify_instrument(instrument))
            except Exception as e:
                logger.warning("qualify_instrument failed", symbol=instrument.symbol, error=str(e))

    async def _rtb_loop(self) -> None:
        """Consume 5-second RealTimeBars from IBKRProvider and aggregate to 1m bars.

        Maintains per-symbol OHLCV state. Data is EMITTED by _heartbeat_loop
        to ensure deterministic timing even during quiet periods (FX/Crypto).
        """
        if not self.provider:
            return
        symbols = [c["symbol"] for c in self.contracts]

        def _init_state(minute=None, prev_close=None) -> dict:
            return {
                "bar_minute": minute,
                "open": None,
                "high": None,
                "low": None,
                "close": None,
                "volume": 0.0,
                "last_update": time.time(),
                "emitted": False,
                "prev_close": prev_close if prev_close is not None else self._UNSET
            }

        try:
            async for symbol, rtb in self.provider.stream_real_time_bars(symbols):
                if not self.running:
                    break
                try:
                    bar_minute = rtb.time.replace(second=0, microsecond=0)
                    s = self._rtb_state.setdefault(symbol, _init_state(bar_minute))

                    # If this 5s bar belongs to a newer minute than our current state,
                    # it means the heartbeat should have already emitted the old one.
                    # We update state to the new minute.
                    if s["bar_minute"] is not None and bar_minute > s["bar_minute"]:
                        if not s["emitted"]:
                            # Force emit the stale bar if the heartbeat was late
                            await self._emit_bar(symbol, s)
                        # Carry forward close price for flat bar emission if next minute has no 5s ticks
                        prev_close = s.get("prev_close", self._UNSET)
                        s.update(_init_state(bar_minute, prev_close))

                    if s["bar_minute"] is None or bar_minute >= s["bar_minute"]:
                        if s["open"] is None:
                            s["open"] = rtb.open_
                        s["high"] = max(s["high"] or rtb.high, rtb.high)
                        s["low"] = min(s["low"] or rtb.low, rtb.low)
                        s["close"] = rtb.close
                        s["volume"] += rtb.volume
                        s["last_update"] = time.time()

                    # Publish 5s close as price update for dashboard
                    await self._kafka_producer.publish(
                        topic_market_ticks(self.env_name),
                        {
                            "symbol": symbol,
                            "price": str(rtb.close),
                            "timestamp": rtb.time.isoformat(),
                            "source": "ibkr",
                        },
                        key=symbol,
                    )
                    self.ticks_processed += 1
                    self.m_ticks.inc()

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning("RTB loop error", symbol=symbol, error=str(e))

        except asyncio.CancelledError:
            logger.info("RTB loop cancelled")

    async def _official_bars_loop(self) -> None:
        """Consume official, audited 1m bars from IBKR for reconciliation."""
        if not self.provider:
            return
        symbols = [c["symbol"] for c in self.contracts]

        try:
            async for symbol, bar in self.provider.stream_official_bars(symbols):
                if not self.running:
                    break
                # Store in cache for heartbeat/emit to compare
                ts_str = bar.timestamp.isoformat()
                self._official_bars_cache[symbol][ts_str] = bar

                # Cleanup old cache entries (keep last 20)
                if len(self._official_bars_cache[symbol]) > 20:
                    oldest_ts = min(self._official_bars_cache[symbol].keys())
                    del self._official_bars_cache[symbol][oldest_ts]

        except asyncio.CancelledError:
            logger.info("Official bars loop cancelled")
        except Exception as e:
            logger.error("Official bars loop error", error=str(e))

    async def _heartbeat_loop(self) -> None:
        """Deterministic bar emission loop.

        Runs every 1s. Checks if current_time > bar_minute + 61s.
        If yes, emits the bar regardless of whether new data arrived.
        """
        while self.running:
            try:
                now_utc = datetime.now(UTC)
                # Check all active symbols for minutes that need sealing
                for symbol in self._symbol_to_base:
                    s = self._rtb_state.get(symbol)
                    if not s or not s["bar_minute"]:
                        continue

                    # If we are at least 1 second into the NEXT minute, emit the PREVIOUS minute
                    # e.g. at 10:01:01, emit the 10:00:00 bar.
                    if now_utc >= s["bar_minute"] + timedelta(seconds=61) and not s["emitted"]:
                        await self._emit_bar(symbol, s)
                        s["emitted"] = True

                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat loop error", error=str(e))
                await asyncio.sleep(1)

    async def _emit_bar(self, symbol: str, state: dict) -> None:
        """Publish completed 1m bar and perform reconciliation with official source."""
        bar_minute = state["bar_minute"]
        bar_timestamp = bar_minute.isoformat()

        # Dedup guard
        if bar_timestamp in self.seen_bar_timestamps[symbol]:
            return
        self.seen_bar_timestamps[symbol].add(bar_timestamp)
        order = self.seen_bar_timestamps_order[symbol]
        if len(order) >= 30:
            evicted = order[0]
            self.seen_bar_timestamps[symbol].discard(evicted)
        order.append(bar_timestamp)  # deque(maxlen=30) auto-evicts oldest on overflow

        # 1. Reconciliation (Renaissance Audit)
        official = self._official_bars_cache.get(symbol, {}).get(bar_timestamp)
        drift_detected = False
        if official:
            # Check close price drift (threshold: 0.01%)
            price_diff = abs(float(state["close"]) - official.close)
            if price_diff > (official.close * 0.0001):
                drift_detected = True
                self.m_drift.inc()
                logger.warning(
                    "Data drift detected",
                    symbol=symbol,
                    ts=bar_timestamp,
                    derived=state["close"],
                    official=official.close,
                    diff=price_diff
                )

        # Handle the case where state is completely empty (no 5s data for the minute)
        # Use official bar data if available, otherwise flat bar from prev close
        if state["open"] is None:
            if official:
                state.update({
                    "open": official.open,
                    "high": official.high,
                    "low": official.low,
                    "close": official.close,
                    "volume": official.volume
                })
            else:
                # Emit flat bar using previous close (canonical 1440-bar grid)
                prev_close = state.get("prev_close", self._UNSET)
                if prev_close is not self._UNSET:
                    flat_price = float(prev_close)
                    flat_bar_data = {
                        "timestamp": bar_timestamp,
                        "symbol": symbol,
                        "timeframe": "1m",
                        "open": str(flat_price),
                        "high": str(flat_price),
                        "low": str(flat_price),
                        "close": str(flat_price),
                        "volume": "0.0",
                        "source": "authoritative",
                        "bar_close_ts": bar_timestamp,
                        "is_reconciled": False,
                        "drift_detected": False
                    }
                    await self._kafka_producer.publish(
                        topic_market_bars(self.env_name),
                        flat_bar_data,
                        key=message_key(symbol, "1m"),
                    )
                    self.bars_processed += 1
                    self.m_bars.inc()
                    # Track close price for next flat bar
                    state["prev_close"] = flat_price
                    logger.info("Flat bar emitted", symbol=symbol, close=flat_price, ts=bar_timestamp)
                    return  # Early exit after flat bar emission
                else:
                    # No previous close available - skip this bar
                    logger.warning("No data for bar emission and no prev_close", symbol=symbol, ts=bar_timestamp)
                    return

        bar_data = {
            "timestamp": bar_timestamp,
            "symbol": symbol,
            "timeframe": "1m",
            "open": str(state["open"]),
            "high": str(state["high"]),
            "low": str(state["low"]),
            "close": str(state["close"]),
            "volume": str(state["volume"]),
            "source": "authoritative",
            "bar_close_ts": bar_timestamp,
            "is_reconciled": bool(official),
            "drift_detected": drift_detected
        }
        await self._kafka_producer.publish(
            topic_market_bars(self.env_name),
            bar_data,
            key=message_key(symbol, "1m"),
        )
        self.bars_processed += 1
        self.m_bars.inc()

        # Track close price for next flat bar
        state["prev_close"] = float(state["close"])

        logger.info(
            "1m bar emitted",
            symbol=symbol,
            close=state["close"],
            vol=state["volume"],
            reconciled=bool(official)
        )

    def health_check(self) -> None:
        if not self.running or not self.start_time:
            return
        current_time = time.time()
        if current_time - self.last_health_check < self.health_check_interval:
            return
        self.last_health_check = current_time
        elapsed = (datetime.now(UTC) - self.start_time).total_seconds()
        tick_rate = self.ticks_processed / elapsed if elapsed > 0 else 0
        performance = "HIGH" if tick_rate > 50 else "MEDIUM" if tick_rate > 10 else "LOW"
        logger.info(
            "Health check",
            uptime_minutes=round(elapsed / 60, 2),
            ticks_processed=self.ticks_processed,
            bars_processed=self.bars_processed,
            tick_rate_per_sec=round(tick_rate, 2),
            performance=performance,
        )

    def run(self) -> None:
        logger.info("Starting DataProviderAgent (Kafka)")

        try:
            start_http_server(self.metrics_port)
            logger.info("Prometheus metrics server started", port=self.metrics_port)
        except Exception as e:
            logger.warning("Failed to start metrics server", error=str(e))

        if self.use_async_publish:
            self.loop = asyncio.new_event_loop()

            def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
                asyncio.set_event_loop(loop)
                loop.run_forever()

            self.loop_thread = threading.Thread(target=_run_loop, args=(self.loop,), daemon=True)
            self.loop_thread.start()

            # Start Kafka producer in the async loop
            asyncio.run_coroutine_threadsafe(self._kafka_producer.start(), self.loop).result(
                timeout=10
            )

        if not self.connect_tws():
            logger.error("TWS connection required for operation")
            return

        if self.loop:
            self._rtb_task = asyncio.run_coroutine_threadsafe(self._rtb_loop(), self.loop)
            self._official_task = asyncio.run_coroutine_threadsafe(
                self._official_bars_loop(), self.loop
            )
            self._heartbeat_task = asyncio.run_coroutine_threadsafe(
                self._heartbeat_loop(), self.loop
            )

        self.running = True
        self.start_time = datetime.now(UTC)

        logger.info("DataProviderAgent started successfully")

        while self.running:
            try:
                if self.connected and self.provider and not self.provider.is_connected():
                    logger.warning("Provider reports disconnected")
                    self.connected = False
                    self._on_disconnected()

                if not self.connected:
                    logger.warning("Disconnected from TWS, attempting reconnect...")
                    if self.connect_tws():
                        if self.loop:
                            self._rtb_task = asyncio.run_coroutine_threadsafe(
                                self._rtb_loop(), self.loop
                            )
                            self._official_task = asyncio.run_coroutine_threadsafe(
                                self._official_bars_loop(), self.loop
                            )
                            self._heartbeat_task = asyncio.run_coroutine_threadsafe(
                                self._heartbeat_loop(), self.loop
                            )
                        self.m_reconnects.inc()
                        self.reconnects += 1
                        self._reconnect_delay = 1.0
                    else:
                        time.sleep(self._reconnect_delay)
                        self._reconnect_delay = min(
                            self._reconnect_delay * 2 + random.uniform(0.0, 0.5), 16.0
                        )
                        continue

                now_ts = time.time()
                if now_ts - self.last_mode_check_ts >= self.mode_check_interval:
                    self.last_mode_check_ts = now_ts
                    self.current_mode = self.market_hours.get_mode(datetime.now(UTC))

                self.health_check()
                time.sleep(0.1)

            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received")
                break
            except Exception as e:
                logger.error("Processing error", error=str(e))
                time.sleep(1.0)

        self.cleanup()

    def _on_disconnected(self, *args):
        logger.warning("TWS disconnected event received")
        self.connected = False
        self.g_connected.set(0)
        for task in [self._rtb_task, self._official_task, self._heartbeat_task]:
            if task is not None and not task.done():
                task.cancel()
        logger.info("Background tasks cancelled for reconnect")

    def cleanup(self) -> None:
        logger.info("Cleaning up DataProviderAgent...")
        self.running = False

        # Stop Kafka producer
        if self.loop and self._kafka_producer:
            try:
                fut = asyncio.run_coroutine_threadsafe(self._kafka_producer.stop(), self.loop)
                fut.result(timeout=5)
            except Exception as e:
                logger.warning("Kafka producer stop failed", error=str(e))

        if self.provider and self.provider.is_connected():
            try:
                if self.loop:
                    fut = asyncio.run_coroutine_threadsafe(self.provider.disconnect(), self.loop)
                    fut.result(timeout=5)
                else:
                    asyncio.run(self.provider.disconnect())
                logger.info("Disconnected from TWS")
            except Exception as e:
                logger.warning("TWS disconnect error", error=str(e))

        if self.loop:
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
                if self.loop_thread:
                    self.loop_thread.join(timeout=2.0)
            except Exception:
                pass

        if self.start_time:
            elapsed = (datetime.now(UTC) - self.start_time).total_seconds()
            tick_rate = self.ticks_processed / elapsed if elapsed > 0 else 0
            logger.info(
                "DataProviderAgent session complete",
                uptime_seconds=round(elapsed, 2),
                ticks_processed=self.ticks_processed,
                bars_processed=self.bars_processed,
                avg_tick_rate=round(tick_rate, 2),
            )

        logger.info("DataProviderAgent cleanup complete")


class MarketHoursManager:
    """Minimal CME market hours manager for RTH/ETH/CLOSED classification."""

    def __init__(self) -> None:
        self.tz = ZoneInfo("US/Eastern")

    def get_mode(self, now_utc: datetime) -> str:
        now_et = now_utc.astimezone(self.tz)
        wd = now_et.weekday()
        t = now_et.time()

        if wd == 5:
            return "CLOSED"
        if wd == 6:
            return "ETH" if t >= dtime(18, 0) else "CLOSED"

        if dtime(17, 0) <= t < dtime(18, 0):
            return "CLOSED"
        if dtime(9, 30) <= t < dtime(16, 0):
            return "RTH"
        return "ETH"


def main():
    import argparse

    _settings = Settings()
    parser = argparse.ArgumentParser(description="DataProviderAgent (Kafka)")
    parser.add_argument("--host", default=_settings.ib_host)
    parser.add_argument("--port", type=int, default=_settings.ib_port)
    parser.add_argument("--client-id", type=int, default=_settings.ib_client_id)

    args = parser.parse_args()

    daemon = DataProviderAgent(host=args.host, port=args.port, client_id=args.client_id)
    daemon.run()


if __name__ == "__main__":
    main()
