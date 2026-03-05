#!/usr/bin/env python3
"""
Signal Lifecycle Service — institutional-grade signal lifecycle management.

Replaces signal_tracker_service. Extends lifecycle tracking with:
- Zone-aware entry activation (bar range overlaps entry_zone_low:zone_high)
- Bars-elapsed computed from timestamps (fixes TTL silent bug)
- In-memory MAE/MFE tracking per active signal; written to DB on exit
- 8-class outcome classification
- Tracks activation_price, zone_entry_pct, bars_to_activation, bars_in_trade
"""

import asyncio
import json
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import redis.asyncio as redis
import structlog

from src.config.settings import Settings, get_active_contracts, get_point_value
from src.core.database_manager import DatabaseManager
from src.core.service_utils import setup_service_logging
from src.core.stream_keys import market as sk_market
from src.core.stream_utils import ensure_consumer_group_with_reset
from src.intelligence.trading.lifecycle_tracker import (
    OUTCOME_THRESHOLD_QUICK_STOP_BARS,
    evaluate_signal,
)
from src.intelligence.trading.signal_ledger import get_active_signals, update_signal_status
from src.observability.metrics import counter, gauge, start_metrics_server

TF_SECONDS: dict[str, int] = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}


def _bars_elapsed(signal_timestamp: datetime, current_bar_time: datetime, timeframe: str) -> int:
    """Bars elapsed since signal fire, based on timestamps."""
    tf_secs = TF_SECONDS.get(timeframe, 60)
    delta = (current_bar_time - signal_timestamp).total_seconds()
    return max(0, int(delta / tf_secs))


def _bars_in_trade(activated_at: datetime | None, exit_at: datetime, timeframe: str) -> int | None:
    """Bars from activation to exit."""
    if activated_at is None:
        return None
    tf_secs = TF_SECONDS.get(timeframe, 60)
    delta = (exit_at - activated_at).total_seconds()
    return max(0, int(delta / tf_secs))


def _classify_stop_outcome(current_mfe: float, bars_in_trade_count: int | None) -> str:
    """Resolve fine-grained outcome for a stopped-out signal."""
    if (
        bars_in_trade_count is None
        or bars_in_trade_count <= OUTCOME_THRESHOLD_QUICK_STOP_BARS
        or current_mfe <= 0.05
    ):
        return "stopped_at_entry"
    return "stopped_in_trade"


class SignalLifecycleService:
    """Zone-aware institutional signal lifecycle tracker."""

    def __init__(self, config_file: str | None = None):
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now(tz=UTC)
        self.config = self._load_config(config_file)
        self._setup_logging()

        self.redis_client: redis.Redis | None = None
        self.db_manager: DatabaseManager | None = None
        self.consumer_group = "signal_lifecycle"
        self.consumer_name = f"lifecycle_{os.getpid()}"

        settings = Settings()
        self.env_prefix = f"{settings.env_name}:" if settings.env_name else ""

        self.point_values: dict[str, float] = {
            sym: float(get_point_value(sym) or 1.0)
            for sym in self.config["service"]["symbols"]
        }

        # In-memory MAE/MFE tracking: signal_id → float
        self._mae: dict[str, float] = {}
        self._mfe: dict[str, float] = {}
        # activation_time tracking for bars_in_trade: signal_id → datetime
        self._activated_at: dict[str, datetime] = {}

        self.lifecycle_transitions_total = counter(
            "lifecycle_transitions_total", "Total signal lifecycle transitions"
        )
        self.active_signals_count = gauge(
            "lifecycle_active_signals_count", "Current count of open signals"
        )
        self.service_uptime_seconds = gauge(
            "lifecycle_service_uptime_seconds", "Signal lifecycle uptime in seconds"
        )
        self.error_count_total = counter(
            "lifecycle_errors_total", "Total errors in signal lifecycle service"
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
            },
            "metrics_port": 9115,
            "logging": {
                "level": "INFO",
                "file": "logs/signal_lifecycle_service.log",
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
        setup_service_logging(
            self.config["logging"]["file"],
            level=self.config["logging"].get("level", "INFO"),
        )

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self.logger.info("Received shutdown signal", signal=signum)
        self.shutdown_requested = True

    async def _evaluate_signals_against_bar(
        self,
        symbol: str,
        timeframe: str,
        bar: dict[str, Any],
        bar_time: datetime,
        all_active: list[dict[str, Any]] | None = None,
    ) -> None:
        """Evaluate all relevant signals against the current bar.

        Regime-suppressed signals are virtually activated at signal bar close
        (SIGINT-05). They skip zone-activation and are evaluated as if immediately
        active. Their status never changes from 'regime_suppressed' — the outcome
        provides counterfactual data for gate threshold validation.
        """
        if not self.db_manager:
            return

        relevant = [s for s in (all_active or []) if s.get("timeframe") == timeframe]
        self.active_signals_count.set(len(relevant))
        now = datetime.now(tz=UTC)

        for sig in relevant:
            sid = str(sig["signal_id"])
            point_value = self.point_values.get(symbol, 1.0)
            status = sig.get("status")

            # Compute bars_elapsed from timestamps (fixes TTL bug)
            sig_ts = sig.get("timestamp")
            if sig_ts and isinstance(sig_ts, datetime):
                computed_bars = _bars_elapsed(sig_ts, bar_time, timeframe)
            else:
                computed_bars = sig.get("bars_elapsed", 0)

            sig_with_extras = {
                **sig,
                "point_value": point_value,
                "bars_elapsed": computed_bars,
            }

            current_mae = self._mae.get(sid, 0.0)
            current_mfe = self._mfe.get(sid, 0.0)

            # --- Shadow signal virtual-activation path (SIGINT-05) ---
            # Regime-suppressed signals skip zone-activation. They are treated as
            # immediately active from signal bar close for MAE/MFE/outcome tracking.
            if status == "regime_suppressed":
                # Ensure _mae/_mfe initialized (covers first-bar-after-startup case)
                if sid not in self._mae:
                    self._mae[sid] = 0.0
                    current_mae = 0.0
                if sid not in self._mfe:
                    self._mfe[sid] = 0.0
                    current_mfe = 0.0
                # Ensure activated_at is set (use signal timestamp as virtual activation)
                if sid not in self._activated_at and sig_ts:
                    try:
                        act_ts = (
                            sig_ts
                            if isinstance(sig_ts, datetime)
                            else datetime.fromisoformat(str(sig_ts))
                        )
                        self._activated_at[sid] = act_ts
                    except (ValueError, TypeError) as e:
                        self.logger.warning(
                            "Invalid timestamp for shadow activation",
                            signal_id=sid,
                            sig_ts=str(sig_ts),
                            error=str(e),
                        )
                        continue

                # Pass status='active' override so evaluate_signal() takes exit path
                sig_for_eval = {**sig_with_extras, "status": "active"}
                try:
                    transition = evaluate_signal(
                        sig_for_eval,
                        high=float(bar["high"]),
                        low=float(bar["low"]),
                        close=float(bar["close"]),
                        current_mae=current_mae,
                        current_mfe=current_mfe,
                    )
                except Exception as e:
                    self.logger.warning(
                        "Shadow signal evaluation failed",
                        signal_id=sid,
                        error=str(e),
                    )
                    continue

                if transition is None:
                    # No exit — update MAE/MFE in-memory (same logic as active signals)
                    entry = float(sig.get("entry_price", 0))
                    stop = float(sig.get("stop_loss", 0))
                    risk = abs(entry - stop)
                    if risk > 0:
                        direction = sig.get("direction", 1)
                        close_pnl_r = ((float(bar["close"]) - entry) * direction) / risk
                        self._mae[sid] = min(current_mae, close_pnl_r)
                        self._mfe[sid] = max(current_mfe, close_pnl_r)
                    continue

                # Shadow signal exit (stop/target/TTL hit)
                if transition.exit_reason:
                    exit_at = now
                    bit = _bars_in_trade(self._activated_at.get(sid), now, timeframe)
                    outcome = transition.outcome
                    if outcome is None:
                        outcome = _classify_stop_outcome(current_mfe, bit)

                    confidence = float(sig.get("confidence") or 1.0)
                    signal_quality = max(
                        0.0, round((transition.pnl_r or 0.0) * confidence, 4)
                    )

                    # Status stays 'regime_suppressed' — never promoted to 'active'
                    await update_signal_status(
                        self.db_manager,
                        sid,
                        status="regime_suppressed",
                        exit_at=exit_at,
                        exit_price=transition.exit_price,
                        exit_reason=transition.exit_reason,
                        pnl_ticks=transition.pnl_ticks,
                        pnl_r=transition.pnl_r,
                        pnl_dollars=transition.pnl_dollars,
                        signal_quality=signal_quality,
                        mae=transition.mae,
                        mfe=transition.mfe,
                        bars_in_trade=bit,
                        outcome=outcome,
                    )

                    # Clean up in-memory state
                    self._mae.pop(sid, None)
                    self._mfe.pop(sid, None)
                    self._activated_at.pop(sid, None)

                    self.lifecycle_transitions_total.inc()
                    self.logger.info(
                        "Shadow signal exit",
                        signal_id=sid,
                        exit_reason=transition.exit_reason,
                        pnl_r=transition.pnl_r,
                        outcome=outcome,
                    )
                continue  # regime_suppressed handled; skip normal pending/active paths

            try:
                transition = evaluate_signal(
                    sig_with_extras,
                    high=float(bar["high"]),
                    low=float(bar["low"]),
                    close=float(bar["close"]),
                    current_mae=current_mae,
                    current_mfe=current_mfe,
                )
            except Exception as e:
                self.logger.warning(
                    "Lifecycle evaluation failed",
                    signal_id=sid,
                    error=str(e),
                )
                continue

            if transition is None:
                # Update in-memory MAE/MFE for active signals
                if status == "active":
                    entry = float(sig.get("entry_price", 0))
                    stop = float(sig.get("stop_loss", 0))
                    risk = abs(entry - stop)
                    if risk > 0:
                        direction = sig.get("direction", 1)
                        close_pnl_r = ((float(bar["close"]) - entry) * direction) / risk
                        self._mae[sid] = min(current_mae, close_pnl_r)
                        self._mfe[sid] = max(current_mfe, close_pnl_r)
                continue

            # --- State transition ---
            activated_at = None
            exit_at = None
            outcome = transition.outcome
            bit = None  # bars_in_trade
            signal_quality = None

            if transition.new_status == "active":
                # Pending → Active
                activated_at = now
                self._activated_at[sid] = now
                self._mae[sid] = 0.0
                self._mfe[sid] = 0.0

            elif transition.exit_reason:
                # Active → Exit
                exit_at = now
                bit = _bars_in_trade(self._activated_at.get(sid), now, timeframe)

                # Resolve stop outcome (needs bars_in_trade which lifecycle_tracker doesn't have)
                if outcome is None:
                    outcome = _classify_stop_outcome(current_mfe, bit)

                # Compute signal_quality
                confidence = float(sig.get("confidence") or 1.0)
                signal_quality = max(0.0, round((transition.pnl_r or 0.0) * confidence, 4))

                # Clean up memory
                self._mae.pop(sid, None)
                self._mfe.pop(sid, None)
                self._activated_at.pop(sid, None)

            await update_signal_status(
                self.db_manager,
                sid,
                status=transition.new_status,
                activated_at=activated_at,
                exit_at=exit_at,
                exit_price=transition.exit_price,
                exit_reason=transition.exit_reason,
                pnl_ticks=transition.pnl_ticks,
                pnl_r=transition.pnl_r,
                pnl_dollars=transition.pnl_dollars,
                signal_quality=signal_quality,
                activation_price=transition.activation_price,
                zone_entry_pct=transition.zone_entry_pct,
                bars_to_activation=transition.bars_to_activation,
                mae=transition.mae,
                mfe=transition.mfe,
                bars_in_trade=bit,
                outcome=outcome,
            )

            self.lifecycle_transitions_total.inc()
            self.logger.info(
                "Signal transition",
                signal_id=sid,
                new_status=transition.new_status,
                exit_reason=transition.exit_reason,
                pnl_r=transition.pnl_r,
                outcome=outcome,
            )

    async def _process_single_bar(
        self,
        symbol: str,
        timeframe: str,
        fields: dict[bytes, bytes],
    ) -> bool:
        try:
            bar = {
                "high": float(fields[b"high"].decode()),
                "low": float(fields[b"low"].decode()),
                "close": float(fields[b"close"].decode()),
            }
            bar_time = datetime.now(tz=UTC)

            # Fetch all active signals once per symbol per bar
            active = await get_active_signals(self.db_manager, symbol=symbol)

            for tf in self.config["service"]["timeframes"]:
                await self._evaluate_signals_against_bar(symbol, tf, bar, bar_time, active)

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

    async def _connect_database(self) -> None:
        try:
            self.db_manager = DatabaseManager(self.config["database"]["url"])
            await self.db_manager.initialize()
        except Exception as e:
            self.logger.warning("Database unavailable", error=str(e))
            self.db_manager = None

    async def _setup_consumer_groups(self) -> None:
        for symbol in self.config["service"]["symbols"]:
            stream_name = sk_market(self.env_prefix, symbol, "1m")
            await ensure_consumer_group_with_reset(
                self.redis_client, stream_name, self.consumer_group
            )
            self._stream_map[stream_name] = (symbol, "1m")

    async def _process_loop(self) -> None:
        all_streams = {name: ">" for name in self._stream_map}
        while self.running and not self.shutdown_requested:
            try:
                messages = await self.redis_client.xreadgroup(
                    self.consumer_group,
                    self.consumer_name,
                    all_streams,
                    count=10,
                    block=1000,
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
                        ok = await self._process_single_bar(symbol, timeframe, fields)
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
                if "NOGROUP" in str(e):
                    await self._setup_consumer_groups()
                else:
                    self.logger.error("Error in lifecycle loop", error=str(e))
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
        self.logger.info("Starting Signal Lifecycle Service")
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
            self.logger.info("Signal Lifecycle Service started")
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error("Failed to start", error=str(e))
            raise
        finally:
            await self.stop()

    async def stop(self) -> None:
        self.logger.info("Stopping Signal Lifecycle Service")
        self.running = False
        self.shutdown_requested = True
        if self.redis_client:
            await self.redis_client.aclose()
        if self.db_manager:
            await self.db_manager.close()


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Signal Lifecycle Service")
    parser.add_argument("--config", help="Config file path")
    args = parser.parse_args()
    service = SignalLifecycleService(args.config)
    try:
        await service.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
