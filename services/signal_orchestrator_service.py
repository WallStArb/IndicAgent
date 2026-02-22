#!/usr/bin/env python3
"""
Signal Orchestrator Service — I7 plugin execution, aggregation, and lifecycle tracking

Subscribes to intelligence:SYMBOL:TF stream (enriched with OHLCV by intelligence_processor).
On each bar: runs 5 I7 setup plugins, aggregates signals, inserts all to signal_ledger,
publishes winner to signals:SYMBOL:TF:aggregated, and tracks open signal lifecycle.

Version: 1.0.0
Last Updated: 2026-02-18
Status: Production Ready
"""

from __future__ import annotations

import asyncio
import json
import logging
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

from logging.handlers import RotatingFileHandler  # noqa: E402

import pandas as pd  # noqa: E402
import redis.asyncio as redis  # noqa: E402
import structlog  # noqa: E402

from src.config.settings import Settings, get_point_value  # noqa: E402
from src.core.database_manager import DatabaseManager  # noqa: E402
from src.core.stream_keys import (  # noqa: E402
    signals_aggregated,
)
from src.intelligence.plugins import registry  # noqa: E402
from src.intelligence.register_plugins import TIER_I7, register_all_plugins  # noqa: E402
from src.intelligence.trading.aggregator import AggregatedResult, aggregate  # noqa: E402
from src.intelligence.trading.lifecycle_tracker import evaluate_signal  # noqa: E402
from src.intelligence.trading.signal_ledger import (  # noqa: E402
    LedgerEntry,
    get_active_signals,
    insert_signals,
    update_signal_status,
)
from src.observability.metrics import (  # noqa: E402
    counter,
    gauge,
    record_plugin_execution,
    start_metrics_server,
)

# I7 plugin names — imported from register_plugins (single source of truth)
I7_PLUGINS = TIER_I7

# Fields that are metadata / OHLCV — everything else is a feature
_META_FIELDS = frozenset({
    "timestamp", "symbol", "timeframe",
    "open", "high", "low", "close", "volume",
})

# Fixed set of features to snapshot as market_context JSONB.
# Must remain stable across versions — ML training depends on consistent feature vectors.
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

# TTL bars by timeframe: how many bars before an unfilled signal expires
_TTL_BY_TIMEFRAME: dict[str, int] = {
    "1m": 30,
    "5m": 20,
    "15m": 12,
    "1h": 6,
}
_TTL_DEFAULT = 10


# ---------------------------------------------------------------------------
# Pure helper functions (no I/O — easy to test)
# ---------------------------------------------------------------------------

def parse_intelligence_message(
    fields: dict[bytes, bytes],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split an intelligence stream message into (bar_dict, features_dict).

    bar_dict contains OHLCV values as floats/int.
    features_dict contains all other numeric fields as floats; non-numeric as strings.
    """
    bar: dict[str, Any] = {}
    features: dict[str, Any] = {}

    for raw_key, raw_val in fields.items():
        key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
        val = raw_val.decode() if isinstance(raw_val, bytes) else str(raw_val)

        if key in _META_FIELDS:
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
            # timestamp/symbol/timeframe not added to bar — caller knows them
        else:
            try:
                features[key] = float(val)
            except (ValueError, TypeError):
                features[key] = val

    return bar, features


def build_ledger_entries(
    result: AggregatedResult,
    symbol: str,
    timeframe: str,
    timestamp: datetime,
    features: dict[str, Any],
) -> list[LedgerEntry]:
    """Build LedgerEntry list from an AggregatedResult.

    All ranked signals are logged (winners and losers). was_selected=True only
    for the rank-1 signal when a winner was chosen.
    """
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
        ))
    return entries


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------

class SignalOrchestratorService:
    """Execute I7 setup plugins, aggregate signals, persist, and track lifecycle."""

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
        self.consumer_group = f"signal_orchestrator_{int(time.time())}"
        self.consumer_name = f"orchestrator_{os.getpid()}"

        settings = Settings()
        self.env_prefix = f"{settings.env_name}:" if settings.env_name else ""

        # Bar history per symbol:timeframe key
        self.bar_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))

        # point_value lookup: symbol → dollars per point
        self.point_values: dict[str, float] = {
            sym: float(get_point_value(sym) or 1.0)
            for sym in self.config["service"]["symbols"]
        }

        # Prometheus metrics
        self.bars_processed_total = counter(
            "orchestrator_bars_processed_total",
            "Total intelligence events processed by orchestrator",
        )
        self.signals_generated_total = counter(
            "orchestrator_signals_generated_total",
            "Total signals inserted to signal_ledger",
        )
        self.signals_selected_total = counter(
            "orchestrator_signals_selected_total",
            "Total signals where was_selected=True",
        )
        self.lifecycle_transitions_total = counter(
            "orchestrator_lifecycle_transitions_total",
            "Total signal status updates",
        )
        self.calculation_duration_ms = gauge(
            "orchestrator_calculation_duration_ms",
            "Per-bar processing time in milliseconds",
        )
        self.active_signals_count = gauge(
            "orchestrator_active_signals_count",
            "Current count of pending/active signals",
        )
        self.service_uptime_seconds = gauge(
            "orchestrator_service_uptime_seconds",
            "Orchestrator service uptime in seconds",
        )
        self.error_count_total = counter(
            "orchestrator_errors_total",
            "Total errors encountered by orchestrator",
        )

        self._total_bars = 0
        self._total_signals = 0
        self._total_transitions = 0
        self._error_count = 0

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger = structlog.get_logger(__name__)
        start_metrics_server(port=9112)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

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
                "symbols": ["ESH6", "NQH6", "RTYH6"],
                "timeframes": ["5m", "15m"],
                "min_history_bars": 50,
                "processing_interval": 0.1,
                "health_check_interval": 30,
            },
            "logging": {
                "level": "INFO",
                "file": "logs/signal_orchestrator.log",
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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

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
        for tf in self.config["service"]["timeframes"]:
            for sym in self.config["service"]["symbols"]:
                from src.core.stream_keys import intelligence as sk_intel
                stream_name = sk_intel(self.env_prefix, sym, tf)
                try:
                    await self.redis_client.xgroup_create(
                        stream_name, self.consumer_group, "0", mkstream=True
                    )
                except Exception:
                    pass  # Group already exists

    async def stop(self) -> None:
        self.logger.info("Stopping Signal Orchestrator Service")
        self.running = False
        self.shutdown_requested = True
        if self.redis_client:
            await self.redis_client.aclose()
        if self.db_manager:
            await self.db_manager.close()
        self.logger.info("Signal Orchestrator Service stopped")

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def _run_setup_plugins(self, frames: dict[str, Any]) -> list[dict]:
        """Run all 5 I7 setup plugins and return only directional signals."""
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
        """Full per-bar pipeline: generate signals, aggregate, persist, track lifecycle."""
        df = frames.get("main")
        min_bars = self.config["service"]["min_history_bars"]
        if df is None or len(df) < min_bars:
            return

        calc_start = time.time()

        # --- Signal generation ---
        raw_signals = self._run_setup_plugins(frames)
        trend_regime = float(features.get("trend_regime", 0.0))
        result = aggregate(raw_signals, trend_regime=trend_regime)

        entries = build_ledger_entries(result, symbol, timeframe, timestamp, features)
        if entries and self.db_manager:
            await insert_signals(self.db_manager, entries)
            selected_count = sum(1 for e in entries if e.was_selected)
            self.signals_generated_total.inc(len(entries))
            self.signals_selected_total.inc(selected_count)
            self._total_signals += len(entries)

        if result.selected_signal and self.redis_client:
            stream_name = signals_aggregated(self.env_prefix, symbol, timeframe)
            message = {
                k: str(v) for k, v in result.selected_signal.items()
                if isinstance(v, (str, int, float, bool))
            }
            message["timestamp"] = timestamp.isoformat()
            message["symbol"] = symbol
            message["timeframe"] = timeframe
            await self.redis_client.xadd(stream_name, message, maxlen=200, approximate=True)

        # --- Lifecycle tracking ---
        await self._track_lifecycle(symbol, timeframe, bar, timestamp)

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

    # ------------------------------------------------------------------
    # Lifecycle tracking
    # ------------------------------------------------------------------

    async def _track_lifecycle(
        self,
        symbol: str,
        timeframe: str,
        bar: dict[str, Any],
        timestamp: datetime,
    ) -> None:
        """Evaluate open signals and persist any state transitions."""
        if not self.db_manager:
            return

        active = await get_active_signals(self.db_manager, symbol=symbol)
        # Only evaluate signals that belong to THIS timeframe
        relevant = [s for s in active if s.get("timeframe") == timeframe]
        self.active_signals_count.set(len(relevant))

        for sig in relevant:
            # Inject point_value from settings (not stored in DB)
            sig_with_pv = {
                **sig,
                "point_value": self.point_values.get(symbol, 1.0),
            }
            try:
                transition = evaluate_signal(
                    sig_with_pv,
                    high=float(bar["high"]),
                    low=float(bar["low"]),
                    close=float(bar["close"]),
                )
            except Exception as e:
                self.logger.warning(
                    "Lifecycle evaluation failed",
                    signal_id=sig.get("signal_id"),
                    error=str(e),
                )
                continue

            if transition is None:
                continue

            activated_at = timestamp if transition.new_status == "active" else None
            exit_at = timestamp if transition.exit_reason else None

            await update_signal_status(
                self.db_manager,
                transition.signal_id,
                status=transition.new_status,
                activated_at=activated_at,
                exit_at=exit_at,
                exit_price=transition.exit_price,
                exit_reason=transition.exit_reason,
                pnl_ticks=transition.pnl_ticks,
                pnl_r=transition.pnl_r,
                pnl_dollars=transition.pnl_dollars,
            )
            self.lifecycle_transitions_total.inc()
            self._total_transitions += 1
            self.logger.info(
                "Signal transition",
                signal_id=transition.signal_id,
                new_status=transition.new_status,
                exit_reason=transition.exit_reason,
                pnl_r=transition.pnl_r,
            )

    # ------------------------------------------------------------------
    # Main service loop
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self.logger.info("Starting Signal Orchestrator Service", config=self.config["service"])
        try:
            await self._connect_redis()
            await self._connect_database()
            await self._setup_consumer_groups()

            self.running = True
            tasks = [
                asyncio.create_task(self._process_loop()),
                asyncio.create_task(self._health_monitor_loop()),
            ]
            self.logger.info("Signal Orchestrator Service started")
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error("Failed to start orchestrator", error=str(e))
            raise
        finally:
            await self.stop()

    async def _process_loop(self) -> None:
        """Consume intelligence stream events and process each bar."""
        from src.core.stream_keys import intelligence as sk_intel

        self.logger.info("Starting intelligence stream processing loop")

        while self.running and not self.shutdown_requested:
            try:
                for tf in self.config["service"]["timeframes"]:
                    for sym in self.config["service"]["symbols"]:
                        stream_name = sk_intel(self.env_prefix, sym, tf)
                        messages = await self.redis_client.xreadgroup(
                            self.consumer_group,
                            self.consumer_name,
                            {stream_name: ">"},
                            count=10,
                            block=100,
                        )
                        for _stream, msgs in messages:
                            for message_id, fields in msgs:
                                await self._process_single_message(
                                    sym, tf, fields, stream_name, message_id
                                )

                await asyncio.sleep(self.config["service"]["processing_interval"])

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in processing loop", error=str(e))
                self.error_count_total.inc()
                self._error_count += 1
                await asyncio.sleep(1)

    async def _process_single_message(
        self,
        symbol: str,
        timeframe: str,
        fields: dict[bytes, bytes],
        stream_name: str,
        message_id: bytes,
    ) -> None:
        try:
            raw_ts = fields.get(b"timestamp", b"").decode()
            timestamp = datetime.fromisoformat(raw_ts) if raw_ts else datetime.now(tz=UTC)

            bar, features = parse_intelligence_message(fields)

            # Buffer bar in history
            key = f"{symbol}:{timeframe}"
            bar_with_ts = {**bar, "timestamp": timestamp}
            self.bar_history[key].append(bar_with_ts)

            df_history = list(self.bar_history[key])
            frames = {
                "main": pd.DataFrame(df_history),
                "features": features,
            }

            await self._process_bar(symbol, timeframe, bar, features, frames, timestamp)
            await self.redis_client.xack(stream_name, self.consumer_group, message_id)

        except Exception as e:
            self.logger.error(
                "Error processing message",
                symbol=symbol,
                timeframe=timeframe,
                error=str(e),
            )
            self.error_count_total.inc()
            self._error_count += 1

    async def _health_monitor_loop(self) -> None:
        while self.running and not self.shutdown_requested:
            try:
                uptime = int((datetime.now(tz=UTC) - self.start_time).total_seconds())
                self.service_uptime_seconds.set(uptime)
                interval = self.config["service"]["health_check_interval"]
                if uptime % interval == 0:
                    self.logger.info(
                        "Health check",
                        uptime=uptime,
                        bars_processed=self._total_bars,
                        signals_generated=self._total_signals,
                        lifecycle_transitions=self._total_transitions,
                        errors=self._error_count,
                    )
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in health monitor", error=str(e))
                await asyncio.sleep(5)


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Signal Orchestrator Service")
    parser.add_argument("--config", help="Configuration file path")
    parser.add_argument("--foreground", action="store_true", help="Run in foreground")
    args = parser.parse_args()

    svc = SignalOrchestratorService(args.config)

    if args.foreground:
        print("Starting Signal Orchestrator Service in foreground...")
        print("Press Ctrl+C to stop")

    try:
        await svc.start()
    except KeyboardInterrupt:
        print("\nService stopped by user")
    except Exception as e:
        print(f"Service failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
