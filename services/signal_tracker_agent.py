#!/usr/bin/env python3
"""
SignalTrackerAgent — institutional-grade signal lifecycle tracker.

Inherits BaseAgent for SIGTERM drain, lag reporting, and structured logging.
All SQL is delegated to SignalLedgerRepository — the agent is DB-ignorant in
its core processing path.

Renamed from signal_lifecycle_service.py / SignalLifecycleService as part of
Phase 52.4 Agentic DAG taxonomy conformance.
"""

import asyncio
import json
import math
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


from src.config.settings import Settings, get_active_symbols, get_point_value
from src.core.agent.base import BaseAgent
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.service_utils import TF_SECONDS, setup_service_logging
from src.core.stream_keys import (
    message_key,
    topic_llm_outcomes,
    topic_market_bars,
    topic_market_bars_htf,
    topic_signals_aggregated,
)
from src.intelligence.trading.lifecycle_tracker import (
    STALENESS_SCORE_THRESHOLD,
    _classify_stop_outcome,
    _determine_target_outcome,
    compute_chandelier_stop,  # noqa: F401 — imported for service-level usage
    compute_staleness_score,
    evaluate_market_entry,
    evaluate_signal,
)
from src.intelligence.trading.signal_outcome import SignalOutcome
from src.observability.metrics import counter, gauge, start_metrics_server
from src.persistence.repository.signal_ledger_repository import SignalLedgerRepository, SignalStatus


def _tf_to_seconds(timeframe: str) -> int:
    """Convert timeframe string to seconds."""
    return TF_SECONDS.get(timeframe, 60)


def _compute_tightening_rate(history: list[dict]) -> float | None:
    """Compute trailing stop tightening rate as slope over last 5 entries."""
    if len(history) < 2:
        return None
    tail = history[-5:]
    prices = [e["price"] for e in tail]
    n = len(prices)
    if n < 2:
        return None
    return round((prices[-1] - prices[0]) / (n - 1), 6)


# QUAL-03: freshness decay half-life — bars after which an active signal's effective
# confidence halves. Applied in-memory per bar; original confidence in signal_ledger
# is NEVER mutated (it is ground truth for ML training).
FRESHNESS_HALF_LIFE_BARS: dict[str, int] = {"1m": 20, "5m": 10, "15m": 6, "1h": 4}


def _compute_freshness_decay(bars_since: int, timeframe: str) -> float:
    """QUAL-03: Compute exponential freshness decay factor."""
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
    """Build the Kafka message payload for an llm.outcomes topic message."""
    return {
        "signal_id": signal_id,
        "outcome": outcome or "",
        "pnl_r": str(pnl_r) if pnl_r is not None else "",
        "mae": str(mae) if mae is not None else "",
        "mfe": str(mfe) if mfe is not None else "",
        "bars_in_trade": str(bars_in_trade) if bars_in_trade is not None else "",
        "outcome_at": datetime.now(tz=UTC).isoformat(),
    }


class SignalTrackerAgent(BaseAgent):
    """Zone-aware institutional signal lifecycle tracker.

    Inherits BaseAgent for SIGTERM drain and structured logging.
    All SQL is delegated to SignalLedgerRepository — no direct SQL in this class.
    """

    def __init__(self, config_file: str | None = None, db_manager: DatabaseManager | None = None):
        self.config = self._load_config(config_file)
        self._setup_logging()  # must run before super().__init__ to avoid logger cache miss
        super().__init__(name="signal_tracker_agent")
        self.start_time = datetime.now(tz=UTC)

        self.db_manager: DatabaseManager | None = db_manager
        self._ledger_repo: SignalLedgerRepository | None = (
            SignalLedgerRepository(db_manager) if db_manager else None
        )

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

        # Market-entry parallel track state
        self._market_mae: dict[str, float] = {}
        self._market_mfe: dict[str, float] = {}
        self._market_activated_at: dict[str, datetime] = {}
        self._resolved_market: set[str] = set()

        # Chandelier trailing stop state
        self._chandelier_state: dict[str, dict] = {}
        # Staleness consecutive-bar counter
        self._staleness_consecutive: dict[str, int] = {}
        # Shadow tracking state
        self._shadow_signals: dict[str, dict] = {}

        # PERF-04: In-memory active signal index
        self._active_index: dict[tuple[str, str], list[dict]] = defaultdict(list)

        # Tracked background tasks (Kafka publish, terminal event)
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

    def _load_config(self, config_file: str | None) -> dict[str, Any]:
        try:
            _settings = Settings()
        except Exception:
            _settings = None

        default: dict[str, Any] = {
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
                "file": "logs/signal_tracker_agent.log",
            },
        }
        if config_file and Path(config_file).exists():
            import json as _json

            with open(config_file) as f:
                user_config = _json.load(f)
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
        """Publish a terminal lifecycle event to the signals.aggregated topic."""
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

        All DB writes are delegated to self._ledger_repo — no direct SQL in this method.
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
            if status == SignalStatus.REGIME_SUPPRESSED:
                if sid not in self._mae:
                    self._mae[sid] = 0.0
                    current_mae = 0.0
                if sid not in self._mfe:
                    self._mfe[sid] = 0.0
                    current_mfe = 0.0
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

                sig_for_eval = {**sig_with_extras, "status": SignalStatus.ACTIVE.value}
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
                    entry = float(sig.get("entry_price", 0))
                    stop = float(sig.get("stop_loss", 0))
                    risk = abs(entry - stop)
                    if risk > 0:
                        direction = sig.get("direction", 1)
                        close_pnl_r = ((float(bar["close"]) - entry) * direction) / risk
                        self._mae[sid] = min(current_mae, close_pnl_r)
                        self._mfe[sid] = max(current_mfe, close_pnl_r)
                    continue

                if transition.exit_reason:
                    exit_at = bar_time
                    bit = _bars_in_trade(self._activated_at.get(sid), bar_time, timeframe)
                    outcome = transition.outcome
                    if outcome is None:
                        outcome = _classify_stop_outcome(current_mfe, bit)

                    signal_quality = max(
                        0.0, round((transition.pnl_r or 0.0) * effective_confidence, 4)
                    )

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

                    await self._ledger_repo.record_zone_resolution(
                        sid,
                        status=SignalStatus.REGIME_SUPPRESSED.value,
                        exit_at=exit_at,
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

                    self._mae.pop(sid, None)
                    self._mfe.pop(sid, None)
                    self._activated_at.pop(sid, None)
                    self._remove_from_index(sid, symbol, timeframe)

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
                continue

            # ── Market track (runs before zone on every bar) ──────────────
            market_entry_price = sig.get("market_entry_price")
            if market_entry_price is not None and sid not in self._resolved_market:
                if sid not in self._market_activated_at:
                    self._market_activated_at[sid] = bar_time

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
                    self.logger.warning(
                        "Market track evaluation failed", signal_id=sid, error=str(e)
                    )
                    m_trans = None

                if m_trans is not None and m_trans.exit_price is not None:
                    m_bit = _bars_in_trade(self._market_activated_at.get(sid), bar_time, timeframe)
                    m_outcome = m_trans.outcome
                    if m_outcome is None:
                        m_outcome = _classify_stop_outcome(m_mfe, m_bit)

                    try:
                        await self._ledger_repo.record_market_resolution(
                            sid,
                            market_entry_at=self._market_activated_at.get(sid),
                            market_entry_exit_price=m_trans.exit_price,
                            market_entry_exit_at=bar_time,
                            market_entry_pnl_r=m_trans.pnl_r,
                            market_entry_mae=m_trans.mae,
                            market_entry_mfe=m_trans.mfe,
                            market_entry_bars_in_trade=m_bit,
                            market_entry_outcome=m_outcome,
                            market_entry_gap_bars=None,
                        )
                        self._resolved_market.add(sid)
                    except Exception as e:
                        self.logger.warning(
                            "record_market_resolution failed", signal_id=sid, error=str(e)
                        )
                    finally:
                        self._resolved_market.add(sid)
                        self._market_mae.pop(sid, None)
                        self._market_mfe.pop(sid, None)
                        self._market_activated_at.pop(sid, None)

                elif m_trans is not None:
                    direction_val = sig.get("direction", 1)
                    risk = abs(float(market_entry_price) - float(sig.get("stop_loss", 0)))
                    if risk > 0:
                        close_pnl_r = (
                            (float(bar["close"]) - float(market_entry_price)) * direction_val / risk
                        )
                        self._market_mae[sid] = min(m_mae, close_pnl_r)
                        self._market_mfe[sid] = max(m_mfe, close_pnl_r)
            # ── End market track ──────────────────────────────────────────

            # ── Chandelier + Staleness state for active signals ───────────
            staleness_score_val = 0.0
            staleness_reason_val: str | None = None
            if status == SignalStatus.ACTIVE:
                if sid not in self._chandelier_state:
                    bar_high = float(bar["high"])
                    bar_low = float(bar["low"])
                    garch_sigma = float(sig.get("garch_sigma_at_fire") or 0.0)
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
                        "_last_written_stop": None,
                    }
                    if self._ledger_repo and vol_source:
                        try:
                            await self._ledger_repo.update_chandelier_vol_source(sid, vol_source)
                        except Exception as e:
                            self.logger.warning(
                                "Failed to write chandelier_vol_source",
                                signal_id=sid,
                                error=str(e),
                            )

                _hmm_v = sig.get("hmm_regime")
                hmm_now = _hmm_v if isinstance(_hmm_v, int) else None
                _g_v = sig.get("garch_sigma")
                garch_now = _g_v if isinstance(_g_v, (int, float)) else None
                _hmm_f = sig.get("hmm_regime_at_fire")
                hmm_fire = _hmm_f if isinstance(_hmm_f, int) else None
                _g_f = sig.get("garch_sigma_at_fire")
                garch_fire = _g_f if isinstance(_g_f, (int, float)) else None
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
                        self._chandelier_state.get(sid) if status == SignalStatus.ACTIVE else None
                    ),
                    staleness_consecutive_bars=(
                        self._staleness_consecutive.get(sid, 0)
                        if status == SignalStatus.ACTIVE
                        else 0
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
            if status == SignalStatus.ACTIVE and self.db_manager:
                ch_state = self._chandelier_state.get(sid, {})
                trailing_stop = ch_state.get("trailing_stop")
                if trailing_stop is not None:
                    last_written = ch_state.get("_last_written_stop")
                    skip_write = False
                    if last_written is not None and last_written > 0:
                        change_pct = abs(trailing_stop - last_written) / last_written
                        if change_pct < 0.0001:
                            skip_write = True

                    if not skip_write:
                        history = ch_state.setdefault("history", [])
                        history.append({"ts": bar_time.isoformat(), "price": trailing_stop})
                        if len(history) > 20:
                            del history[:-20]
                        tightening_rate = _compute_tightening_rate(history)
                        try:
                            await self._ledger_repo.update_chandelier_state(
                                sid,
                                json.dumps(history),
                                tightening_rate,
                                staleness_score_val,
                                staleness_reason_val,
                                ch_state.get("vol_source"),
                            )
                            ch_state["_last_written_stop"] = trailing_stop
                        except Exception as e:
                            self.logger.warning(
                                "Failed to write chandelier state",
                                signal_id=sid,
                                error=str(e),
                            )

            if transition is None:
                if status == SignalStatus.ACTIVE:
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
            bit = None
            signal_quality = None

            if transition.new_status == SignalStatus.ACTIVE:
                self._activated_at[sid] = bar_time
                self._mae[sid] = 0.0
                self._mfe[sid] = 0.0

            elif transition.exit_reason:
                exit_at = bar_time
                bit = _bars_in_trade(self._activated_at.get(sid), bar_time, timeframe)

                if outcome is None:
                    outcome = _classify_stop_outcome(current_mfe, bit)

                signal_quality = max(
                    0.0, round((transition.pnl_r or 0.0) * effective_confidence, 4)
                )

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

                self._mae.pop(sid, None)
                self._mfe.pop(sid, None)
                self._activated_at.pop(sid, None)
                self._resolved_market.discard(sid)
                self._chandelier_state.pop(sid, None)
                self._staleness_consecutive.pop(sid, None)
                self._remove_from_index(sid, symbol, timeframe)

                # Shadow tracking: condition_expired signals continue in shadow mode
                if outcome == "condition_expired":
                    ttl_bars = sig.get("ttl_bars", 10)
                    tf_seconds = _tf_to_seconds(timeframe)
                    sig_ts = sig.get("timestamp")
                    if sig_ts and isinstance(sig_ts, datetime) and tf_seconds > 0:
                        bars_elapsed_total = int((bar_time - sig_ts).total_seconds() / tf_seconds)
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
                    if self._ledger_repo:
                        try:
                            await self._ledger_repo.set_shadow_tracking_start(sid, bar_time)
                        except Exception as e:
                            self.logger.warning(
                                "Failed to write shadow_tracking_start_ts",
                                signal_id=sid,
                                error=str(e),
                            )

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

            if transition.new_status == SignalStatus.ACTIVE:
                await self._ledger_repo.record_activation(
                    sid,
                    activated_at=bar_time,
                    activation_price=transition.activation_price,
                    zone_entry_pct=transition.zone_entry_pct,
                    bars_to_activation=transition.bars_to_activation,
                )
            elif transition.exit_reason:
                await self._ledger_repo.record_zone_resolution(
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
            if shadow.get("symbol") != symbol or shadow.get("timeframe") != timeframe:
                continue
            shadow["remaining_ttl"] -= 1

            direction_s = shadow["direction"]
            entry_s = shadow["entry"]
            stop_s = shadow["stop"]
            targets_s = shadow["targets"]
            risk_s = abs(entry_s - stop_s)

            if risk_s > 0:
                bar_close = float(bar["close"])
                pnl_r_s = ((bar_close - entry_s) * direction_s) / risk_s
                shadow["shadow_mae"] = min(shadow["shadow_mae"], pnl_r_s)
                shadow["shadow_mfe"] = max(shadow["shadow_mfe"], pnl_r_s)

            if shadow["remaining_ttl"] <= 0:
                s_outcome = SignalOutcome.TTL_EXPIRED_BEHIND
                if shadow["shadow_mfe"] > 0:
                    for i in range(len(targets_s) - 1, -1, -1):
                        tgt = targets_s[i]
                        hit = (direction_s == 1 and bar_high >= tgt) or (
                            direction_s == -1 and bar_low <= tgt
                        )
                        if hit:
                            s_outcome = _determine_target_outcome(i)
                            break
                    else:
                        s_outcome = SignalOutcome.TTL_EXPIRED_AHEAD

                if self._ledger_repo:
                    try:
                        await self._ledger_repo.update_shadow_outcome(
                            shadow_sid,
                            shadow["start_ts"],
                            round(shadow["shadow_mae"], 4),
                            round(shadow["shadow_mfe"], 4),
                            s_outcome,
                        )
                    except Exception as e:
                        self.logger.warning(
                            "Failed to write shadow outcome",
                            signal_id=shadow_sid,
                            error=str(e),
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

            active_index = getattr(self, "_active_index", {})
            active = []
            for tf in self.config["service"]["timeframes"]:
                active.extend(active_index.get((symbol, tf), []))

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
            self._ledger_repo = SignalLedgerRepository(self.db_manager)
        except Exception as e:
            self.logger.warning("Database unavailable", error=str(e))
            self.db_manager = None

    async def _setup_kafka_clients(self) -> None:
        self._kafka_consumer = KafkaConsumerClient(
            topic_market_bars(self.env_name),
            topic_market_bars_htf(self.env_name),
            bootstrap_servers=self._kafka_bootstrap,
            group_id="signal_lifecycle",
            auto_offset_reset="earliest",
            enable_auto_commit=False,
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
            if self._stop_event.is_set():
                break
            try:
                key_str = key if isinstance(key, str) else (key.decode() if key else "")
                parts = key_str.split(":")
                if len(parts) != 2:
                    continue
                symbol, timeframe = parts
                await self._process_single_bar(symbol, timeframe, payload)
                await self._kafka_consumer.commit()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.error_count_total.inc()
                self.logger.error("Error in lifecycle loop", error=str(e))

    async def _health_monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                uptime = int((datetime.now(tz=UTC) - self.start_time).total_seconds())
                self.service_uptime_seconds.set(uptime)
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break

    async def _reseed_chandelier_state(self) -> None:
        """Re-seed Chandelier state from DB for active signals on startup."""
        if not self.db_manager or not self._ledger_repo:
            return
        try:
            symbols = self.config["service"]["symbols"]
            for sym in symbols:
                active = await self._ledger_repo.get_active_signals(symbol=sym)
                for sig in active:
                    sid = str(sig["signal_id"])
                    if sig.get("status") != SignalStatus.ACTIVE:
                        continue
                    trailing_history = sig.get("trailing_stop_price")
                    garch_fire = float(sig.get("garch_sigma_at_fire") or 0.0)
                    vol_source = sig.get("chandelier_vol_source") or "restored"
                    if trailing_history and isinstance(trailing_history, list) and trailing_history:
                        last_entry = trailing_history[-1]
                        last_stop = (
                            float(last_entry.get("price", 0.0))
                            if isinstance(last_entry, dict)
                            else 0.0
                        )
                        if last_stop > 0:
                            self._chandelier_state[sid] = {
                                "trailing_stop": last_stop,
                                "highest_high": last_stop,
                                "lowest_low": last_stop,
                                "vol": garch_fire,
                                "vol_source": vol_source,
                                "history": list(trailing_history),
                                "_last_written_stop": last_stop,
                            }
                    self._staleness_consecutive[sid] = 0
            self.logger.info(
                "Chandelier state re-seeded from DB", signals_reseeded=len(self._chandelier_state)
            )
        except Exception as e:
            self.logger.warning("Failed to re-seed Chandelier state", error=str(e))

    async def _build_active_index(self) -> dict[tuple[str, str], list[dict]]:
        """Query DB and return a fresh (symbol, timeframe) → [signals] index."""
        new_index: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for sym in self.config["service"]["symbols"]:
            for sig in await self._ledger_repo.get_active_signals(symbol=sym):
                new_index[(str(sig["symbol"]), str(sig["timeframe"]))].append(sig)
        return new_index

    async def _seed_active_index(self) -> None:
        """Build in-memory (symbol, timeframe) → [signals] index at startup."""
        if not self.db_manager:
            return
        self._active_index = await self._build_active_index()
        total = sum(len(v) for v in self._active_index.values())
        self.logger.info("active_index_seeded", total=total, keys=len(self._active_index))

    async def _reseed_active_index(self) -> None:
        """Periodically refresh the active index from DB to pick up new signals."""
        if not self.db_manager:
            return
        self._active_index = await self._build_active_index()
        total = sum(len(v) for v in self._active_index.values())
        self.logger.debug("active_index_reseeded", total=total, keys=len(self._active_index))

    def _remove_from_index(self, signal_id: str, symbol: str, timeframe: str) -> None:
        """Immediately remove a signal from the in-memory index on exit."""
        active_index = getattr(self, "_active_index", None)
        if active_index is None:
            return
        key = (symbol, timeframe)
        active_index[key] = [
            s for s in active_index.get(key, []) if str(s["signal_id"]) != signal_id
        ]

    async def _active_index_reseed_loop(self) -> None:
        """Reseed active index every 60s to pick up new signals from DB."""
        _RESEED_INTERVAL = 60
        while not self._stop_event.is_set():
            try:
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=_RESEED_INTERVAL)
                    break
                except TimeoutError:
                    pass
                if self._stop_event.is_set():
                    break
                await self._reseed_active_index()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.error("active_index_reseed_loop error", error=str(exc))
                await asyncio.sleep(30)

    async def _report_consumer_lag(self) -> None:
        """Emit persistence_consumer_lag metric.

        Uses in-memory pending task count as proxy for lag — KafkaConsumerClient
        has no partition end-offset API. Consistent with Phase 52.1/52.2 pattern.
        """
        while not self._stop_event.is_set():
            try:
                # Pending tasks approximate in-flight lifecycle updates
                self.logger.debug(
                    "signal_tracker_agent.consumer_lag",
                    pending_tasks=len(self._pending_tasks),
                )
            except Exception:
                pass
            await asyncio.sleep(15)

    async def _run(self) -> None:
        """Main agent loop — required by BaseAgent abstract method.

        SignalTrackerAgent manages its own start() lifecycle to support the
        reseed loop + chandelier seeding before the main process loop begins.
        _run() is called by start() but delegates immediately to _process_loop().
        """
        await self._process_loop()

    async def start(self) -> None:
        """Full agent lifecycle: connect, seed, run, drain."""
        self._register_signal_handlers()
        self.logger.info("Starting SignalTrackerAgent")
        reseed_task: asyncio.Task | None = None
        try:
            await self._connect_database()
            start_metrics_server(port=self.config.get("metrics_port", 9115))
            await self._setup_kafka_clients()
            await self._reseed_chandelier_state()
            await self._seed_active_index()
            reseed_task = asyncio.create_task(self._active_index_reseed_loop())
            lag_task = asyncio.create_task(self._report_consumer_lag())
            tasks = [
                asyncio.create_task(self._process_loop()),
                asyncio.create_task(self._health_monitor_loop()),
            ]
            self.logger.info("SignalTrackerAgent started")
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error("Failed to start", error=str(e))
            raise
        finally:
            if reseed_task and not reseed_task.done():
                reseed_task.cancel()
                try:
                    await reseed_task
                except (asyncio.CancelledError, Exception):
                    pass
            if "lag_task" in dir() and not lag_task.done():
                lag_task.cancel()
                try:
                    await lag_task
                except (asyncio.CancelledError, Exception):
                    pass
            await self.stop()

    async def stop(self) -> None:
        """Drain in-flight lifecycle updates before exit."""
        self.logger.info("Stopping SignalTrackerAgent")
        self._stop_event.set()
        if self._pending_tasks:
            self.logger.info("Draining background tasks", count=len(self._pending_tasks))
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)
        if self._kafka_consumer:
            await self._kafka_consumer.stop()
        if self._kafka_producer:
            await self._kafka_producer.stop()
        if self.db_manager:
            await self.db_manager.close()
        await super().stop()


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="SignalTrackerAgent")
    parser.add_argument("--config", help="Config file path")
    args = parser.parse_args()
    agent = SignalTrackerAgent(args.config)
    try:
        await agent.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
