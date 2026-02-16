#!/usr/bin/env python3
"""
Enhanced Indicator Processor Service - Production-grade with incremental calculations

An optimized version of the indicator processor that uses incremental calculations
for maximum performance while maintaining compatibility with existing infrastructure.

Features:
- Incremental indicator calculations (RSI, MACD, SMA, EMA, ATR, BB, Stochastic)
- Automatic fallback to full calculation when needed
- Memory-efficient state management
- Compatible with existing Redis streams and database storage
- Performance monitoring and metrics
- Graceful shutdown and error handling

Version: 2.0.0
Last Updated: 2025-08-13
Status: Production Ready
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from logging.handlers import RotatingFileHandler

import pandas as pd
import redis.asyncio as redis
import structlog

from config.symbol_config import get_active_contracts
from src.config.settings import Settings
from src.core.database_manager import DatabaseManager
from src.core.stream_keys import indicators as sk_indicators
from src.core.stream_keys import market as sk_market
from src.indicators.calculations import IndicatorCalculations

# Import our components
from src.indicators.incremental_manager import IncrementalIndicatorManager

# Import Prometheus metrics
from src.observability.metrics import counter, gauge, start_metrics_server


@dataclass
class EnhancedIndicatorMetrics:
    """Enhanced indicator processing metrics with incremental stats."""

    start_time: datetime
    uptime_seconds: int
    total_bars_processed: int
    total_indicators_calculated: int
    incremental_calculations: int
    full_recalculations: int
    indicators_per_minute: float
    active_symbols: set[str]
    active_timeframes: set[str]
    redis_connected: bool
    database_connected: bool
    health_status: str
    error_count: int
    last_processing_time: datetime | None
    # Performance metrics
    avg_calculation_time_ms: float = 0.0
    incremental_speed_improvement: float = 0.0
    memory_usage_mb: float = 0.0
    # Redis stream observability
    stream_total_length: int = 0
    pending_total: int = 0


class EnhancedIndicatorProcessorService:
    """
    Enhanced indicator processing service with incremental calculations.

    Uses intelligent incremental updates to dramatically improve performance
    while maintaining full compatibility with existing systems.
    """

    def __init__(self, config_file: str | None = None):
        """Initialize the enhanced indicator processor service."""

        # Service state
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now()

        # Load configuration
        self.config = self._load_config(config_file)

        # Setup logging
        self._setup_logging()

        # Initialize managers
        self.incremental_manager = IncrementalIndicatorManager()
        self.indicator_calc = IndicatorCalculations()  # Fallback for non-incremental

        # Connection objects
        self.redis_client: redis.Redis | None = None
        self.db_manager: DatabaseManager | None = None

        # Processing state
        self.consumer_group = f"enhanced_indicator_processor_{int(time.time())}"
        self.consumer_name = f"enhanced_consumer_{os.getpid()}"
        self.settings = Settings()
        self.env_prefix = f"{self.settings.env_name}:" if self.settings.env_name else ""

        # Bar history for initialization
        self.bar_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))

        # Enhanced Prometheus Metrics
        self.bars_processed_total = counter(
            "enhanced_bars_processed_total", "Total market data bars processed by enhanced service"
        )
        self.indicators_calculated_total = counter(
            "enhanced_indicators_calculated_total",
            "Total indicators calculated by enhanced service",
        )
        self.incremental_calculations_total = counter(
            "enhanced_incremental_calculations_total", "Total incremental calculations performed"
        )
        self.full_recalculations_total = counter(
            "enhanced_full_recalculations_total", "Total full recalculations performed (fallback)"
        )
        self.calculation_duration_ms = gauge(
            "enhanced_calculation_duration_ms", "Average calculation time in milliseconds"
        )
        self.memory_usage_mb = gauge("enhanced_memory_usage_mb", "Memory usage in megabytes")
        self.service_uptime_seconds = gauge(
            "enhanced_service_uptime_seconds", "Service uptime in seconds"
        )
        self.active_symbols_count = gauge(
            "enhanced_active_symbols_count", "Number of active symbols being processed"
        )
        self.error_count_total = counter(
            "enhanced_errors_total", "Total errors encountered by enhanced service"
        )

        # Legacy metrics object for backward compatibility
        self.metrics = EnhancedIndicatorMetrics(
            start_time=self.start_time,
            uptime_seconds=0,
            total_bars_processed=0,
            total_indicators_calculated=0,
            incremental_calculations=0,
            full_recalculations=0,
            indicators_per_minute=0.0,
            active_symbols=set(),
            active_timeframes=set(),
            redis_connected=False,
            database_connected=False,
            health_status="starting",
            error_count=0,
            last_processing_time=None,
        )

        # Signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger = structlog.get_logger(__name__)

    def _load_config(self, config_file: str | None) -> dict[str, Any]:
        """Load service configuration."""
        default_config = {
            "redis": {"host": "localhost", "port": 6379, "db": 0},
            "database": {"url": "postgresql://postgres:postgres@localhost:5432/indicagent"},
            "service": {
                "symbols": get_active_contracts(),
                "timeframes": ["1m", "5m", "15m", "1h", "4h", "1d"],
                "indicators": [
                    "RSI",
                    "MACD",
                    "MACD_SIGNAL",
                    "MACD_HISTOGRAM",
                    "BB_UPPER",
                    "BB_MIDDLE",
                    "BB_LOWER",
                    "SMA_20",
                    "SMA_50",
                    "EMA_12",
                    "EMA_26",
                    "ATR",
                    "STOCH_K",
                    "STOCH_D",
                ],
                "processing_interval": 0.1,  # Faster processing
                "health_check_interval": 30,
                "min_history_bars": 200,
                "use_incremental": True,
                "fallback_threshold": 50,  # Bars needed before using incremental
            },
            "logging": {
                "level": "INFO",
                "file": "logs/enhanced_indicator_processor.log",
                "max_size": "10MB",
                "backup_count": 5,
            },
        }

        if config_file and Path(config_file).exists():
            with open(config_file) as f:
                user_config = json.load(f)
                # Deep merge configs
                for key, value in user_config.items():
                    if isinstance(value, dict) and key in default_config:
                        default_config[key].update(value)
                    else:
                        default_config[key] = value

        return default_config

    def _setup_logging(self):
        """Setup structured logging with file rotation."""
        log_dir = Path(self.config["logging"]["file"]).parent
        log_dir.mkdir(exist_ok=True)

        # Setup rotating file handler
        file_handler = RotatingFileHandler(
            self.config["logging"]["file"], maxBytes=10 * 1024 * 1024, backupCount=5  # 10MB
        )

        # Configure structlog
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.processors.JSONRenderer(),
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

        # Setup standard logging
        logging.basicConfig(
            level=getattr(logging, self.config["logging"]["level"]),
            handlers=[file_handler],
            format="%(message)s",
        )

    async def start(self):
        """Start the enhanced indicator processor service."""
        self.logger.info(
            "🚀 Starting Enhanced Indicator Processor Service...", config=self.config["service"]
        )

        try:
            # Connect to Redis and Database
            await self._connect_redis()
            await self._connect_database()

            # Start Prometheus metrics server
            start_metrics_server(port=9109)
            self.logger.info("🔍 Prometheus metrics server started on port 9109")

            # Setup consumer groups and initialize bar history
            await self._setup_consumer_groups()
            await self._initialize_bar_history()

            # Start service tasks
            self.running = True
            tasks = [
                asyncio.create_task(self._process_market_data()),
                asyncio.create_task(self._health_monitor_loop()),
                asyncio.create_task(self._metrics_update_loop()),
                asyncio.create_task(self._memory_monitor_loop()),
            ]

            self.logger.info("✅ Enhanced Indicator Processor Service started")

            # Wait for all tasks to complete
            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            self.logger.error("Failed to start enhanced indicator service", error=str(e))
            raise
        finally:
            await self.stop()

    async def _connect_redis(self):
        """Connect to Redis."""
        try:
            self.redis_client = redis.Redis(
                host=self.config["redis"]["host"],
                port=self.config["redis"]["port"],
                db=self.config["redis"]["db"],
                decode_responses=False,
            )
            await self.redis_client.ping()
            self.metrics.redis_connected = True
            self.logger.info("✅ Connected to Redis")
        except Exception as e:
            self.logger.error("Redis connection failed", error=str(e))
            raise

    async def _connect_database(self):
        """Connect to database."""
        try:
            self.db_manager = DatabaseManager(self.config["database"]["url"])
            await self.db_manager.initialize()
            self.metrics.database_connected = True
            self.logger.info("✅ Connected to database")
        except Exception as e:
            self.logger.error("Database connection failed", error=str(e))
            raise

    async def _setup_consumer_groups(self):
        """Setup Redis consumer groups for each timeframe."""
        for timeframe in self.config["service"]["timeframes"]:
            for symbol in self.config["service"]["symbols"]:
                stream_name = sk_market(self.env_prefix, symbol, timeframe)

                try:
                    await self.redis_client.xgroup_create(
                        stream_name, self.consumer_group, "0", mkstream=True
                    )
                    self.logger.debug(
                        "Created consumer group", stream=stream_name, group=self.consumer_group
                    )
                except Exception:
                    pass  # Group probably already exists

    async def _initialize_bar_history(self):
        """Initialize bar history and incremental manager state."""
        self.logger.info("📊 Initializing bar history and incremental state...")

        for timeframe in self.config["service"]["timeframes"]:
            for symbol in self.config["service"]["symbols"]:
                try:
                    # Get recent historical data
                    query = """
                        SELECT timestamp, open, high, low, close, volume
                        FROM market_data_ohlcv
                        WHERE symbol = $1 AND timeframe = $2
                        ORDER BY timestamp DESC
                        LIMIT $3
                    """

                    rows = await self.db_manager.execute_query(
                        query, symbol, timeframe, self.config["service"]["min_history_bars"]
                    )

                    if rows:
                        symbol_timeframe = f"{symbol}:{timeframe}"
                        history = []

                        for row in reversed(rows):  # Chronological order
                            bar_data = {
                                "timestamp": row["timestamp"],
                                "open": float(row["open"]),
                                "high": float(row["high"]),
                                "low": float(row["low"]),
                                "close": float(row["close"]),
                                "volume": int(float(row["volume"])),
                            }
                            history.append(bar_data)

                        self.bar_history[symbol_timeframe].extend(history)

                        # Initialize incremental manager with historical data
                        for bar_data in history:
                            self.incremental_manager.add_bar_data(symbol, timeframe, bar_data)

                        self.logger.info(
                            "📈 Initialized incremental state",
                            symbol=symbol,
                            timeframe=timeframe,
                            bars=len(history),
                        )

                except Exception as e:
                    self.logger.error(
                        "Error initializing history",
                        symbol=symbol,
                        timeframe=timeframe,
                        error=str(e),
                    )

    async def _process_market_data(self):
        """Main processing loop for market data."""
        self.logger.info("🔄 Starting enhanced market data processing loop")

        while self.running and not self.shutdown_requested:
            try:
                for timeframe in self.config["service"]["timeframes"]:
                    for symbol in self.config["service"]["symbols"]:
                        stream_name = sk_market(self.env_prefix, symbol, timeframe)

                        # Read from stream
                        messages = await self.redis_client.xreadgroup(
                            self.consumer_group,
                            self.consumer_name,
                            {stream_name: ">"},
                            count=10,
                            block=100,  # 100ms timeout
                        )

                        # Process messages
                        for _stream, msgs in messages:
                            for message_id, fields in msgs:
                                await self._process_single_bar(
                                    symbol, timeframe, fields, stream_name, message_id
                                )

                await asyncio.sleep(self.config["service"]["processing_interval"])

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in processing loop", error=str(e))
                self.error_count_total.inc()
                self.metrics.error_count += 1
                await asyncio.sleep(1)

    async def _process_single_bar(
        self, symbol: str, timeframe: str, fields: dict, stream_name: str, message_id: str
    ):
        """Process a single market data bar with enhanced calculations."""
        try:
            # Decode bar data
            bar_data = {
                "timestamp": datetime.fromisoformat(fields[b"timestamp"].decode()),
                "open": float(fields[b"open"].decode()),
                "high": float(fields[b"high"].decode()),
                "low": float(fields[b"low"].decode()),
                "close": float(fields[b"close"].decode()),
                "volume": int(float(fields[b"volume"].decode())),
            }

            # Add to incremental manager
            self.incremental_manager.add_bar_data(symbol, timeframe, bar_data)

            # Add to bar history
            symbol_timeframe = f"{symbol}:{timeframe}"
            self.bar_history[symbol_timeframe].append(bar_data)

            # Calculate indicators using enhanced methods
            calculation_start = time.time()
            indicators_calculated = await self._calculate_enhanced_indicators(
                symbol, timeframe, bar_data["timestamp"]
            )
            calculation_time = (time.time() - calculation_start) * 1000  # ms

            # Update Prometheus metrics
            self.bars_processed_total.inc()
            self.indicators_calculated_total.inc(indicators_calculated)
            self.calculation_duration_ms.set(calculation_time)

            # Update legacy metrics for backward compatibility
            self.metrics.total_bars_processed += 1
            self.metrics.total_indicators_calculated += indicators_calculated
            self.metrics.last_processing_time = datetime.now()
            self.metrics.active_symbols.add(symbol)
            self.metrics.active_timeframes.add(timeframe)

            # Update average calculation time
            self.metrics.avg_calculation_time_ms = (
                self.metrics.avg_calculation_time_ms * 0.9 + calculation_time * 0.1
            )

            # Acknowledge message
            await self.redis_client.xack(stream_name, self.consumer_group, message_id)

            if indicators_calculated > 0:
                self.logger.debug(
                    "Enhanced indicators calculated",
                    symbol=symbol,
                    timeframe=timeframe,
                    count=indicators_calculated,
                    calculation_time_ms=round(calculation_time, 2),
                )

        except Exception as e:
            self.logger.error(
                "Error processing single bar", symbol=symbol, timeframe=timeframe, error=str(e)
            )
            self.error_count_total.inc()
            self.metrics.error_count += 1

    async def _calculate_enhanced_indicators(
        self, symbol: str, timeframe: str, timestamp: datetime
    ) -> int:
        """Calculate indicators using enhanced incremental methods."""
        indicators_calculated = 0
        use_incremental = self.config["service"]["use_incremental"]
        fallback_threshold = self.config["service"]["fallback_threshold"]

        symbol_timeframe = f"{symbol}:{timeframe}"
        history_length = len(self.bar_history[symbol_timeframe])

        for indicator_name in self.config["service"]["indicators"]:
            try:
                value = None
                is_incremental = False

                # Use incremental if enabled and enough history
                if use_incremental and history_length >= fallback_threshold:
                    value = await self._calculate_indicator_incremental(
                        symbol, timeframe, indicator_name
                    )
                    is_incremental = True

                # Fallback to full calculation if needed
                if value is None:
                    value = await self._calculate_indicator_full(symbol_timeframe, indicator_name)
                    is_incremental = False

                if value is not None:
                    # Handle both single values and dictionaries
                    if isinstance(value, dict):
                        for sub_indicator, sub_value in value.items():
                            await self._publish_and_store_indicator(
                                symbol, timeframe, sub_indicator, sub_value, timestamp
                            )
                            indicators_calculated += 1
                    else:
                        await self._publish_and_store_indicator(
                            symbol, timeframe, indicator_name, value, timestamp
                        )
                        indicators_calculated += 1

                    # Update Prometheus metrics
                    if is_incremental:
                        self.incremental_calculations_total.inc()
                        self.metrics.incremental_calculations += 1
                    else:
                        self.full_recalculations_total.inc()
                        self.metrics.full_recalculations += 1

            except Exception as e:
                self.logger.error(
                    "Error calculating enhanced indicator",
                    indicator=indicator_name,
                    symbol=symbol,
                    timeframe=timeframe,
                    error=str(e),
                )

        return indicators_calculated

    async def _calculate_indicator_incremental(
        self, symbol: str, timeframe: str, indicator_name: str
    ) -> float | dict[str, float] | None:
        """Calculate indicator using incremental methods."""
        try:
            if indicator_name == "RSI":
                return self.incremental_manager.calculate_rsi_incremental(symbol, timeframe)

            elif indicator_name.startswith("SMA_"):
                period = int(indicator_name.split("_")[1])
                return self.incremental_manager.calculate_sma_incremental(symbol, timeframe, period)

            elif indicator_name.startswith("EMA_"):
                period = int(indicator_name.split("_")[1])
                return self.incremental_manager.calculate_ema_incremental(symbol, timeframe, period)

            elif indicator_name in ["MACD", "MACD_SIGNAL", "MACD_HISTOGRAM"]:
                macd_result = self.incremental_manager.calculate_macd_incremental(symbol, timeframe)
                if macd_result:
                    if indicator_name == "MACD":
                        return macd_result.get("macd")
                    elif indicator_name == "MACD_SIGNAL":
                        return macd_result.get("signal")
                    elif indicator_name == "MACD_HISTOGRAM":
                        return macd_result.get("histogram")
                return None

            elif indicator_name == "ATR":
                return self.incremental_manager.calculate_atr_incremental(symbol, timeframe)

            elif indicator_name in ["BB_UPPER", "BB_MIDDLE", "BB_LOWER"]:
                bb_result = self.incremental_manager.calculate_bollinger_bands_incremental(
                    symbol, timeframe
                )
                if bb_result:
                    if indicator_name == "BB_UPPER":
                        return bb_result.get("upper")
                    elif indicator_name == "BB_MIDDLE":
                        return bb_result.get("middle")
                    elif indicator_name == "BB_LOWER":
                        return bb_result.get("lower")
                return None

            elif indicator_name in ["STOCH_K", "STOCH_D"]:
                stoch_result = self.incremental_manager.calculate_stochastic_incremental(
                    symbol, timeframe
                )
                if stoch_result:
                    if indicator_name == "STOCH_K":
                        return stoch_result.get("%K")
                    elif indicator_name == "STOCH_D":
                        return stoch_result.get("%D")
                return None

            else:
                # Indicator not supported incrementally
                return None

        except Exception as e:
            self.logger.error(
                "Error in incremental calculation", indicator=indicator_name, error=str(e)
            )
            return None

    async def _calculate_indicator_full(
        self, symbol_timeframe: str, indicator_name: str
    ) -> float | None:
        """Calculate indicator using full recalculation as fallback."""
        try:
            history = list(self.bar_history[symbol_timeframe])
            if len(history) < 20:  # Minimum bars needed
                return None

            df = pd.DataFrame(history)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df.sort_values("timestamp").reset_index(drop=True)

            # Use existing calculation methods
            if indicator_name == "RSI":
                rsi_result = self.indicator_calc.calculate_rsi(df, period=14)
                return rsi_result.get("rsi") if rsi_result else None

            elif indicator_name == "MACD":
                macd_result = self.indicator_calc.calculate_macd(df)
                return macd_result.get("macd") if macd_result else None

            elif indicator_name == "MACD_SIGNAL":
                macd_result = self.indicator_calc.calculate_macd(df)
                return macd_result.get("signal") if macd_result else None

            elif indicator_name == "MACD_HISTOGRAM":
                macd_result = self.indicator_calc.calculate_macd(df)
                return macd_result.get("histogram") if macd_result else None

            elif indicator_name == "BB_UPPER":
                bb_result = self.indicator_calc.calculate_bollinger_bands(df)
                return bb_result.get("upper") if bb_result else None

            elif indicator_name == "BB_MIDDLE":
                bb_result = self.indicator_calc.calculate_bollinger_bands(df)
                return bb_result.get("middle") if bb_result else None

            elif indicator_name == "BB_LOWER":
                bb_result = self.indicator_calc.calculate_bollinger_bands(df)
                return bb_result.get("lower") if bb_result else None

            elif indicator_name.startswith("SMA_"):
                period = int(indicator_name.split("_")[1])
                ma_result = self.indicator_calc.calculate_moving_averages(df, periods=[period])
                return ma_result.get(f"sma_{period}") if ma_result else None

            elif indicator_name.startswith("EMA_"):
                period = int(indicator_name.split("_")[1])
                ma_result = self.indicator_calc.calculate_moving_averages(df, periods=[period])
                return ma_result.get(f"ema_{period}") if ma_result else None

            elif indicator_name == "ATR":
                atr_result = self.indicator_calc.calculate_atr(df, period=14)
                return atr_result.get("atr_14") if atr_result else None

            elif indicator_name == "STOCH_K":
                stoch_result = self.indicator_calc.calculate_stochastic(df)
                return stoch_result.get("%K") if stoch_result else None

            elif indicator_name == "STOCH_D":
                stoch_result = self.indicator_calc.calculate_stochastic(df)
                return stoch_result.get("%D") if stoch_result else None

            else:
                self.logger.warning("Unknown indicator", indicator=indicator_name)
                return None

        except Exception as e:
            self.logger.error("Error in full calculation", indicator=indicator_name, error=str(e))
            return None

    async def _publish_and_store_indicator(
        self, symbol: str, timeframe: str, indicator_name: str, value: float, timestamp: datetime
    ):
        """Publish indicator to Redis and store in database."""
        try:
            # Publish to Redis
            stream_name = sk_indicators(self.env_prefix, symbol, timeframe)

            indicator_data = {
                "timestamp": timestamp.isoformat(),
                "symbol": symbol,
                "timeframe": timeframe,
                "indicator_name": indicator_name,
                "value": str(value),
                "source": "enhanced_indicator_processor",
            }

            await self.redis_client.xadd(stream_name, indicator_data, maxlen=200000)

            # Store in database
            insert_query = """
                INSERT INTO technical_indicators
                (timestamp, symbol, timeframe, indicator_name, value)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (timestamp, symbol, timeframe, indicator_name)
                DO UPDATE SET value = EXCLUDED.value
            """

            await self.db_manager.execute_query(
                insert_query, timestamp, symbol, timeframe, indicator_name, value
            )

        except Exception as e:
            self.logger.error(
                "Error publishing/storing indicator",
                indicator=indicator_name,
                symbol=symbol,
                timeframe=timeframe,
                error=str(e),
            )

    async def _health_monitor_loop(self):
        """Health monitoring loop with enhanced metrics."""
        while self.running and not self.shutdown_requested:
            try:
                # Update uptime
                uptime_seconds = int((datetime.now() - self.metrics.start_time).total_seconds())
                self.metrics.uptime_seconds = uptime_seconds
                self.service_uptime_seconds.set(uptime_seconds)

                # Update active symbols count
                self.active_symbols_count.set(len(self.metrics.active_symbols))

                # Update memory usage (estimated)
                memory_stats = self.incremental_manager.get_memory_usage()
                memory_mb = memory_stats.get("total_bars_cached", 0) * 0.001
                self.memory_usage_mb.set(memory_mb)
                self.metrics.memory_usage_mb = memory_mb

                # Calculate indicators per minute
                if self.metrics.uptime_seconds > 0:
                    self.metrics.indicators_per_minute = (
                        self.metrics.total_indicators_calculated
                        * 60.0
                        / self.metrics.uptime_seconds
                    )

                # Calculate incremental speed improvement
                if self.metrics.full_recalculations > 0:
                    total_calculations = (
                        self.metrics.incremental_calculations + self.metrics.full_recalculations
                    )
                    incremental_ratio = self.metrics.incremental_calculations / total_calculations
                    self.metrics.incremental_speed_improvement = incremental_ratio * 100.0

                # Update health status
                self.metrics.health_status = "healthy"

                # Log health info every 30 seconds
                if self.metrics.uptime_seconds % 30 == 0:
                    self.logger.info(
                        "Enhanced health check",
                        uptime=self.metrics.uptime_seconds,
                        bars_processed=self.metrics.total_bars_processed,
                        indicators_calculated=self.metrics.total_indicators_calculated,
                        indicators_per_min=round(self.metrics.indicators_per_minute, 2),
                        incremental_pct=round(self.metrics.incremental_speed_improvement, 1),
                        avg_calc_time_ms=round(self.metrics.avg_calculation_time_ms, 2),
                        health_status=self.metrics.health_status,
                    )

                await asyncio.sleep(self.config["service"]["health_check_interval"])

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in health monitor", error=str(e))
                self.metrics.health_status = "error"
                await asyncio.sleep(5)

    async def _memory_monitor_loop(self):
        """Monitor memory usage of incremental manager."""
        while self.running and not self.shutdown_requested:
            try:
                memory_stats = self.incremental_manager.get_memory_usage()
                self.metrics.memory_usage_mb = (
                    memory_stats.get("total_bars_cached", 0) * 0.001  # Rough estimate
                )

                # Log memory stats every 5 minutes
                if self.metrics.uptime_seconds % 300 == 0:
                    self.logger.info(
                        "Memory usage stats",
                        total_states=memory_stats.get("total_states", 0),
                        total_bars_cached=memory_stats.get("total_bars_cached", 0),
                        avg_bars_per_state=round(memory_stats.get("average_bars_per_state", 0), 1),
                        estimated_mb=round(self.metrics.memory_usage_mb, 2),
                    )

                await asyncio.sleep(60)  # Check every minute

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in memory monitor", error=str(e))
                await asyncio.sleep(5)

    async def _metrics_update_loop(self):
        """Update metrics file with enhanced data."""
        while self.running and not self.shutdown_requested:
            try:
                status_file = Path("logs/enhanced_indicator_processor_status.json")
                status_file.parent.mkdir(exist_ok=True)

                status = {
                    "service": "enhanced_indicator_processor",
                    "version": "2.0.0",
                    "status": self.metrics.health_status,
                    "uptime_seconds": self.metrics.uptime_seconds,
                    "bars_processed": self.metrics.total_bars_processed,
                    "indicators_calculated": self.metrics.total_indicators_calculated,
                    "incremental_calculations": self.metrics.incremental_calculations,
                    "full_recalculations": self.metrics.full_recalculations,
                    "indicators_per_minute": round(self.metrics.indicators_per_minute, 2),
                    "avg_calculation_time_ms": round(self.metrics.avg_calculation_time_ms, 2),
                    "incremental_speed_improvement_pct": round(
                        self.metrics.incremental_speed_improvement, 1
                    ),
                    "memory_usage_mb": round(self.metrics.memory_usage_mb, 2),
                    "active_symbols": list(self.metrics.active_symbols),
                    "active_timeframes": list(self.metrics.active_timeframes),
                    "error_count": self.metrics.error_count,
                    "last_update": datetime.now().isoformat(),
                }

                with open(status_file, "w") as f:
                    json.dump(status, f, indent=2)

                await asyncio.sleep(60)  # Update every minute

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error writing enhanced metrics", error=str(e))
                await asyncio.sleep(5)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        self.logger.info("Received shutdown signal", signal=signum)
        self.shutdown_requested = True

    async def stop(self):
        """Stop the enhanced service."""
        self.logger.info("⏹️  Stopping Enhanced Indicator Processor Service...")

        self.running = False
        self.shutdown_requested = True

        # Close database connection
        if self.db_manager:
            await self.db_manager.close()

        # Close Redis connection
        if self.redis_client:
            await self.redis_client.aclose()

        self.logger.info("✅ Enhanced Indicator Processor Service stopped")


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Enhanced Indicator Processor Service")
    parser.add_argument("--config", help="Configuration file path")
    parser.add_argument("--foreground", action="store_true", help="Run in foreground")

    args = parser.parse_args()

    service = EnhancedIndicatorProcessorService(args.config)

    if args.foreground:
        print("🚀 Starting Enhanced Indicator Processor Service in foreground...")
        print("Press Ctrl+C to stop")

    try:
        await service.start()
    except KeyboardInterrupt:
        print("\n⏹️  Service stopped by user")
    except Exception as e:
        print(f"❌ Service failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
