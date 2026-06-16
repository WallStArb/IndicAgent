#!/usr/bin/env python3
"""Signal Tracker Compute — evaluates signal lifecycle transitions (DB-ignorant).

Consumes market.bars + market.bars.htf, maintains active signals in-memory,
evaluates lifecycle via evaluate_signal(), publishes transitions to
lifecycle.transitions Kafka topic.

Also consumes intelligence.i7.signals to ingest new signals into the active
index in real-time, eliminating the need for periodic DB re-seeding.

ComputeAgent role: zero DB writes, pure compute. Bootstrap is the only DB read.
Bootstrap queries signal_events + trade_frames directly via SignalEventsRepository
(not signal_ledger, which NULLs all lifecycle fields — RESEARCH Pitfall 1).

Consumer groups:
  - signal_tracker_compute (bars)
  - signal_tracker_compute_signals (i7.signals)
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import _path_bootstrap  # noqa: F401 — project root on sys.path
import structlog

from src.config.settings import get_point_value
from src.core.agent.base import BaseDaemon
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.service_utils import TF_SECONDS, format_iso_ts, parse_iso_ts, tf_to_seconds
from src.core.stream_keys import (
    message_key,
    topic_intelligence_i7_signals,
    topic_lifecycle_transitions,
    topic_llm_outcomes,
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
from src.observability.metrics import (
    SIGNAL_TRACKER_BACKFILL_FAST_PATH_TOTAL,
    SIGNAL_TRACKER_INVALID_SIGNAL_TOTAL,
    counter,
    gauge,
)
from src.persistence.repository.signal_events_repository import (
    SignalEventsRepository,
    SignalStatus,
)

logger = structlog.get_logger(__name__)

_NULL_EXPIRES_AT_COUNTER = counter(
    "signal_tracker_null_expires_at_total",
    "Count of signals skipped at startup due to NULL expires_at — data-integrity alert (D-17)",
)

SIGNAL_TRACKER_BACKFILL_ROUTED_TO_REPLAY_TOTAL = counter(
    "signal_tracker_backfill_routed_to_replay_total",
    "Backfill signals with elapsed TTL routed to dedup-only (no EXIT published); "
    "SignalReplayAuditor evaluates these bar-by-bar (1-H / D-09)",
)


def _as_int(value: Any) -> int | None:
    """Return value if it is an int, else None — for staleness regime inputs."""
    return value if isinstance(value, int) else None


def _as_float(value: Any) -> float | None:
    """Return value if it is numeric, else None — for staleness sigma inputs."""
    return value if isinstance(value, (int, float)) else None


@dataclass
class SignalState:
    """Per-signal in-memory tracking state for lifecycle evaluation.

    Mutable lifecycle fields (status, market_entry_price) live here so canonical
    dicts in _active_index are read-only after ingestion (CONCERN-02 fix).
    """

    # Lifecycle state — mutated during evaluation; canonical dict is immutable
    status: str = "pending"
    market_entry_price: float = 0.0

    mae: float = 0.0
    mfe: float = 0.0
    market_mae: float = 0.0
    market_mfe: float = 0.0
    chandelier_state: dict | None = None
    staleness_consecutive: int = 0
    activated_at: datetime | None = None
    active_bars_elapsed: int = 0
    bars_since_activation: int = 0
    # Count of active-bar evaluations for MAE/MFE periodic publish trigger (every 10 bars).
    # Incremented only when signal is ACTIVE and bar has real price range (high != low).
    active_bar_count: int = 0


class SignalTracker(BaseDaemon):
    """DB-ignorant lifecycle evaluation agent.

    Consumes bars from Kafka, evaluates signal lifecycle transitions using
    evaluate_signal(), and publishes transitions to lifecycle.transitions topic
    for LifecycleWriter to persist.

    Bootstrap queries signal_events + trade_frames directly via
    SignalEventsRepository.get_active_signals_for_bootstrap() to load non-NULL
    lifecycle state (activated_at, trailing_stop_price, chandelier_vol_source, etc.).
    APR keys feature.signal_tracker.bootstrap_* control window days and max attempts.

    Invariants:
      - Never writes to DB (bootstrap is the only read)
      - Maintains all active signal state in memory
      - Publishes LifecycleTransition events for every state change
    """

    # Bootstrap retry configuration — defaults used before APR loads in _setup()
    _BOOTSTRAP_BACKOFF_SECONDS = (2, 4, 8)

    def __init__(self) -> None:
        super().__init__(max_idle_seconds=300)
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
        # Per-(symbol, tf) current regime state — updated from i7.signals envelope.
        # Used for staleness computation to compare current vs fire-time regime (BUG-02 fix).
        self._regime_cache: dict[tuple[str, str], dict] = {}

        # APR-backed bootstrap configuration — loaded in _setup() from config_service.
        # Defaults match APR seed values (migration 142).
        self._bootstrap_max_attempts: int = 3
        self._bootstrap_pending_window_days: int = 7
        self._bootstrap_active_window_days: int = 30
        self._bootstrap_dedup_window_days: int = 3
        self._staleness_score_threshold: float = STALENESS_SCORE_THRESHOLD

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
        """Bootstrap: load APR config, load active signals from DB, start Kafka clients."""
        # Load APR-backed bootstrap configuration (feature.signal_tracker.* namespace,
        # seeded in migration 142). get_config() reads from the OPS snapshot loaded by
        # BaseDaemon._pre_setup_config_load() before _setup() is called.
        self._bootstrap_max_attempts = int(
            self.get_config("feature.signal_tracker.bootstrap_max_attempts", default=3)
        )
        self._bootstrap_pending_window_days = int(
            self.get_config("feature.signal_tracker.bootstrap_pending_window_days", default=7)
        )
        self._bootstrap_active_window_days = int(
            self.get_config("feature.signal_tracker.bootstrap_active_window_days", default=30)
        )
        self._bootstrap_dedup_window_days = int(
            self.get_config("feature.signal_tracker.bootstrap_dedup_window_days", default=3)
        )
        self._staleness_score_threshold = float(
            self.get_config(
                "threshold.signal_tracker.staleness_score", default=STALENESS_SCORE_THRESHOLD
            )
        )

        await self._bootstrap_active_signals()

        # Bar consumer — subscribes to both 1m and HTF bar topics.
        # earliest: _signal_ids bootstrap completes before consumer start, so
        # replaying known signals is a dedup no-op (2-F / D-10).
        self._bar_consumer = KafkaConsumerClient(
            topic_market_bars(self.env_name),
            topic_market_bars_htf(self.env_name),
            bootstrap_servers=self._kafka_bootstrap,
            group_id="signal_tracker_compute_consumer",
            auto_offset_reset="earliest",
        )
        await self._bar_consumer.start()

        # Signal consumer — subscribes to i7.signals for new signal ingestion.
        # earliest: _bootstrap_active_signals() runs BEFORE consumer start in _setup(),
        # so _signal_ids is fully populated for all active signals before any replay
        # begins. Re-reading an already-known sid short-circuits at the dedup check (2-F).
        self._signal_consumer = KafkaConsumerClient(
            topic_intelligence_i7_signals(self.env_name),
            bootstrap_servers=self._kafka_bootstrap,
            group_id="signal_tracker_compute_signals_consumer",
            auto_offset_reset="earliest",
        )
        await self._signal_consumer.start()

        # Producer — publishes lifecycle transitions
        self._producer = KafkaProducerClient(
            bootstrap_servers=self._kafka_bootstrap,
        )
        await self._producer.start()

        total = sum(len(v) for v in self._active_index.values())
        self.logger.info(
            "signal_tracker.setup_complete",
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
            except Exception as error:
                self.logger.warning(
                    "bar_loop.error",
                    error=str(error),
                    key=key,
                )
                # Route failed payload to DLQ
                await self._send_to_dlq(payload, error)

    async def _signal_loop(self) -> None:
        """Consume i7.signal payloads and ingest new signals."""
        if self._signal_consumer is None:
            return
        async for _topic, key, payload in self._signal_consumer.messages():
            if self._stop_event.is_set():
                break
            try:
                self._record_message_consumed()
                await self._ingest_i7_payload(payload)
            except asyncio.CancelledError:
                break
            except Exception as error:
                self.logger.warning(
                    "signal_loop.error",
                    error=str(error),
                    key=key,
                )
                # Route failed payload to DLQ
                await self._send_to_dlq(payload, error)

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

        Both Kafka consumer and bootstrap DB-SELECT paths route through this.
        Hard rejects: missing signal_id, empty symbol/tf, invalid/empty timestamp,
        missing entry_price or stop_loss.

        Args:
            raw: Raw signal dict from Kafka or DB

        Returns:
            Normalized signal dict, or None if hard-rejected.
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
        ttl_bars = int(raw.get("ttl_bars", 10))
        canonical = {
            "signal_id": str(sid),
            "symbol": symbol,
            "timeframe": tf,
            "timestamp": ts,
            "entry_price": float(entry_price),
            "stop_loss": float(stop_loss),
            "is_backfill": bool(raw.get("is_backfill", False)),
            "is_shadow": bool(raw.get("is_shadow", False)),
            "ttl_bars": ttl_bars,
            "status": raw.get("status", "pending"),
            "direction": int(raw.get("direction", 1)),
            "targets": list(raw.get("targets", []) or []),
            "entry_zone_low": float(
                raw["entry_zone_low"] if raw.get("entry_zone_low") is not None else entry_price
            ),
            "entry_zone_high": float(
                raw["entry_zone_high"] if raw.get("entry_zone_high") is not None else entry_price
            ),
            "market_entry_price": raw.get("market_entry_price"),
            "activated_at": parse_iso_ts(raw.get("activated_at")),
            "garch_sigma_at_fire": raw.get("garch_sigma_at_fire"),
            "hmm_regime_at_fire": raw.get("hmm_regime_at_fire"),
            "expires_at": raw.get("expires_at")
            or (ts + timedelta(seconds=ttl_bars * tf_to_seconds(tf)) if tf else None),
        }
        # Shadow signals skip zone-entry and are tracked as immediately active so
        # outcomes accumulate for the shadow governance promotion gate.
        if canonical["is_shadow"] and canonical["status"] == SignalStatus.REGIME_SUPPRESSED:
            canonical["status"] = "active"
        return canonical

    # ------------------------------------------------------------------
    # Signal ingestion (from i7.signals topic)
    # ------------------------------------------------------------------

    async def _ingest_i7_payload(self, payload: dict) -> None:
        """Ingest a full i7.signals payload (contains multiple signals per bar).

        Args:
            payload: Kafka message with {symbol, tf, bar_ts, computed_at,
                     hmm_regime, garch_sigma, signals: list}
        """
        signals_list = payload.get("signals") or []
        symbol = payload.get("symbol", "")
        tf = payload.get("tf", "")

        if not symbol or not tf:
            return

        # Update per-(symbol, tf) regime cache from envelope (BUG-02 fix: enables
        # staleness regime drift to compare current vs fire-time regime).
        hmm = payload.get("hmm_regime")
        sigma = payload.get("garch_sigma")
        if hmm is not None or sigma is not None:
            self._regime_cache[(symbol, tf)] = {
                "hmm_regime": hmm,
                "garch_sigma": sigma,
            }

        for sig in signals_list:
            status = sig.get("status")
            if status and status not in (SignalStatus.PENDING, SignalStatus.ACTIVE):
                if not (status == SignalStatus.REGIME_SUPPRESSED and sig.get("is_shadow")):
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
            await self._ingest_signal(canonical)

    async def _ingest_signal(self, canonical: dict) -> None:
        """Ingest a canonical signal dict into the active index.

        Three-branch decision tree:
          1. Dedup: skip if already tracked
          2. Backfill fast-path: publish TTL-expired if elapsed, skip active index
          3. Normal path: enter active index

        The signal ID is only added to _signal_ids AFTER a successful publish on the
        fast-path, preventing ghost IDs when the Kafka publish fails.

        Args:
            canonical: Normalized signal dict from _load_signal
        """
        sid = canonical["signal_id"]
        if sid in self._signal_ids:
            return  # dedup

        tf = canonical["timeframe"]
        now_utc = datetime.now(UTC)

        expires_at = canonical.get("expires_at")
        if expires_at is None:
            # D-17: NULL expires_at post-backfill is a data-integrity bug. Fail loud, do NOT
            # fall back to bar-count. Increment counter, warn, and skip fast-path.
            _NULL_EXPIRES_AT_COUNTER.add(
                1,
                {
                    "symbol": canonical.get("symbol", "unknown"),
                    "timeframe": tf,
                },
            )
            self.logger.warning(
                "ingest_null_expires_at_skip",
                signal_id=str(canonical.get("signal_id")),
            )
            # Skip fast-path: do not fire TTL from bar count. Add to active index normally below.
        elif now_utc >= expires_at:
            # Fast-path: TTL elapsed at ingest.
            #
            # BACKFILL ROUTING (1-H / D-09): is_backfill signals with elapsed TTL
            # are routed to dedup-only — do NOT publish EXIT, do NOT enter active index.
            # SignalReplayAuditor evaluates these bar-by-bar against historical bars.
            # Publishing a false EXIT here would contaminate the ledger.
            if canonical.get("is_backfill") is True:
                # Dedup-only: register sid so subsequent re-ingestion is a no-op.
                self._signal_ids.add(sid)
                SIGNAL_TRACKER_BACKFILL_ROUTED_TO_REPLAY_TOTAL.add(
                    1, {"symbol": canonical["symbol"]}
                )
                self.logger.info(
                    "backfill_routed_to_replay",
                    signal_id=sid,
                    symbol=canonical["symbol"],
                    timeframe=tf,
                    note="TTL elapsed; routed to dedup-only — SignalReplayAuditor owns evaluation",
                )
                return

            # Non-backfill: publish TTL-expired, never enter index.
            # Await the publish before deduping: if publish fails, do NOT add to _signal_ids
            # so the signal can be retried on the next ingest attempt.
            tf_secs = TF_SECONDS.get(tf, 60)
            bars_elapsed = int((now_utc - canonical["timestamp"]).total_seconds() / tf_secs)
            published = await self._publish_ttl_expired_transition(canonical, bars_elapsed)
            if published:
                SIGNAL_TRACKER_BACKFILL_FAST_PATH_TOTAL.add(
                    1, {"symbol": canonical["symbol"], "timeframe": tf}
                )
                self._signal_ids.add(sid)
            return

        # Normal path (TTL window still open): enter active index
        self._add_to_active_index(canonical)
        self._signal_ids.add(sid)

    def _add_to_active_index(self, canonical: dict) -> None:
        """Add a canonical signal to the in-memory active index and initialize tracking.

        Args:
            canonical: Normalized signal dict from _load_signal
        """
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

        state = SignalState(
            # Seed mutable lifecycle fields from canonical so they start correct.
            # Canonical dict is NOT mutated after this point (CONCERN-02 fix).
            status=str(canonical.get("status") or "pending"),
            market_entry_price=float(canonical.get("market_entry_price") or 0.0),
            # Bootstrap MAE/MFE from frame_details if present in the canonical dict
            # (1-I / D-18): get_active_signals_for_bootstrap() sets mae/mfe from
            # trade_frames.frame_details JSONB. Live signals default to 0.0 — correct.
            mae=float(canonical.get("mae") or 0.0),
            mfe=float(canonical.get("mfe") or 0.0),
        )
        if state.status == SignalStatus.ACTIVE and canonical.get("activated_at"):
            state.activated_at = canonical["activated_at"]
            # Restore chandelier state persisted in trade_frames.frame_details (CONCERN-01 fix).
            # trailing_stop_price is a JSONB dict stored by _publish_chandelier_update
            # and loaded from frame_details->>'trailing_stop_price' by the bootstrap query.
            raw_cs = canonical.get("trailing_stop_price")
            if isinstance(raw_cs, dict) and raw_cs.get("trailing_stop") is not None:
                state.chandelier_state = {
                    "trailing_stop": raw_cs.get("trailing_stop"),
                    "highest_high": raw_cs.get("highest_high"),
                    "lowest_low": raw_cs.get("lowest_low"),
                    "vol": raw_cs.get("vol"),
                    "vol_source": raw_cs.get("vol_source")
                    or canonical.get("chandelier_vol_source"),
                }
        self._signal_states[sid] = state

        self.logger.debug(
            "signal_ingested",
            signal_id=sid,
            symbol=symbol,
            timeframe=tf,
        )

    async def _bootstrap_apply_signal(self, canonical: dict) -> None:
        """Apply one signal loaded from DB during bootstrap.

        Mirrors _ingest_signal fast-path logic: signals with elapsed TTL are
        fast-pathed (publish TTL exit or dedup-only for backfill) rather than
        loaded into the active index. This prevents reloading stale piles on restart.
        """
        now_utc = datetime.now(UTC)
        expires_at = canonical.get("expires_at")

        if expires_at is not None and now_utc >= expires_at:
            if canonical.get("is_backfill") is True:
                self._signal_ids.add(canonical["signal_id"])
                SIGNAL_TRACKER_BACKFILL_ROUTED_TO_REPLAY_TOTAL.add(
                    1, {"symbol": canonical["symbol"]}
                )
                self.logger.debug(
                    "bootstrap_ttl_elapsed_backfill_skip",
                    signal_id=canonical["signal_id"],
                )
            else:
                tf_secs = TF_SECONDS.get(canonical["timeframe"], 60)
                bars_elapsed = int((now_utc - canonical["timestamp"]).total_seconds() / tf_secs)
                published = await self._publish_ttl_expired_transition(canonical, bars_elapsed)
                if published:
                    self._signal_ids.add(canonical["signal_id"])
            return

        self._add_to_active_index(canonical)
        self._signal_ids.add(canonical["signal_id"])

    async def _publish_ttl_expired_transition(self, canonical: dict, bars_elapsed: int) -> bool:
        """Publish a TTL-expired LifecycleTransition for a backfill signal.

        Returns True if published successfully, False on failure. The caller
        must NOT dedup the signal_id on failure so retries remain possible.
        """
        from datetime import timedelta

        tf = canonical["timeframe"]
        fire_ts = canonical["timestamp"]
        exit_at = fire_ts + timedelta(seconds=tf_to_seconds(tf) * canonical["ttl_bars"])

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
                "pnl_ticks": None,
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
            await self._publish_transition(lt)
            self.logger.info(
                "backfill_ttl_fast_path",
                signal_id=canonical["signal_id"],
                symbol=canonical["symbol"],
                timeframe=tf,
                bars_elapsed=bars_elapsed,
                ttl_bars=canonical["ttl_bars"],
            )
            return True
        except Exception as error:
            self.logger.warning(
                "backfill_ttl_fast_path.publish_failed",
                signal_id=canonical["signal_id"],
                error=str(error),
            )
            return False

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

            state = self._signal_states.get(sid)
            if state is None:
                continue

            # Read lifecycle status from SignalState — canonical dict is immutable
            # after ingestion (CONCERN-02 fix). state.status is the authoritative
            # mutable status; sig.get("status") is the fire-time snapshot only.
            status = state.status

            # Skip already-expired signals
            if status == SignalStatus.EXPIRED:
                continue

            # Active-bar counting: only count bars with actual price range (high != low).
            # Empty bars (overnight/session gaps) don't decrement TTL.
            sig_ts = sig.get("timestamp")
            is_active_bar = float(bar["high"]) != float(bar["low"])
            if is_active_bar:
                state.active_bars_elapsed += 1
                if status == SignalStatus.ACTIVE:
                    state.bars_since_activation += 1
                    # active_bar_count: tracks ACTIVE-only bars for MAE/MFE periodic publish
                    state.active_bar_count += 1
            computed_bars = state.active_bars_elapsed

            # Build evaluation dict — inject mutable state fields here so
            # evaluate_signal() sees current status/market_entry_price WITHOUT
            # modifying the canonical sig dict.
            sig_with_extras = {
                **sig,
                "status": state.status,
                "market_entry_price": state.market_entry_price,
                "point_value": point_value,
                "bars_elapsed": computed_bars,
            }

            # --- Market-entry dual track (evaluate on EVERY bar) ---
            # Read from state.market_entry_price — state is the sole mutable store
            market_entry_price = state.market_entry_price
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
                        # Clear market entry price via state — never mutate canonical dict
                        state.market_entry_price = 0.0
                    else:
                        pnl_now = (float(bar["close"]) - market_entry_price) * int(sig["direction"])
                        risk_m = abs(
                            market_entry_price - float(sig.get("stop_loss", market_entry_price))
                        )
                        if risk_m > 0:
                            pnl_r = pnl_now / risk_m
                            state.market_mae = min(state.market_mae, pnl_r)
                            state.market_mfe = max(state.market_mfe, pnl_r)
                except Exception as error:
                    self.logger.warning("market_entry.eval.error", signal_id=sid, error=str(error))

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

                # Staleness computation — use regime cache for current bar state (BUG-02 fix).
                # sig.get("hmm_regime") is fire-time only; _regime_cache has current bar.
                regime_now = self._regime_cache.get((symbol, timeframe), {})
                hmm_now = _as_int(regime_now.get("hmm_regime"))
                hmm_fire = _as_int(sig.get("hmm_regime_at_fire"))
                garch_now = _as_float(regime_now.get("garch_sigma"))
                garch_fire = _as_float(sig.get("garch_sigma_at_fire"))
                staleness_score_val, _ = compute_staleness_score(
                    hmm_now, hmm_fire, garch_now, garch_fire
                )
                consecutive = state.staleness_consecutive
                state.staleness_consecutive = (
                    consecutive + 1 if staleness_score_val > self._staleness_score_threshold else 0
                )

            # Capture chandelier stop before evaluation to detect ratchet updates
            chandelier_stop_before = (
                state.chandelier_state.get("trailing_stop")
                if state.chandelier_state is not None
                else None
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
            except Exception as error:
                self.logger.warning(
                    "evaluate_signal.error",
                    signal_id=sid,
                    error=str(error),
                )
                continue

            # No transition — update MAE/MFE and persist chandelier ratchet if it moved
            if transition is None:
                if status == SignalStatus.ACTIVE:
                    self._update_mae_mfe(state, sig, bar)
                    # Publish chandelier state whenever trailing_stop ratchets so it
                    # survives a service restart (restored from trade_frames.frame_details
                    # JSONB via SignalEventsRepository.get_active_signals_for_bootstrap).
                    if state.chandelier_state is not None:
                        chandelier_stop_after = state.chandelier_state.get("trailing_stop")
                        if chandelier_stop_after != chandelier_stop_before:
                            await self._publish_chandelier_update(
                                sid, symbol, timeframe, state, bar_time
                            )
                    # MAE/MFE persist trigger (1-I / D-18): publish when threshold crossed
                    # AND every 10th active bar. Payload verified against
                    # repo.batch_execute("mae_mfe_update") in SignalLedgerRepository —
                    # handler extracts signal_id, mae, mfe (lines ~797-799 of repository).
                    if (
                        is_active_bar
                        and state.active_bar_count > 0
                        and state.active_bar_count % 10 == 0
                        and (abs(state.mae) > 0.05 or abs(state.mfe) > 0.05)
                    ):
                        await self._publish_mae_mfe_update(sid, symbol, timeframe, state, bar_time)
                continue

            # --- Transition occurred ---
            if transition.new_status == SignalStatus.ACTIVE:
                state.activated_at = bar_time
                state.mae = 0.0
                state.mfe = 0.0
                state.bars_since_activation = 0
                # Update status via SignalState — never mutate canonical dict (CONCERN-02)
                state.status = SignalStatus.ACTIVE

            elif transition.exit_reason:
                # Compute bars_in_trade if available
                if transition.bars_in_trade is None:
                    transition = self._enrich_exit_transition(transition, sid)
                # Stop-loss exits return outcome=None from lifecycle_tracker because
                # bars_in_trade context is only available here in the service. When
                # bars_in_trade is still None after enrichment (signal not in
                # _signal_states), fall back to mfe alone so signals that moved
                # meaningfully in profit before stopping aren't forced to stopped_at_entry.
                if transition.outcome is None and transition.exit_reason == "stop_loss":
                    mfe = transition.mfe or 0.0
                    if transition.bars_in_trade is not None:
                        transition.outcome = _classify_stop_outcome(mfe, transition.bars_in_trade)
                    elif mfe > 0.05:
                        transition.outcome = SignalOutcome.STOPPED_IN_TRADE
                    else:
                        transition.outcome = SignalOutcome.STOPPED_AT_ENTRY

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
                "pnl_ticks": transition.pnl_ticks,
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
        except Exception as error:
            self.logger.warning(
                "publish_transition.failed",
                signal_id=lt.signal_id,
                error=str(error),
            )

        if lt.transition_type == TransitionType.EXIT:
            outcomes_msg = {
                "signal_id": lt.signal_id,
                "outcome": lt.data.get("outcome"),
                "pnl_r": lt.data.get("pnl_r"),
                "mae": lt.data.get("mae"),
                "mfe": lt.data.get("mfe"),
                "bars_in_trade": lt.data.get("bars_in_trade"),
                "outcome_at": format_iso_ts(lt.bar_ts),
            }
            try:
                await self._producer.publish(
                    topic_llm_outcomes(self.env_name), outcomes_msg, key=key
                )
            except Exception as error:
                self.logger.warning(
                    "publish_llm_outcome.failed",
                    signal_id=lt.signal_id,
                    error=str(error),
                )

    async def _publish_chandelier_update(
        self,
        signal_id: str,
        symbol: str,
        timeframe: str,
        state: SignalState,
        bar_time: datetime,
    ) -> None:
        """Publish a CHANDELIER_UPDATE transition so trailing stop survives restarts."""
        cs = state.chandelier_state
        if cs is None:
            return
        lt = LifecycleTransition(
            transition_type=TransitionType.CHANDELIER_UPDATE,
            signal_id=signal_id,
            symbol=symbol,
            timeframe=timeframe,
            bar_ts=bar_time,
            data={
                "signal_id": signal_id,
                "trailing_stop_price": {
                    "trailing_stop": cs.get("trailing_stop"),
                    "highest_high": cs.get("highest_high"),
                    "lowest_low": cs.get("lowest_low"),
                    "vol": cs.get("vol"),
                    "vol_source": cs.get("vol_source"),
                },
                "trailing_stop_tightening_rate": None,
                "staleness_score": None,
                "staleness_trigger_reason": None,
                "chandelier_vol_source": cs.get("vol_source"),
            },
        )
        await self._publish_transition(lt)

    async def _publish_mae_mfe_update(
        self,
        signal_id: str,
        symbol: str,
        timeframe: str,
        state: SignalState,
        bar_time: datetime,
    ) -> None:
        """Publish a MAE_MFE_UPDATE transition to Kafka for persistence.

        Payload fields verified against SignalLedgerRepository.batch_execute(
        "mae_mfe_update") — handler extracts signal_id, mae, mfe.
        Published when abs(mae|mfe) > 0.05 AND every 10th active bar (1-I / D-18).
        """
        lt = LifecycleTransition(
            transition_type=TransitionType.MAE_MFE_UPDATE,
            signal_id=signal_id,
            symbol=symbol,
            timeframe=timeframe,
            bar_ts=bar_time,
            data={
                "signal_id": signal_id,
                "mae": state.mae,
                "mfe": state.mfe,
            },
        )
        await self._publish_transition(lt)

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
        """One-time DB read at startup to load pending/active signals from signal_events.

        Queries signal_events + trade_frames directly (not signal_ledger, which
        returns NULL for all lifecycle fields — activated_at, trailing_stop_price,
        chandelier_vol_source, entry_zone_low/high, mae/mfe — per RESEARCH Pitfall 1).

        Window parameters and max-attempt count are APR-backed:
          feature.signal_tracker.bootstrap_pending_window_days  (default 7)
          feature.signal_tracker.bootstrap_active_window_days   (default 30)
          feature.signal_tracker.bootstrap_dedup_window_days    (default 3)
          feature.signal_tracker.bootstrap_max_attempts         (default 3)

        Bootstrap retries protect against transient DB connection failures at startup.
        We proceed with empty state after exhaustion to avoid blocking the service
        start. On exhaustion, publishes a bootstrap_failed health event for monitoring.

        sd_notify(READY=1) is called ONLY after this method returns.
        """
        db = DatabaseManager(self.settings.database_url)
        await db.initialize()
        repo = SignalEventsRepository(db)
        try:
            for attempt in range(self._bootstrap_max_attempts):
                rows = await repo.get_active_signals_for_bootstrap(
                    pending_window_days=self._bootstrap_pending_window_days,
                    active_window_days=self._bootstrap_active_window_days,
                )

                # If we got rows, load them and succeed
                if rows:
                    _regime_cache_collisions: dict[tuple, int] = {}
                    for row in rows:
                        raw = dict(row)
                        # signal_events.direction is text "long"/"short"; _load_signal
                        # expects int (1/-1). Convert before passing to _load_signal.
                        dir_raw = raw.get("direction")
                        if isinstance(dir_raw, str):
                            raw["direction"] = 1 if dir_raw == "long" else -1
                        # Bootstrap MAE/MFE from frame_details if present; live signals
                        # default to 0.0 which is correct (no prior tracking history).
                        raw.setdefault("mae", 0.0)
                        raw.setdefault("mfe", 0.0)
                        # market_entry_price maps to activation_price stored in frame_details;
                        # it is not a top-level column in the 3-table schema.
                        raw.setdefault("market_entry_price", None)
                        # asyncpg returns datetime objects for timestamptz — pass directly.
                        canonical = self._load_signal(raw)
                        if canonical is None:
                            continue

                        await self._bootstrap_apply_signal(canonical)

                        # Regime cache bootstrap (1-J / D-19): seed _regime_cache from
                        # fire-time regime data so the first live bars after restart are
                        # not regime-blind. Uses same dict shape as the live update site
                        # near _ingest_i7_payload (_regime_cache[(symbol, tf)] = {...}).
                        # This is a coarse fire-time approximation that self-corrects on
                        # the first live i7.signals message (which overwrites the entry).
                        # Last-writer-wins across multiple signals sharing a (symbol, tf).
                        symbol = canonical.get("symbol", "")
                        tf = canonical.get("timeframe", "")
                        hmm_at_fire = canonical.get("hmm_regime_at_fire")
                        garch_at_fire = canonical.get("garch_sigma_at_fire")
                        if symbol and tf and (hmm_at_fire is not None or garch_at_fire is not None):
                            cache_key = (symbol, tf)
                            if cache_key in self._regime_cache:
                                _regime_cache_collisions[cache_key] = (
                                    _regime_cache_collisions.get(cache_key, 1) + 1
                                )
                            self._regime_cache[cache_key] = {
                                "hmm_regime": hmm_at_fire,
                                "garch_sigma": garch_at_fire,
                            }

                    total = sum(len(v) for v in self._active_index.values())
                    self.logger.info(
                        "bootstrap_complete",
                        signals=total,
                        symbols=len(self._active_symbols),
                        regime_cache_entries=len(self._regime_cache),
                        regime_cache_collisions=sum(_regime_cache_collisions.values()),
                        attempt=attempt + 1,
                    )
                    return

                # No rows returned — check if signal_events is truly empty or transient failure
                count_row = await db.execute_query(
                    """
                    SELECT COUNT(*) AS count
                    FROM signal_events
                    WHERE status IN ('pending', 'active')
                      AND ts > NOW() - ($1::int * INTERVAL '1 day')
                    """,
                    self._bootstrap_dedup_window_days,
                )
                signal_count = count_row[0]["count"] if count_row else 0

                if signal_count == 0:
                    # signal_events truly empty — success, no retry needed
                    self.logger.info("bootstrap_complete_empty_ledger")
                    return

                # signal_events has rows but we got 0 — transient failure, retry with backoff
                if attempt < self._bootstrap_max_attempts - 1:
                    backoff = self._BOOTSTRAP_BACKOFF_SECONDS[attempt]
                    self.logger.warning(
                        "bootstrap_empty_retry",
                        attempt=attempt + 1,
                        max_attempts=self._bootstrap_max_attempts,
                        signal_count=signal_count,
                        backoff_seconds=backoff,
                    )
                    await asyncio.sleep(backoff)
                else:
                    # Exhausted retries — publish health event and proceed with empty state
                    self.logger.error(
                        "bootstrap_failed_exhausted",
                        signal_count=signal_count,
                        attempts=self._bootstrap_max_attempts,
                    )
                    await self._publish_bootstrap_failed_event(signal_count)

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
                "attempts": self._bootstrap_max_attempts,
                "reason": (
                    f"DB returned 0 rows after {self._bootstrap_max_attempts}"
                    " retry attempts with exponential backoff"
                ),
            },
        }

        try:
            await self._producer.publish(
                topic_health_events(self.env_name),
                key=message_key("signal_tracker_compute"),
                msg=payload,
            )
        except Exception as error:
            self.logger.error("bootstrap_failed_event_publish_error", error=str(error))


async def main() -> None:
    agent = SignalTracker()
    try:
        await agent.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
