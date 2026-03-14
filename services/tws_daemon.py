#!/usr/bin/env python3
"""
TWS Daemon — Kafka-native bar and tick publisher (Phase 30: Redpanda migration)

Reads 1-minute bars from IBKR via IBKRProvider and publishes to Redpanda:
  - Bars  → dev.market.bars  (key: SYMBOL:1m)
  - Ticks → dev.market.ticks (key: SYMBOL)

Replaces production/daemons/high_frequency_tws_daemon.py Redis XADD calls.
DragonflyDB writes are fully removed. ib_insync logic remains in src/providers/ibkr.py.

Version: 1.0.0
Last Updated: 2026-03-14
Status: Current ✅
"""

from __future__ import annotations

import asyncio
import random
import signal
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from datetime import time as dtime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from zoneinfo import ZoneInfo

import structlog
from prometheus_client import start_http_server

from src.config.settings import Settings
from src.core.kafka_utils import KafkaProducerClient
from src.core.stream_keys import message_key, topic_market_bars, topic_market_ticks
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


class TwsDaemon:
    """Kafka-native TWS daemon: publishes bars to market.bars and ticks to market.ticks."""

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

        self.contracts = [c.model_dump() for c in self.settings.contracts]
        self.health_check_interval = 30

        # Stream namespacing by environment (e.g., dev, prod)
        self.env_name = self.settings.env_name.strip()

        # Market hours
        self.market_hours = MarketHoursManager()
        self.current_mode: str | None = None
        self.mode_check_interval = 60
        self.last_mode_check_ts = 0.0

        # Minute-boundary bar polling
        self.last_bar_poll_minute: int = -1

        # Seen bar dedup (last 30 bars per symbol)
        self.seen_bar_timestamps: dict[str, set[str]] = defaultdict(set)
        self.seen_bar_timestamps_order: dict[str, list[str]] = defaultdict(list)

        # Metrics
        self.metrics_port = int(self.settings.metrics_port)
        self.m_ticks = prom_counter("indicagent_ticks_total", "Total ticks processed")
        self.m_dropped = prom_counter(
            "indicagent_ticks_dropped_total", "Dropped ticks due to backpressure"
        )
        from prometheus_client import Counter as _Counter

        self.m_dropped_by_reason = _Counter(
            "indicagent_tws_ticks_dropped_reason_total",
            "Dropped ticks by reason",
            labelnames=("reason",),
        )
        self.m_bars = prom_counter("indicagent_bars_total", "Total bars processed")
        self.m_reconnects = prom_counter("indicagent_ibkr_reconnects_total", "IBKR reconnects")
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
        self._tick_task: asyncio.Future | None = None

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info(
            "TWS Daemon (Kafka) initialized",
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
            self.provider = IBKRProvider(
                host=self.host, port=self.port, client_id=self.client_id
            )
            if self.loop:
                fut = asyncio.run_coroutine_threadsafe(self.provider.connect(), self.loop)
                connected = fut.result(timeout=30)
            else:
                connected = asyncio.run(self.provider.connect())

            if connected:
                self.connected = True
                self.g_connected.set(1)
                self.current_mode = self.market_hours.get_mode(datetime.now())
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
        for instrument in self.settings.contracts:
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

    async def _tick_loop(self) -> None:
        """Consume ticks from IBKRProvider and publish to Redpanda market.ticks topic."""
        if not self.provider:
            return
        symbols = [c["symbol"] for c in self.contracts]
        try:
            async for tick in self.provider.stream_ticks(symbols):
                if not self.running:
                    break
                try:
                    tick_dict = {
                        k: str(v)
                        for k, v in tick.model_dump(mode="json").items()
                        if v is not None
                    }
                    await self._kafka_producer.publish(
                        topic_market_ticks(self.env_name),
                        tick_dict,
                        key=tick.symbol,
                    )
                    self.ticks_processed += 1
                    self.m_ticks.inc()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.dropped_ticks += 1
                    self.m_dropped.inc()
                    self.m_dropped_by_reason.labels(reason="tick_loop_error").inc()
                    logger.warning("Tick loop error", error=str(e))
        except asyncio.CancelledError:
            logger.info("Tick loop cancelled (disconnect or shutdown)")

    def health_check(self) -> None:
        if not self.running or not self.start_time:
            return
        current_time = time.time()
        if current_time - self.last_health_check < self.health_check_interval:
            return
        self.last_health_check = current_time
        elapsed = (datetime.now() - self.start_time).total_seconds()
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
        logger.info("Starting TWS Daemon (Kafka)")

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

            self.loop_thread = threading.Thread(
                target=_run_loop, args=(self.loop,), daemon=True
            )
            self.loop_thread.start()

            # Start Kafka producer in the async loop
            asyncio.run_coroutine_threadsafe(self._kafka_producer.start(), self.loop).result(
                timeout=10
            )

        if not self.connect_tws():
            logger.error("TWS connection required for operation")
            return

        if self.loop:
            self._tick_task = asyncio.run_coroutine_threadsafe(self._tick_loop(), self.loop)

        self.running = True
        self.start_time = datetime.now()

        logger.info("TWS Daemon started successfully")

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
                            self._tick_task = asyncio.run_coroutine_threadsafe(
                                self._tick_loop(), self.loop
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
                    self.current_mode = self.market_hours.get_mode(datetime.now())

                now = datetime.now()
                if now.second >= 5 and self.last_bar_poll_minute != now.minute:
                    self.last_bar_poll_minute = now.minute
                    self.poll_1m_bars()

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
        if self._tick_task is not None and not self._tick_task.done():
            self._tick_task.cancel()
            logger.info("Tick loop task cancelled for reconnect")

    def poll_1m_bars(self) -> None:
        if not self.provider or not self.connected or not self.loop:
            logger.warning("poll_1m_bars skipped - provider not connected or no loop")
            return

        now = datetime.now()
        start = now - timedelta(minutes=2)

        async def _gather_all() -> None:
            sem = asyncio.Semaphore(5)

            async def _with_sem(symbol: str) -> None:
                async with sem:
                    await self._fetch_bars_for_symbol(symbol, start, now)

            symbols = [c["symbol"] for c in self.contracts]
            await asyncio.gather(*[_with_sem(s) for s in symbols], return_exceptions=True)

        fut = asyncio.run_coroutine_threadsafe(_gather_all(), self.loop)
        fut.result(timeout=30)

    async def _fetch_bars_for_symbol(
        self, symbol: str, start: datetime, now: datetime
    ) -> int:
        """Fetch 1-minute bars for a symbol and publish to Redpanda market.bars.

        Returns count of newly published bars (0 if all were duplicates).
        """
        try:
            ohlcv_bars = await self.provider.fetch_historical_bars(symbol, "1m", start, now)
            if not ohlcv_bars:
                logger.warning("poll_1m_bars: 0 bars returned", symbol=symbol)
                return 0

            bars_published = 0
            for bar in ohlcv_bars:
                bar_timestamp = bar.timestamp.isoformat()
                if bar_timestamp in self.seen_bar_timestamps[symbol]:
                    continue
                self.seen_bar_timestamps[symbol].add(bar_timestamp)
                self.seen_bar_timestamps_order[symbol].append(bar_timestamp)
                if len(self.seen_bar_timestamps_order[symbol]) > 30:
                    evicted = self.seen_bar_timestamps_order[symbol].pop(0)
                    self.seen_bar_timestamps[symbol].discard(evicted)

                self.bars_processed += 1
                bar_data = {
                    "timestamp": bar_timestamp,
                    "symbol": symbol,
                    "timeframe": "1m",
                    "open": str(bar.open),
                    "high": str(bar.high),
                    "low": str(bar.low),
                    "close": str(bar.close),
                    "volume": str(bar.volume),
                    "source": "authoritative",
                    "bar_close_ts": bar_timestamp,
                }
                await self._kafka_producer.publish(
                    topic_market_bars(self.env_name),
                    bar_data,
                    key=message_key(symbol, "1m"),
                )
                logger.info("1m bar polled", symbol=symbol, close=bar.close, volume=bar.volume)
                self.m_bars.inc()
                bars_published += 1

            return bars_published

        except Exception as e:
            logger.warning("1m bar polling error", symbol=symbol, error=str(e))
            return 0

    def cleanup(self) -> None:
        logger.info("Cleaning up TWS Daemon...")
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
            elapsed = (datetime.now() - self.start_time).total_seconds()
            tick_rate = self.ticks_processed / elapsed if elapsed > 0 else 0
            logger.info(
                "TWS Daemon session complete",
                uptime_seconds=round(elapsed, 2),
                ticks_processed=self.ticks_processed,
                bars_processed=self.bars_processed,
                avg_tick_rate=round(tick_rate, 2),
            )

        logger.info("TWS Daemon cleanup complete")


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
    parser = argparse.ArgumentParser(description="TWS Daemon (Kafka)")
    parser.add_argument("--host", default=_settings.ib_host)
    parser.add_argument("--port", type=int, default=_settings.ib_port)
    parser.add_argument("--client-id", type=int, default=_settings.ib_client_id)

    args = parser.parse_args()

    daemon = TwsDaemon(host=args.host, port=args.port, client_id=args.client_id)
    daemon.run()


if __name__ == "__main__":
    main()
