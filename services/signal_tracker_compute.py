#!/usr/bin/env python3
"""Signal Tracker Compute — evaluates signal lifecycle transitions (DB-ignorant).

Consumes market.bars + market.bars.htf, maintains active signals in-memory,
evaluates lifecycle via evaluate_signal(), publishes transitions to
lifecycle.transitions Kafka topic.

Also consumes intelligence.i7.signals to ingest new signals into the active
index in real-time, eliminating the need for periodic DB re-seeding.

ComputeAgent role: zero DB writes, pure compute. Bootstrap is the only DB read.

Consumer groups:
  - signal_tracker_compute (bars)
  - signal_tracker_compute_signals (i7.signals)
"""

import asyncio
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import structlog

from src.config.settings import Settings, get_point_value
from src.core.agent.base import BaseAgent
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.service_utils import TF_SECONDS
from src.core.stream_keys import (
    message_key,
    topic_intelligence_i7_signals,
    topic_lifecycle_transitions,
    topic_market_bars,
    topic_market_bars_htf,
)
from src.intelligence.trading.lifecycle_tracker import (
    STALENESS_SCORE_THRESHOLD,
    compute_staleness_score,
    evaluate_signal,
)
from src.intelligence.trading.lifecycle_transitions import (
    LifecycleTransition,
    TransitionType,
    to_dict,
)
from src.observability.metrics import counter, gauge
from src.persistence.repository.signal_ledger_repository import SignalStatus

logger = structlog.get_logger(__name__)


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


class SignalTrackerCompute(BaseAgent):
    """DB-ignorant lifecycle evaluation agent.

    Consumes bars from Kafka, evaluates signal lifecycle transitions using
    evaluate_signal(), and publishes transitions to lifecycle.transitions
    topic for LifecycleWriterAgent to persist.

    Invariants:
      - Never writes to DB (bootstrap is the only read)
      - Maintains all active signal state in memory
      - Publishes LifecycleTransition events for every state change
    """

    def __init__(self) -> None:
        super().__init__(name="SignalTrackerCompute", metrics_port=9127)
        settings = Settings()
        self._settings = settings
        self._env_name = settings.env_name or ""
        self._kafka_bootstrap = getattr(settings, "kafka_bootstrap_servers", "localhost:19092")

        # In-memory active signal index: (symbol, timeframe) -> [signal dicts]
        self._active_index: dict[tuple[str, str], list[dict]] = defaultdict(list)
        # Fast symbol filter: only process bars for symbols with active signals
        self._active_symbols: set[str] = set()

        # Per-signal tracking state
        self._signal_ids: set[str] = set()
        self._mae: dict[str, float] = {}
        self._mfe: dict[str, float] = {}
        self._chandelier_state: dict[str, dict] = {}
        self._staleness_consecutive: dict[str, int] = {}
        self._activated_at: dict[str, datetime] = {}
        self._point_values: dict[str, float] = {}

        # Kafka clients (initialized in _setup)
        self._bar_consumer: KafkaConsumerClient | None = None
        self._signal_consumer: KafkaConsumerClient | None = None
        self._producer: KafkaProducerClient | None = None

        # Metrics
        self._transitions_total = counter(
            "signal_tracker_compute_transitions_total",
            "Total lifecycle transitions published",
        )
        self._active_signals_gauge = gauge(
            "signal_tracker_compute_active_signals",
            "Current count of active signals",
        )

    @property
    def topics_consumed(self) -> list[str]:
        return [
            topic_market_bars(self._env_name),
            topic_market_bars_htf(self._env_name),
            topic_intelligence_i7_signals(self._env_name),
        ]

    @property
    def topics_produced(self) -> list[str]:
        return [topic_lifecycle_transitions(self._env_name)]

    async def _setup(self) -> None:
        """Bootstrap: load active signals from DB, start Kafka clients."""
        await self._bootstrap_active_signals()

        # Bar consumer — subscribes to both 1m and HTF bar topics
        self._bar_consumer = KafkaConsumerClient(
            topic_market_bars(self._env_name),
            topic_market_bars_htf(self._env_name),
            bootstrap_servers=self._kafka_bootstrap,
            group_id="signal_tracker_compute",
            auto_offset_reset="latest",
        )
        await self._bar_consumer.start()

        # Signal consumer — subscribes to i7.signals for new signal ingestion
        self._signal_consumer = KafkaConsumerClient(
            topic_intelligence_i7_signals(self._env_name),
            bootstrap_servers=self._kafka_bootstrap,
            group_id="signal_tracker_compute_signals",
            auto_offset_reset="latest",
        )
        await self._signal_consumer.start()

        # Producer — publishes lifecycle transitions
        self._producer = KafkaProducerClient(
            bootstrap_servers=self._kafka_bootstrap,
        )
        await self._producer.start()

        total = sum(len(v) for v in self._active_index.values())
        self.logger.info(
            "signal_tracker_compute.setup_complete",
            bootstrapped_signals=total,
            active_symbols=len(self._active_symbols),
        )

    async def _teardown(self) -> None:
        """Close Kafka clients."""
        for client in (self._bar_consumer, self._signal_consumer, self._producer):
            if client is not None:
                try:
                    await client.stop()
                except Exception:
                    pass

    async def _run(self) -> None:
        """Run two concurrent consumer loops until stop event."""
        await asyncio.gather(
            self._bar_loop(),
            self._signal_loop(),
            return_exceptions=True,
        )

    # ------------------------------------------------------------------
    # Consumer loops
    # ------------------------------------------------------------------

    async def _bar_loop(self) -> None:
        """Consume market bars and evaluate active signals."""
        if self._bar_consumer is None:
            return
        async for _topic, key, payload in self._bar_consumer.messages():
            if self._stop_event.is_set():
                break
            try:
                self._record_message_consumed()
                key_str = key if isinstance(key, str) else (key.decode() if key else "")
                parts = key_str.split(":")
                if len(parts) != 2:
                    continue
                symbol, timeframe = parts[0], parts[1]

                if not self._should_process_bar(symbol, timeframe):
                    continue

                bar_time = self._parse_bar_time(payload)
                bar = {
                    "high": float(payload.get("high", 0)),
                    "low": float(payload.get("low", 0)),
                    "close": float(payload.get("close", 0)),
                }
                await self._evaluate_bar(symbol, timeframe, bar, bar_time)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.warning(
                    "bar_loop.error",
                    error=str(exc),
                    key=key,
                )

    async def _signal_loop(self) -> None:
        """Consume i7.signal payloads and ingest new signals."""
        if self._signal_consumer is None:
            return
        async for _topic, key, payload in self._signal_consumer.messages():
            if self._stop_event.is_set():
                break
            try:
                self._record_message_consumed()
                self._ingest_i7_payload(payload)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.warning(
                    "signal_loop.error",
                    error=str(exc),
                    key=key,
                )

    # ------------------------------------------------------------------
    # Symbol / timeframe filtering
    # ------------------------------------------------------------------

    def _should_process_bar(self, symbol: str, timeframe: str) -> bool:
        """Return True if the symbol has active signals to evaluate."""
        return symbol in self._active_symbols

    def _get_signals_for_bar(self, symbol: str, timeframe: str) -> list[dict]:
        """Return only signals matching this bar's timeframe."""
        return list(self._active_index.get((symbol, timeframe), []))

    # ------------------------------------------------------------------
    # Signal ingestion (from i7.signals topic)
    # ------------------------------------------------------------------

    def _ingest_i7_payload(self, payload: dict) -> None:
        """Ingest a full i7.signals payload (contains multiple signals per bar).

        Payload schema: {symbol, tf, bar_ts, computed_at, signals: list[dict]}
        """
        signals_list = payload.get("signals") or []
        symbol = payload.get("symbol", "")
        tf = payload.get("tf", "")

        if not symbol or not tf:
            return

        for sig in signals_list:
            # Skip regime-suppressed signals (they won't activate in zone track)
            status = sig.get("status")
            if status and status not in (SignalStatus.PENDING, SignalStatus.ACTIVE):
                continue
            sig_dict = {
                **sig,
                "symbol": sig.get("symbol", symbol),
                "timeframe": sig.get("timeframe", tf),
            }
            self._ingest_signal_payload(sig_dict)

    def _ingest_signal_payload(self, sig: dict) -> None:
        """Add a single signal to the active index."""
        sid = sig.get("signal_id")
        if not sid:
            return

        symbol = sig.get("symbol", "")
        tf = sig.get("timeframe", "")
        if not symbol or not tf:
            return

        if sid in self._signal_ids:
            return

        self._signal_ids.add(sid)
        key = (symbol, tf)
        self._active_index[key].append(sig)
        self._active_symbols.add(symbol)

        if symbol not in self._point_values:
            pv = get_point_value(symbol)
            if pv is not None:
                self._point_values[symbol] = float(pv)

        # Initialize MAE/MFE for new signals
        if sid not in self._mae:
            self._mae[sid] = 0.0
        if sid not in self._mfe:
            self._mfe[sid] = 0.0

        self.logger.debug(
            "signal_ingested",
            signal_id=sid,
            symbol=symbol,
            timeframe=tf,
        )

    # ------------------------------------------------------------------
    # Signal removal
    # ------------------------------------------------------------------

    def _remove_signal(self, signal_id: str, symbol: str, tf: str) -> None:
        """Remove a resolved signal from all in-memory state."""
        key = (symbol, tf)
        self._active_index[key] = [
            s for s in self._active_index.get(key, []) if s.get("signal_id") != signal_id
        ]

        # Clean up per-signal state
        self._signal_ids.discard(signal_id)
        self._mae.pop(signal_id, None)
        self._mfe.pop(signal_id, None)
        self._chandelier_state.pop(signal_id, None)
        self._staleness_consecutive.pop(signal_id, None)
        self._activated_at.pop(signal_id, None)

        # Update symbol filter: remove symbol if no signals remain
        has_any = any(symbol == k[0] and len(v) > 0 for k, v in self._active_index.items())
        if not has_any:
            self._active_symbols.discard(symbol)

        self._active_signals_gauge.set(sum(len(v) for v in self._active_index.values()))

    # ------------------------------------------------------------------
    # Bar evaluation
    # ------------------------------------------------------------------

    async def _evaluate_bar(
        self, symbol: str, timeframe: str, bar: dict, bar_time: datetime
    ) -> None:
        """Evaluate all signals matching (symbol, timeframe) against this bar."""
        signals = self._get_signals_for_bar(symbol, timeframe)
        if not signals:
            return

        self._active_signals_gauge.set(sum(len(v) for v in self._active_index.values()))

        point_value = self._point_values.get(symbol, 1.0)

        for sig in list(signals):
            sid = str(sig.get("signal_id", ""))
            status = sig.get("status")

            # Skip already-expired signals
            if status == SignalStatus.EXPIRED:
                continue

            # Compute bars_elapsed from timestamps
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

            # --- Chandelier + Staleness state for active signals ---
            staleness_score_val = 0.0
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
                    }

                # Staleness computation
                _hmm_v = sig.get("hmm_regime")
                hmm_now = _hmm_v if isinstance(_hmm_v, int) else None
                _g_v = sig.get("garch_sigma")
                garch_now = _g_v if isinstance(_g_v, (int, float)) else None
                _hmm_f = sig.get("hmm_regime_at_fire")
                hmm_fire = _hmm_f if isinstance(_hmm_f, int) else None
                _g_f = sig.get("garch_sigma_at_fire")
                garch_fire = _g_f if isinstance(_g_f, (int, float)) else None
                staleness_score_val, _ = compute_staleness_score(
                    hmm_now, hmm_fire, garch_now, garch_fire
                )
                consecutive = self._staleness_consecutive.get(sid, 0)
                if staleness_score_val > STALENESS_SCORE_THRESHOLD:
                    consecutive += 1
                else:
                    consecutive = 0
                self._staleness_consecutive[sid] = consecutive

            # --- Evaluate signal ---
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
            except Exception as exc:
                self.logger.warning(
                    "evaluate_signal.error",
                    signal_id=sid,
                    error=str(exc),
                )
                continue

            # No transition — update MAE/MFE for active signals and continue
            if transition is None:
                if status == SignalStatus.ACTIVE:
                    self._update_mae_mfe(sid, sig, bar)
                continue

            # --- Transition occurred ---
            if transition.new_status == SignalStatus.ACTIVE:
                self._activated_at[sid] = bar_time
                self._mae[sid] = 0.0
                self._mfe[sid] = 0.0
                # Update signal status in index for future evaluations
                sig["status"] = SignalStatus.ACTIVE

            elif transition.exit_reason:
                # Compute bars_in_trade if available
                if transition.bars_in_trade is None:
                    transition = self._enrich_exit_transition(transition, sid, bar_time, timeframe)

            # Map to LifecycleTransition and publish
            lifecycle_t = self._transition_to_lifecycle(transition, symbol, timeframe, bar_time)

            await self._publish_transition(lifecycle_t)

            # Clean up on exit
            if transition.exit_reason:
                self._remove_signal(sid, symbol, timeframe)

            self._transitions_total.inc()
            self.logger.info(
                "signal_transition",
                signal_id=sid,
                new_status=transition.new_status,
                exit_reason=transition.exit_reason,
                pnl_r=transition.pnl_r,
            )

    # ------------------------------------------------------------------
    # Transition mapping
    # ------------------------------------------------------------------

    def _transition_to_lifecycle(
        self,
        transition: Any,
        symbol: str,
        timeframe: str,
        bar_time: datetime,
    ) -> LifecycleTransition:
        """Map evaluate_signal() Transition to a LifecycleTransition.

        Data dict matches batch_execute() expectations in SignalLedgerRepository.
        """
        # Determine transition type
        if transition.new_status == SignalStatus.ACTIVE:
            t_type = TransitionType.ACTIVATION
            data = {
                "signal_id": transition.signal_id,
                "activated_at": bar_time,
                "activation_price": transition.activation_price,
                "zone_entry_pct": transition.zone_entry_pct,
                "bars_to_activation": transition.bars_to_activation,
            }
        elif transition.exit_reason:
            t_type = TransitionType.EXIT
            data = {
                "signal_id": transition.signal_id,
                "status": transition.new_status,
                "exit_at": bar_time,
                "exit_price": transition.exit_price,
                "exit_reason": transition.exit_reason,
                "pnl_r": transition.pnl_r,
                "pnl_dollars": transition.pnl_dollars,
                "signal_quality": None,
                "mae": transition.mae,
                "mfe": transition.mfe,
                "bars_in_trade": transition.bars_in_trade,
                "outcome": transition.outcome,
            }
        else:
            t_type = TransitionType.MAE_MFE_UPDATE
            data = {
                "signal_id": transition.signal_id,
            }

        return LifecycleTransition(
            transition_type=t_type,
            signal_id=transition.signal_id,
            symbol=symbol,
            timeframe=timeframe,
            bar_ts=bar_time,
            data=data,
        )

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    async def _publish_transition(self, lt: LifecycleTransition) -> None:
        """Publish a LifecycleTransition to Kafka."""
        if self._producer is None:
            return
        topic = topic_lifecycle_transitions(self._env_name)
        msg = to_dict(lt)
        key = message_key(lt.symbol, lt.timeframe)

        try:
            await self._producer.publish(topic, msg, key=key)
        except Exception as exc:
            self.logger.warning(
                "publish_transition.failed",
                signal_id=lt.signal_id,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_mae_mfe(self, sid: str, sig: dict, bar: dict) -> None:
        """Update in-memory MAE/MFE for active signals."""
        entry = float(sig.get("entry_price", 0))
        stop = float(sig.get("stop_loss", 0))
        risk = abs(entry - stop)
        if risk <= 0:
            return
        direction = sig.get("direction", 1)
        close_pnl_r = ((float(bar["close"]) - entry) * direction) / risk
        self._mae[sid] = min(self._mae.get(sid, 0.0), close_pnl_r)
        self._mfe[sid] = max(self._mfe.get(sid, 0.0), close_pnl_r)

    def _enrich_exit_transition(
        self,
        transition: Any,
        sid: str,
        bar_time: datetime,
        timeframe: str,
    ) -> Any:
        """Compute bars_in_trade for exit transitions if not set."""
        activated = self._activated_at.get(sid)
        if transition.bars_in_trade is None and activated is not None:
            transition.bars_in_trade = _bars_in_trade(activated, bar_time, timeframe)
        return transition

    def _parse_bar_time(self, payload: dict) -> datetime:
        """Extract bar timestamp from payload, defaulting to now UTC."""
        ts = payload.get("ts") or payload.get("timestamp")
        if ts:
            if isinstance(ts, datetime):
                return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
            try:
                dt = datetime.fromisoformat(str(ts))
                return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                pass
        return datetime.now(tz=UTC)

    # ------------------------------------------------------------------
    # Bootstrap (only DB read)
    # ------------------------------------------------------------------

    async def _bootstrap_active_signals(self) -> None:
        """One-time DB read at startup to load pending/active signals."""
        try:
            settings = self._settings
            db = DatabaseManager(settings.database_url)
            await db.initialize()
            try:
                rows = await db.execute_query("""
                    SELECT signal_id, timestamp, symbol, timeframe, status, direction,
                           entry_price, stop_loss, targets, confidence, entry_zone_low,
                           entry_zone_high, ttl_bars, bars_elapsed, hmm_regime_at_fire,
                           garch_sigma_at_fire, garch_sigma, hmm_regime, atr_14,
                           point_value, activated_at, market_entry_price
                    FROM signal_ledger
                    WHERE status IN ('pending', 'active') AND exit_at IS NULL
                    """)
                for row in rows:
                    sig = dict(row)
                    sid = str(sig.get("signal_id", ""))
                    symbol = sig.get("symbol", "")
                    tf = sig.get("timeframe", "")
                    if not sid or not symbol or not tf:
                        continue

                    # Restore point value
                    if symbol not in self._point_values:
                        pv = sig.get("point_value")
                        if pv:
                            self._point_values[symbol] = float(pv)
                        else:
                            pv_setting = get_point_value(symbol)
                            if pv_setting:
                                self._point_values[symbol] = float(pv_setting)

                    # Initialize MAE/MFE
                    self._mae[sid] = 0.0
                    self._mfe[sid] = 0.0

                    # Restore activated_at for active signals
                    if sig.get("status") == SignalStatus.ACTIVE and sig.get("activated_at"):
                        self._activated_at[sid] = sig["activated_at"]

                    self._signal_ids.add(sid)
                    self._active_index[(symbol, tf)].append(sig)
                    self._active_symbols.add(symbol)

                total = sum(len(v) for v in self._active_index.values())
                self.logger.info(
                    "bootstrap_complete",
                    signals=total,
                    symbols=len(self._active_symbols),
                )
            finally:
                await db.close()
        except Exception as exc:
            self.logger.warning("bootstrap_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Consumer lag reporting
    # ------------------------------------------------------------------

    async def _report_consumer_lag(self) -> None:
        """No-op — no partition offset API available on KafkaConsumerClient."""
        while not self._stop_event.is_set():
            await asyncio.sleep(15)


async def main() -> None:
    agent = SignalTrackerCompute()
    try:
        await agent.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
