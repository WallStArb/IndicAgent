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
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import _path_bootstrap  # noqa: F401 — project root on sys.path
import structlog

from src.config.settings import get_point_value
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
    topic_signal_tracker_dlq,
)
from src.intelligence.trading.lifecycle_tracker import (
    STALENESS_SCORE_THRESHOLD,
    MarketTransition,
    _classify_stop_outcome,
    compute_staleness_score,
    evaluate_market_entry,
    evaluate_signal,
)
from src.intelligence.trading.lifecycle_transitions import (
    LifecycleTransition,
    TransitionType,
    to_dict,
)
from src.intelligence.trading.signal_outcome import SignalOutcome
from src.intelligence.trading.signal_schema import SIGNAL_SCHEMA_VERSION
from src.observability.metrics import (
    SIGNAL_TRACKER_BACKFILL_FAST_PATH_TOTAL,
    SIGNAL_TRACKER_INVALID_SIGNAL_TOTAL,
    counter,
    gauge,
)
from src.persistence.repository.signal_ledger_repository import SignalStatus

logger = structlog.get_logger(__name__)


@dataclass
class SignalState:
    """Per-signal in-memory tracking state."""

    mae: float = 0.0
    mfe: float = 0.0
    market_mae: float = 0.0
    market_mfe: float = 0.0
    chandelier_state: dict | None = None
    staleness_consecutive: int = 0
    activated_at: datetime | None = None
    active_bars_elapsed: int = 0
    bars_since_activation: int = 0


class SignalTrackerComputeAgent(BaseAgent):
    """DB-ignorant lifecycle evaluation agent.

    Consumes bars from Kafka, evaluates signal lifecycle transitions using
    evaluate_signal(), and publishes transitions to lifecycle.transitions
    topic for LifecycleWriterAgent to persist.

    Invariants:
      - Never writes to DB (bootstrap is the only read)
      - Maintains all active signal state in memory
      - Publishes LifecycleTransition events for every state change
    """

    # Bootstrap retry configuration
    _BOOTSTRAP_MAX_ATTEMPTS = 3
    _BOOTSTRAP_BACKOFF_SECONDS = (2, 4, 8)

    def __init__(self) -> None:
        super().__init__(name="SignalTrackerComputeAgent", max_idle_seconds=300)
        self._kafka_bootstrap = self.settings.kafka_bootstrap_servers

        # In-memory active signal index: (symbol, timeframe) -> [signal dicts]
        self._active_index: dict[tuple[str, str], list[dict]] = defaultdict(list)
        # Fast symbol filter: only process bars for symbols with active signals
        self._active_symbols: set[str] = set()

        # Per-signal tracking state
        self._signal_ids: set[str] = set()
        self._signal_states: dict[str, SignalState] = {}
        # Per-symbol (not per-signal) — not in SignalState
        self._point_values: dict[str, float] = {}

        # Kafka clients (initialized in _setup)
        self._bar_consumer: KafkaConsumerClient | None = None
        self._signal_consumer: KafkaConsumerClient | None = None
        self._producer: KafkaProducerClient | None = None

        # Tracks active signal count for delta-based gauge reporting
        self._active_signal_count: int = 0

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
            topic_market_bars(self.env_name),
            topic_market_bars_htf(self.env_name),
            topic_intelligence_i7_signals(self.env_name),
        ]

    @property
    def topics_produced(self) -> list[str]:
        return [topic_lifecycle_transitions(self.env_name)]

    def _dlq_topic(self) -> str | None:
        """Route unparseable payloads to DLQ."""
        return topic_signal_tracker_dlq(self.env_name)

    async def _setup(self) -> None:
        """Bootstrap: load active signals from DB, start Kafka clients."""
        await self._bootstrap_active_signals()

        # Bar consumer — subscribes to both 1m and HTF bar topics
        self._bar_consumer = KafkaConsumerClient(
            topic_market_bars(self.env_name),
            topic_market_bars_htf(self.env_name),
            bootstrap_servers=self._kafka_bootstrap,
            group_id="signal_tracker_compute_consumer",
            auto_offset_reset="latest",
        )
        await self._bar_consumer.start()

        # Signal consumer — subscribes to i7.signals for new signal ingestion
        self._signal_consumer = KafkaConsumerClient(
            topic_intelligence_i7_signals(self.env_name),
            bootstrap_servers=self._kafka_bootstrap,
            group_id="signal_tracker_compute_signals_consumer",
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
                    # Malformed key — route to DLQ
                    await self._send_to_dlq(payload, Exception(f"Malformed key: {key_str}"))
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
                # Route failed payload to DLQ
                await self._send_to_dlq(payload, exc)

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
                # Route failed payload to DLQ
                await self._send_to_dlq(payload, exc)

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
    # Canonical signal intake
    # ------------------------------------------------------------------

    def _load_signal(self, raw: dict) -> dict | None:
        """Canonical signal intake. Returns normalized dict or None (-> DLQ).

        Both the Kafka consumer path and the bootstrap DB-SELECT path route
        through this function. Output is a single dict shape — downstream
        code never branches on source.

        Hard rejects (return None + counter increment):
            - signal_id missing
            - symbol or timeframe empty
            - timestamp is None, "", or not a tz-aware datetime
            - entry_price or stop_loss missing
        """

        def _reject(reason: str) -> None:
            SIGNAL_TRACKER_INVALID_SIGNAL_TOTAL.add(1, {"reason": reason})
            self.logger.warning("signal_rejected", reason=reason, signal_id=raw.get("signal_id"))
            return None

        sid = raw.get("signal_id")
        if not sid:
            return _reject("missing_signal_id")

        symbol = raw.get("symbol") or ""
        tf = raw.get("timeframe") or raw.get("tf") or ""
        if not symbol or not tf:
            return _reject("missing_symbol_or_timeframe")

        ts = raw.get("timestamp")
        if ts is None or ts == "":
            return _reject("empty_timestamp")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return _reject("malformed_timestamp")
        if not isinstance(ts, datetime):
            return _reject("invalid_timestamp_type")
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        entry_price = raw.get("entry_price")
        stop_loss = raw.get("stop_loss")
        if entry_price is None or stop_loss is None:
            return _reject("missing_entry_or_stop")

        # Optional / defaulted fields
        canonical = {
            "signal_id": str(sid),
            "symbol": symbol,
            "timeframe": tf,
            "timestamp": ts,
            "entry_price": float(entry_price),
            "stop_loss": float(stop_loss),
            "is_backfill": bool(raw.get("is_backfill", False)),
            "ttl_bars": int(raw.get("ttl_bars", 10)),
            "signal_schema_version": raw.get("signal_schema_version", SIGNAL_SCHEMA_VERSION),
            "status": raw.get("status", "pending"),
            "direction": int(raw.get("direction", 1)),
            "targets": list(raw.get("targets", []) or []),
            "entry_zone_low": float(raw.get("entry_zone_low") or entry_price),
            "entry_zone_high": float(raw.get("entry_zone_high") or entry_price),
            "market_entry_price": raw.get("market_entry_price"),
            "activated_at": raw.get("activated_at"),
            "garch_sigma_at_fire": raw.get("garch_sigma_at_fire"),
            "hmm_regime_at_fire": raw.get("hmm_regime_at_fire"),
        }
        return canonical

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
            # Normalize: pipeline payloads may have empty symbol/timeframe/timestamp
            # at the signal level — fill from top-level envelope before _load_signal
            raw = {
                **sig,
                "symbol": sig.get("symbol") or symbol,
                "timeframe": sig.get("timeframe") or tf,
                # timestamp may be "" in pipeline payloads — bar_ts is authoritative
                "timestamp": sig.get("timestamp") or payload.get("bar_ts", ""),
            }
            canonical = self._load_signal(raw)
            if canonical is None:
                continue  # rejected -> DLQ counter incremented inside _load_signal
            self._ingest_signal(canonical)

    def _ingest_signal(self, canonical: dict) -> None:
        """Ingest a canonical signal dict (output of _load_signal) into the active index.

        Three-branch decision tree:
          1. dedup: already tracked -> skip
          2. backfill fast-path: TTL already elapsed -> publish TTL-expired, skip active index
          3. normal path: enter active index
        """
        sid = canonical["signal_id"]
        if sid in self._signal_ids:
            return  # dedup

        tf = canonical["timeframe"]
        tf_secs = TF_SECONDS.get(tf, 60)
        now_utc = datetime.now(UTC)
        bars_elapsed = int((now_utc - canonical["timestamp"]).total_seconds() / tf_secs)

        if canonical["is_backfill"] and bars_elapsed >= canonical["ttl_bars"]:
            # Backfill fast-path: TTL elapsed at ingest — publish TTL-expired, never enter index
            self._publish_ttl_expired_transition_sync(canonical, bars_elapsed)
            SIGNAL_TRACKER_BACKFILL_FAST_PATH_TOTAL.add(
                1, {"symbol": canonical["symbol"], "timeframe": tf}
            )
            self._signal_ids.add(sid)
            return

        # Normal path (live OR backfill with TTL remaining): enter active index
        self._add_to_active_index(canonical)
        self._signal_ids.add(sid)

    def _add_to_active_index(self, canonical: dict) -> None:
        """Add a canonical signal to the in-memory active index and initialize tracking."""
        sid = canonical["signal_id"]
        symbol = canonical["symbol"]
        tf = canonical["timeframe"]

        key = (symbol, tf)
        self._active_index[key].append(canonical)
        self._active_symbols.add(symbol)
        self._active_signal_count += 1
        self._active_signals_gauge.add(1)

        if symbol not in self._point_values:
            pv = get_point_value(symbol)
            if pv is not None:
                self._point_values[symbol] = float(pv)

        state = SignalState()
        if canonical.get("status") == SignalStatus.ACTIVE and canonical.get("activated_at"):
            state.activated_at = canonical["activated_at"]
        self._signal_states[sid] = state

        self.logger.debug(
            "signal_ingested",
            signal_id=sid,
            symbol=symbol,
            timeframe=tf,
        )

    def _publish_ttl_expired_transition_sync(self, canonical: dict, bars_elapsed: int) -> None:
        """Schedule a TTL-expired LifecycleTransition for a backfill signal.

        The transition is scheduled via asyncio so the sync context (_ingest_signal)
        can publish without blocking. If no event loop is running, the transition is
        dropped (startup edge case — not critical for correctness).
        """
        from datetime import timedelta

        tf = canonical["timeframe"]
        tf_secs = TF_SECONDS.get(tf, 60)
        fire_ts = canonical["timestamp"]
        exit_at = fire_ts + timedelta(seconds=tf_secs * canonical["ttl_bars"])

        lt = LifecycleTransition(
            transition_type=TransitionType.EXIT,
            signal_id=canonical["signal_id"],
            symbol=canonical["symbol"],
            timeframe=tf,
            bar_ts=exit_at,
            data={
                "signal_id": canonical["signal_id"],
                "status": SignalStatus.EXPIRED,
                "exit_at": exit_at,
                "exit_price": None,
                "exit_reason": "ttl_expired",
                "pnl_r": 0.0,
                "pnl_dollars": None,
                "signal_quality": None,
                "mae": 0.0,
                "mfe": 0.0,
                "bars_in_trade": canonical["ttl_bars"],
                "outcome": "ttl_expired_behind",
            },
        )

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._publish_transition(lt))
        except RuntimeError:
            pass  # No event loop — startup edge case, log and continue
        self.logger.info(
            "backfill_ttl_fast_path",
            signal_id=canonical["signal_id"],
            symbol=canonical["symbol"],
            timeframe=tf,
            bars_elapsed=bars_elapsed,
            ttl_bars=canonical["ttl_bars"],
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
        self._signal_states.pop(signal_id, None)

        # Update symbol filter: remove symbol if no signals remain
        has_any = any(symbol == k[0] and len(v) > 0 for k, v in self._active_index.items())
        if not has_any:
            self._active_symbols.discard(symbol)

        self._active_signal_count -= 1
        self._active_signals_gauge.add(-1)

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

        point_value = self._point_values.get(symbol, 1.0)

        for sig in list(signals):
            sid = str(sig.get("signal_id", ""))
            status = sig.get("status")

            # Skip already-expired signals
            if status == SignalStatus.EXPIRED:
                continue

            state = self._signal_states.get(sid)
            if state is None:
                continue

            # Active-bar counting: only count bars with actual price range (high != low).
            # Empty bars (overnight/session gaps) don't decrement TTL.
            sig_ts = sig.get("timestamp")
            is_active_bar = float(bar["high"]) != float(bar["low"])
            if is_active_bar:
                state.active_bars_elapsed += 1
                if status == SignalStatus.ACTIVE:
                    state.bars_since_activation += 1
            computed_bars = state.active_bars_elapsed

            sig_with_extras = {
                **sig,
                "point_value": point_value,
                "bars_elapsed": computed_bars,
            }

            # --- Market-entry dual track (evaluate on EVERY bar) ---
            try:
                market_entry_price = float(sig.get("market_entry_price") or 0)
            except (TypeError, ValueError):
                market_entry_price = 0.0
            if market_entry_price > 0:
                try:
                    mkt = evaluate_market_entry(
                        sig_with_extras,
                        market_entry_price=market_entry_price,
                        high=float(bar["high"]),
                        low=float(bar["low"]),
                        close=float(bar["close"]),
                        current_mae=state.market_mae,
                        current_mfe=state.market_mfe,
                    )
                    if mkt.outcome is not None:
                        await self._publish_market_resolution(mkt, bar_time)
                        state.market_mae = 0.0
                        state.market_mfe = 0.0
                        sig["market_entry_price"] = 0
                    else:
                        pnl_now = (float(bar["close"]) - market_entry_price) * int(sig["direction"])
                        risk_m = abs(
                            market_entry_price - float(sig.get("stop_loss", market_entry_price))
                        )
                        if risk_m > 0:
                            pnl_r = pnl_now / risk_m
                            state.market_mae = min(state.market_mae, pnl_r)
                            state.market_mfe = max(state.market_mfe, pnl_r)
                except Exception as exc:
                    self.logger.warning("market_entry.eval.error", signal_id=sid, error=str(exc))

            # --- Chandelier + Staleness state for active signals ---
            staleness_score_val = 0.0
            if status == SignalStatus.ACTIVE:
                if state.chandelier_state is None:
                    bar_high = float(bar["high"])
                    bar_low = float(bar["low"])
                    garch_sigma = float(sig.get("garch_sigma_at_fire") or 0.0)
                    atr_14 = float(sig.get("atr_14") or 0.0)
                    vol = garch_sigma if garch_sigma > 0 else atr_14
                    vol_source = "garch_sigma" if garch_sigma > 0 else "atr_14"
                    state.chandelier_state = {
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
                consecutive = state.staleness_consecutive
                state.staleness_consecutive = (
                    consecutive + 1 if staleness_score_val > STALENESS_SCORE_THRESHOLD else 0
                )

            # --- Evaluate signal ---
            try:
                transition = evaluate_signal(
                    sig_with_extras,
                    high=float(bar["high"]),
                    low=float(bar["low"]),
                    close=float(bar["close"]),
                    current_mae=state.mae,
                    current_mfe=state.mfe,
                    chandelier_state=(
                        state.chandelier_state if status == SignalStatus.ACTIVE else None
                    ),
                    staleness_consecutive_bars=(
                        state.staleness_consecutive if status == SignalStatus.ACTIVE else 0
                    ),
                    staleness_score=staleness_score_val,
                    signal_timestamp=sig_ts,  # D-01: pass signal fire time
                    bar_time=bar_time,  # D-01: pass current bar time
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
                    self._update_mae_mfe(state, sig, bar)
                continue

            # --- Transition occurred ---
            if transition.new_status == SignalStatus.ACTIVE:
                state.activated_at = bar_time
                state.mae = 0.0
                state.mfe = 0.0
                state.bars_since_activation = 0
                # Update signal status in index for future evaluations
                sig["status"] = SignalStatus.ACTIVE

            elif transition.exit_reason:
                # Compute bars_in_trade if available
                if transition.bars_in_trade is None:
                    transition = self._enrich_exit_transition(transition, sid)
                # Stop-loss exits return outcome=None from lifecycle_tracker because
                # bars_in_trade context is only available here in the service.
                # When bars_in_trade is still None after enrichment (signal not in
                # _signal_states), fall back to mfe alone so signals that moved
                # meaningfully in profit before stopping aren't forced to stopped_at_entry.
                if transition.outcome is None and transition.exit_reason == "stop_loss":
                    mfe = transition.mfe if transition.mfe is not None else 0.0
                    if transition.bars_in_trade is None:
                        transition.outcome = (
                            SignalOutcome.STOPPED_IN_TRADE
                            if mfe > 0.05
                            else SignalOutcome.STOPPED_AT_ENTRY
                        )
                    else:
                        transition.outcome = _classify_stop_outcome(mfe, transition.bars_in_trade)

            # Map to LifecycleTransition and publish
            lifecycle_t = self._transition_to_lifecycle(transition, symbol, timeframe, bar_time)

            await self._publish_transition(lifecycle_t)

            self._transitions_total.add(1)
            self.logger.info(
                "signal_transition",
                signal_id=sid,
                new_status=transition.new_status,
                exit_reason=transition.exit_reason,
                pnl_r=transition.pnl_r,
            )

            # Clean up on exit
            if transition.exit_reason:
                self._remove_signal(sid, symbol, timeframe)
                continue

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
                "signal_id": str(transition.signal_id),
                "activated_at": bar_time,
                "activation_price": transition.activation_price,
                "zone_entry_pct": transition.zone_entry_pct,
                "bars_to_activation": transition.bars_to_activation,
            }
        elif transition.exit_reason:
            t_type = TransitionType.EXIT
            data = {
                "signal_id": str(transition.signal_id),
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
                "signal_id": str(transition.signal_id),
            }

        return LifecycleTransition(
            transition_type=t_type,
            signal_id=str(transition.signal_id),
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
        topic = topic_lifecycle_transitions(self.env_name)
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

    async def _publish_market_resolution(self, mkt: MarketTransition, bar_time: datetime) -> None:
        """Publish market-track resolution as a LifecycleTransition to Kafka."""
        lt = LifecycleTransition(
            transition_type=TransitionType.MARKET_RESOLUTION,
            signal_id=mkt.signal_id,
            symbol="",
            timeframe="",
            bar_ts=bar_time,
            data={
                "market_entry_at": bar_time,
                "market_entry_exit_price": mkt.exit_price,
                "market_entry_exit_at": bar_time,
                "market_entry_pnl_r": mkt.pnl_r,
                "market_entry_mae": mkt.mae,
                "market_entry_mfe": mkt.mfe,
                "market_entry_bars_in_trade": None,
                "market_entry_outcome": mkt.outcome,
                "market_entry_gap_bars": mkt.gap_bars,
            },
        )
        await self._publish_transition(lt)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_mae_mfe(self, state: SignalState, sig: dict, bar: dict) -> None:
        """Update in-memory MAE/MFE for active signals."""
        entry = float(sig.get("entry_price", 0))
        stop = float(sig.get("stop_loss", 0))
        risk = abs(entry - stop)
        if risk <= 0:
            return
        direction = sig.get("direction", 1)
        close_pnl_r = ((float(bar["close"]) - entry) * direction) / risk
        state.mae = min(state.mae, close_pnl_r)
        state.mfe = max(state.mfe, close_pnl_r)

    def _enrich_exit_transition(self, transition: Any, sid: str) -> Any:
        """Set bars_in_trade using market-session bar counter (excludes weekend/overnight gaps)."""
        state = self._signal_states.get(sid)
        if (
            transition.bars_in_trade is None
            and state is not None
            and state.activated_at is not None
        ):
            transition.bars_in_trade = state.bars_since_activation
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
        """One-time DB read at startup to load pending/active signals.

        Bootstrap retries protect against transient DB connection failures at
        startup. We proceed with empty state after exhaustion to avoid blocking
        the service start. On exhaustion, publishes a bootstrap_failed health
        event for monitoring.

        sd_notify(READY=1) is called ONLY after this method returns.
        """
        db = DatabaseManager(self.settings.database_url)
        await db.initialize()
        try:
            for attempt in range(self._BOOTSTRAP_MAX_ATTEMPTS):
                rows = await db.execute_query("""
                    SELECT signal_id, symbol, timeframe, timestamp, entry_price, stop_loss,
                           status, direction, targets, entry_zone_low, entry_zone_high,
                           market_entry_price, activated_at,
                           ttl_bars, signal_schema_version, garch_sigma_at_fire,
                           hmm_regime_at_fire, is_backfill
                    FROM signal_ledger
                    WHERE exit_at IS NULL
                      AND status IN ('pending', 'active')
                      AND timestamp > NOW() - INTERVAL '7 days'
                """)

                # If we got rows, load them and succeed
                if rows:
                    for row in rows:
                        raw = dict(row)
                        # asyncpg returns datetime objects for timestamptz — pass directly
                        canonical = self._load_signal(raw)
                        if canonical is None:
                            continue

                        # Bootstrap path: these are already-active signals from DB.
                        # Route directly to _add_to_active_index — do NOT run
                        # backfill fast-path or dedup check (signal_ids not set yet).
                        self._add_to_active_index(canonical)
                        self._signal_ids.add(canonical["signal_id"])

                    total = sum(len(v) for v in self._active_index.values())
                    self.logger.info(
                        "bootstrap_complete",
                        signals=total,
                        symbols=len(self._active_symbols),
                        attempt=attempt + 1,
                    )
                    return

                # No rows returned — check if ledger is truly empty or transient failure
                count_row = await db.execute_query("""
                    SELECT COUNT(*) as count
                    FROM signal_ledger
                    WHERE status IN ('pending', 'active') AND exit_at IS NULL
                      AND timestamp > NOW() - INTERVAL '3 days'
                """)
                ledger_count = count_row[0]["count"] if count_row else 0

                if ledger_count == 0:
                    # Ledger truly empty — success, no retry needed
                    self.logger.info("bootstrap_complete_empty_ledger")
                    return

                # Ledger has rows but we got 0 — transient failure, retry with backoff
                if attempt < self._BOOTSTRAP_MAX_ATTEMPTS - 1:
                    backoff = self._BOOTSTRAP_BACKOFF_SECONDS[attempt]
                    self.logger.warning(
                        "bootstrap_empty_retry",
                        attempt=attempt + 1,
                        max_attempts=self._BOOTSTRAP_MAX_ATTEMPTS,
                        ledger_count=ledger_count,
                        backoff_seconds=backoff,
                    )
                    await asyncio.sleep(backoff)
                else:
                    # Exhausted retries — publish health event and proceed with empty state
                    self.logger.error(
                        "bootstrap_failed_exhausted",
                        ledger_count=ledger_count,
                        attempts=self._BOOTSTRAP_MAX_ATTEMPTS,
                    )
                    await self._publish_bootstrap_failed_event(ledger_count)

        finally:
            await db.close()

    async def _publish_bootstrap_failed_event(self, ledger_count: int) -> None:
        """Publish bootstrap_failed health event to Kafka."""
        if not self._producer:
            return

        from src.core.stream_keys import topic_health_events

        payload = {
            "event_type": "bootstrap_failed",
            "service": "signal_tracker_compute",
            "severity": "HIGH",
            "timestamp": datetime.now(UTC).isoformat(),
            "details": {
                "ledger_count": ledger_count,
                "attempts": self._BOOTSTRAP_MAX_ATTEMPTS,
                "reason": (
                    f"DB returned 0 rows after {self._BOOTSTRAP_MAX_ATTEMPTS}"
                    " retry attempts with exponential backoff"
                ),
            },
        }

        try:
            await self._producer.publish(
                topic_health_events(self.env_name),
                key=message_key("signal_tracker_compute"),
                value=payload,
            )
        except Exception as exc:
            self.logger.error("bootstrap_failed_event_publish_error", error=str(exc))


async def main() -> None:
    agent = SignalTrackerComputeAgent()
    try:
        await agent.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
