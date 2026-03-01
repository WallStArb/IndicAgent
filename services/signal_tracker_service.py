#!/usr/bin/env python3
"""
Signal Tracker Service — open signal lifecycle management

Subscribes to market:SYMBOL:1m. For each bar, queries the signal_ledger
for active signals on that symbol/timeframe and evaluates whether they have
hit their stop loss, take profit targets, or expired via TTL.

Decoupled from signal_generator_service so that lifecycle tracking continues
even when the intelligence pipeline is stopped for maintenance.
"""

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import redis.asyncio as redis
import structlog

from src.config.settings import Settings, get_active_contracts, get_point_value
from src.core.database_manager import DatabaseManager
from src.core.stream_keys import market as sk_market
from src.intelligence.trading.lifecycle_tracker import evaluate_signal
from src.intelligence.trading.signal_ledger import get_active_signals, update_signal_status
from src.observability.metrics import counter, gauge, start_metrics_server


class SignalTrackerService:
    """Evaluate open signal lifecycle per incoming market bar."""

    def __init__(self, config_file: str | None = None):
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now(tz=UTC)
        self.config = self._load_config(config_file)
        self._setup_logging()

        self.redis_client: redis.Redis | None = None
        self.db_manager: DatabaseManager | None = None
        self.consumer_group = "signal_tracker"
        self.consumer_name = f"tracker_{os.getpid()}"

        settings = Settings()
        self.env_prefix = f"{settings.env_name}:" if settings.env_name else ""

        self.point_values: dict[str, float] = {
            sym: float(get_point_value(sym) or 1.0)
            for sym in self.config["service"]["symbols"]
        }

        self.lifecycle_transitions_total = counter(
            "tracker_lifecycle_transitions_total",
            "Total signal lifecycle transitions",
        )
        self.active_signals_count = gauge(
            "tracker_active_signals_count",
            "Current count of open signals",
        )
        self.service_uptime_seconds = gauge(
            "tracker_service_uptime_seconds",
            "Signal tracker uptime in seconds",
        )
        self.error_count_total = counter(
            "tracker_errors_total",
            "Total errors in signal tracker",
        )

        self._stream_map: dict[str, tuple[str, str]] = {}

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        self.logger = structlog.get_logger(__name__)

    def _load_config(self, config_file: str | None) -> dict[str, Any]:
        try:
            _settings = Settings()
        except Exception:
            _settings = None

        default: dict[str, Any] = {
            "redis": {"host": "localhost", "port": 6379, "db": 0},
            "database": {
                "url": (
                    _settings.database_url
                    if _settings and getattr(_settings, "database_url", None)
                    else "postgresql://postgres:postgres@localhost:5432/indicagent"
                )
            },
            "service": {
                "symbols": get_active_contracts(),
                "timeframes": ["1m", "5m", "15m", "1h"],
                "processing_interval": 0.1,
            },
            "metrics_port": 9115,
            "logging": {
                "level": "INFO",
                "file": "logs/signal_tracker_service.log",
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

    async def _evaluate_signals_against_bar(
        self,
        symbol: str,
        timeframe: str,
        bar: dict[str, Any],
        all_active: list[dict[str, Any]] | None = None,
    ) -> list[Any]:
        """Evaluate all active signals for this symbol/timeframe against bar OHLCV.

        Returns list of transitions applied (empty if db_manager is None).
        """
        if not self.db_manager:
            return []

        # Filter active signals by timeframe for this evaluation (N+1 fix)
        relevant = [s for s in all_active if s.get("timeframe") == timeframe]
        self.active_signals_count.set(len(relevant))

        transitions = []
        timestamp = datetime.now(tz=UTC)

        for sig in relevant:
            sig_with_pv = {**sig, "point_value": self.point_values.get(symbol, 1.0)}
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

            # Compute signal_quality on exit: pnl_r * confidence_at_fire (clamped ≥ 0)
            # Vol regime is not stored at fire time; simplified formula omits it.
            signal_quality: float | None = None
            if transition.exit_reason and transition.pnl_r is not None:
                confidence = float(sig.get("confidence") or 1.0)
                signal_quality = max(0.0, round(transition.pnl_r * confidence, 4))

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
                signal_quality=signal_quality,
            )
            self.lifecycle_transitions_total.inc()
            self.logger.info(
                "Signal transition",
                signal_id=transition.signal_id,
                new_status=transition.new_status,
                exit_reason=transition.exit_reason,
                pnl_r=transition.pnl_r,
            )
            transitions.append(transition)

        return transitions

    async def _process_single_bar(
        self,
        symbol: str,
        timeframe: str,
        fields: dict[bytes, bytes],
        stream_name: str,
        message_id: bytes,
    ) -> bool:
        try:
            bar = {
                "high": float(fields[b"high"].decode()),
                "low": float(fields[b"low"].decode()),
                "close": float(fields[b"close"].decode()),
            }

            # Fetch all active signals once per bar (N+1 fix: 92 queries → 1)
            active = await get_active_signals(self.db_manager, symbol=symbol)
            self.active_signals_count.set(len(active))

            for tf in self.config["service"]["timeframes"]:
                await self._evaluate_signals_against_bar(symbol, tf, bar, active)

            return True

        except Exception as e:
            self.logger.error("Error processing bar", symbol=symbol, error=str(e))
            self.error_count_total.inc()
            return False

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
            self.logger.warning(
                "Database unavailable, lifecycle tracking disabled", error=str(e)
            )
            self.db_manager = None

    async def _setup_consumer_groups(self) -> None:
        for symbol in self.config["service"]["symbols"]:
            stream_name = sk_market(self.env_prefix, symbol, "1m")
            try:
                await self.redis_client.xgroup_create(
                    stream_name, self.consumer_group, "$", mkstream=True
                )
            except Exception:
                # Group already exists — reset to current tail to avoid replaying history
                await self.redis_client.xgroup_setid(stream_name, self.consumer_group, "$")
            self._stream_map[stream_name] = (symbol, "1m")

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
                        ok = await self._process_single_bar(
                            symbol, timeframe, fields, stream_name, message_id
                        )
                        if ok:
                            to_ack.append(message_id)
                    if to_ack:
                        await self.redis_client.xack(
                            stream_name, self.consumer_group, *to_ack
                        )
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.error_count_total.inc()
                error_str = str(e)
                if "NOGROUP" in error_str:
                    self.logger.warning("Consumer group missing, recreating", error=error_str)
                    await self._setup_consumer_groups()
                else:
                    self.logger.error("Error in tracker loop", error=error_str)
                await asyncio.sleep(1)

    async def _health_monitor_loop(self) -> None:
        while self.running and not self.shutdown_requested:
            try:
                uptime = int((datetime.now(tz=UTC) - self.start_time).total_seconds())
                self.service_uptime_seconds.set(uptime)
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break

    async def start(self) -> None:
        self.logger.info("Starting Signal Tracker Service", config=self.config["service"])
        try:
            await self._connect_redis()
            await self._connect_database()
            start_metrics_server(port=self.config.get("metrics_port", 9115))
            await self._setup_consumer_groups()
            self.running = True
            tasks = [
                asyncio.create_task(self._process_loop()),
                asyncio.create_task(self._health_monitor_loop()),
            ]
            self.logger.info("Signal Tracker Service started")
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error("Failed to start signal tracker", error=str(e))
            raise
        finally:
            await self.stop()

    async def stop(self) -> None:
        self.logger.info("Stopping Signal Tracker Service")
        self.running = False
        self.shutdown_requested = True
        if self.redis_client:
            await self.redis_client.aclose()
        if self.db_manager:
            await self.db_manager.close()
        self.logger.info("Signal Tracker Service stopped")


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Signal Tracker Service")
    parser.add_argument("--config", help="Config file path")
    args = parser.parse_args()
    service = SignalTrackerService(args.config)
    try:
        await service.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
