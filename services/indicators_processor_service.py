#!/usr/bin/env python3
"""
Indicator Processor Service - Production-grade continuous indicator calculation

A robust daemon that watches for new OHLCV bars in Redis Streams and automatically
calculates technical indicators, publishing results back to Redis and database.

Features:
- Daemon-style background operation
- Multi-timeframe indicator processing (1m, 5m, 15m, 1h, 4h, 1d)
- Consumer group pattern for reliability
- Automatic error handling and retries
- Performance monitoring and metrics
- Graceful shutdown handling
- Configurable indicator sets

Version: 1.0.0
Last Updated: 2025-08-05
Status: Production Ready ✅
"""

import asyncio
import json
import logging
import signal
import sys
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
from aiohttp import web, web_request

from config.symbol_config import get_active_contracts
from src.config.settings import Settings
from src.core.database_manager import DatabaseManager
from src.core.stream_keys import indicators as sk_indicators
from src.core.stream_keys import market as sk_market

# Import our indicator calculations
from src.indicators.calculations import IndicatorCalculations
from src.intelligence.indicators.atr import plugin as atr_plugin
from src.intelligence.indicators.bollinger import plugin as bb_plugin
from src.intelligence.indicators.cci import plugin as cci_plugin
from src.intelligence.indicators.macd import plugin as macd_plugin
from src.intelligence.indicators.mfi import plugin as mfi_plugin
from src.intelligence.indicators.moving_averages import plugin as ma_plugin
from src.intelligence.indicators.obv import plugin as obv_plugin
from src.intelligence.indicators.rsi import plugin as rsi_plugin
from src.intelligence.indicators.stochastic import plugin as stoch_plugin
from src.intelligence.indicators.vwap import plugin as vwap_plugin
from src.intelligence.indicators.williams_r import plugin as williams_plugin

# Plugin framework imports
from src.intelligence.plugins import PluginRegistry


@dataclass
class IndicatorMetrics:
    """Indicator processing metrics."""

    start_time: datetime
    uptime_seconds: int
    total_bars_processed: int
    total_indicators_calculated: int
    indicators_per_minute: float
    active_symbols: set[str]
    active_timeframes: set[str]
    redis_connected: bool
    database_connected: bool
    health_status: str
    error_count: int
    last_processing_time: datetime | None
    # Redis stream observability
    stream_total_length: int = 0
    pending_total: int = 0
    # Plugin metrics
    plugin_calculations: int = 0
    legacy_calculations: int = 0
    plugin_enabled: bool = False


class IndicatorProcessorService:
    """
    Production-grade indicator processing service.

    Watches Redis Streams for new OHLCV bars and automatically calculates
    technical indicators, publishing results to Redis and database.
    """

    def __init__(self, config_file: str | None = None):
        """Initialize the indicator processor service."""

        # Service state
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now()

        # Load configuration
        self.config = self._load_config(config_file)

        # Setup logging
        self._setup_logging()
        self.logger = structlog.get_logger(__name__)

        # Redis connection
        self.redis_client: redis.Redis | None = None

        # Database connection
        self.db_manager: DatabaseManager | None = None

        # Indicator calculator
        self.indicator_calc = IndicatorCalculations()

        # Plugin registry initialization
        self.plugin_registry = PluginRegistry()
        self._initialize_plugins()

        # Processing state
        self.consumer_group = "indicator_processor"
        self.consumer_name = f"indicator_proc_{int(datetime.now().timestamp())}"

        # Metrics tracking (initialized after config loading)
        self._initialize_metrics()

        # Bar history for indicator calculations (keyed by symbol:timeframe)
        self.bar_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))

        # Processing queue
        self.processing_queue = asyncio.Queue()

        # HTTP server for health endpoints
        self.http_app: web.Application | None = None
        self.http_server: web.TCPSite | None = None
        self.health_port = 9109  # Port for health endpoint

        # Pre-created consumer groups cache to avoid repeated create attempts
        self._groups_ensured: set[str] = set()

        # Env prefix support
        self.settings = Settings()
        self.env_prefix = f"{self.settings.env_name}:" if self.settings.env_name else ""
        # Replay existing bars from start once on startup for backfill/testing
        self.replay_on_start: bool = True

    def _initialize_plugins(self):
        """Initialize and register all available indicator plugins."""
        try:
            # Register built-in indicator plugins with graceful handling for import failures
            plugins_config = [
                ("rsi_plugin", rsi_plugin),
                ("ma_plugin", ma_plugin),
                ("macd_plugin", macd_plugin),
                ("bb_plugin", bb_plugin),
                ("atr_plugin", atr_plugin),
                ("stoch_plugin", stoch_plugin),
                ("cci_plugin", cci_plugin),
                ("williams_plugin", williams_plugin),
                ("mfi_plugin", mfi_plugin),
                ("obv_plugin", obv_plugin),
                ("vwap_plugin", vwap_plugin),
            ]

            registered_count = 0
            for plugin_name, plugin_obj in plugins_config:
                try:
                    if plugin_obj is not None:
                        self.plugin_registry.register_indicator(plugin_obj)
                        self.logger.debug("Registered plugin", name=plugin_obj.name)
                        registered_count += 1
                    else:
                        self.logger.warning("Plugin object is None", plugin=plugin_name)
                except Exception as e:
                    self.logger.warning(
                        "Failed to register plugin", plugin=plugin_name, error=str(e)
                    )

            self.logger.info(
                "Plugin registry initialized",
                registered_count=registered_count,
                total_plugins=len(self.plugin_registry.list_indicators()),
            )

        except Exception as e:
            self.logger.warning("Plugin initialization failed", error=str(e))
            # Continue with legacy calculations only

    def _initialize_metrics(self):
        """Initialize metrics with plugin support."""
        self.metrics = IndicatorMetrics(
            start_time=self.start_time,
            uptime_seconds=0,
            total_bars_processed=0,
            total_indicators_calculated=0,
            indicators_per_minute=0.0,
            active_symbols=set(),
            active_timeframes=set(),
            redis_connected=False,
            database_connected=False,
            health_status="starting",
            error_count=0,
            last_processing_time=None,
            plugin_calculations=0,
            legacy_calculations=0,
            plugin_enabled=self.config["service"].get("plugin_mode", "legacy") != "legacy",
        )

    def _load_config(self, config_file: str | None) -> dict[str, Any]:
        """Load service configuration."""
        # Use centralized Settings for configuration defaults
        try:
            from src.config.settings import Settings as _Settings

            _settings = _Settings()
        except Exception:
            _settings = None
        default_config = {
            "redis": {"host": "localhost", "port": 6379, "db": 0},
            "database": {
                "url": (
                    _settings.database_url
                    if _settings and getattr(_settings, "database_url", None)
                    else "postgresql://postgres:postgres@localhost:5432/indicagent"
                )
            },
            "service": {
                "timeframes": ["1m", "5m", "15m", "1h", "4h", "1d"],
                "symbols": get_active_contracts(),  # Use centralized symbol config
                "indicators": [
                    "RSI",
                    "MACD",
                    "MACD_SIGNAL",
                    "MACD_HISTOGRAM",
                    "BB_UPPER",
                    "BB_MIDDLE",
                    "BB_LOWER",
                    "SMA_10",
                    "SMA_20",
                    "SMA_50",
                    "EMA_12",
                    "EMA_20",
                    "EMA_26",
                    "EMA_50",
                    "ATR",
                    "STOCH_K",
                    "STOCH_D",
                    "CCI",
                    "WILLIAMS_R",
                    "MFI",
                    "OBV",
                    "VWAP",
                ],
                "batch_size": 10,
                "processing_interval": 0.5,
                "health_check_interval": 30,
                # Redis stream tuning
                "indicator_stream_maxlen": 200000,
                "lag_metrics_enabled": True,
                "lag_metrics_sample_size": 50,
                # Plugin configuration
                "plugin_mode": "hybrid",  # Options: "legacy", "plugin", "hybrid"
                "plugin_fallback": True,  # Fallback to legacy if plugin fails
                "plugin_preference": [
                    "RSI",
                    "MovingAverages",
                    "MACD",
                    "BollingerBands",
                ],  # Plugins to prioritize
            },
            "logging": {
                "level": "INFO",
                "file": "logs/indicator_processor.log",
                "max_size": "10MB",
                "backup_count": 5,
            },
        }

        if config_file and Path(config_file).exists():
            with open(config_file) as f:
                user_config = json.load(f)
                # Merge configs
                for key, value in user_config.items():
                    if isinstance(value, dict) and key in default_config:
                        default_config[key].update(value)
                    else:
                        default_config[key] = value

        return default_config

    def _setup_logging(self):
        """Setup structured logging with file rotation."""
        log_dir = Path(self.config["logging"]["file"]).parent
        log_dir.mkdir(parents=True, exist_ok=True)

        # Setup file handler with rotation
        file_handler = RotatingFileHandler(
            self.config["logging"]["file"],
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=self.config["logging"]["backup_count"],
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
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )

        # Setup Python logging
        logging.basicConfig(
            level=getattr(logging, self.config["logging"]["level"]),
            handlers=[file_handler, logging.StreamHandler()],
            format="%(message)s",
        )

    async def start(self):
        """Start the indicator processor service."""
        self.logger.info(
            "🚀 Starting Indicator Processor Service...", config=self.config["service"]
        )

        try:
            # Connect to Redis
            await self._connect_redis()

            # Connect to database
            await self._connect_database()

            # Setup consumer groups
            await self._setup_consumer_groups()

            # Initialize bar history from database
            await self._initialize_bar_history()

            # Optional: one-time replay from start for existing bars
            if self.replay_on_start:
                await self._replay_from_start_once()

            # Start HTTP server for health endpoints
            await self._start_http_server()

            # Start processing tasks
            self.running = True
            tasks = [
                asyncio.create_task(self._indicator_processing_loop()),
                asyncio.create_task(self._health_monitor_loop()),
                asyncio.create_task(self._metrics_update_loop()),
            ]

            # Setup signal handlers
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)

            self.metrics.health_status = "running"
            self.logger.info("✅ Indicator Processor Service started successfully")

            # Wait for tasks to complete
            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            self.logger.error("Failed to start Indicator Processor Service", error=str(e))
            self.metrics.health_status = "failed"
            raise

    async def _replay_from_start_once(self) -> None:
        """One-time replay of existing market bars from the beginning to seed indicators."""
        try:
            for timeframe in self.config["service"]["timeframes"]:
                for symbol in self.config["service"]["symbols"]:
                    stream_name = sk_market(self.env_prefix, symbol, timeframe)
                    # Page through existing entries
                    last_id = "0"
                    total = 0
                    for _ in range(10):  # up to 10 pages
                        messages = await self.redis_client.xread(
                            {stream_name: last_id}, count=200, block=100
                        )
                        if not messages:
                            break
                        _, batch = messages[0]
                        await self._process_stream_messages(stream_name, batch)
                        total += len(batch)
                        last_id = (
                            batch[-1][0].decode()
                            if isinstance(batch[-1][0], bytes | bytearray)
                            else batch[-1][0]
                        )
                    if total:
                        self.logger.info("Replayed existing bars", stream=stream_name, count=total)
        except Exception as e:
            self.logger.debug("Replay from start skipped", error=str(e))

    async def _connect_redis(self):
        """Connect to Redis."""
        try:
            self.redis_client = redis.Redis(
                host=self.config["redis"]["host"],
                port=self.config["redis"]["port"],
                db=self.config["redis"]["db"],
                decode_responses=False,  # Keep bytes for Redis Streams
            )

            # Test connection
            await self.redis_client.ping()
            self.metrics.redis_connected = True
            self.logger.info("✅ Connected to Redis")

        except Exception as e:
            self.logger.error("Failed to connect to Redis", error=str(e))
            raise

    async def _connect_database(self):
        """Connect to database."""
        try:
            self.db_manager = DatabaseManager(self.config["database"]["url"])
            await self.db_manager.initialize()
            self.metrics.database_connected = True
            self.logger.info("✅ Connected to database")

        except Exception as e:
            self.logger.error("Failed to connect to database", error=str(e))
            raise

    async def _setup_consumer_groups(self):
        """Setup Redis consumer groups for each timeframe (start from beginning)."""
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
                    # Group probably already exists
                    pass

    async def _initialize_bar_history(self):
        """Initialize bar history from database for each symbol/timeframe."""
        self.logger.info("📊 Initializing bar history from database...")

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
                        query,
                        symbol,
                        timeframe,
                        self.config["service"].get("min_history_bars", 200),
                    )

                    if rows:
                        # Convert to the format expected by indicator processing
                        symbol_timeframe = f"{symbol}:{timeframe}"
                        history = []

                        for row in reversed(rows):  # Reverse to get chronological order
                            history.append(
                                {
                                    "timestamp": row["timestamp"],
                                    "open": float(row["open"]),
                                    "high": float(row["high"]),
                                    "low": float(row["low"]),
                                    "close": float(row["close"]),
                                    "volume": int(float(row["volume"])),
                                }
                            )

                        self.bar_history[symbol_timeframe].extend(history)
                        self.logger.info(
                            "📈 Loaded historical bars",
                            symbol=symbol,
                            timeframe=timeframe,
                            bars=len(history),
                        )

                        # Calculate indicators immediately on startup data
                        if len(history) >= 20:  # Minimum bars for indicator calculations
                            await self._calculate_and_publish_indicators(
                                symbol_timeframe, list(self.bar_history[symbol_timeframe])
                            )
                            self.logger.info(
                                "🔢 Calculated startup indicators",
                                symbol=symbol,
                                timeframe=timeframe,
                            )
                    else:
                        self.logger.warning(
                            "⚠️ No historical data found", symbol=symbol, timeframe=timeframe
                        )

                except Exception as e:
                    self.logger.error(
                        "❌ Error loading historical data",
                        symbol=symbol,
                        timeframe=timeframe,
                        error=str(e),
                    )

    async def _indicator_processing_loop(self):
        """Main indicator processing loop."""
        self.logger.info("🔄 Starting indicator processing loop")

        while self.running and not self.shutdown_requested:
            try:
                processed_any = False

                # Process each timeframe
                for timeframe in self.config["service"]["timeframes"]:
                    for symbol in self.config["service"]["symbols"]:
                        stream_name = sk_market(self.env_prefix, symbol, timeframe)
                        # Ensure consumer group exists; if created now, start from '0'
                        created_now = await self._ensure_consumer_group(stream_name)

                        try:
                            # Read from stream
                            start_id = "0" if created_now else ">"
                            messages = await self.redis_client.xreadgroup(
                                self.consumer_group,
                                self.consumer_name,
                                {stream_name: start_id},
                                count=self.config["service"]["batch_size"],
                                block=100,  # 100ms timeout
                            )

                            if messages:
                                processed_any = True
                                await self._process_stream_messages(stream_name, messages[0][1])

                        except Exception as e:
                            self.logger.error(
                                "Error reading from stream", stream=stream_name, error=str(e)
                            )
                            self.metrics.error_count += 1

                # Small delay if no messages processed
                if not processed_any:
                    await asyncio.sleep(self.config["service"]["processing_interval"])

            except asyncio.CancelledError:
                break

    async def _ensure_consumer_group(self, stream_name: str) -> bool:
        """Create consumer group if missing (idempotent). Returns True if created now."""
        if stream_name in self._groups_ensured:
            return False
        try:
            await self.redis_client.xgroup_create(
                stream_name, self.consumer_group, id="0", mkstream=True
            )
            self._groups_ensured.add(stream_name)
            self.logger.info(
                "Created consumer group", stream=stream_name, group=self.consumer_group
            )
            return True
        except Exception as e:
            # BUSYGROUP means it already exists
            if "BUSYGROUP" in str(e):
                self._groups_ensured.add(stream_name)
                return False
            else:
                self.logger.debug(
                    "Consumer group create error (ignored)", stream=stream_name, error=str(e)
                )
                return False

    async def _process_stream_messages(self, stream_name: str, messages: list):
        """Process messages from a stream."""
        # Strip env prefix + 'market:' to get SYMBOL:TIMEFRAME
        prefix = f"{self.env_prefix}market:"
        symbol_timeframe = (
            stream_name[len(prefix) :]
            if stream_name.startswith(prefix)
            else stream_name.split("market:", 1)[-1]
        )

        for message_id, fields in messages:
            try:
                # Parse OHLCV data
                ohlcv_data = self._parse_ohlcv_message(fields)
                if not ohlcv_data:
                    continue

                # Add to history
                self.bar_history[symbol_timeframe].append(ohlcv_data)

                # Calculate indicators if we have enough history
                if len(self.bar_history[symbol_timeframe]) >= 20:  # Minimum for most indicators
                    await self._calculate_and_publish_indicators(
                        symbol_timeframe, list(self.bar_history[symbol_timeframe])
                    )

                # Acknowledge message
                await self.redis_client.xack(stream_name, self.consumer_group, message_id)

                self.metrics.total_bars_processed += 1
                self.metrics.last_processing_time = datetime.now()

            except Exception as e:
                self.logger.error(
                    "Error processing message",
                    stream=stream_name,
                    message_id=message_id,
                    error=str(e),
                )
                self.metrics.error_count += 1

    def _parse_ohlcv_message(self, fields: dict) -> dict | None:
        """Parse OHLCV data from Redis message."""
        try:
            # Handle byte keys from Redis
            def get_field(key):
                if key.encode() in fields:
                    val = fields[key.encode()]
                    return val.decode() if isinstance(val, bytes) else val
                return fields.get(key)

            return {
                "timestamp": datetime.fromisoformat(get_field("timestamp").replace("Z", "")),
                "open": float(get_field("open")),
                "high": float(get_field("high")),
                "low": float(get_field("low")),
                "close": float(get_field("close")),
                "volume": int(float(get_field("volume"))),
            }
        except Exception as e:
            self.logger.error("Error parsing OHLCV message", error=str(e))
            return None

    async def _calculate_and_publish_indicators(self, symbol_timeframe: str, history: list[dict]):
        """Calculate indicators and publish results."""
        try:
            symbol, timeframe = symbol_timeframe.split(":", 1)

            # Convert to DataFrame
            df = pd.DataFrame(history)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df.sort_values("timestamp").reset_index(drop=True)

            current_timestamp = df.iloc[-1]["timestamp"]
            indicators_calculated = 0

            # Calculate each configured indicator
            for indicator_name in self.config["service"]["indicators"]:
                try:
                    indicator_value = await self._calculate_single_indicator(df, indicator_name)

                    if indicator_value is not None:
                        # Publish to Redis
                        await self._publish_indicator_result(
                            symbol, timeframe, indicator_name, indicator_value, current_timestamp
                        )

                        # Store in database
                        await self._store_indicator_result(
                            symbol, timeframe, indicator_name, indicator_value, current_timestamp
                        )

                        indicators_calculated += 1

                except Exception as e:
                    self.logger.error(
                        "Error calculating indicator",
                        indicator=indicator_name,
                        symbol=symbol,
                        timeframe=timeframe,
                        error=str(e),
                    )

            self.metrics.total_indicators_calculated += indicators_calculated
            self.metrics.active_symbols.add(symbol)
            self.metrics.active_timeframes.add(timeframe)

            if indicators_calculated > 0:
                self.logger.debug(
                    "Calculated indicators",
                    symbol=symbol,
                    timeframe=timeframe,
                    count=indicators_calculated,
                )

        except Exception as e:
            self.logger.error(
                "Error in indicator calculation", symbol_timeframe=symbol_timeframe, error=str(e)
            )
            self.metrics.error_count += 1

    async def _calculate_single_indicator(
        self, df: pd.DataFrame, indicator_name: str
    ) -> float | None:
        """Calculate a single indicator value using plugin-hybrid approach."""
        plugin_mode = self.config["service"].get("plugin_mode", "legacy")
        plugin_fallback = self.config["service"].get("plugin_fallback", True)
        plugin_preferences = set(self.config["service"].get("plugin_preference", []))

        # Try plugin-based calculation first if enabled
        if plugin_mode in ["plugin", "hybrid"]:
            plugin_result = await self._calculate_with_plugins(
                df, indicator_name, plugin_preferences
            )
            if plugin_result is not None:
                self.metrics.plugin_calculations += 1
                return plugin_result
            elif plugin_mode == "plugin" and not plugin_fallback:
                # Pure plugin mode with no fallback
                return None

        # Fallback to legacy calculation or legacy-only mode
        legacy_result = await self._calculate_with_legacy(df, indicator_name)
        if legacy_result is not None:
            self.metrics.legacy_calculations += 1
        return legacy_result

    async def _calculate_with_plugins(
        self, df: pd.DataFrame, indicator_name: str, preferences: set
    ) -> float | None:
        """Calculate indicator using plugin framework."""
        try:
            # Map indicator names to plugin names and outputs
            plugin_mapping = {
                "RSI": ("RSI", "rsi_14"),
                "SMA_20": ("MovingAverages", "sma_20"),
                "SMA_50": ("MovingAverages", "sma_50"),
                "SMA_10": ("MovingAverages", "sma_10"),
                "EMA_12": ("MovingAverages", "ema_12"),
                "EMA_20": ("MovingAverages", "ema_20"),
                "EMA_26": ("MovingAverages", "ema_26"),
                "EMA_50": ("MovingAverages", "ema_50"),
                "MACD": ("MACD", "macd_12_26_9"),
                "MACD_SIGNAL": ("MACD", "macd_signal_12_26_9"),
                "MACD_HISTOGRAM": ("MACD", "macd_histogram_12_26_9"),
                "BB_UPPER": ("BollingerBands", "bb_20_2_upper"),
                "BB_MIDDLE": ("BollingerBands", "bb_20_2_mid"),
                "BB_LOWER": ("BollingerBands", "bb_20_2_lower"),
                "ATR": ("ATR", "atr_14"),
                # Note: Need to verify these plugin output names
                "STOCH_K": ("Stochastic", "stoch_k"),
                "STOCH_D": ("Stochastic", "stoch_d"),
                "CCI": ("CCI", "cci_20"),
                "WILLIAMS_R": ("WilliamsR", "williams_r"),
                "MFI": ("MFI", "mfi_14"),
                "OBV": ("OBV", "obv"),
                "VWAP": ("VWAP", "vwap"),
            }

            if indicator_name not in plugin_mapping:
                return None

            plugin_name, output_key = plugin_mapping[indicator_name]

            # Skip if plugin not preferred (in hybrid mode)
            if preferences and plugin_name not in preferences:
                return None

            # Get plugin from registry
            try:
                plugin = self.plugin_registry.get_indicator(plugin_name)
            except KeyError:
                return None

            # Prepare frames for plugin
            frames = {"main": df}

            # Execute plugin calculation
            results = plugin.compute_full(frames)

            # Extract the specific output we need
            return results.get(output_key)

        except Exception as e:
            self.logger.debug("Plugin calculation failed", indicator=indicator_name, error=str(e))
            return None

    async def _calculate_with_legacy(self, df: pd.DataFrame, indicator_name: str) -> float | None:
        """Calculate indicator using legacy calculation methods."""
        try:
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

            elif indicator_name == "CCI":
                cci_result = self.indicator_calc.calculate_cci(df)
                return cci_result.get("cci_20") if cci_result else None

            elif indicator_name == "WILLIAMS_R":
                williams_result = self.indicator_calc.calculate_williams_r(df)
                return williams_result.get("willr_14") if williams_result else None

            elif indicator_name == "MFI":
                mfi_result = self.indicator_calc.calculate_mfi(df)
                return mfi_result.get("mfi_14") if mfi_result else None

            elif indicator_name == "OBV":
                obv_result = self.indicator_calc.calculate_enhanced_obv(df)
                return obv_result.get("obv") if obv_result else None

            elif indicator_name == "VWAP":
                vwap_result = self.indicator_calc.calculate_vwap(df)
                return vwap_result.get("vwap") if vwap_result else None

            else:
                self.logger.warning("Unknown indicator", indicator=indicator_name)
                return None

        except Exception as e:
            self.logger.error(
                "Error calculating legacy indicator", indicator=indicator_name, error=str(e)
            )
            return None

    async def _publish_indicator_result(
        self, symbol: str, timeframe: str, indicator_name: str, value: float, timestamp: datetime
    ):
        """Publish indicator result to Redis."""
        try:
            stream_name = sk_indicators(self.env_prefix, symbol, timeframe)

            indicator_data = {
                "timestamp": timestamp.isoformat(),
                "symbol": symbol,
                "timeframe": timeframe,
                "indicator_name": indicator_name,
                "value": str(value),
                "source": "indicator_processor_service",
            }

            # Safe trimming to cap memory usage per stream
            maxlen = int(self.config["service"].get("indicator_stream_maxlen", 200000))
            await self.redis_client.xadd(
                stream_name, indicator_data, maxlen=maxlen, approximate=True
            )

        except Exception as e:
            self.logger.error(
                "Error publishing indicator result", indicator=indicator_name, error=str(e)
            )

    async def _store_indicator_result(
        self, symbol: str, timeframe: str, indicator_name: str, value: float, timestamp: datetime
    ):
        """Store indicator result in database."""
        try:
            async with self.db_manager.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO technical_indicators
                    (timestamp, symbol, timeframe, indicator_name, value, source)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (timestamp, symbol, timeframe, indicator_name)
                    DO UPDATE SET value = EXCLUDED.value, source = EXCLUDED.source
                """,
                    timestamp,
                    symbol,
                    timeframe,
                    indicator_name,
                    value,
                    "indicator_processor_service",
                )

        except Exception as e:
            self.logger.error(
                "Error storing indicator result", indicator=indicator_name, error=str(e)
            )

    async def _health_monitor_loop(self):
        """Health monitoring loop."""
        while self.running and not self.shutdown_requested:
            try:
                await asyncio.sleep(self.config["service"]["health_check_interval"])

                # Update metrics
                current_time = datetime.now()
                self.metrics.uptime_seconds = int((current_time - self.start_time).total_seconds())

                # Calculate indicators per minute
                if self.metrics.uptime_seconds > 0:
                    self.metrics.indicators_per_minute = (
                        self.metrics.total_indicators_calculated
                        * 60.0
                        / self.metrics.uptime_seconds
                    )

                # Check health
                redis_healthy = await self._check_redis_health()
                db_healthy = await self._check_database_health()

                # Collect lightweight stream metrics (optional)
                if redis_healthy and self.config["service"].get("lag_metrics_enabled", True):
                    try:
                        stream_len, pending = await self._collect_stream_metrics()
                        self.metrics.stream_total_length = stream_len
                        self.metrics.pending_total = pending
                    except Exception as e:
                        self.logger.debug("Stream metrics collection skipped", error=str(e))

                if redis_healthy and db_healthy:
                    self.metrics.health_status = "healthy"
                else:
                    self.metrics.health_status = "degraded"

                # Log health status with plugin metrics
                self.logger.info(
                    "Health check",
                    uptime=self.metrics.uptime_seconds,
                    bars_processed=self.metrics.total_bars_processed,
                    indicators_calculated=self.metrics.total_indicators_calculated,
                    indicators_per_min=self.metrics.indicators_per_minute,
                    plugin_calculations=self.metrics.plugin_calculations,
                    legacy_calculations=self.metrics.legacy_calculations,
                    plugin_enabled=self.metrics.plugin_enabled,
                    stream_len=self.metrics.stream_total_length,
                    pending=self.metrics.pending_total,
                    health_status=self.metrics.health_status,
                )

            except Exception as e:
                self.logger.error("Error in health monitor", error=str(e))
                self.metrics.health_status = "error"

    async def _collect_stream_metrics(self) -> tuple[int, int]:
        """Collect aggregate stream length and pending counts across a sample of streams.
        Returns (total_stream_length, total_pending).
        """
        total_len = 0
        total_pending = 0
        sample_size = int(self.config["service"].get("lag_metrics_sample_size", 50))

        # Build a finite list of streams to sample
        streams: list[str] = []
        for timeframe in self.config["service"]["timeframes"]:
            for symbol in self.config["service"]["symbols"]:
                streams.append(sk_indicators(self.env_prefix, symbol, timeframe))
                if len(streams) >= sample_size:
                    break
            if len(streams) >= sample_size:
                break

        # Query xlen and xpending summary for our consumer group
        group = self.consumer_group
        for stream in streams:
            try:
                slen = await self.redis_client.xlen(stream)
                total_len += int(slen or 0)
                # Pending summary for the group
                pending_summary = await self.redis_client.xpending(stream, group)
                # redis-py returns dict-like: {'pending': int, ...} or raises
                if isinstance(pending_summary, dict) and "pending" in pending_summary:
                    total_pending += int(pending_summary.get("pending", 0))
                else:
                    # Some versions return a tuple (pending, smallest, largest, consumers)
                    try:
                        total_pending += int(pending_summary[0])  # type: ignore[index]
                    except Exception:
                        pass
            except Exception:
                # Stream or group may not exist yet
                continue

        return total_len, total_pending

    async def _metrics_update_loop(self):
        """Metrics update loop."""
        while self.running and not self.shutdown_requested:
            try:
                await asyncio.sleep(60)  # Update every minute

                # Write metrics to status file
                status_file = Path("logs/indicator_processor_status.json")
                status_file.parent.mkdir(exist_ok=True)

                status = {
                    "service": "indicator_processor",
                    "status": self.metrics.health_status,
                    "uptime_seconds": self.metrics.uptime_seconds,
                    "bars_processed": self.metrics.total_bars_processed,
                    "indicators_calculated": self.metrics.total_indicators_calculated,
                    "indicators_per_minute": self.metrics.indicators_per_minute,
                    "plugin_calculations": self.metrics.plugin_calculations,
                    "legacy_calculations": self.metrics.legacy_calculations,
                    "plugin_enabled": self.metrics.plugin_enabled,
                    "plugin_ratio": (
                        self.metrics.plugin_calculations
                        / max(1, self.metrics.total_indicators_calculated)
                    )
                    * 100,
                    "active_symbols": list(self.metrics.active_symbols),
                    "active_timeframes": list(self.metrics.active_timeframes),
                    "error_count": self.metrics.error_count,
                    "last_update": datetime.now().isoformat(),
                }

                with open(status_file, "w") as f:
                    json.dump(status, f, indent=2)

            except Exception as e:
                self.logger.error("Error updating metrics", error=str(e))

    async def _check_redis_health(self) -> bool:
        """Check Redis connection health."""
        try:
            await self.redis_client.ping()
            self.metrics.redis_connected = True
            return True
        except Exception:
            self.metrics.redis_connected = False
            return False

    async def _check_database_health(self) -> bool:
        """Check database connection health."""
        try:
            async with self.db_manager.get_connection() as conn:
                await conn.fetchval("SELECT 1")
            self.metrics.database_connected = True
            return True
        except Exception:
            self.metrics.database_connected = False
            return False

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        self.logger.info("Received shutdown signal", signal=signum)
        self.shutdown_requested = True

    async def stop(self):
        """Stop the service."""
        self.logger.info("⏹️  Stopping Indicator Processor Service...")

        self.running = False
        self.shutdown_requested = True

        # Stop HTTP server
        await self._stop_http_server()

        # Close connections
        if self.redis_client:
            await self.redis_client.aclose()

        if self.db_manager:
            await self.db_manager.close()

        self.logger.info("✅ Indicator Processor Service stopped")

    async def _start_http_server(self):
        """Start HTTP server for health endpoints."""
        try:
            self.http_app = web.Application()

            # Add health endpoint
            self.http_app.router.add_get("/health", self._handle_health)
            self.http_app.router.add_get("/metrics", self._handle_metrics)

            # Start server
            runner = web.AppRunner(self.http_app)
            await runner.setup()

            self.http_server = web.TCPSite(runner, "localhost", self.health_port)
            await self.http_server.start()

            self.logger.info("HTTP health server started", port=self.health_port)

        except Exception as e:
            self.logger.error("Failed to start HTTP server", error=str(e))
            raise

    async def _stop_http_server(self):
        """Stop HTTP server."""
        try:
            if self.http_server:
                await self.http_server.stop()
                self.http_server = None
                self.logger.info("HTTP health server stopped")
        except Exception as e:
            self.logger.error("Error stopping HTTP server", error=str(e))

    async def _handle_health(self, request: web_request.Request) -> web.Response:
        """Handle health check endpoint."""
        try:
            health_data = {
                "status": self.metrics.health_status,
                "service": "indicator_processor",
                "uptime_seconds": self.metrics.uptime_seconds,
                "redis_connected": self.metrics.redis_connected,
                "database_connected": self.metrics.database_connected,
                "bars_processed": self.metrics.total_bars_processed,
                "indicators_calculated": self.metrics.total_indicators_calculated,
                "error_count": self.metrics.error_count,
                "last_processing": (
                    self.metrics.last_processing_time.isoformat()
                    if self.metrics.last_processing_time
                    else None
                ),
                "timestamp": datetime.now().isoformat(),
            }

            # Return appropriate HTTP status based on health
            if self.metrics.health_status == "healthy":
                status = 200
            elif self.metrics.health_status in ["degraded", "starting"]:
                status = 503  # Service Unavailable but recoverable
            else:
                status = 500  # Internal Server Error

            return web.json_response(health_data, status=status)

        except Exception as e:
            self.logger.error("Error in health endpoint", error=str(e))
            return web.json_response({"status": "error", "error": str(e)}, status=500)

    async def _handle_metrics(self, request: web_request.Request) -> web.Response:
        """Handle metrics endpoint (Prometheus-style)."""
        try:
            metrics_text = f"""# HELP indicator_bars_processed_total Total bars processed
# TYPE indicator_bars_processed_total counter
indicator_bars_processed_total {self.metrics.total_bars_processed}

# HELP indicator_calculations_total Total indicators calculated
# TYPE indicator_calculations_total counter
indicator_calculations_total {self.metrics.total_indicators_calculated}

# HELP indicator_errors_total Total processing errors
# TYPE indicator_errors_total counter
indicator_errors_total {self.metrics.error_count}

# HELP indicator_uptime_seconds Service uptime in seconds
# TYPE indicator_uptime_seconds gauge
indicator_uptime_seconds {self.metrics.uptime_seconds}

# HELP indicator_redis_connected Redis connection status (1=connected, 0=disconnected)
# TYPE indicator_redis_connected gauge
indicator_redis_connected {1 if self.metrics.redis_connected else 0}

# HELP indicator_database_connected Database connection status (1=connected, 0=disconnected)
# TYPE indicator_database_connected gauge
indicator_database_connected {1 if self.metrics.database_connected else 0}

# HELP indicator_stream_length Current stream length
# TYPE indicator_stream_length gauge
indicator_stream_length {self.metrics.stream_total_length}

# HELP indicator_pending_messages Pending messages in consumer group
# TYPE indicator_pending_messages gauge
indicator_pending_messages {self.metrics.pending_total}
"""

            return web.Response(
                text=metrics_text, content_type="text/plain; version=0.0.4; charset=utf-8"
            )

        except Exception as e:
            self.logger.error("Error in metrics endpoint", error=str(e))
            return web.Response(text=f"# Error: {e}", status=500)


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Indicator Processor Service")
    parser.add_argument("--config", help="Configuration file path")
    parser.add_argument("--foreground", action="store_true", help="Run in foreground")
    args = parser.parse_args()

    service = IndicatorProcessorService(args.config)

    try:
        await service.start()
    except KeyboardInterrupt:
        await service.stop()
    except Exception as e:
        print(f"Service failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
