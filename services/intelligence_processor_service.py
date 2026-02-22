#!/usr/bin/env python3
"""
Intelligence Processor Service — I3/I4/I5/SMC/I6 plugin execution

Consumes market data bars from Redis Streams, computes I1 features internally,
then runs I3 (structure) → I4 (context) → I5 (pattern) → SMC (smart money)
plugins and publishes combined intelligence results back to Redis.

Design: self-contained I1 computation avoids timing/sync issues with the
indicators stream (where each indicator arrives as a separate message).
I1 is <1ms total, negligible vs the 10-25ms I3/I4/I5 work.

Version: 1.0.0
Last Updated: 2026-02-11
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
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from logging.handlers import RotatingFileHandler  # noqa: E402

import pandas as pd  # noqa: E402
import redis.asyncio as redis  # noqa: E402
import structlog  # noqa: E402

from src.config.settings import Settings  # noqa: E402
from src.core.database_manager import DatabaseManager  # noqa: E402
from src.core.stream_keys import intelligence as sk_intelligence  # noqa: E402
from src.core.stream_keys import market as sk_market  # noqa: E402
from src.intelligence.plugins import registry  # noqa: E402
from src.intelligence.register_plugins import (  # noqa: E402
    TIER_I1,
    TIER_I3,
    TIER_I4,
    TIER_I5,
    TIER_I6,
    TIER_SMC,
    register_all_plugins,
)
from src.observability.metrics import (  # noqa: E402
    counter,
    gauge,
    record_plugin_execution,
    start_metrics_server,
)

# Plugin name lists — must match names in register_plugins.py
# Plugin tier lists — imported from register_plugins (single source of truth)
I1_PLUGINS = TIER_I1
I3_PLUGINS = TIER_I3
I4_PLUGINS = TIER_I4
I5_PLUGINS = TIER_I5
SMC_PLUGINS = TIER_SMC
I6_PLUGINS = TIER_I6


class IntelligenceProcessorService:
    """Execute I3/I4/I5/SMC/I6 intelligence plugins on incoming market data."""

    def __init__(self, config_file: str | None = None):
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now()

        self.config = self._load_config(config_file)
        self._setup_logging()

        # Populate the plugin registry
        register_all_plugins()
        for tier_list, tier_name in [
            (I1_PLUGINS, "I1"), (I3_PLUGINS, "I3"), (I4_PLUGINS, "I4"),
            (I5_PLUGINS, "I5"), (SMC_PLUGINS, "SMC"), (I6_PLUGINS, "I6"),
        ]:
            registry.validate_tier(tier_list, tier_name)

        self.redis_client: redis.Redis | None = None
        self.db_manager: DatabaseManager | None = None
        self.consumer_group = f"intelligence_processor_{int(time.time())}"
        self.consumer_name = f"intelligence_consumer_{os.getpid()}"

        settings = Settings()
        self.env_prefix = f"{settings.env_name}:" if settings.env_name else ""

        self.bar_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))

        # Cross-timeframe intelligence cache: symbol → timeframe → last intelligence dict
        self.intelligence_cache: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)

        # Prometheus metrics
        self.bars_processed_total = counter(
            "intelligence_bars_processed_total",
            "Total market data bars processed by intelligence service",
        )
        self.calculations_total = counter(
            "intelligence_calculations_total",
            "Total intelligence calculations performed",
        )
        self.calculation_duration_ms = gauge(
            "intelligence_calculation_duration_ms",
            "Last calculation duration in milliseconds",
        )
        self.service_uptime_seconds = gauge(
            "intelligence_service_uptime_seconds",
            "Intelligence service uptime in seconds",
        )
        self.active_symbols_count = gauge(
            "intelligence_active_symbols_count",
            "Number of active symbols being processed",
        )
        self.error_count_total = counter(
            "intelligence_errors_total",
            "Total errors encountered by intelligence service",
        )

        # Tracking
        self._total_bars = 0
        self._total_calculations = 0
        self._error_count = 0
        self._active_symbols: set[str] = set()

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger = structlog.get_logger(__name__)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _load_config(self, config_file: str | None) -> dict[str, Any]:
        try:
            from src.config.settings import Settings as _Settings
            _settings = _Settings()
        except Exception:
            _settings = None

        default_config: dict[str, Any] = {
            "redis": {"host": "localhost", "port": 6379, "db": 0},
            "database": {
                "url": (
                    _settings.database_url
                    if _settings and getattr(_settings, "database_url", None)
                    else "postgresql://postgres:postgres@localhost:5432/indicagent"
                )
            },
            "service": {
                "symbols": ["ESU5", "NQU5", "RTYU5", "CLU5", "GCZ5", "NGU25"],
                "timeframes": ["1m", "5m", "15m", "1h"],
                "processing_interval": 0.1,
                "health_check_interval": 30,
                "min_history_bars": 120,
            },
            "logging": {
                "level": "INFO",
                "file": "logs/intelligence_processor.log",
                "max_size": "10MB",
                "backup_count": 5,
            },
        }

        if config_file and Path(config_file).exists():
            with open(config_file) as f:
                user_config = json.load(f)
            for key, value in user_config.items():
                if isinstance(value, dict) and key in default_config:
                    default_config[key].update(value)
                else:
                    default_config[key] = value

        return default_config

    def _setup_logging(self) -> None:
        log_dir = Path(self.config["logging"]["file"]).parent
        log_dir.mkdir(exist_ok=True)

        file_handler = RotatingFileHandler(
            self.config["logging"]["file"],
            maxBytes=10 * 1024 * 1024,
            backupCount=self.config["logging"].get("backup_count", 5),
        )

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

        logging.basicConfig(
            level=getattr(logging, self.config["logging"]["level"]),
            handlers=[file_handler],
            format="%(message)s",
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self.logger.info(
            "Starting Intelligence Processor Service",
            config=self.config["service"],
        )

        try:
            await self._connect_redis()
            await self._connect_database()
            start_metrics_server(port=9111)
            await self._setup_consumer_groups()

            self.running = True
            tasks = [
                asyncio.create_task(self._process_market_data()),
                asyncio.create_task(self._health_monitor_loop()),
            ]

            self.logger.info("Intelligence Processor Service started")
            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            self.logger.error("Failed to start intelligence service", error=str(e))
            raise
        finally:
            await self.stop()

    async def _connect_redis(self) -> None:
        self.redis_client = redis.Redis(
            host=self.config["redis"]["host"],
            port=self.config["redis"]["port"],
            db=self.config["redis"]["db"],
            decode_responses=False,
        )
        await self.redis_client.ping()
        self.logger.info("Connected to Redis")

    async def _connect_database(self) -> None:
        try:
            self.db_manager = DatabaseManager(self.config["database"]["url"])
            await self.db_manager.initialize()
            self.logger.info("Connected to database")
        except Exception as e:
            self.logger.warning("Database connection failed, persistence disabled", error=str(e))
            self.db_manager = None

    async def _setup_consumer_groups(self) -> None:
        for timeframe in self.config["service"]["timeframes"]:
            for symbol in self.config["service"]["symbols"]:
                stream_name = sk_market(self.env_prefix, symbol, timeframe)
                try:
                    await self.redis_client.xgroup_create(
                        stream_name, self.consumer_group, "0", mkstream=True
                    )
                except Exception:
                    pass  # Group already exists

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self.logger.info("Received shutdown signal", signal=signum)
        self.shutdown_requested = True

    async def stop(self) -> None:
        self.logger.info("Stopping Intelligence Processor Service")
        self.running = False
        self.shutdown_requested = True
        if self.redis_client:
            await self.redis_client.aclose()
        if self.db_manager:
            await self.db_manager.close()
        self.logger.info("Intelligence Processor Service stopped")

    # ------------------------------------------------------------------
    # Processing loop
    # ------------------------------------------------------------------

    async def _process_market_data(self) -> None:
        self.logger.info("Starting market data processing loop")

        while self.running and not self.shutdown_requested:
            try:
                for timeframe in self.config["service"]["timeframes"]:
                    for symbol in self.config["service"]["symbols"]:
                        stream_name = sk_market(self.env_prefix, symbol, timeframe)
                        messages = await self.redis_client.xreadgroup(
                            self.consumer_group,
                            self.consumer_name,
                            {stream_name: ">"},
                            count=10,
                            block=100,
                        )
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
                self._error_count += 1
                await asyncio.sleep(1)

    async def _process_single_bar(
        self,
        symbol: str,
        timeframe: str,
        fields: dict[bytes, bytes],
        stream_name: str,
        message_id: bytes,
    ) -> None:
        try:
            bar_ts = datetime.fromisoformat(fields[b"timestamp"].decode())
            bar_source = fields.get(b"source", b"").decode()
            bar_data = {
                "timestamp": bar_ts,
                "open": float(fields[b"open"].decode()),
                "high": float(fields[b"high"].decode()),
                "low": float(fields[b"low"].decode()),
                "close": float(fields[b"close"].decode()),
                "volume": int(float(fields[b"volume"].decode())),
            }

            key = f"{symbol}:{timeframe}"
            history = self.bar_history[key]

            if bar_source == "authoritative":
                # Correction: update history, skip pipeline
                if history and history[-1]["timestamp"] == bar_ts:
                    history[-1] = bar_data  # in-place correction
                else:
                    history.append(bar_data)  # no prior provisional; add to history
                await self.redis_client.xack(stream_name, self.consumer_group, message_id)
                return

            history.append(bar_data)

            calc_start = time.time()
            intelligence = await self._calculate_intelligence(
                symbol, timeframe, bar_data["timestamp"]
            )
            calc_ms = (time.time() - calc_start) * 1000

            if intelligence:
                await self._publish_intelligence(
                    symbol, timeframe, intelligence, bar_data["timestamp"], bar_data
                )
                await self._persist_intelligence(
                    symbol, timeframe, intelligence, bar_data["timestamp"]
                )

            # Metrics
            self.bars_processed_total.inc()
            self._total_bars += 1
            self._active_symbols.add(symbol)
            self.calculation_duration_ms.set(calc_ms)

            await self.redis_client.xack(stream_name, self.consumer_group, message_id)

            self.logger.debug(
                "Bar processed",
                symbol=symbol,
                timeframe=timeframe,
                outputs=len(intelligence) if intelligence else 0,
                calc_ms=round(calc_ms, 2),
            )

        except Exception as e:
            self.logger.error(
                "Error processing bar",
                symbol=symbol,
                timeframe=timeframe,
                error=str(e),
            )
            self.error_count_total.inc()
            self._error_count += 1

    # ------------------------------------------------------------------
    # Intelligence calculation — core tier-chaining logic
    # ------------------------------------------------------------------

    async def _calculate_intelligence(
        self, symbol: str, timeframe: str, timestamp: datetime
    ) -> dict[str, float]:
        key = f"{symbol}:{timeframe}"
        history = self.bar_history[key]
        min_bars = self.config["service"]["min_history_bars"]

        if len(history) < min_bars:
            return {}

        df = pd.DataFrame(list(history))
        frames: dict[str, Any] = {"main": df}

        # Inject cross-timeframe bar history and cached intelligence
        tf_hierarchy = ["1m", "5m", "15m", "1h"]
        for other_tf in tf_hierarchy:
            if other_tf == timeframe:
                continue
            other_key = f"{symbol}:{other_tf}"
            if other_key in self.bar_history and len(self.bar_history[other_key]) >= 50:
                frames[f"tf_{other_tf}"] = pd.DataFrame(list(self.bar_history[other_key]))
            cached = self.intelligence_cache.get(symbol, {}).get(other_tf)
            if cached:
                frames[f"intel_{other_tf}"] = cached

        features: dict[str, Any] = {}

        # --- I1: compute indicator features from OHLCV ---
        for plugin_name in I1_PLUGINS:
            t0 = time.time()
            try:
                p = registry.get_indicator(plugin_name)
                result = p.compute_full(frames)
                features.update(result)
                record_plugin_execution(
                    plugin_name, symbol, timeframe,
                    time.time() - t0, "success", "I1",
                )
            except Exception as e:
                self.logger.warning(
                    "I1 plugin failed", plugin=plugin_name, error=str(e)
                )
                record_plugin_execution(
                    plugin_name, symbol, timeframe,
                    time.time() - t0, "error", "I1",
                )

        frames["features"] = features

        # --- I3: market structure ---
        i3_results: dict[str, Any] = {}
        for plugin_name in I3_PLUGINS:
            t0 = time.time()
            try:
                p = registry.get_pattern(plugin_name)
                result = p.compute_full(frames)
                i3_results.update(result)
                record_plugin_execution(
                    plugin_name, symbol, timeframe,
                    time.time() - t0, "success", "I3",
                )
            except Exception as e:
                self.logger.warning(
                    "I3 plugin failed", plugin=plugin_name, error=str(e)
                )
                record_plugin_execution(
                    plugin_name, symbol, timeframe,
                    time.time() - t0, "error", "I3",
                )

        # Fold I3 outputs into features so I4 TrendRegime can blend
        features.update(i3_results)
        frames["features"] = features

        # --- I4: context classification ---
        i4_results: dict[str, Any] = {}
        for plugin_name in I4_PLUGINS:
            t0 = time.time()
            try:
                p = registry.get_pattern(plugin_name)
                result = p.compute_full(frames)
                i4_results.update(result)
                record_plugin_execution(
                    plugin_name, symbol, timeframe,
                    time.time() - t0, "success", "I4",
                )
            except Exception as e:
                self.logger.warning(
                    "I4 plugin failed", plugin=plugin_name, error=str(e)
                )
                record_plugin_execution(
                    plugin_name, symbol, timeframe,
                    time.time() - t0, "error", "I4",
                )

        # Fold I4 outputs into features so I5 Confluence has full context
        features.update(i4_results)
        frames["features"] = features

        # --- I5: pattern detection ---
        i5_results: dict[str, Any] = {}
        for plugin_name in I5_PLUGINS:
            t0 = time.time()
            try:
                p = registry.get_pattern(plugin_name)
                result = p.compute_full(frames)
                i5_results.update(result)
                record_plugin_execution(
                    plugin_name, symbol, timeframe,
                    time.time() - t0, "success", "I5",
                )
            except Exception as e:
                self.logger.warning(
                    "I5 plugin failed", plugin=plugin_name, error=str(e)
                )
                record_plugin_execution(
                    plugin_name, symbol, timeframe,
                    time.time() - t0, "error", "I5",
                )

        # Fold I5 outputs into features so SMC BOCPD has full context
        features.update(i5_results)
        frames["features"] = features

        # --- SMC: smart money concepts ---
        smc_results: dict[str, Any] = {}
        for plugin_name in SMC_PLUGINS:
            t0 = time.time()
            try:
                p = registry.get_pattern(plugin_name)
                result = p.compute_full(frames)
                smc_results.update(result)
                record_plugin_execution(
                    plugin_name, symbol, timeframe,
                    time.time() - t0, "success", "SMC",
                )
            except Exception as e:
                self.logger.warning(
                    "SMC plugin failed", plugin=plugin_name, error=str(e)
                )
                record_plugin_execution(
                    plugin_name, symbol, timeframe,
                    time.time() - t0, "error", "SMC",
                )

        # Fold SMC outputs into features so I6 has full context
        features.update(smc_results)
        frames["features"] = features

        # --- I6: cross-timeframe confluence ---
        i6_results: dict[str, Any] = {}
        for plugin_name in I6_PLUGINS:
            t0 = time.time()
            try:
                p = registry.get_pattern(plugin_name)
                result = p.compute_full(frames)
                i6_results.update(result)
                record_plugin_execution(
                    plugin_name, symbol, timeframe,
                    time.time() - t0, "success", "I6",
                )
            except Exception as e:
                self.logger.warning(
                    "I6 plugin failed", plugin=plugin_name, error=str(e)
                )
                record_plugin_execution(
                    plugin_name, symbol, timeframe,
                    time.time() - t0, "error", "I6",
                )

        # Combine all higher-tier outputs (exclude I1 raw features)
        intelligence = {}
        intelligence.update(i3_results)
        intelligence.update(i4_results)
        intelligence.update(i5_results)
        intelligence.update(smc_results)
        intelligence.update(i6_results)

        # Cache for cross-timeframe access by later timeframes
        self.intelligence_cache[symbol][timeframe] = intelligence

        self.calculations_total.inc()
        self._total_calculations += 1
        return intelligence

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    async def _publish_intelligence(
        self,
        symbol: str,
        timeframe: str,
        intelligence: dict[str, Any],
        timestamp: datetime,
        bar_data: dict[str, Any] | None = None,
    ) -> None:
        stream_name = sk_intelligence(self.env_prefix, symbol, timeframe)
        message: dict[str, str] = {
            "timestamp": timestamp.isoformat(),
            "symbol": symbol,
            "timeframe": timeframe,
        }
        # Include raw bar OHLCV so downstream services need only one stream
        if bar_data:
            message["open"]   = str(bar_data.get("open", ""))
            message["high"]   = str(bar_data.get("high", ""))
            message["low"]    = str(bar_data.get("low", ""))
            message["close"]  = str(bar_data.get("close", ""))
            message["volume"] = str(bar_data.get("volume", ""))
        for k, v in intelligence.items():
            message[k] = str(v)

        await self.redis_client.xadd(stream_name, message, maxlen=1000, approximate=True)

    async def _persist_intelligence(
        self,
        symbol: str,
        timeframe: str,
        intelligence: dict[str, Any],
        timestamp: datetime,
    ) -> None:
        """Persist intelligence results to TimescaleDB (cold storage)."""
        if not self.db_manager:
            return
        try:
            async with self.db_manager.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO intelligence (timestamp, symbol, timeframe, kind, payload, source)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (timestamp, symbol, timeframe, kind)
                    DO UPDATE SET payload = EXCLUDED.payload, source = EXCLUDED.source
                    """,
                    timestamp,
                    symbol,
                    timeframe,
                    "combined",
                    json.dumps({
                        k: v for k, v in intelligence.items()
                        if isinstance(v, (int, float, str, bool))
                    }),
                    "intelligence_processor_service",
                )
        except Exception as e:
            self.logger.warning("Failed to persist intelligence", symbol=symbol, error=str(e))

    # ------------------------------------------------------------------
    # Health monitoring
    # ------------------------------------------------------------------

    async def _health_monitor_loop(self) -> None:
        while self.running and not self.shutdown_requested:
            try:
                uptime = int((datetime.now() - self.start_time).total_seconds())
                self.service_uptime_seconds.set(uptime)
                self.active_symbols_count.set(len(self._active_symbols))

                if uptime % self.config["service"]["health_check_interval"] == 0:
                    self.logger.info(
                        "Health check",
                        uptime=uptime,
                        bars_processed=self._total_bars,
                        calculations=self._total_calculations,
                        active_symbols=len(self._active_symbols),
                        errors=self._error_count,
                    )

                await asyncio.sleep(self.config["service"]["health_check_interval"])
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in health monitor", error=str(e))
                await asyncio.sleep(5)


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Intelligence Processor Service")
    parser.add_argument("--config", help="Configuration file path")
    parser.add_argument("--foreground", action="store_true", help="Run in foreground")
    args = parser.parse_args()

    service = IntelligenceProcessorService(args.config)

    if args.foreground:
        print("Starting Intelligence Processor Service in foreground...")
        print("Press Ctrl+C to stop")

    try:
        await service.start()
    except KeyboardInterrupt:
        print("\nService stopped by user")
    except Exception as e:
        print(f"Service failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
