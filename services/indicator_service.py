#!/usr/bin/env python3
"""
Indicator Service — I1 technical indicator computation

Reads market bars from Redis Streams, runs all 23 I1 plugins via the
plugin registry, and publishes ONE combined OHLCV+indicators message per
bar to indicators:SYMBOL:TF. Downstream services consume this single
message — no coordination across multiple indicator messages needed.

Replaces: indicators_processor_service.py + indicators_enhanced_service.py
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

from src.config.settings import Settings, get_active_contracts
from src.core.stream_keys import indicators as sk_indicators
from src.core.stream_keys import market as sk_market
from src.intelligence.plugins import registry
from src.intelligence.register_plugins import TIER_I1, register_all_plugins
from src.observability.metrics import counter, gauge, record_plugin_execution, start_metrics_server

# I1 plugin names — imported from register_plugins (single source of truth)
I1_PLUGINS = TIER_I1

_OHLCV_FIELDS = frozenset(
    {"timestamp", "symbol", "timeframe", "open", "high", "low", "close", "volume", "source"}
)


def build_i1_message(
    bar: dict[str, Any],
    features: dict[str, Any],
    timestamp: datetime,
    symbol: str,
    timeframe: str,
) -> dict[str, str]:
    """Build a flat string-valued Redis message combining OHLCV and I1 features.

    Only scalar values (str, int, float, bool) are included. Lists and dicts
    are silently dropped — Redis stream fields must be flat strings.
    """
    msg: dict[str, str] = {
        "timestamp": timestamp.isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "open": str(bar.get("open", "")),
        "high": str(bar.get("high", "")),
        "low": str(bar.get("low", "")),
        "close": str(bar.get("close", "")),
        "volume": str(int(bar.get("volume", 0))),
    }
    for k, v in features.items():
        if isinstance(v, (str, int, float, bool)):
            msg[k] = str(v)
    return msg


def parse_indicators_message(
    fields: dict[bytes, bytes],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split an indicators stream message into (bar_dict, features_dict).

    bar_dict has float OHLCV values. features_dict has all other numeric
    fields as floats. Used by market_analysis_service to consume this stream.
    """
    bar: dict[str, Any] = {}
    features: dict[str, Any] = {}

    for raw_key, raw_val in fields.items():
        key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
        val = raw_val.decode() if isinstance(raw_val, bytes) else str(raw_val)

        if key in _OHLCV_FIELDS:
            if key == "open":
                bar["open"] = float(val)
            elif key == "high":
                bar["high"] = float(val)
            elif key == "low":
                bar["low"] = float(val)
            elif key == "close":
                bar["close"] = float(val)
            elif key == "volume":
                bar["volume"] = int(float(val))
        else:
            try:
                features[key] = float(val)
            except (ValueError, TypeError):
                features[key] = val

    return bar, features


class IndicatorService:
    """Compute I1 technical indicators and publish one combined message per bar."""

    def __init__(self, config_file: str | None = None):
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now()
        self.config = self._load_config(config_file)
        self._setup_logging()

        register_all_plugins()
        registry.validate_tier(I1_PLUGINS, "I1")

        self.redis_client: redis.Redis | None = None
        self.consumer_group = f"indicator_service_{int(time.time())}"
        self.consumer_name = f"indicator_consumer_{os.getpid()}"

        settings = Settings()
        self.env_prefix = f"{settings.env_name}:" if settings.env_name else ""

        self.bar_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))

        self.bars_processed_total = counter(
            "indicator_bars_processed_total",
            "Total market bars processed by indicator service",
        )
        self.service_uptime_seconds = gauge(
            "indicator_service_uptime_seconds",
            "Indicator service uptime in seconds",
        )
        self.error_count_total = counter(
            "indicator_errors_total",
            "Total errors in indicator service",
        )

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        self.logger = structlog.get_logger(__name__)

    def _load_config(self, config_file: str | None) -> dict[str, Any]:
        default: dict[str, Any] = {
            "redis": {"host": "localhost", "port": 6379, "db": 0},
            "service": {
                "symbols": get_active_contracts(),
                "timeframes": ["1m", "5m", "15m", "1h", "4h", "1d"],
                "min_history_bars": 120,
                "processing_interval": 0.1,
            },
            "metrics_port": 9109,
            "logging": {
                "level": "INFO",
                "file": "logs/indicator_service.log",
            },
        }
        if config_file and Path(config_file).exists():
            with open(config_file) as f:
                user_config = json.load(f)
            for k, v in user_config.items():
                if isinstance(v, dict) and k in default:
                    default[k].update(v)
                else:
                    default[k] = v
        return default

    def _setup_logging(self) -> None:
        log_dir = Path(self.config["logging"]["file"]).parent
        log_dir.mkdir(exist_ok=True)
        file_handler = RotatingFileHandler(
            self.config["logging"]["file"], maxBytes=10 * 1024 * 1024, backupCount=5
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

    def _run_i1_plugins(self, frames: dict[str, Any]) -> dict[str, Any]:
        """Run all I1 plugins and return merged feature dict."""
        features: dict[str, Any] = {}
        for plugin_name in I1_PLUGINS:
            t0 = time.time()
            try:
                p = registry.get_indicator(plugin_name)
                result = p.compute_full(frames)
                features.update(result)
                record_plugin_execution(plugin_name, "", "", time.time() - t0, "success", "I1")
            except Exception as e:
                self.logger.warning("I1 plugin failed", plugin=plugin_name, error=str(e))
                record_plugin_execution(plugin_name, "", "", time.time() - t0, "error", "I1")
        return features

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

            if bar_source == "tick_derived":
                # Tick data drives display only; real IBKR bars drive the pipeline
                await self.redis_client.xack(stream_name, self.consumer_group, message_id)
                return

            # authoritative bar: update history (dedup by timestamp)
            history = self.bar_history[key]
            if history and history[-1]["timestamp"] == bar_ts:
                history[-1] = bar_data
            else:
                history.append(bar_data)

            min_bars = self.config["service"]["min_history_bars"]
            if len(self.bar_history[key]) < min_bars:
                await self.redis_client.xack(stream_name, self.consumer_group, message_id)
                return

            df = pd.DataFrame(list(self.bar_history[key]))
            frames = {"main": df}

            features = self._run_i1_plugins(frames)

            msg = build_i1_message(bar_data, features, bar_ts, symbol, timeframe)
            out_stream = sk_indicators(self.env_prefix, symbol, timeframe)
            await self.redis_client.xadd(out_stream, msg, maxlen=1000, approximate=True)

            self.bars_processed_total.inc()
            await self.redis_client.xack(stream_name, self.consumer_group, message_id)

            self.logger.debug(
                "I1 published",
                symbol=symbol,
                timeframe=timeframe,
                features=len(features),
            )

        except Exception as e:
            self.logger.error(
                "Error processing bar", symbol=symbol, timeframe=timeframe, error=str(e)
            )
            self.error_count_total.inc()

    async def _connect_redis(self) -> None:
        self.redis_client = redis.Redis(
            host=self.config["redis"]["host"],
            port=self.config["redis"]["port"],
            db=self.config["redis"]["db"],
            decode_responses=False,
        )
        await self.redis_client.ping()
        self.logger.info("Connected to Redis")

    async def _setup_consumer_groups(self) -> None:
        for timeframe in self.config["service"]["timeframes"]:
            for symbol in self.config["service"]["symbols"]:
                stream_name = sk_market(self.env_prefix, symbol, timeframe)
                try:
                    await self.redis_client.xgroup_create(
                        stream_name, self.consumer_group, "0", mkstream=True
                    )
                except Exception:
                    pass

    async def _process_market_data(self) -> None:
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
                await asyncio.sleep(1)

    async def _health_monitor_loop(self) -> None:
        while self.running and not self.shutdown_requested:
            try:
                uptime = int((datetime.now() - self.start_time).total_seconds())
                self.service_uptime_seconds.set(uptime)
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break

    async def start(self) -> None:
        self.logger.info("Starting Indicator Service", config=self.config["service"])
        try:
            await self._connect_redis()
            start_metrics_server(port=self.config.get("metrics_port", 9109))
            await self._setup_consumer_groups()
            self.running = True
            tasks = [
                asyncio.create_task(self._process_market_data()),
                asyncio.create_task(self._health_monitor_loop()),
            ]
            self.logger.info("Indicator Service started")
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error("Failed to start indicator service", error=str(e))
            raise
        finally:
            await self.stop()

    async def stop(self) -> None:
        self.logger.info("Stopping Indicator Service")
        self.running = False
        self.shutdown_requested = True
        if self.redis_client:
            await self.redis_client.aclose()
        self.logger.info("Indicator Service stopped")


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Indicator Service")
    parser.add_argument("--config", help="Config file path")
    args = parser.parse_args()
    service = IndicatorService(args.config)
    try:
        await service.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
