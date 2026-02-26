#!/usr/bin/env python3
"""
Market Analysis Service — I3/I4/I5/SMC/I6 plugin execution

Consumes the combined OHLCV+I1 messages published by indicator_service
from indicators:SYMBOL:TF, then runs I3 (structure) → I4 (context) →
I5 (pattern) → SMC (smart money) → I6 (confluence) and publishes
combined intelligence results to intelligence:SYMBOL:TF.

I1 is NOT recomputed here — it arrives pre-computed from indicator_service.
This eliminates the triple I1 computation that existed when each service
maintained its own indicator pipeline.
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
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import redis.asyncio as redis
import structlog

from services.indicator_service import parse_indicators_message
from src.config.settings import Settings, get_active_contracts
from src.core.database_manager import DatabaseManager
from src.core.stream_keys import indicators as sk_indicators
from src.core.stream_keys import intelligence as sk_intelligence
from src.intelligence.plugins import registry
from src.intelligence.register_plugins import (
    TIER_I3,
    TIER_I4,
    TIER_I5,
    TIER_I6,
    TIER_SMC,
    register_all_plugins,
)
from src.observability.metrics import (
    counter,
    gauge,
    record_plugin_execution,
    start_metrics_server,
)

# Plugin tier lists — imported from register_plugins (single source of truth)
I3_PLUGINS = TIER_I3
I4_PLUGINS = TIER_I4
I5_PLUGINS = TIER_I5
SMC_PLUGINS = TIER_SMC
I6_PLUGINS = TIER_I6


class MarketAnalysisService:
    """Execute I3/I4/I5/SMC/I6 intelligence plugins, consuming I1 from indicators stream."""

    def __init__(self, config_file: str | None = None):
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now()

        self.config = self._load_config(config_file)
        self._setup_logging()

        register_all_plugins()
        for tier_list, tier_name in [
            (I3_PLUGINS, "I3"), (I4_PLUGINS, "I4"), (I5_PLUGINS, "I5"),
            (SMC_PLUGINS, "SMC"), (I6_PLUGINS, "I6"),
        ]:
            registry.validate_tier(tier_list, tier_name)

        self.redis_client: redis.Redis | None = None
        self.db_manager: DatabaseManager | None = None
        self.consumer_group = "market_analysis"
        self.consumer_name = f"market_analysis_consumer_{os.getpid()}"

        settings = Settings()
        self.env_prefix = f"{settings.env_name}:" if settings.env_name else ""

        self.bar_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
        self.intelligence_cache: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)

        self.bars_processed_total = counter(
            "market_analysis_bars_processed_total",
            "Total indicator messages processed by market analysis service",
        )
        self.calculations_total = counter(
            "market_analysis_calculations_total",
            "Total intelligence calculations performed",
        )
        self.calculation_duration_ms = gauge(
            "market_analysis_calculation_duration_ms",
            "Last calculation duration in milliseconds",
        )
        self.service_uptime_seconds = gauge(
            "market_analysis_service_uptime_seconds",
            "Market analysis service uptime in seconds",
        )
        self.active_symbols_count = gauge(
            "market_analysis_active_symbols_count",
            "Number of active symbols being processed",
        )
        self.error_count_total = counter(
            "market_analysis_errors_total",
            "Total errors encountered by market analysis service",
        )

        self._total_bars = 0
        self._total_calculations = 0
        self._error_count = 0
        self._active_symbols: set[str] = set()

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        self.logger = structlog.get_logger(__name__)

    def _load_config(self, config_file: str | None) -> dict[str, Any]:
        try:
            _settings = Settings()
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
                "symbols": get_active_contracts(_settings),
                "timeframes": ["1m", "5m", "15m", "1h"],
                "processing_interval": 0.1,
                "health_check_interval": 30,
                "min_history_bars": 120,
            },
            "logging": {
                "level": "INFO",
                "file": "logs/market_analysis_service.log",
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

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self.logger.info("Received shutdown signal", signal=signum)
        self.shutdown_requested = True

    def _run_analysis_pipeline(
        self, symbol: str, timeframe: str, frames: dict[str, Any]
    ) -> dict[str, Any]:
        """Run I3→I4→I5→SMC→I6 synchronously.

        Returns tiered dict with keys: i3, i4, i5, smc, i6, flat.
        - i3/i4/i5/smc/i6 — per-tier result dicts for IntelligenceEvent construction
        - flat — merged dict for backward-compat (intelligence_cache, cross-tier feature sharing)
        """
        features: dict[str, Any] = dict(frames.get("features", {}))
        frames["features"] = features

        def _run_tier(
            plugins: list[str], tier: str, results: dict[str, Any]
        ) -> None:
            for pname in plugins:
                t0 = time.time()
                try:
                    p = registry.get_pattern(pname)
                    out = p.compute_full(frames)
                    results.update(out)
                    record_plugin_execution(
                        pname, symbol, timeframe, time.time() - t0, "success", tier
                    )
                except Exception as exc:
                    self.logger.warning(
                        f"{tier} plugin failed", plugin=pname, error=str(exc)
                    )
                    record_plugin_execution(
                        pname, symbol, timeframe, time.time() - t0, "error", tier
                    )

        i3_results: dict[str, Any] = {}
        _run_tier(I3_PLUGINS, "I3", i3_results)
        features.update(i3_results)
        frames["features"] = features

        i4_results: dict[str, Any] = {}
        _run_tier(I4_PLUGINS, "I4", i4_results)
        features.update(i4_results)
        frames["features"] = features

        i5_results: dict[str, Any] = {}
        _run_tier(I5_PLUGINS, "I5", i5_results)
        features.update(i5_results)
        frames["features"] = features

        smc_results: dict[str, Any] = {}
        _run_tier(SMC_PLUGINS, "SMC", smc_results)
        # Rename SMC's trend_direction to smc_trend_direction before updating features
        # to avoid collision with I3's trend_direction in the flat features dict
        if "trend_direction" in smc_results:
            smc_results["smc_trend_direction"] = smc_results.pop("trend_direction")
        features.update(smc_results)
        frames["features"] = features

        i6_results: dict[str, Any] = {}
        _run_tier(I6_PLUGINS, "I6", i6_results)

        flat: dict[str, Any] = {}
        flat.update(i3_results)
        flat.update(i4_results)
        flat.update(i5_results)
        flat.update(smc_results)
        flat.update(i6_results)

        tiered = {
            "i3": i3_results,
            "i4": i4_results,
            "i5": i5_results,
            "smc": smc_results,
            "i6": i6_results,
            "flat": flat,
        }

        self.intelligence_cache[symbol][timeframe] = flat
        return tiered

    def _min_bars_for_tf(self, timeframe: str) -> int:
        """Return minimum bars before publishing intelligence, per-TF."""
        if timeframe == "1m":
            return self.config["service"]["min_history_bars"]
        return 26  # 5m/15m/1h — fewer unique bars available after dedup

    async def _calculate_intelligence(
        self,
        symbol: str,
        timeframe: str,
        timestamp: datetime,
        i1_features: dict[str, Any],
    ) -> dict[str, Any]:
        """Run the I3→I6 pipeline. Returns tiered dict (i3/i4/i5/smc/i6/flat) or {}."""
        key = f"{symbol}:{timeframe}"
        history = self.bar_history[key]
        min_bars = self._min_bars_for_tf(timeframe)

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

        # I1 features arrive pre-computed from indicator_service
        frames["features"] = dict(i1_features)

        tiered = self._run_analysis_pipeline(symbol, timeframe, frames)

        self.calculations_total.inc()
        self._total_calculations += 1
        return tiered

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
            bar_data, i1_features = parse_indicators_message(fields)
            bar_data["timestamp"] = bar_ts

            key = f"{symbol}:{timeframe}"
            self.bar_history[key].append(bar_data)

            calc_start = time.time()
            tiered = await self._calculate_intelligence(
                symbol, timeframe, bar_ts, i1_features
            )
            calc_ms = (time.time() - calc_start) * 1000

            if tiered:
                await self._publish_intelligence(
                    symbol, timeframe, tiered, bar_ts, bar_data, i1_features
                )
                await self._persist_intelligence(symbol, timeframe, tiered.get("flat", {}), bar_ts)

            self.bars_processed_total.inc()
            self._total_bars += 1
            self._active_symbols.add(symbol)
            self.calculation_duration_ms.set(calc_ms)

            await self.redis_client.xack(stream_name, self.consumer_group, message_id)

            self.logger.debug(
                "Bar processed",
                symbol=symbol,
                timeframe=timeframe,
                outputs=len(tiered.get("flat", {})) if tiered else 0,
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

    async def _publish_intelligence(
        self,
        symbol: str,
        timeframe: str,
        tiered: dict[str, Any],
        timestamp: datetime,
        bar_data: dict[str, Any] | None = None,
        i1_features: dict[str, Any] | None = None,
    ) -> None:
        """Publish a validated IntelligenceEvent to the intelligence: Redis stream.

        Emits a single {"event": "<json>"} field — not flat str(v) k/v pairs.
        Drops the event on ValidationError (malformed plugin output) after logging.
        """
        from pydantic import ValidationError

        from src.intelligence.schemas import (
            I1Indicators,
            I3Structure,
            I4Context,
            I5Patterns,
            I6Confluence,
            IntelligenceEvent,
            OHLCVBar,
            SMCContext,
        )

        bar_data = bar_data or {}
        i1_features = i1_features or {}

        try:
            event = IntelligenceEvent(
                ts=timestamp,
                symbol=symbol,
                tf=timeframe,
                bar=OHLCVBar(
                    o=float(bar_data.get("open", 0.0)),
                    h=float(bar_data.get("high", 0.0)),
                    l=float(bar_data.get("low", 0.0)),
                    c=float(bar_data.get("close", 0.0)),
                    v=int(bar_data.get("volume", 0)),
                ),
                i1=I1Indicators(**{k: v for k, v in i1_features.items() if v is not None}),
                i3=I3Structure(**tiered.get("i3", {})),
                i4=I4Context(**tiered.get("i4", {})),
                i5=I5Patterns(**tiered.get("i5", {})),
                smc=SMCContext(**tiered.get("smc", {})),
                i6=I6Confluence(**tiered.get("i6", {})),
                source="live",
            )
        except ValidationError as e:
            self.logger.error(
                "IntelligenceEvent validation failed — event dropped",
                symbol=symbol,
                tf=timeframe,
                error=str(e),
            )
            self.error_count_total.inc()
            return  # Do NOT publish malformed events

        stream_name = sk_intelligence(self.env_prefix, symbol, timeframe)
        await self.redis_client.xadd(
            stream_name,
            {"event": event.model_dump_json()},
            maxlen=1000,
            approximate=True,
        )

    async def _persist_intelligence(
        self,
        symbol: str,
        timeframe: str,
        intelligence: dict[str, Any],
        timestamp: datetime,
    ) -> None:
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
                    "market_analysis_service",
                )
        except Exception as e:
            self.logger.warning("Failed to persist intelligence", symbol=symbol, error=str(e))

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
                stream_name = sk_indicators(self.env_prefix, symbol, timeframe)
                try:
                    await self.redis_client.xgroup_create(
                        stream_name, self.consumer_group, "$", mkstream=True
                    )
                except Exception:
                    # Group already exists — reset to current tail so stale backlog is skipped
                    await self.redis_client.xgroup_setid(stream_name, self.consumer_group, "$")

    async def _process_market_data(self) -> None:
        while self.running and not self.shutdown_requested:
            try:
                for timeframe in self.config["service"]["timeframes"]:
                    for symbol in self.config["service"]["symbols"]:
                        stream_name = sk_indicators(self.env_prefix, symbol, timeframe)
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

    async def start(self) -> None:
        self.logger.info("Starting Market Analysis Service", config=self.config["service"])
        try:
            await self._connect_redis()
            await self._connect_database()
            start_metrics_server(port=self.config.get("metrics_port", 9114))
            await self._setup_consumer_groups()
            self.running = True
            tasks = [
                asyncio.create_task(self._process_market_data()),
                asyncio.create_task(self._health_monitor_loop()),
            ]
            self.logger.info("Market Analysis Service started")
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error("Failed to start market analysis service", error=str(e))
            raise
        finally:
            await self.stop()

    async def stop(self) -> None:
        self.logger.info("Stopping Market Analysis Service")
        self.running = False
        self.shutdown_requested = True
        if self.redis_client:
            await self.redis_client.aclose()
        if self.db_manager:
            await self.db_manager.close()
        self.logger.info("Market Analysis Service stopped")


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Market Analysis Service")
    parser.add_argument("--config", help="Configuration file path")
    args = parser.parse_args()

    service = MarketAnalysisService(args.config)
    try:
        await service.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
