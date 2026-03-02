#!/usr/bin/env python3
"""
Signal Generator Service — I7 plugin execution and aggregation

Subscribes to intelligence:SYMBOL:TF stream (enriched with OHLCV by
market_analysis_service). On each bar: runs all I7 setup plugins,
aggregates signals, inserts all to signal_ledger, publishes winner to
signals:SYMBOL:TF:aggregated.

Lifecycle tracking (pending→active→exit, P&L) is handled separately by
signal_tracker_service, which subscribes to market:SYMBOL:1m directly.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import redis.asyncio as redis
import structlog
from pydantic import ValidationError

from src.config.settings import Settings, get_active_contracts
from src.core.database_manager import DatabaseManager
from src.core.service_utils import setup_service_logging
from src.core.stream_keys import signals_aggregated
from src.core.stream_utils import ensure_consumer_group_with_reset
from src.intelligence.plugins import registry
from src.intelligence.register_plugins import TIER_I7, register_all_plugins
from src.intelligence.schemas import IntelligenceEvent
from src.intelligence.trading.aggregator import AggregatedResult, aggregate
from src.intelligence.trading.signal_ledger import LedgerEntry, insert_signals
from src.intelligence.trading.trade_framer import frame_trade
from src.observability.metrics import (
    counter,
    gauge,
    record_plugin_execution,
    start_metrics_server,
)

# I7 plugin names — imported from register_plugins (single source of truth)
I7_PLUGINS = TIER_I7

MARKET_CONTEXT_KEYS: tuple[str, ...] = (
    "trend_regime",
    "volatility_regime",
    "trend_confidence",
    "atr_14",
    "rsi_14",
    "ctf_score",
    "swing_pattern",
    "trend_strength",
    "volatility_percentile",
    "hmm_regime_state",
)

logger = structlog.get_logger(__name__)


def _parse_intelligence_event(fields: dict[bytes, bytes]) -> IntelligenceEvent | None:
    """Parse intelligence stream message into typed IntelligenceEvent.

    Returns None and logs a warning if the message is malformed or version unknown.
    """
    raw = fields.get(b"event", b"")
    if not raw:
        return None
    try:
        return IntelligenceEvent.model_validate_json(raw)
    except (ValidationError, ValueError) as e:
        logger.warning("Failed to parse IntelligenceEvent", error=str(e))
        return None


def _build_features_from_event(event: IntelligenceEvent) -> dict[str, Any]:
    """Build a features dict from a typed IntelligenceEvent for I7 plugins.

    Flattens all sub-models so every I7 plugin gets the features it needs.
    Legacy key aliases are preserved for signal_ledger market_context stability.
    """
    f: dict[str, Any] = {}

    # I1 — all fields including extras (VWAP, etc.)
    for k, v in event.i1.model_dump().items():
        if v is not None:
            f[k] = v
    # BB aliases: plugins may expect bb_middle / bb_upper / bb_lower
    f["bb_middle"] = event.i1.bb_20_2_mid
    f["bb_upper"] = event.i1.bb_20_2_upper
    f["bb_lower"] = event.i1.bb_20_2_lower

    # I3 — swing, S/R, trend structure
    for k, v in event.i3.model_dump().items():
        if v is not None:
            f[k] = v
    # SR aliases: plugins use sr_nearest_support / sr_nearest_resistance
    f["sr_nearest_support"] = event.i3.nearest_support
    f["sr_nearest_resistance"] = event.i3.nearest_resistance

    # I4 — regimes, GARCH, Kalman
    for k, v in event.i4.model_dump().items():
        if v is not None:
            f[k] = v
    # Legacy key aliases
    f["vol_regime"] = event.i4.vol_regime
    f["volatility_regime"] = event.i4.vol_regime
    f["volatility_percentile"] = event.i4.vol_percentile
    f["hmm_regime_state"] = event.smc.hmm_regime

    # I5 — squeeze_fired, rsi divergence, momentum, patterns
    for k, v in event.i5.model_dump().items():
        if v is not None:
            f[k] = v

    # SMC — all 61 fields (sweep_*, fvg_*, ob_*, bsl_*, ssl_*, S/D zones, etc.)
    for k, v in event.smc.model_dump().items():
        if v is not None:
            f[k] = v

    # I6 — cross-timeframe confluence
    for k, v in event.i6.model_dump().items():
        if v is not None:
            f[k] = v

    return f


def build_ledger_entries(
    result: AggregatedResult,
    symbol: str,
    timeframe: str,
    timestamp: datetime,
    features: dict[str, Any],
) -> list[LedgerEntry]:
    """Build LedgerEntry list from an AggregatedResult."""
    if not result.all_ranked:
        return []

    market_ctx = {k: features.get(k, None) for k in MARKET_CONTEXT_KEYS
                  if features.get(k) is not None}

    entries = []
    for sig in result.all_ranked:
        rank = sig.get("composite_rank", 99)
        was_selected = (rank == 1 and result.selected_signal is not None)
        entries.append(LedgerEntry(
            signal_id=str(uuid4()),
            timestamp=timestamp,
            symbol=symbol,
            timeframe=timeframe,
            setup_plugin=sig.get("setup_plugin", "unknown"),
            signal_type=sig.get("signal_type", "unknown"),
            direction=int(sig.get("direction", 0)),
            entry_price=float(sig.get("entry_price", 0.0)),
            stop_loss=float(sig.get("stop_loss", 0.0)),
            targets=[float(t) for t in sig.get("targets", [])],
            confidence=float(sig.get("confidence", 0.0)),
            confluence_score=float(sig.get("confluence_score", 0.0)),
            regime_context=str(sig.get("regime_context", "")),
            supporting_factors=list(sig.get("supporting_factors", [])),
            was_selected=was_selected,
            num_signals_bar=result.num_signals_fired,
            num_agreeing=result.num_agreeing,
            num_conflicting=result.num_conflicting,
            resolution_method=result.resolution_method,
            composite_rank=rank,
            market_context=market_ctx,
            status="pending",
            feature_ts=timestamp,   # IntelligenceEvent.ts — the bar timestamp
            feature_tf=timeframe,   # IntelligenceEvent.tf — the timeframe string
            # CIS fields — populated by aggregator, None for non-CIS signals
            cis_score=result.cis_score,
            bucket_scores=result.bucket_scores,
            weights_version=result.weights_version,
            signal_quality=None,    # populated by signal_tracker on exit
        ))
    return entries


class SignalGeneratorService:
    """Execute I7 setup plugins, aggregate signals, and persist to signal_ledger."""

    def __init__(self, config_file: str | None = None):
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now(tz=UTC)

        self.config = self._load_config(config_file)
        self._setup_logging()

        register_all_plugins()
        registry.validate_tier(I7_PLUGINS, "I7")

        self.redis_client: redis.Redis | None = None
        self.db_manager: DatabaseManager | None = None
        self.consumer_group = "signal_generator"
        self.consumer_name = f"generator_{os.getpid()}"

        settings = Settings()
        self.env_prefix = f"{settings.env_name}:" if settings.env_name else ""

        self.bar_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
        self._stream_map: dict[str, tuple[str, str]] = {}
        self._df_cache: dict[str, pd.DataFrame | None] = {}

        self.bars_processed_total = counter(
            "generator_bars_processed_total",
            "Total intelligence events processed by signal generator",
        )
        self.signals_generated_total = counter(
            "generator_signals_generated_total",
            "Total signals inserted to signal_ledger",
        )
        self.signals_selected_total = counter(
            "generator_signals_selected_total",
            "Total signals where was_selected=True",
        )
        self.calculation_duration_ms = gauge(
            "generator_calculation_duration_ms",
            "Per-bar processing time in milliseconds",
        )
        self.service_uptime_seconds = gauge(
            "generator_service_uptime_seconds",
            "Signal generator service uptime in seconds",
        )
        self.error_count_total = counter(
            "generator_errors_total",
            "Total errors encountered by signal generator",
        )

        self._total_bars = 0
        self._total_signals = 0
        self._error_count = 0

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger = structlog.get_logger(__name__)
        start_metrics_server(port=9112)

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
                "min_history_bars": 50,
                "processing_interval": 0.1,
                "health_check_interval": 30,
            },
            "logging": {
                "level": "INFO",
                "file": "logs/signal_generator_service.log",
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
        setup_service_logging(
            self.config["logging"]["file"],
            level=self.config["logging"].get("level", "INFO"),
            backup_count=self.config["logging"].get("backup_count", 5),
        )

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self.logger.info("Received shutdown signal", signal=signum)
        self.shutdown_requested = True

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
            self.logger.warning("Database unavailable, persistence disabled", error=str(e))
            self.db_manager = None

    async def _setup_consumer_groups(self) -> None:
        from src.core.stream_keys import intelligence as sk_intel
        warmup_bars = 60
        for tf in self.config["service"]["timeframes"]:
            for sym in self.config["service"]["symbols"]:
                stream_name = sk_intel(self.env_prefix, sym, tf)
                group_freshly_created = await ensure_consumer_group_with_reset(
                    self.redis_client, stream_name, self.consumer_group
                )
                # Only rewind warmup_bars if group was freshly created
                if group_freshly_created:
                    try:
                        msgs = await self.redis_client.xrevrange(stream_name, count=warmup_bars + 1)
                        if len(msgs) > warmup_bars:
                            await self.redis_client.xgroup_setid(
                                stream_name, self.consumer_group, msgs[warmup_bars][0]
                            )
                        elif msgs:
                            await self.redis_client.xgroup_setid(
                                stream_name, self.consumer_group, "0-0"
                            )
                    except Exception as e:
                        self.logger.warning(
                            "Consumer group rewind failed", stream=stream_name, error=str(e)
                        )
                self._stream_map[stream_name] = (sym, tf)

    async def stop(self) -> None:
        self.logger.info("Stopping Signal Generator Service")
        self.running = False
        self.shutdown_requested = True
        if self.redis_client:
            await self.redis_client.aclose()
        if self.db_manager:
            await self.db_manager.close()
        self.logger.info("Signal Generator Service stopped")

    def _get_df(self, key: str) -> pd.DataFrame:
        if self._df_cache.get(key) is None:
            self._df_cache[key] = pd.DataFrame(list(self.bar_history[key]))
        return self._df_cache[key]

    def _run_setup_plugins(self, frames: dict[str, Any]) -> list[dict]:
        """Run all I7 setup plugins and return only directional signals."""
        signals = []
        for name in I7_PLUGINS:
            t0 = time.time()
            try:
                plugin = registry.get_pattern(name)
                result = plugin.compute_full(frames)
                elapsed = time.time() - t0
                if result and result.get("direction", 0) != 0:
                    result["setup_plugin"] = name
                    signals.append(result)
                    record_plugin_execution(name, "", "", elapsed, "success", "I7")
                else:
                    record_plugin_execution(name, "", "", elapsed, "no_signal", "I7")
            except Exception as e:
                self.logger.warning("I7 plugin failed", plugin=name, error=str(e))
                record_plugin_execution(name, "", "", time.time() - t0, "error", "I7")
        return signals

    async def _process_bar(
        self,
        symbol: str,
        timeframe: str,
        bar: dict[str, Any],
        features: dict[str, Any],
        frames: dict[str, Any],
        timestamp: datetime,
    ) -> None:
        """Generate signals, aggregate, persist, and publish winner."""
        df = frames.get("main")
        min_bars = self.config["service"]["min_history_bars"]
        if df is None or len(df) < min_bars:
            return

        calc_start = time.time()

        raw_signals = self._run_setup_plugins(frames)
        trend_regime = float(features.get("trend_regime", 0.0))
        result = aggregate(raw_signals, trend_regime=trend_regime, features=features)

        # Apply structural trade framing to the winning signal
        if result.selected_signal:
            atr = float(features.get("atr_14") or 0.0)
            sig = result.selected_signal
            frame = frame_trade(
                setup_type=sig.get("signal_type", ""),
                direction=int(sig.get("direction", 1)),
                entry=float(sig.get("entry_price", 0.0)),
                features=features,
                atr=atr,
            )
            if not frame.viable:
                self.logger.info(
                    "Signal filtered: RR gate",
                    symbol=symbol,
                    timeframe=timeframe,
                    signal_type=sig.get("signal_type"),
                    reason=frame.rejection_reason,
                )
                result = AggregatedResult(
                    selected_signal=None,
                    all_ranked=result.all_ranked,
                    resolution_method="rr_filtered",
                    num_signals_fired=result.num_signals_fired,
                    num_agreeing=result.num_agreeing,
                    num_conflicting=result.num_conflicting,
                )
            else:
                result.selected_signal.update({
                    "entry_price":    frame.entry,
                    "entry_type":     frame.entry_type,
                    "stop_loss":      frame.stop,
                    "stop_type":      frame.stop_type,
                    "targets":        [t.price for t in frame.targets],
                    "target_labels":  [t.label for t in frame.targets],
                    "target_types":   [t.level_type for t in frame.targets],
                    "rr_t1":          frame.rr_t1,
                    "rr_t2":          frame.rr_t2,
                    "rr_t3":          frame.rr_t3,
                    "framing_method": frame.method,
                })

        entries = build_ledger_entries(result, symbol, timeframe, timestamp, features)
        if entries and self.db_manager:
            await insert_signals(self.db_manager, entries)
            selected_count = sum(1 for e in entries if e.was_selected)
            self.signals_generated_total.inc(len(entries))
            self.signals_selected_total.inc(selected_count)
            self._total_signals += len(entries)

        if result.selected_signal and self.redis_client:
            stream_name = signals_aggregated(self.env_prefix, symbol, timeframe)
            sig = result.selected_signal
            message = {
                k: str(v) for k, v in sig.items()
                if isinstance(v, (str, int, float, bool))
            }
            # Promote individual targets as scalar fields
            targets = sig.get("targets") or []
            target_labels = sig.get("target_labels") or []
            if targets:
                message["profit_target"] = str(float(targets[0]))
                if len(targets) > 1:
                    message["profit_target_2"] = str(float(targets[1]))
                if len(targets) > 2:
                    message["profit_target_3"] = str(float(targets[2]))
            # Serialise list fields as JSON strings
            message["target_labels"] = json.dumps(target_labels)
            message["target_types"] = json.dumps(sig.get("target_types") or [])
            # RR fields
            entry_p = float(sig.get("entry_price", 0))
            stop_p = float(sig.get("stop_loss", 0))
            risk = abs(entry_p - stop_p)
            if risk > 0 and targets:
                message["risk_reward_ratio"] = str(
                    round(abs(float(targets[0]) - entry_p) / risk, 2)
                )
            message["timestamp"] = timestamp.isoformat()
            message["symbol"] = symbol
            message["timeframe"] = timeframe
            await self.redis_client.xadd(stream_name, message, maxlen=200, approximate=True)

        elapsed_ms = (time.time() - calc_start) * 1000
        self.bars_processed_total.inc()
        self.calculation_duration_ms.set(elapsed_ms)
        self._total_bars += 1

        self.logger.debug(
            "Bar processed",
            symbol=symbol,
            timeframe=timeframe,
            signals_fired=result.num_signals_fired,
            selected=result.selected_signal is not None,
            resolution=result.resolution_method,
            calc_ms=round(elapsed_ms, 2),
        )

    async def _process_single_message(
        self,
        symbol: str,
        timeframe: str,
        fields: dict[bytes, bytes],
        stream_name: str,
        message_id: bytes,
    ) -> bool:
        try:
            event = _parse_intelligence_event(fields)
            if event is None:
                # Malformed or missing event — ack and skip (do not crash)
                return True

            timestamp = event.ts
            bar = {
                "open": event.bar.o,
                "high": event.bar.h,
                "low": event.bar.l,
                "close": event.bar.c,
                "volume": event.bar.v,
            }
            features = _build_features_from_event(event)

            key = f"{symbol}:{timeframe}"
            bar_with_ts = {**bar, "timestamp": timestamp}
            self.bar_history[key].append(bar_with_ts)
            self._df_cache[key] = None

            frames = {
                "main": self._get_df(key),
                "features": features,
            }

            await self._process_bar(symbol, timeframe, bar, features, frames, timestamp)
            return True

        except Exception as e:
            self.logger.error(
                "Error processing message",
                symbol=symbol,
                timeframe=timeframe,
                error=str(e),
            )
            self.error_count_total.inc()
            self._error_count += 1
            return False

    async def _process_loop(self) -> None:
        all_streams = {name: ">" for name in self._stream_map}
        while self.running and not self.shutdown_requested:
            try:
                messages = await self.redis_client.xreadgroup(
                    self.consumer_group, self.consumer_name,
                    all_streams, count=10, block=1000,
                )
                for stream_bytes, msgs in messages:
                    stream_name = (
                        stream_bytes.decode()
                        if isinstance(stream_bytes, bytes)
                        else stream_bytes
                    )
                    symbol, timeframe = self._stream_map[stream_name]
                    to_ack: list[bytes] = []
                    for message_id, fields in msgs:
                        await self._process_single_message(
                            symbol, timeframe, fields, stream_name, message_id
                        )
                        # Always acknowledge (at-most-once delivery)
                        to_ack.append(message_id)
                    if to_ack:
                        await self.redis_client.xack(
                            stream_name, self.consumer_group, *to_ack
                        )
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
                uptime = int((datetime.now(tz=UTC) - self.start_time).total_seconds())
                self.service_uptime_seconds.set(uptime)
                interval = self.config["service"]["health_check_interval"]
                self.logger.info(
                    "Health check",
                    uptime=uptime,
                    bars_processed=self._total_bars,
                    signals_generated=self._total_signals,
                    errors=self._error_count,
                )
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in health monitor", error=str(e))
                await asyncio.sleep(5)

    async def start(self) -> None:
        self.logger.info("Starting Signal Generator Service", config=self.config["service"])
        try:
            await self._connect_redis()
            await self._connect_database()
            await self._setup_consumer_groups()
            self.running = True
            tasks = [
                asyncio.create_task(self._process_loop()),
                asyncio.create_task(self._health_monitor_loop()),
            ]
            self.logger.info("Signal Generator Service started")
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error("Failed to start signal generator", error=str(e))
            raise
        finally:
            await self.stop()


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Signal Generator Service")
    parser.add_argument("--config", help="Configuration file path")
    args = parser.parse_args()

    svc = SignalGeneratorService(args.config)
    try:
        await svc.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
