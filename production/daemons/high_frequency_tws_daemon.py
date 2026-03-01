#!/usr/bin/env python3
"""
High-Frequency TWS Daemon - Optimized for maximum tick throughput

Uses proper IBKR tick callbacks for real-time data instead of polling.
Designed for institutional-grade tick rates (100-500+ ticks/sec).

Performance targets:
- ES: 100-300+ ticks/sec during RTH
- NQ: 50-200+ ticks/sec during RTH
- RTY: 30-150+ ticks/sec during RTH
"""

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

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from zoneinfo import ZoneInfo

import redis
import redis.asyncio as aioredis
import structlog
from prometheus_client import start_http_server

from src.core.stream_keys import live_tick as sk_live_tick
from src.core.stream_keys import market as sk_market
from src.observability.metrics import counter as prom_counter
from src.observability.metrics import gauge as prom_gauge

# Ensure repository root is available for imports (src.*)
try:
    repo_root_path = Path(__file__).resolve().parents[2]
    if str(repo_root_path) not in sys.path:
        sys.path.insert(0, str(repo_root_path))
except Exception:
    pass

from src.config.settings import Settings
from src.core.async_tick_publisher import AsyncTickPublisher
from src.providers import IBKRProvider

logger = structlog.get_logger(__name__)

# --- Module-level constants/config ---
# Simplified tick types for futures - avoid Error 321
FUTURES_TICK_TYPES = {
    "essential": "",  # Empty for basic last/bid/ask (default)
    "volume": "233",  # RTVolume (supported on futures)
    "all": "233",  # Only RTVolume for now - most reliable
}

# Contract configuration is now handled via src/config/settings.Settings
# which provides typed access to HF_CONTRACTS_JSON with fallback defaults


class HighFrequencyTWSDaemon:
    """High-frequency TWS daemon optimized for maximum tick throughput."""

    def __init__(
        self, host: str | None = None, port: int | None = None, client_id: int | None = None
    ):
        # Centralized settings
        self.settings = Settings()
        self.host = host or self.settings.ib_host
        self.port = port or self.settings.ib_port
        self.client_id = client_id or self.settings.ib_client_id

        self.provider: IBKRProvider | None = None
        self.redis_client: redis.Redis | None = None

        self.running = False
        self.connected = False

        # High-frequency metrics
        self.ticks_processed = 0
        self.bars_processed = 0
        self.dropped_ticks = 0
        self.start_time: datetime | None = None
        self.last_health_check = 0
        self.last_tick_signature: dict[str, tuple] = {}
        self.reconnects = 0

        # Contracts via settings (env override supported)
        self.contracts = [c.model_dump() for c in self.settings.contracts]

        # Performance optimization settings
        self.health_check_interval = 30  # Log every 30 seconds

        # Stream namespacing by environment (e.g., dev:, prod:)
        env_name = self.settings.env_name.strip()
        self.env_prefix = f"{env_name}:" if env_name else ""

        # Market hours manager
        self.market_hours = MarketHoursManager()
        self.current_mode: str | None = None  # 'RTH' | 'ETH' | 'CLOSED'
        self.mode_check_interval = 60  # seconds
        self.last_mode_check_ts = 0.0

        # Minute-boundary bar polling (replaces 60s countdown)
        self.last_bar_poll_minute: int = -1       # wall-clock minute of last authoritative poll
        self.last_provisional_minute: int = -1    # wall-clock minute of last provisional flush
        # Per-symbol tick accumulator for provisional bars
        self.tick_accum: dict[str, dict] = {}

        # 1-minute bar polling (reqRealTimeBars doesn't work reliably)
        # Rolling set of seen bar timestamps per symbol (last 30 bars ~= 30 min)
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
            "indicagent_ticks_dropped_reason_total",
            "Dropped ticks by reason",
            labelnames=("reason",),
        )
        self.m_bars = prom_counter("indicagent_bars_total", "Total bars processed")
        self.m_reconnects = prom_counter("indicagent_ibkr_reconnects_total", "IBKR reconnects")
        self.g_connected = prom_gauge("indicagent_ibkr_connected", "1 when connected")
        self.g_tick_queue = prom_gauge("indicagent_tick_queue_size", "Async tick queue depth")

        # Async publishing configuration (default enabled)
        self.use_async_publish = bool(self.settings.hf_async_publish)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.loop_thread: threading.Thread | None = None
        self.async_redis: aioredis.Redis | None = None
        self.publisher: AsyncTickPublisher | None = None
        self._reconnect_delay = 1.0
        self._tick_task: asyncio.Future | None = None

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info(
            "High-Frequency TWS Daemon initialized",
            host=host,
            port=port,
            client_id=client_id,
            target_contracts=len(self.contracts),
        )

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info("Shutdown signal received", signal=signum)
        self.running = False

    def connect_redis(self) -> bool:
        """Connect to Redis with connection pooling for performance."""
        try:
            # Use connection pool for better performance
            pool = redis.ConnectionPool(
                host=self.settings.redis_host,
                port=self.settings.redis_port,
                db=self.settings.redis_db,
                max_connections=20,
                retry_on_timeout=True,
            )
            self.redis_client = redis.Redis(connection_pool=pool)
            self.redis_client.ping()
            logger.info("Connected to Redis with connection pool")
            return True
        except Exception as e:
            logger.error("Redis connection failed", error=str(e))
            return False

    def connect_tws(self) -> bool:
        """Connect to TWS via IBKRProvider."""
        try:
            logger.info(
                "Connecting to TWS for high-frequency data",
                host=self.host,
                port=self.port,
                client_id=self.client_id,
            )
            self.provider = IBKRProvider(
                host=self.host, port=self.port, client_id=self.client_id
            )
            # IBKRProvider.connect() is async — run it synchronously here
            if self.loop:
                fut = asyncio.run_coroutine_threadsafe(self.provider.connect(), self.loop)
                connected = fut.result(timeout=30)
            else:
                connected = asyncio.run(self.provider.connect())

            if connected:
                self.connected = True
                self.g_connected.set(1)
                self.current_mode = self.market_hours.get_mode(datetime.now())
                # Qualify all configured instruments
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
        """Qualify all configured instruments with IBKR."""
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
        """Consume ticks from IBKRProvider and publish to Redis."""
        if not self.provider:
            return
        symbols = [c["symbol"] for c in self.contracts]
        try:
            async for tick in self.provider.stream_ticks(symbols):
                if not self.running:
                    break
                try:
                    stream_name = sk_live_tick(self.env_prefix, tick.symbol)
                    if self.async_redis:
                        tick_fields = {k: str(v) for k, v in tick.model_dump(mode="json").items() if v is not None}
                        await self.async_redis.xadd(
                            stream_name,
                            tick_fields,
                            maxlen=10000,
                            approximate=True,
                        )
                    tick_data = {"last": tick.price, "volume": tick.size or 0}
                    self._update_tick_accumulator(tick.symbol, tick_data, datetime.now())
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

    def on_bar_update(self, symbol: str, bars_list):
        """Handle 1-minute bar updates."""
        try:
            if not bars_list:
                return

            latest_bar = bars_list[-1]
            self.bars_processed += 1

            bar_data = {
                "timestamp": latest_bar.time.isoformat(),
                "symbol": symbol,
                "timeframe": "1m",
                "open": str(latest_bar.open),
                "high": str(latest_bar.high),
                "low": str(latest_bar.low),
                "close": str(latest_bar.close),
                "volume": str(latest_bar.volume),
                "source": "hf_tws_daemon",
            }

            # Publish bar data
            if self.redis_client:
                stream_name = sk_market(self.env_prefix, symbol, "1m")
                # Bounded retention for 1m bars in the hot stream
                self.redis_client.xadd(stream_name, bar_data, maxlen=2000, approximate=True)

            logger.info(
                "High-frequency 1m bar received",
                symbol=symbol,
                time=latest_bar.time,
                close=latest_bar.close,
                volume=latest_bar.volume,
            )
            self.m_bars.inc()

        except Exception as e:
            logger.warning("Error processing high-frequency bar", symbol=symbol, error=str(e))

    def health_check(self) -> None:
        """Log high-frequency health status."""
        if not self.running or not self.start_time:
            return

        current_time = time.time()
        if current_time - self.last_health_check < self.health_check_interval:
            return

        self.last_health_check = current_time
        elapsed = (datetime.now() - self.start_time).total_seconds()
        tick_rate = self.ticks_processed / elapsed if elapsed > 0 else 0

        # Performance assessment
        performance = "🔥 HIGH" if tick_rate > 50 else "⚡ MEDIUM" if tick_rate > 10 else "🐌 LOW"

        logger.info(
            "High-frequency health check",
            uptime_minutes=round(elapsed / 60, 2),
            ticks_processed=self.ticks_processed,
            bars_processed=self.bars_processed,
            tick_rate_per_sec=round(tick_rate, 2),
            performance=performance,
            symbols=len(self.contracts),
        )

    def run(self) -> None:
        """Main high-frequency daemon loop."""
        logger.info("Starting High-Frequency TWS Daemon")
        logger.info("🚀 Target: 100-500+ ticks/sec for liquid futures")
        logger.info("=" * 60)

        try:
            # Start metrics server
            try:
                start_http_server(self.metrics_port)
                logger.info("Prometheus metrics server started", port=self.metrics_port)
            except Exception as e:
                logger.warning("Failed to start metrics server", error=str(e))

            # Connect to Redis
            if not self.connect_redis():
                logger.error("Redis connection required for high-frequency operation")
                return

            # Start async publisher (decouple callback from Redis I/O)
            if self.use_async_publish:
                self.loop = asyncio.new_event_loop()

                def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
                    asyncio.set_event_loop(loop)
                    loop.run_forever()

                self.loop_thread = threading.Thread(target=_run_loop, args=(self.loop,), daemon=True)
                self.loop_thread.start()
                self.async_redis = aioredis.Redis(
                    host=self.settings.redis_host,
                    port=self.settings.redis_port,
                    db=self.settings.redis_db,
                    max_connections=self.settings.redis_max_connections,
                )
                self.publisher = AsyncTickPublisher(
                    redis_client=self.async_redis,
                    env_prefix=self.env_prefix,
                    queue_maxsize=5000,
                    max_batch=250,
                    max_delay=0.03,
                    queue_gauge=self.g_tick_queue,
                )
                asyncio.run_coroutine_threadsafe(self.publisher.run(), self.loop)

            # Connect to TWS (also qualifies all instruments)
            if not self.connect_tws():
                logger.error("TWS connection required for high-frequency operation")
                return

            # Start tick stream in async loop
            if self.loop:
                self._tick_task = asyncio.run_coroutine_threadsafe(self._tick_loop(), self.loop)

            # Start high-frequency processing
            self.running = True
            self.start_time = datetime.now()

            logger.info("High-frequency TWS daemon started successfully")
            logger.info("⚡ Real-time tick processing active...")

            # Main loop - minimal processing, ticks handled by _tick_loop
            while self.running:
                try:
                    # Secondary disconnect detection: catches false-connected state
                    # (self.connected=True but provider actually disconnected)
                    if self.connected and self.provider and not self.provider.is_connected():
                        logger.warning(
                            "Provider reports disconnected — correcting false-connected state",
                            connected_flag=self.connected,
                        )
                        self.connected = False
                        self._on_disconnected()

                    # Attempt reconnect if disconnected
                    if not self.connected:
                        logger.warning("Disconnected from TWS, attempting reconnect...")
                        if self.connect_tws():
                            if self.loop:
                                self._tick_task = asyncio.run_coroutine_threadsafe(self._tick_loop(), self.loop)
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
                        new_mode = self.market_hours.get_mode(datetime.now())
                        self.current_mode = new_mode

                    # Minute-boundary bar events
                    now = datetime.now()
                    # Flush provisional bar at start of each new minute (seconds 0-4)
                    if now.second < 5 and self.last_provisional_minute != now.minute:
                        self.last_provisional_minute = now.minute
                        self._flush_provisional_bars(now)
                    # Fire authoritative poll at :05+ past each minute
                    if now.second >= 5 and self.last_bar_poll_minute != now.minute:
                        self.last_bar_poll_minute = now.minute
                        self.poll_1m_bars()

                    # Health monitoring
                    self.health_check()

                    # Very short sleep - ticks processed via callbacks
                    time.sleep(0.1)

                except KeyboardInterrupt:
                    logger.info("Keyboard interrupt received")
                    break
                except Exception as e:
                    logger.error("High-frequency processing error", error=str(e))
                    time.sleep(1.0)

        except Exception as e:
            logger.error("High-frequency daemon error", error=str(e))
        finally:
            self.cleanup()

    # --- Internal: Connection events ---
    def _on_disconnected(self, *args):
        """IBKR disconnected event handler."""
        logger.warning("TWS disconnected event received")
        self.connected = False
        self.g_connected.set(0)
        if self._tick_task is not None and not self._tick_task.done():
            self._tick_task.cancel()
            logger.info("Tick loop task cancelled for reconnect")

    # --- Market hours management ---
    def _tick_list_for_mode(self, mode: str) -> str:
        """Return IBKR genericTickList by market mode - simplified for futures."""
        if mode == "RTH":
            return FUTURES_TICK_TYPES["all"]
        elif mode == "ETH":
            return FUTURES_TICK_TYPES["volume"]
        else:  # CLOSED
            return ""

    def _update_tick_accumulator(self, symbol: str, tick_data: dict, now: datetime) -> None:
        """Update per-symbol OHLCV accumulator from a tick. Thread-safe under Python GIL."""
        last = tick_data.get("last")
        volume = tick_data.get("volume")
        if not last:
            return
        current_minute = (now.hour, now.minute)
        if symbol not in self.tick_accum or self.tick_accum[symbol].get("minute") != current_minute:
            self.tick_accum[symbol] = {
                "minute": current_minute,
                "open": last,
                "high": last,
                "low": last,
                "close": last,
                "vol_start": volume or 0,
                "vol_current": volume or 0,
            }
        else:
            acc = self.tick_accum[symbol]
            if last > acc["high"]:
                acc["high"] = last
            if last < acc["low"]:
                acc["low"] = last
            acc["close"] = last
            if volume is not None:
                acc["vol_current"] = volume

    def _flush_provisional_bars(self, now: datetime) -> None:
        """Publish tick-derived provisional bars for the just-closed minute.

        Called at the start of each new minute (second 0-4). Emits bars with
        source='tick_derived' so downstream services can trigger immediately.
        The authoritative reqHistoricalData correction arrives ~5s later.
        """
        if not self.redis_client:
            return
        closed_minute_ts = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
        closed_minute = (closed_minute_ts.hour, closed_minute_ts.minute)

        for symbol, acc in list(self.tick_accum.items()):
            if acc.get("minute") != closed_minute:
                continue
            if not acc.get("close"):
                continue
            volume = max(0, acc["vol_current"] - acc["vol_start"])
            bar_data = {
                "timestamp": closed_minute_ts.isoformat(),
                "symbol": symbol,
                "timeframe": "1m",
                "open": str(acc["open"]),
                "high": str(acc["high"]),
                "low": str(acc["low"]),
                "close": str(acc["close"]),
                "volume": str(volume),
                "source": "tick_derived",
            }
            stream_name = sk_market(self.env_prefix, symbol, "1m")
            self.redis_client.xadd(stream_name, bar_data, maxlen=2000, approximate=True)
            self.m_bars.inc()
            logger.info(
                "Provisional 1m bar flushed",
                symbol=symbol,
                ts=closed_minute_ts.isoformat(),
                close=acc["close"],
            )

    def poll_1m_bars(self) -> None:
        """Poll for 1-minute bars via IBKRProvider."""
        if not self.provider or not self.connected:
            return

        now = datetime.now()
        start = now - timedelta(minutes=2)

        for contract_config in self.contracts:
            symbol = contract_config["symbol"]
            try:
                if self.loop:
                    fut = asyncio.run_coroutine_threadsafe(
                        self.provider.fetch_historical_bars(symbol, "1m", start, now),
                        self.loop,
                    )
                    ohlcv_bars = fut.result(timeout=10)
                else:
                    ohlcv_bars = asyncio.run(
                        self.provider.fetch_historical_bars(symbol, "1m", start, now)
                    )

                for bar in ohlcv_bars:
                    bar_timestamp = bar.timestamp.isoformat()
                    if bar_timestamp in self.seen_bar_timestamps[symbol]:
                        continue
                    self.seen_bar_timestamps[symbol].add(bar_timestamp)
                    self.seen_bar_timestamps_order[symbol].append(bar_timestamp)
                    # Trim to last 30 to bound memory
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
                    }
                    if self.redis_client:
                        stream_name = sk_market(self.env_prefix, symbol, "1m")
                        self.redis_client.xadd(stream_name, bar_data, maxlen=2000, approximate=True)
                    logger.info("1m bar polled", symbol=symbol, close=bar.close, volume=bar.volume)
                    self.m_bars.inc()

            except Exception as e:
                logger.warning("1m bar polling error", symbol=symbol, error=str(e))

    def cleanup(self) -> None:
        """Cleanup connections and resources."""
        logger.info("Cleaning up high-frequency daemon...")

        self.running = False

        # Drain async queue or process remaining buffered ticks
        try:
            if self.publisher and self.loop and self.use_async_publish:
                logger.info("Draining async tick queue", size=self.publisher.size())
                # Give up to 2 seconds to drain
                fut = asyncio.run_coroutine_threadsafe(self.publisher.drain(timeout=2.0), self.loop)
                fut.result(timeout=3.0)
        except Exception as e:
            logger.warning("Async queue drain failed", error=str(e))

        # Disconnect from TWS via provider
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

        # Close Redis connection
        if self.redis_client:
            try:
                self.redis_client.close()
                logger.info("Disconnected from Redis")
            except Exception as e:
                logger.warning("Redis disconnect error", error=str(e))
        if self.async_redis:
            try:
                if self.loop:
                    # Ensure proper coroutine close with a small timeout
                    fut = asyncio.run_coroutine_threadsafe(self.async_redis.close(), self.loop)
                    try:
                        fut.result(timeout=1.0)
                    except Exception:
                        pass
            except Exception:
                pass
        if self.loop:
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
                if self.loop_thread:
                    self.loop_thread.join(timeout=2.0)
            except Exception:
                pass

        # Final performance stats
        if self.start_time:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            tick_rate = self.ticks_processed / elapsed if elapsed > 0 else 0

            performance_grade = (
                "🏆 EXCELLENT"
                if tick_rate > 100
                else "🔥 GOOD" if tick_rate > 50 else "⚡ FAIR" if tick_rate > 10 else "🐌 POOR"
            )

            logger.info(
                "High-frequency session complete",
                uptime_seconds=round(elapsed, 2),
                ticks_processed=self.ticks_processed,
                bars_processed=self.bars_processed,
                avg_tick_rate=round(tick_rate, 2),
                performance_grade=performance_grade,
            )

        logger.info("High-frequency TWS daemon cleanup complete")


class MarketHoursManager:
    """Minimal CME market hours manager for RTH/ETH/CLOSED classification."""

    def __init__(self) -> None:
        self.tz = ZoneInfo("US/Eastern")

    def get_mode(self, now_utc: datetime) -> str:
        """Return 'RTH', 'ETH', or 'CLOSED' based on simplified CME hours."""
        now_et = now_utc.astimezone(self.tz)
        wd = now_et.weekday()  # Monday=0
        t = now_et.time()

        # Saturday always closed
        if wd == 5:
            return "CLOSED"
        # Sunday: ETH opens at 18:00
        if wd == 6:
            return "ETH" if t >= dtime(18, 0) else "CLOSED"

        # Weekdays Mon-Fri
        # Maintenance window 17:00-18:00 (closed)
        if dtime(17, 0) <= t < dtime(18, 0):
            return "CLOSED"
        # Regular Trading Hours 09:30-16:00
        if dtime(9, 30) <= t < dtime(16, 0):
            return "RTH"
        # Otherwise ETH
        return "ETH"


def main():
    """Main entry point for high-frequency daemon."""
    import argparse

    _settings = Settings()
    parser = argparse.ArgumentParser(description="High-Frequency TWS Daemon")
    parser.add_argument("--host", default=_settings.ib_host, help="TWS host")
    parser.add_argument("--port", type=int, default=_settings.ib_port, help="TWS port")
    parser.add_argument(
        "--client-id", type=int, default=_settings.ib_client_id, help="TWS client ID"
    )

    args = parser.parse_args()

    daemon = HighFrequencyTWSDaemon(host=args.host, port=args.port, client_id=args.client_id)

    daemon.run()


if __name__ == "__main__":
    main()
