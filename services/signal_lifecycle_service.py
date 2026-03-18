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
import math
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import structlog

from src.config.settings import Settings, get_active_symbols, get_point_value
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.service_utils import TF_SECONDS, setup_service_logging
from src.core.stream_keys import (
    message_key,
    topic_llm_outcomes,
    topic_market_bars,
    topic_signals_aggregated,
)
from src.intelligence.trading.lifecycle_tracker import (
    STALENESS_SCORE_THRESHOLD,
    _classify_stop_outcome,
    compute_chandelier_stop,  # noqa: F401 — imported for service-level usage
    compute_staleness_score,
    evaluate_market_entry,
    evaluate_signal,
)
from src.intelligence.trading.signal_ledger import (
    get_active_signals,
    record_activation,
    record_market_resolution,
    record_zone_resolution,
    record_zone_resolution_with_activation,  # noqa: F401 — used via mock.patch in tests
    update_signal_status,
)
from src.observability.metrics import counter, gauge, start_metrics_server

# ---------------------------------------------------------------------------
# Chandelier + staleness DB update helpers
# ---------------------------------------------------------------------------

_UPDATE_CHANDELIER_SQL = """
UPDATE signal_ledger
SET trailing_stop_price = $2::jsonb,
    trailing_stop_tightening_rate = $3,
    staleness_score = $4,
    staleness_trigger_reason = $5,
    chandelier_vol_source = COALESCE(chandelier_vol_source, $6)
WHERE signal_id = $1::uuid
"""

_UPDATE_SHADOW_SQL = """
UPDATE signal_ledger
SET shadow_tracking_start_ts = $2,
    shadow_mae = $3,
    shadow_mfe = $4,
    shadow_outcome = $5
WHERE signal_id = $1::uuid
"""


def _tf_to_seconds(timeframe: str) -> int:
    """Convert timeframe string to seconds."""
    return TF_SECONDS.get(timeframe, 60)


def _compute_tightening_rate(history: list[dict]) -> float | None:
    """Compute trailing stop tightening rate as slope over last 5 entries.

    A positive slope for longs (stop moving up) is tightening.
    Returns None when history has < 2 entries.
    """
    if len(history) < 2:
        return None
    tail = history[-5:]
    prices = [e["price"] for e in tail]
    n = len(prices)
    if n < 2:
        return None
    # Simple linear slope: (last - first) / n
    return round((prices[-1] - prices[0]) / (n - 1), 6)


# QUAL-03: freshness decay half-life — bars after which an active signal's effective
# confidence halves. Applied in-memory per bar; original confidence in signal_ledger
# is NEVER mutated (it is ground truth for ML training).
# Tune after 90 days outcome data.
FRESHNESS_HALF_LIFE_BARS: dict[str, int] = {"1m": 20, "5m": 10, "15m": 6, "1h": 4}


def _compute_freshness_decay(bars_since: int, timeframe: str) -> float:
    """QUAL-03: Compute exponential freshness decay factor.

    Returns a value in (0, 1] representing how fresh the signal is.
    At bars_since=0 → 1.0 (fully fresh).
    At bars_since=half_life → ~0.5 (half-life property of exponential decay).

    Args:
        bars_since: Bars elapsed since signal fire (from _bars_elapsed()).
        timeframe: Timeframe string for half-life lookup.

    Returns:
        float in (0, 1] — multiply by stored_confidence to get effective_confidence.
    """
    half_life = FRESHNESS_HALF_LIFE_BARS.get(timeframe, 10)
    lambda_decay = math.log(2) / half_life
    return math.exp(-lambda_decay * bars_since)


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


def _build_outcome_payload(
    signal_id: str,
    outcome: str,
    pnl_r: float | None,
    mae: float | None,
    mfe: float | None,
    bars_in_trade: int | None,
) -> dict[str, str]:
    """Build the Kafka message payload for an llm.outcomes topic message.

    All values are str for consistency with downstream consumers.
    None numerics become "" so the writer service stores NULL in the DB.
    """
    return {
        "signal_id": signal_id,
        "outcome": outcome or "",
        "pnl_r": str(pnl_r) if pnl_r is not None else "",
        "mae": str(mae) if mae is not None else "",
        "mfe": str(mfe) if mfe is not None else "",
        "bars_in_trade": str(bars_in_trade) if bars_in_trade is not None else "",
        "outcome_at": datetime.now(tz=UTC).isoformat(),
    }


class SignalLifecycleService:
    """Zone-aware institutional signal lifecycle tracker."""

    def __init__(self, config_file: str | None = None):
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now(tz=UTC)
        self.config = self._load_config(config_file)
        self._setup_logging()

        self.db_manager: DatabaseManager | None = None
        self._kafka_consumer: KafkaConsumerClient | None = None
        self._kafka_producer: KafkaProducerClient | None = None

        settings = Settings()
        self.env_name = settings.env_name or ""
        self.env_prefix = f"{settings.env_name}:" if settings.env_name else ""
        self._kafka_bootstrap = getattr(settings, "kafka_bootstrap_servers", "localhost:19092")

        self.point_values: dict[str, float] = {
            sym: float(get_point_value(sym) or 1.0) for sym in self.config["service"]["symbols"]
        }

        # In-memory MAE/MFE tracking: signal_id → float
        self._mae: dict[str, float] = {}
        self._mfe: dict[str, float] = {}
        # activation_time tracking for bars_in_trade: signal_id → datetime
        self._activated_at: dict[str, datetime] = {}

        # Market-entry parallel track state (mirrors _mae/_mfe/_activated_at)
        self._market_mae: dict[str, float] = {}
        self._market_mfe: dict[str, float] = {}
        self._market_activated_at: dict[str, datetime] = {}
        self._resolved_market: set[str] = set()  # sids with market track already written

        # Chandelier trailing stop state: signal_id → {trailing_stop, highest_high,
        #   lowest_low, vol, vol_source, history: [{ts, price}]}
        self._chandelier_state: dict[str, dict] = {}
        # Staleness consecutive-bar counter: signal_id → int
        self._staleness_consecutive: dict[str, int] = {}
        # Shadow tracking state: signal_id → {start_ts, remaining_ttl, direction,
        #   entry, targets, stop, shadow_mae, shadow_mfe}
        self._shadow_signals: dict[str, dict] = {}

        # Tracked background tasks (Kafka publish, terminal event).
        # Prevents silent exception swallowing and allows graceful drain on shutdown.
        self._pending_tasks: set[asyncio.Task] = set()

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
                "symbols": get_active_symbols(),
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

    def _on_task_done(self, task: asyncio.Task) -> None:
        """Remove completed task from tracking set and log any failures."""
        self._pending_tasks.discard(task)
        if not task.cancelled() and task.exception():
            self.logger.error("background task failed", error=str(task.exception()))

    def _spawn_task(self, coro) -> asyncio.Task:
        """Create a tracked background task."""
        task = asyncio.create_task(coro)
        self._pending_tasks.add(task)
        task.add_done_callback(self._on_task_done)
        return task

    async def _publish_terminal_event(
        self,
        signal_id: str,
        symbol: str,
        timeframe: str,
        outcome: str,
        exit_price: float | None,
        bar_ts: str,
    ) -> None:
        """Publish a terminal lifecycle event to the signals.aggregated topic.

        direction=0 is the sentinel meaning "this signal is closed".
        Published unconditionally — even if a newer signal has already replaced
        this one. The dashboard matches by signal_id.
        """
        if not self._kafka_producer:
            return
        payload: dict[str, str] = {
            "direction": "0",
            "signal_id": signal_id,
            "status": outcome,
            "outcome": outcome,
            "exit_price": str(exit_price) if exit_price is not None else "",
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": bar_ts,
        }
        try:
            await self._kafka_producer.publish(
                topic_signals_aggregated(self.env_name),
                payload,
                key=message_key(symbol, timeframe),
            )
        except Exception as e:
            self.logger.warning(
                "Failed to publish terminal signal event",
                signal_id=signal_id,
                error=str(e),
            )

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

            # QUAL-03: compute effective_confidence in-memory — never written to signal_ledger
            freshness = _compute_freshness_decay(bars_since=computed_bars, timeframe=timeframe)
            effective_confidence = float(sig.get("confidence") or 1.0) * freshness

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
                    exit_at = bar_time
                    bit = _bars_in_trade(self._activated_at.get(sid), bar_time, timeframe)
                    outcome = transition.outcome
                    if outcome is None:
                        outcome = _classify_stop_outcome(current_mfe, bit)

                    signal_quality = max(
                        0.0, round((transition.pnl_r or 0.0) * effective_confidence, 4)
                    )

                    # Emit outcome to llm.outcomes topic for LLM call back-fill (LLM-03)
                    if self._kafka_producer:
                        self._spawn_task(
                            self._kafka_producer.publish(
                                topic_llm_outcomes(self.env_name),
                                _build_outcome_payload(
                                    signal_id=sid,
                                    outcome=outcome,
                                    pnl_r=transition.pnl_r,
                                    mae=self._mae.get(sid, current_mae),
                                    mfe=self._mfe.get(sid, current_mfe),
                                    bars_in_trade=bit,
                                ),
                                key=message_key(sid),
                            )
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

                    # Publish terminal event to signals stream for dashboard resolved state
                    self._spawn_task(
                        self._publish_terminal_event(
                            signal_id=sid,
                            symbol=symbol,
                            timeframe=timeframe,
                            outcome=outcome,
                            exit_price=transition.exit_price,
                            bar_ts=bar_time.isoformat(),
                        )
                    )

                    self.lifecycle_transitions_total.inc()
                    self.logger.info(
                        "Shadow signal exit",
                        signal_id=sid,
                        exit_reason=transition.exit_reason,
                        pnl_r=transition.pnl_r,
                        outcome=outcome,
                    )
                continue  # regime_suppressed handled; skip normal pending/active paths

            # ── Market track (runs before zone on every bar) ──────────────
            market_entry_price = sig.get("market_entry_price")
            if market_entry_price is not None and sid not in self._resolved_market:
                if sid not in self._market_activated_at:
                    self._market_activated_at[sid] = bar_time  # first bar = activation time

                m_mae = self._market_mae.get(sid, 0.0)
                m_mfe = self._market_mfe.get(sid, 0.0)

                try:
                    m_trans = evaluate_market_entry(
                        sig_with_extras,
                        market_entry_price=float(market_entry_price),
                        high=float(bar["high"]),
                        low=float(bar["low"]),
                        close=float(bar["close"]),
                        current_mae=m_mae,
                        current_mfe=m_mfe,
                    )
                except Exception as e:
                    self.logger.warning("Market track evaluation failed",
                                        signal_id=sid, error=str(e))
                    m_trans = None

                if m_trans is not None and m_trans.exit_price is not None:
                    # Market track resolved (stop, target, or TTL) — write and clean up
                    m_bit = _bars_in_trade(
                        self._market_activated_at.get(sid), bar_time, timeframe
                    )
                    m_outcome = m_trans.outcome
                    if m_outcome is None:  # stop hit — resolve via classifier
                        m_outcome = _classify_stop_outcome(m_mfe, m_bit)

                    try:
                        await record_market_resolution(
                            self.db_manager,
                            sid,
                            market_entry_at=self._market_activated_at.get(sid),
                            market_entry_exit_price=m_trans.exit_price,
                            market_entry_exit_at=bar_time,
                            market_entry_pnl_r=m_trans.pnl_r,
                            market_entry_mae=m_trans.mae,
                            market_entry_mfe=m_trans.mfe,
                            market_entry_bars_in_trade=m_bit,
                            market_entry_outcome=m_outcome,
                            market_entry_gap_bars=None,  # live signals always None
                        )
                        self._resolved_market.add(sid)
                    except Exception as e:
                        self.logger.warning("record_market_resolution failed",
                                            signal_id=sid, error=str(e))
                    finally:
                        self._resolved_market.add(sid)  # prevent re-tracking on DB failure
                        self._market_mae.pop(sid, None)
                        self._market_mfe.pop(sid, None)
                        self._market_activated_at.pop(sid, None)

                elif m_trans is not None:
                    # Still running — update MAE/MFE accumulators
                    direction_val = sig.get("direction", 1)
                    risk = abs(float(market_entry_price) - float(sig.get("stop_loss", 0)))
                    if risk > 0:
                        close_pnl_r = (
                            (float(bar["close"]) - float(market_entry_price))
                            * direction_val
                            / risk
                        )
                        self._market_mae[sid] = min(m_mae, close_pnl_r)
                        self._market_mfe[sid] = max(m_mfe, close_pnl_r)
            # ── End market track ──────────────────────────────────────────

            # ── Chandelier + Staleness state for active signals ───────────
            staleness_score_val = 0.0
            staleness_reason_val: str | None = None
            if status == "active":
                # Initialize Chandelier state on first active bar
                if sid not in self._chandelier_state:
                    bar_high = float(bar["high"])
                    bar_low = float(bar["low"])
                    # Extract vol from bar features passed via sig dict
                    garch_sigma = float(sig.get("garch_sigma_at_fire") or 0.0)
                    # atr_14 not stored in signal_ledger but we can try features
                    atr_14 = float(sig.get("atr_14") or 0.0)
                    vol = garch_sigma if garch_sigma > 0 else atr_14
                    vol_source = "garch_sigma" if garch_sigma > 0 else "atr_14"
                    self._chandelier_state[sid] = {
                        "trailing_stop": None,
                        "highest_high": bar_high,
                        "lowest_low": bar_low,
                        "vol": vol,
                        "vol_source": vol_source,
                        "history": [],
                    }
                    # Write vol_source to DB at Chandelier initialization time
                    if self.db_manager and vol_source:
                        try:
                            await self.db_manager.execute_command(
                                "UPDATE signal_ledger SET chandelier_vol_source = $2 "
                                "WHERE signal_id = $1::uuid AND chandelier_vol_source IS NULL",
                                sid, vol_source,
                            )
                        except Exception as e:
                            self.logger.warning(
                                "Failed to write chandelier_vol_source",
                                signal_id=sid, error=str(e),
                            )

                # Compute staleness score
                hmm_now = sig.get("hmm_regime") if isinstance(sig.get("hmm_regime"), int) else None
                garch_now = sig.get("garch_sigma") if isinstance(sig.get("garch_sigma"), (int, float)) else None
                hmm_fire = sig.get("hmm_regime_at_fire") if isinstance(sig.get("hmm_regime_at_fire"), int) else None
                garch_fire = sig.get("garch_sigma_at_fire") if isinstance(sig.get("garch_sigma_at_fire"), (int, float)) else None
                staleness_score_val, staleness_reason_val = compute_staleness_score(
                    hmm_now, hmm_fire, garch_now, garch_fire
                )
                consecutive = self._staleness_consecutive.get(sid, 0)
                if staleness_score_val > STALENESS_SCORE_THRESHOLD:
                    consecutive += 1
                else:
                    consecutive = 0
                self._staleness_consecutive[sid] = consecutive
            # ── End Chandelier + Staleness prep ───────────────────────────

            try:
                transition = evaluate_signal(
                    sig_with_extras,
                    high=float(bar["high"]),
                    low=float(bar["low"]),
                    close=float(bar["close"]),
                    current_mae=current_mae,
                    current_mfe=current_mfe,
                    chandelier_state=(
                        self._chandelier_state.get(sid) if status == "active" else None
                    ),
                    staleness_consecutive_bars=(
                        self._staleness_consecutive.get(sid, 0) if status == "active" else 0
                    ),
                    staleness_score=staleness_score_val,
                )
            except Exception as e:
                self.logger.warning(
                    "Lifecycle evaluation failed",
                    signal_id=sid,
                    error=str(e),
                )
                continue

            # ── Post-eval: write Chandelier + staleness to DB (active signals) ──
            if status == "active" and self.db_manager:
                ch_state = self._chandelier_state.get(sid, {})
                trailing_stop = ch_state.get("trailing_stop")
                if trailing_stop is not None:
                    history = ch_state.setdefault("history", [])
                    history.append({"ts": bar_time.isoformat(), "price": trailing_stop})
                    # Cap at 20 entries — tightening_rate only needs last 5
                    if len(history) > 20:
                        del history[:-20]
                    tightening_rate = _compute_tightening_rate(history)
                    try:
                        await self.db_manager.execute_command(
                            _UPDATE_CHANDELIER_SQL,
                            sid,
                            json.dumps(history),
                            tightening_rate,
                            staleness_score_val,
                            staleness_reason_val,
                            ch_state.get("vol_source"),
                        )
                    except Exception as e:
                        self.logger.warning(
                            "Failed to write chandelier state",
                            signal_id=sid, error=str(e),
                        )

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
            exit_at = None
            outcome = transition.outcome
            bit = None  # bars_in_trade
            signal_quality = None

            if transition.new_status == "active":
                # Pending → Active
                self._activated_at[sid] = bar_time
                self._mae[sid] = 0.0
                self._mfe[sid] = 0.0

            elif transition.exit_reason:
                # Active → Exit
                exit_at = bar_time
                bit = _bars_in_trade(self._activated_at.get(sid), bar_time, timeframe)

                # Resolve stop outcome (needs bars_in_trade which lifecycle_tracker doesn't have)
                if outcome is None:
                    outcome = _classify_stop_outcome(current_mfe, bit)

                # Compute signal_quality (QUAL-03: uses effective_confidence, not raw stored value)
                signal_quality = max(
                    0.0, round((transition.pnl_r or 0.0) * effective_confidence, 4)
                )

                # Emit outcome to llm.outcomes topic for LLM call back-fill (LLM-03)
                if self._kafka_producer:
                    self._spawn_task(
                        self._kafka_producer.publish(
                            topic_llm_outcomes(self.env_name),
                            _build_outcome_payload(
                                signal_id=sid,
                                outcome=outcome,
                                pnl_r=transition.pnl_r,
                                mae=self._mae.get(sid, current_mae),
                                mfe=self._mfe.get(sid, current_mfe),
                                bars_in_trade=bit,
                            ),
                            key=message_key(sid),
                        )
                    )

                # Clean up memory
                self._mae.pop(sid, None)
                self._mfe.pop(sid, None)
                self._activated_at.pop(sid, None)
                self._resolved_market.discard(sid)
                self._chandelier_state.pop(sid, None)
                self._staleness_consecutive.pop(sid, None)

                # Shadow tracking: condition_expired signals continue in shadow mode
                if outcome == "condition_expired":
                    ttl_bars = sig.get("ttl_bars", 10)
                    tf_seconds = _tf_to_seconds(timeframe)
                    sig_ts = sig.get("timestamp")
                    if sig_ts and isinstance(sig_ts, datetime) and tf_seconds > 0:
                        bars_elapsed_total = int(
                            (bar_time - sig_ts).total_seconds() / tf_seconds
                        )
                    else:
                        bars_elapsed_total = sig.get("bars_elapsed", 0)
                    remaining_ttl = max(0, ttl_bars - bars_elapsed_total)
                    self._shadow_signals[sid] = {
                        "start_ts": bar_time,
                        "remaining_ttl": remaining_ttl,
                        "direction": sig.get("direction", 1),
                        "entry": float(sig.get("entry_price", 0)),
                        "targets": list(sig.get("targets") or []),
                        "stop": float(sig.get("stop_loss", 0)),
                        "shadow_mae": 0.0,
                        "shadow_mfe": 0.0,
                        "symbol": symbol,
                        "timeframe": timeframe,
                    }
                    if self.db_manager:
                        try:
                            await self.db_manager.execute_command(
                                "UPDATE signal_ledger SET shadow_tracking_start_ts = $2 "
                                "WHERE signal_id = $1::uuid",
                                sid, bar_time,
                            )
                        except Exception as e:
                            self.logger.warning(
                                "Failed to write shadow_tracking_start_ts",
                                signal_id=sid, error=str(e),
                            )

                # Publish terminal event to signals stream for dashboard resolved state
                self._spawn_task(
                    self._publish_terminal_event(
                        signal_id=sid,
                        symbol=symbol,
                        timeframe=timeframe,
                        outcome=outcome,
                        exit_price=transition.exit_price,
                        bar_ts=bar_time.isoformat(),
                    )
                )

            if transition.new_status == "active":
                await record_activation(
                    self.db_manager,
                    sid,
                    activated_at=bar_time,
                    activation_price=transition.activation_price,
                    zone_entry_pct=transition.zone_entry_pct,
                    bars_to_activation=transition.bars_to_activation,
                )
            elif transition.exit_reason:
                await record_zone_resolution(
                    self.db_manager,
                    sid,
                    status=transition.new_status,
                    exit_at=bar_time,
                    exit_price=transition.exit_price,
                    exit_reason=transition.exit_reason,
                    pnl_r=transition.pnl_r,
                    pnl_dollars=transition.pnl_dollars,
                    signal_quality=signal_quality,
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

        # ── Shadow signal tracking loop (post-condition_expired) ────────────
        bar_high = float(bar["high"])
        bar_low = float(bar["low"])
        for shadow_sid, shadow in list(self._shadow_signals.items()):
            # Only process shadows relevant to this symbol+timeframe
            if shadow.get("symbol") != symbol or shadow.get("timeframe") != timeframe:
                continue
            shadow["remaining_ttl"] -= 1

            direction_s = shadow["direction"]
            entry_s = shadow["entry"]
            stop_s = shadow["stop"]
            targets_s = shadow["targets"]
            risk_s = abs(entry_s - stop_s)

            if risk_s > 0:
                # Update shadow MAE/MFE from bar prices
                bar_close = float(bar["close"])
                pnl_r_s = ((bar_close - entry_s) * direction_s) / risk_s
                shadow["shadow_mae"] = min(shadow["shadow_mae"], pnl_r_s)
                shadow["shadow_mfe"] = max(shadow["shadow_mfe"], pnl_r_s)

            if shadow["remaining_ttl"] <= 0:
                # Determine shadow_outcome counterfactually
                s_outcome = "ttl_expired_behind"
                if shadow["shadow_mfe"] > 0:
                    # Check if any target would have been hit
                    for i in range(len(targets_s) - 1, -1, -1):
                        tgt = targets_s[i]
                        hit = (direction_s == 1 and bar_high >= tgt) or (
                            direction_s == -1 and bar_low <= tgt
                        )
                        if hit:
                            s_outcome = ["target_1", "target_1_2", "target_full"][
                                min(i, 2)
                            ]
                            break
                    else:
                        s_outcome = "ttl_expired_ahead"

                if self.db_manager:
                    try:
                        await self.db_manager.execute_command(
                            _UPDATE_SHADOW_SQL,
                            shadow_sid,
                            shadow["start_ts"],
                            round(shadow["shadow_mae"], 4),
                            round(shadow["shadow_mfe"], 4),
                            s_outcome,
                        )
                    except Exception as e:
                        self.logger.warning(
                            "Failed to write shadow outcome",
                            signal_id=shadow_sid, error=str(e),
                        )
                del self._shadow_signals[shadow_sid]
        # ── End shadow signal tracking loop ─────────────────────────────────

    async def _process_single_bar(
        self,
        symbol: str,
        timeframe: str,
        fields: dict,
    ) -> bool:
        try:
            bar = {
                "high": float(fields.get("high") or fields.get(b"high", b"0")),
                "low": float(fields.get("low") or fields.get(b"low", b"0")),
                "close": float(fields.get("close") or fields.get(b"close", b"0")),
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

    async def _connect_database(self) -> None:
        try:
            self.db_manager = DatabaseManager(self.config["database"]["url"])
            await self.db_manager.initialize()
        except Exception as e:
            self.logger.warning("Database unavailable", error=str(e))
            self.db_manager = None

    async def _setup_kafka_clients(self) -> None:
        bars_topic = topic_market_bars(self.env_name)
        self._kafka_consumer = KafkaConsumerClient(
            bars_topic,
            bootstrap_servers=self._kafka_bootstrap,
            group_id="signal_lifecycle",
            auto_offset_reset="latest",
        )
        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self._kafka_bootstrap,
        )
        await self._kafka_consumer.start()
        await self._kafka_producer.start()

    async def _process_loop(self) -> None:
        if not self._kafka_consumer:
            return
        async for _topic, key, payload in self._kafka_consumer.messages():
            if self.shutdown_requested:
                break
            try:
                # Extract symbol and timeframe from key (format "SYMBOL:TF")
                key_str = key if isinstance(key, str) else (key.decode() if key else "")
                parts = key_str.split(":")
                if len(parts) != 2:
                    continue
                symbol, timeframe = parts
                await self._process_single_bar(symbol, timeframe, payload)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.error_count_total.inc()
                self.logger.error("Error in lifecycle loop", error=str(e))

    async def _health_monitor_loop(self) -> None:
        while self.running and not self.shutdown_requested:
            try:
                uptime = int((datetime.now(tz=UTC) - self.start_time).total_seconds())
                self.service_uptime_seconds.set(uptime)
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break

    async def _reseed_chandelier_state(self) -> None:
        """Re-seed Chandelier state from DB for active signals on startup.

        Reads trailing_stop_price JSONB history and chandelier_vol_source for
        each active signal so the Chandelier stop continues from the last known
        level after a restart (rather than re-initialising from scratch).
        """
        if not self.db_manager:
            return
        try:
            symbols = self.config["service"]["symbols"]
            for sym in symbols:
                active = await get_active_signals(self.db_manager, symbol=sym)
                for sig in active:
                    sid = str(sig["signal_id"])
                    if sig.get("status") != "active":
                        continue
                    trailing_history = sig.get("trailing_stop_price")
                    garch_fire = float(sig.get("garch_sigma_at_fire") or 0.0)
                    vol_source = sig.get("chandelier_vol_source") or "restored"
                    if trailing_history and isinstance(trailing_history, list) and len(trailing_history) > 0:
                        last_entry = trailing_history[-1]
                        last_stop = float(last_entry.get("price", 0.0)) if isinstance(last_entry, dict) else 0.0
                        if last_stop > 0:
                            self._chandelier_state[sid] = {
                                "trailing_stop": last_stop,
                                "highest_high": last_stop,  # conservative; will update on next bar
                                "lowest_low": last_stop,
                                "vol": garch_fire,
                                "vol_source": vol_source,
                                "history": list(trailing_history),
                            }
                    # Always reset staleness consecutive counter on restart (conservative)
                    self._staleness_consecutive[sid] = 0
            self.logger.info("Chandelier state re-seeded from DB",
                             signals_reseeded=len(self._chandelier_state))
        except Exception as e:
            self.logger.warning("Failed to re-seed Chandelier state", error=str(e))

    async def start(self) -> None:
        self.logger.info("Starting Signal Lifecycle Service")
        try:
            await self._connect_database()
            start_metrics_server(port=self.config.get("metrics_port", 9115))
            await self._setup_kafka_clients()
            await self._reseed_chandelier_state()
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
        if self._pending_tasks:
            self.logger.info("Draining background tasks", count=len(self._pending_tasks))
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)
        if self._kafka_consumer:
            await self._kafka_consumer.stop()
        if self._kafka_producer:
            await self._kafka_producer.stop()
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
