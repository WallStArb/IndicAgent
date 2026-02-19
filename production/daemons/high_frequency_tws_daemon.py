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
from datetime import datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import Any

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from zoneinfo import ZoneInfo

import redis
import redis.asyncio as aioredis
import structlog
from ib_insync import IB, Future, Ticker
from prometheus_client import start_http_server

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

        self.ib: IB | None = None
        self.redis_client: redis.Redis | None = None

        self.running = False
        self.connected = False
        self.subscribed_symbols: set[str] = set()
        self.qualified_contracts: dict[str, object] = {}

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

        # IBKR subscriptions state
        self.tickers_by_symbol: dict[str, Ticker] = {}

        # Minute-boundary bar polling (replaces 60s countdown)
        self.last_bar_poll_minute: int = -1       # wall-clock minute of last authoritative poll
        self.last_provisional_minute: int = -1    # wall-clock minute of last provisional flush
        # Per-symbol tick accumulator for provisional bars
        self.tick_accum: dict[str, dict] = {}

        # 1-minute bar polling (reqRealTimeBars doesn't work reliably)
        self.last_bar_timestamps: dict[str, str] = {}  # Track last bar per symbol

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
        """Connect to TWS with optimized settings."""
        try:
            logger.info(
                "Connecting to TWS for high-frequency data",
                host=self.host,
                port=self.port,
                client_id=self.client_id,
            )

            self.ib = IB()
            self.ib.connect(
                host=self.host, port=self.port, clientId=self.client_id, timeout=20, readonly=False
            )

            if self.ib.isConnected():
                accounts = self.ib.managedAccounts()
                self.connected = True
                self.g_connected.set(1)
                logger.info("Connected to TWS successfully", accounts=accounts)

                # Set up high-frequency market data processing
                self.ib.pendingTickersEvent += self.on_pending_tickers
                # Reconnection handling
                self.ib.disconnectedEvent += self._on_disconnected
                # Initialize current mode
                self.current_mode = self.market_hours.get_mode(datetime.now())

                return True
            else:
                logger.error("TWS connection failed")
                return False

        except Exception as e:
            logger.error("TWS connection error", error=str(e))
            return False

    def on_pending_tickers(self, tickers):
        """High-frequency callback for tick updates."""
        current_time = datetime.now()

        for ticker in tickers:
            if ticker.contract.localSymbol in self.subscribed_symbols:
                # Extract tick data immediately
                symbol = ticker.contract.localSymbol

                # Process different tick types
                tick_data = self._build_tick_data(symbol, ticker, current_time)
                if self.use_async_publish and self.publisher and self.loop:
                    try:
                        asyncio.run_coroutine_threadsafe(
                            self.publisher.publish_tick(symbol, tick_data), self.loop
                        )
                        self.ticks_processed += 1
                        self.m_ticks.inc()
                        self._update_tick_accumulator(symbol, tick_data, current_time)
                    except Exception as e:
                        self.dropped_ticks += 1
                        self.m_dropped.inc()
                        self.m_dropped_by_reason.labels(reason="async_enqueue_error").inc()
                        logger.warning("Async enqueue failed", error=str(e))

    @staticmethod
    def _build_tick_data(symbol: str, ticker: Ticker, now: datetime) -> dict[str, Any]:
        """Extract fields from ib_insync.Ticker into our tick schema."""
        tick_data: dict[str, Any] = {
            "symbol": symbol,
            "timestamp": now.isoformat(),
            "source": "hf_tws_daemon",
        }
        try:
            # Market, bid/ask, sizes and last trade info
            price = ticker.marketPrice()
            if price and price > 0:
                tick_data["price"] = float(price)
            if getattr(ticker, "bid", None):
                if ticker.bid > 0:
                    tick_data["bid"] = float(ticker.bid)
            if getattr(ticker, "ask", None):
                if ticker.ask > 0:
                    tick_data["ask"] = float(ticker.ask)
            if getattr(ticker, "bidSize", None):
                if ticker.bidSize > 0:
                    tick_data["bid_size"] = int(ticker.bidSize)
            if getattr(ticker, "askSize", None):
                if ticker.askSize > 0:
                    tick_data["ask_size"] = int(ticker.askSize)
            if getattr(ticker, "volume", None):
                if ticker.volume:
                    tick_data["volume"] = int(ticker.volume)
            if getattr(ticker, "last", None):
                if ticker.last and ticker.last > 0:
                    tick_data["last"] = float(ticker.last)
            if getattr(ticker, "lastSize", None):
                if ticker.lastSize:
                    tick_data["last_size"] = int(ticker.lastSize)
        except Exception:
            # Keep critical path robust; upstream validation handles anomalies
            pass
        return tick_data

    def subscribe_to_contracts(self) -> bool:
        """Subscribe to high-frequency tick data."""
        if not self.connected or not self.ib:
            return False

        successful_subscriptions = 0

        for contract_config in self.contracts:
            try:
                logger.info(
                    "Subscribing to high-frequency contract", symbol=contract_config["symbol"]
                )

                # Create and qualify contract
                contract = Future(
                    symbol=contract_config["base"],
                    lastTradeDateOrContractMonth=contract_config["expiry"],
                    exchange=contract_config["exchange"],
                )

                details = self.ib.reqContractDetails(contract)
                if not details:
                    logger.warning("No contract details", symbol=contract_config["symbol"])
                    continue

                qualified_contract = details[0].contract

                # Subscribe to optimized tick data for futures: RTVolume for high-frequency ticks
                tick_list = self._tick_list_for_mode(self.current_mode or "ETH")
                ticker = self.ib.reqMktData(
                    qualified_contract,
                    genericTickList=tick_list,
                    snapshot=False,
                    regulatorySnapshot=False,
                )

                # Note: reqRealTimeBars doesn't work reliably, we'll poll 1m historical bars instead

                # Store references
                self.subscribed_symbols.add(contract_config["symbol"])
                self.qualified_contracts[contract_config["symbol"]] = qualified_contract
                self.tickers_by_symbol[contract_config["symbol"]] = ticker
                successful_subscriptions += 1

                logger.info(
                    "High-frequency subscription successful",
                    symbol=contract_config["symbol"],
                    local_symbol=qualified_contract.localSymbol,
                )

                time.sleep(0.05)  # Minimal delay between subscriptions

            except Exception as e:
                logger.error(
                    "High-frequency subscription failed",
                    symbol=contract_config["symbol"],
                    error=str(e),
                )

        if successful_subscriptions > 0:
            logger.info(
                "High-frequency subscriptions complete",
                successful=successful_subscriptions,
                total=len(self.contracts),
            )
            return True
        else:
            logger.error("No high-frequency subscriptions successful")
            return False

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
            symbols=len(self.subscribed_symbols),
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
                self.loop_thread = threading.Thread(target=self.loop.run_forever, daemon=True)
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

            # Connect to TWS
            if not self.connect_tws():
                logger.error("TWS connection required for high-frequency operation")
                return

            # Subscribe to contracts
            if not self.subscribe_to_contracts():
                logger.error("No contract subscriptions for high-frequency operation")
                return

            # Start high-frequency processing
            self.running = True
            self.start_time = datetime.now()

            logger.info("High-frequency TWS daemon started successfully")
            logger.info("⚡ Real-time tick processing active...")

            # Main loop - minimal processing, ticks handled by callbacks
            while self.running:
                try:
                    # Attempt reconnect if disconnected
                    if not self.connected:
                        logger.warning("Disconnected from TWS, attempting reconnect...")
                        if self.connect_tws():
                            # Re-subscribe after reconnect
                            self.subscribe_to_contracts()
                            self.m_reconnects.inc()
                            self.reconnects += 1
                            self._reconnect_delay = 1.0
                        else:
                            time.sleep(self._reconnect_delay)
                            # Exponential backoff with jitter
                            self._reconnect_delay = min(
                                self._reconnect_delay * 2 + random.uniform(0.0, 0.5), 16.0
                            )
                            continue
                    # Adjust subscription intensity by market hours every minute
                    now_ts = time.time()
                    if now_ts - self.last_mode_check_ts >= self.mode_check_interval:
                        self.last_mode_check_ts = now_ts
                        self.adjust_subscription_intensity()

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

    # --- Market hours & tick list management ---
    def _tick_list_for_mode(self, mode: str) -> str:
        """Return IBKR genericTickList by market mode - simplified for futures."""
        # For futures, start simple to avoid Error 321
        if mode == "RTH":
            return FUTURES_TICK_TYPES["all"]  # Just RTVolume
        elif mode == "ETH":
            return FUTURES_TICK_TYPES["volume"]  # Just RTVolume
        else:  # CLOSED
            return ""  # Empty - let IBKR provide default last/bid/ask

    def adjust_subscription_intensity(self) -> None:
        """Adjust tick subscriptions based on market hours (RTH/ETH/CLOSED)."""
        if not self.ib or not self.connected:
            return
        new_mode = self.market_hours.get_mode(datetime.now())
        if new_mode == self.current_mode:
            return
        try:
            tick_list = self._tick_list_for_mode(new_mode)
            # Re-subscribe each symbol with new tick list
            for symbol, qualified_contract in self.qualified_contracts.items():
                # Cancel existing market data if present
                prev_ticker = self.tickers_by_symbol.get(symbol)
                if prev_ticker is not None:
                    try:
                        self.ib.cancelMktData(prev_ticker.contract)
                    except Exception:
                        pass
                # Request new market data with updated tick list
                new_ticker = self.ib.reqMktData(
                    qualified_contract,
                    genericTickList=tick_list,
                    snapshot=False,
                    regulatorySnapshot=False,
                )
                self.tickers_by_symbol[symbol] = new_ticker
            logger.info(
                "Adjusted subscription intensity", old_mode=self.current_mode, new_mode=new_mode
            )
            self.current_mode = new_mode
        except Exception as e:
            logger.warning("Failed to adjust subscription intensity", error=str(e))

    def _update_tick_accumulator(self, symbol: str, tick_data: dict, now: datetime) -> None:
        """Update per-symbol OHLCV accumulator from a tick. Thread-safe under Python GIL."""
        last = tick_data.get("last")
        volume = tick_data.get("volume")
        if not last:
            return
        current_minute = now.minute
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
        closed_minute = closed_minute_ts.minute

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
        """Poll for 1-minute bars using historical data since reqRealTimeBars is unreliable."""
        if not self.ib or not self.connected:
            return

        for symbol, qualified_contract in self.qualified_contracts.items():
            try:
                # Request latest 2 bars to catch new completed bars
                bars = self.ib.reqHistoricalData(
                    qualified_contract,
                    endDateTime="",
                    durationStr="120 S",  # 120 seconds = 2 minutes
                    barSizeSetting="1 min",
                    whatToShow="TRADES",
                    useRTH=False,
                    formatDate=2,  # Unix timestamp format
                )

                if not bars:
                    continue

                # Process each bar, checking for new ones
                for bar in bars:
                    bar_timestamp = bar.date.isoformat()

                    # Skip if we've already processed this bar
                    if self.last_bar_timestamps.get(symbol) == bar_timestamp:
                        continue

                    # New bar - process it
                    self.last_bar_timestamps[symbol] = bar_timestamp
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

                    # Publish to Redis stream
                    if self.redis_client:
                        stream_name = sk_market(self.env_prefix, symbol, "1m")
                        self.redis_client.xadd(stream_name, bar_data, maxlen=2000, approximate=True)

                    logger.info(
                        "1m bar polled",
                        symbol=symbol,
                        time=bar.date,
                        close=bar.close,
                        volume=bar.volume,
                    )
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

        # Disconnect from TWS
        if self.ib and self.ib.isConnected():
            try:
                self.ib.disconnect()
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
