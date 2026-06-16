"""SignalReplayAuditor — L9 periodic outcome recovery.

Phase 81 Plan 05. On a fast cycle, finds v1 signals with exit_at IS NULL
past their TTL window and replays them bar-by-bar against market_data_ohlcv
to compute outcomes that the live tracker missed (restart, edge cases, gaps).

Two-path safety contract:
  - Live tracker is fast and usually correct.
  - Replay catches everything the live tracker missed.
  - LifecycleWriter EXIT guard (WHERE exit_at IS NULL) ensures the
    second writer is always a safe no-op (first writer wins).

North-star metric: signal_replay_unresolved_gauge == 0.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

import _path_bootstrap  # noqa: F401 — project root on sys.path
import asyncpg

from src.core.agent.base import BaseDaemon
from src.core.database_manager import create_pool as create_db_pool
from src.core.kafka_utils import KafkaProducerClient
from src.core.service_utils import format_iso_ts
from src.core.stream_keys import TF_SECONDS, topic_lifecycle_transitions

# Reuse the live tracker's evaluators — never duplicate evaluation logic.
from src.intelligence.trading.lifecycle_tracker import (
    evaluate_market_entry,
    evaluate_signal,
)
from src.intelligence.trading.lifecycle_transitions import (
    LifecycleTransition,
    TransitionType,
    to_dict,
)
from src.observability.metrics import (
    SIGNAL_REPLAY_ATTEMPTED_TOTAL,
    SIGNAL_REPLAY_NULL_ZONE_TOTAL,
    SIGNAL_REPLAY_OHLCV_GAP_TOTAL,
    SIGNAL_REPLAY_RESOLVED_TOTAL,
    SIGNAL_REPLAY_UNRESOLVED_GAUGE,
)
from src.persistence.repository.signal_ledger_repository import SignalStatus


class SignalReplayAuditor(BaseDaemon):
    """L9 periodic: recovers outcome labels for v1 signals the live tracker missed."""

    agent_id = "signal_replay_auditor"

    def __init__(self) -> None:
        super().__init__(max_idle_seconds=600)
        self._producer: KafkaProducerClient | None = None
        self._pool: asyncpg.Pool | None = None
        self._last_unresolved_count: int = 0

    async def _setup(self) -> None:
        self._pool = await create_db_pool(
            self.settings.database_url,
            pool_name="signal_replay_auditor",
            min_size=1,
            max_size=3,
        )
        self._producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers
        )
        await self._producer.start()
        self.logger.info("signal_replay_auditor.started")

    async def _teardown(self) -> None:
        if self._producer:
            await self._producer.stop()
        if self._pool:
            await self._pool.close()

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    async def _fetch_unresolved(self) -> list[asyncpg.Record]:
        """Fetch a bounded batch of signals whose TTL has genuinely elapsed."""
        query = """
            SELECT sl.signal_id, sl.symbol, sl.timeframe, sl.timestamp, sl.direction,
                   sl.market_entry_price, sl.ttl_bars, sl.expires_at, sl.status, sl.activated_at,
                   sl.hmm_regime_at_fire, sl.garch_sigma_at_fire,
                   COALESCE(sl.entry_price::float, sl.activation_price) AS entry_price,
                   sl.stop_loss::float                                   AS stop_loss,
                   sl.targets                                            AS targets,
                   sl.entry_zone_low::float                             AS entry_zone_low,
                   sl.entry_zone_high::float                            AS entry_zone_high
            FROM signal_ledger sl
            WHERE sl.exit_at IS NULL
              AND sl.status IN ('pending', 'active')
              AND sl.expires_at IS NOT NULL
              AND sl.expires_at < NOW()
              AND sl.entry_zone_low IS NOT NULL
              AND sl.entry_zone_high IS NOT NULL
            ORDER BY sl.expires_at DESC
            LIMIT $1
        """
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            return await conn.fetch(query, self.settings.replay_batch_size)

    async def _fetch_window_bars(
        self, symbol: str, tf: str, start_ts: datetime, end_ts: datetime
    ) -> list[asyncpg.Record]:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            return await conn.fetch(
                """
                SELECT timestamp, open, high, low, close, volume
                FROM market_data_ohlcv
                WHERE symbol = $1 AND timeframe = $2
                  AND timestamp >= $3 AND timestamp <= $4
                ORDER BY timestamp ASC
                """,
                symbol,
                tf,
                start_ts,
                end_ts,
            )

    async def _count_unresolved(self) -> int:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            cnt = await conn.fetchval(
                """
                SELECT COUNT(*) FROM signal_ledger
                WHERE exit_at IS NULL
                  AND expires_at IS NOT NULL
                  AND expires_at < NOW()
                  AND entry_zone_low IS NOT NULL
                  AND entry_zone_high IS NOT NULL
                """,
            )
        return int(cnt or 0)

    # ------------------------------------------------------------------
    # Replay logic
    # ------------------------------------------------------------------

    async def _replay_signal(self, row: asyncpg.Record) -> bool:
        """Replay a single signal bar-by-bar. Returns True if resolved."""
        tf = row["timeframe"]
        tf_secs = TF_SECONDS.get(tf, 60)
        ttl = int(row["ttl_bars"] or 10)
        start_ts: datetime = row["timestamp"]
        end_ts = start_ts + timedelta(seconds=ttl * tf_secs)
        now_utc = datetime.now(UTC)

        # Skip if still within the live tracker's TTL window.
        if (now_utc - start_ts).total_seconds() <= ttl * tf_secs:
            return False

        bars = await self._fetch_window_bars(row["symbol"], tf, start_ts, end_ts)
        if not bars:
            SIGNAL_REPLAY_OHLCV_GAP_TOTAL.add(1, {"symbol": row["symbol"], "timeframe": tf})
            self.logger.warning(
                "replay_ohlcv_gap",
                signal_id=str(row["signal_id"]),
                symbol=row["symbol"],
                tf=tf,
            )
            return False

        signal_dict = self._build_signal_dict(row)
        if signal_dict is None:
            return False
        topic = topic_lifecycle_transitions(self.settings.env_name)
        assert self._producer is not None

        # Zone-entry track: synthesize a never_activated exit only for PENDING signals
        # that exhausted their TTL window without entering the zone. ACTIVE signals
        # that return None had bar gaps preventing TTL exit — skip them so a later
        # cycle can retry with better data.
        zone_transition = self._evaluate_zone_track(signal_dict, bars, start_ts)
        if zone_transition is None:
            if row["status"] != SignalStatus.PENDING:
                return False
            zone_transition = self._build_never_activated_transition(signal_dict, end_ts)

        await self._producer.publish(topic, msg=to_dict(zone_transition))
        outcome_str = zone_transition.data.get("outcome") or "unknown"
        SIGNAL_REPLAY_RESOLVED_TOTAL.add(1, {"outcome": outcome_str})
        self.logger.info(
            "replay_zone_resolved",
            signal_id=str(row["signal_id"]),
            outcome=outcome_str,
        )

        # Market-entry parallel track (if market_entry_price was recorded)
        market_entry_price = row["market_entry_price"]
        if market_entry_price is not None:
            market_transition = self._evaluate_market_track(
                signal_dict, bars, market_entry_price, start_ts
            )
            if market_transition is not None:
                # Market resolution is informational; only zone counts for north-star.
                await self._producer.publish(topic, msg=to_dict(market_transition))

        return True

    def _build_signal_dict(self, row: asyncpg.Record) -> dict[str, Any] | None:
        """Build a signal dict from DB record matching evaluate_signal's expected shape."""
        targets_raw = row["targets"]
        if isinstance(targets_raw, list):
            targets = [float(t) for t in targets_raw]
        else:
            targets = []

        zone_low = row["entry_zone_low"]
        zone_high = row["entry_zone_high"]
        if zone_low is None or zone_high is None:
            SIGNAL_REPLAY_NULL_ZONE_TOTAL.add(1, {"symbol": row["symbol"]})
            self.logger.warning(
                "replay_null_zone_skip",
                signal_id=str(row["signal_id"]),
                symbol=row["symbol"],
            )
            return None

        entry_price = float(row["entry_price"])
        return {
            "signal_id": str(row["signal_id"]),
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
            "status": row["status"] or SignalStatus.PENDING,
            "direction": {"long": 1, "short": -1}.get(row["direction"], int(row["direction"])),
            "entry_price": entry_price,
            "stop_loss": float(row["stop_loss"]),
            "targets": targets,
            "ttl_bars": int(row["ttl_bars"] or 10),
            "bars_elapsed": 0,  # reset for bar-by-bar replay
            "point_value": 1.0,  # replay assumes single-contract base; multi-contract not tracked here
            "entry_zone_low": float(zone_low),
            "entry_zone_high": float(zone_high),
            "activated_at": row["activated_at"],
            "hmm_regime_at_fire": row["hmm_regime_at_fire"],
            "garch_sigma_at_fire": row["garch_sigma_at_fire"],
            "expires_at": row["expires_at"],
            "setup_plugin": "replay",  # placeholder for metrics labels
        }

    def _evaluate_zone_track(
        self,
        signal_dict: dict[str, Any],
        bars: list[asyncpg.Record],
        signal_timestamp: datetime,
    ) -> LifecycleTransition | None:
        """Run evaluate_signal bar-by-bar; return EXIT LifecycleTransition or None."""

        state = dict(signal_dict)  # mutable copy
        current_mae = 0.0
        current_mfe = 0.0
        bars_elapsed = 0
        bars_in_trade = 0  # tracks bars since activation for stop outcome classification
        activated = False

        for bar in bars:
            state["bars_elapsed"] = bars_elapsed
            bar_ts: datetime = bar["timestamp"]

            transition = evaluate_signal(
                state,
                high=float(bar["high"]),
                low=float(bar["low"]),
                close=float(bar["close"]),
                current_mae=current_mae,
                current_mfe=current_mfe,
                signal_timestamp=signal_timestamp,
                bar_time=bar_ts,
            )

            if transition is None:
                # Update MAE/MFE for active signals so TTL outcomes are labeled correctly.
                # This must be in the transition=None branch (active signal, no exit this bar).
                if state.get("status") == SignalStatus.ACTIVE:
                    _entry = float(state["entry_price"])
                    _stop = float(state["stop_loss"])
                    _risk = abs(_entry - _stop)
                    if _risk > 0:
                        _pnl_r = (float(bar["close"]) - _entry) * state["direction"] / _risk
                        current_mae = min(current_mae, _pnl_r)
                        current_mfe = max(current_mfe, _pnl_r)
                    bars_in_trade += 1
                bars_elapsed += 1
                continue

            if transition.new_status == SignalStatus.ACTIVE:
                # Activation — update state and continue
                state["status"] = SignalStatus.ACTIVE
                activated = True
                if transition.activation_price is not None:
                    state["entry_price"] = transition.activation_price
                bars_elapsed += 1
                continue

            # Terminal transition — any exit_reason is terminal (mirrors live tracker logic).
            # Note: target hits use new_status="target_N_hit", NOT SignalStatus.EXPIRED,
            # so checking exit_reason (not new_status) is the correct gate.
            if transition.exit_reason is not None:
                # Populate bars_in_trade on the transition for stop outcome classification.
                if transition.bars_in_trade is None and activated:
                    transition.bars_in_trade = bars_in_trade
                return self._build_exit_transition(signal_dict, transition, bar_ts)

            bars_elapsed += 1

        return None

    def _build_never_activated_transition(
        self,
        signal_dict: dict[str, Any],
        end_ts: datetime,
    ) -> LifecycleTransition:
        """Build a never_activated TTL exit for a signal that never entered its zone."""
        return LifecycleTransition(
            transition_type=TransitionType.EXIT,
            signal_id=signal_dict["signal_id"],
            symbol=signal_dict.get("symbol", ""),
            timeframe=signal_dict.get("timeframe", ""),
            bar_ts=end_ts,
            data={
                "status": SignalStatus.EXPIRED,
                "exit_at": format_iso_ts(end_ts),
                "exit_price": None,
                "exit_reason": "ttl_expired",
                "pnl_r": 0.0,
                "pnl_dollars": None,
                "signal_quality": None,
                "mae": 0.0,
                "mfe": 0.0,
                "bars_in_trade": 0,
                "outcome": "never_activated",
            },
        )

    def _evaluate_market_track(
        self,
        signal_dict: dict[str, Any],
        bars: list[asyncpg.Record],
        market_entry_price: float,
        signal_timestamp: datetime,
    ) -> LifecycleTransition | None:
        """Run evaluate_market_entry bar-by-bar for the parallel market track."""
        state = dict(signal_dict)
        current_mae = 0.0
        current_mfe = 0.0
        bars_elapsed = 0
        bars_in_trade = 0

        for bar in bars:
            state["bars_elapsed"] = bars_elapsed
            bar_ts: datetime = bar["timestamp"]

            mt = evaluate_market_entry(
                state,
                market_entry_price=market_entry_price,
                high=float(bar["high"]),
                low=float(bar["low"]),
                close=float(bar["close"]),
                current_mae=current_mae,
                current_mfe=current_mfe,
            )

            if mt.outcome is None:
                # Still running — update excursions
                entry = market_entry_price
                risk = abs(entry - float(signal_dict["stop_loss"]))
                if risk > 0:
                    pnl_r = round(
                        (float(bar["close"]) - entry) * signal_dict["direction"] / risk, 4
                    )
                    current_mae = min(current_mae, pnl_r)
                    current_mfe = max(current_mfe, pnl_r)
                bars_elapsed += 1
                bars_in_trade += 1
                continue

            # Terminal outcome (mt.outcome is non-None here — None case continues above)
            outcome = mt.outcome.value if hasattr(mt.outcome, "value") else str(mt.outcome)

            lt = LifecycleTransition(
                transition_type=TransitionType.MARKET_RESOLUTION,
                signal_id=signal_dict["signal_id"],
                symbol=signal_dict.get("symbol", ""),
                timeframe=signal_dict.get("timeframe", ""),
                bar_ts=bar_ts,
                data={
                    "market_entry_at": (
                        format_iso_ts(signal_timestamp) if signal_timestamp else None
                    ),
                    "market_entry_exit_price": mt.exit_price,
                    "market_entry_exit_at": format_iso_ts(bar_ts),
                    "market_entry_pnl_r": mt.pnl_r,
                    "market_entry_mae": mt.mae,
                    "market_entry_mfe": mt.mfe,
                    "market_entry_bars_in_trade": bars_in_trade,
                    "market_entry_outcome": outcome,
                    "market_entry_gap_bars": None,
                },
            )
            return lt

        return None

    def _build_exit_transition(
        self,
        signal_dict: dict[str, Any],
        t: Any,
        bar_ts: datetime,
    ) -> LifecycleTransition:
        """Build an EXIT LifecycleTransition from a Transition object."""
        if t.outcome is not None:
            outcome = t.outcome.value if hasattr(t.outcome, "value") else str(t.outcome)
        elif t.exit_reason == "stop_loss":
            # Stop outcome requires bars_in_trade context — classify from mfe.
            # bars_in_trade is unavailable in replay (not tracked), so we use
            # a conservative heuristic: if mfe > 0.05, classify as stopped_in_trade.
            from src.intelligence.trading.lifecycle_tracker import _classify_stop_outcome

            stop_outcome = _classify_stop_outcome(
                current_mfe=float(t.mfe or 0.0),
                bars_in_trade_count=t.bars_in_trade,
            )
            outcome = stop_outcome.value if hasattr(stop_outcome, "value") else str(stop_outcome)
        else:
            outcome = None
        return LifecycleTransition(
            transition_type=TransitionType.EXIT,
            signal_id=signal_dict["signal_id"],
            symbol=signal_dict.get("symbol", ""),
            timeframe=signal_dict.get("timeframe", ""),
            bar_ts=bar_ts,
            data={
                "status": (
                    t.new_status.value if hasattr(t.new_status, "value") else str(t.new_status)
                ),
                "exit_at": format_iso_ts(bar_ts),
                "exit_price": t.exit_price,
                "exit_reason": t.exit_reason,
                "pnl_r": t.pnl_r,
                "pnl_dollars": t.pnl_dollars,
                "signal_quality": None,
                "mae": t.mae,
                "mfe": t.mfe,
                "bars_in_trade": t.bars_in_trade,
                "outcome": outcome,
            },
        )

    # ------------------------------------------------------------------
    # Cycle / run loop
    # ------------------------------------------------------------------

    async def _cycle(self) -> None:
        rows = await self._fetch_unresolved()
        total = len(rows)
        SIGNAL_REPLAY_ATTEMPTED_TOTAL.add(total)
        self.logger.info("replay_cycle_start", total_candidates=total)

        for row in rows:
            if self._stop_event.is_set():
                return
            tf_secs = TF_SECONDS.get(row["timeframe"], 60)
            ttl = int(row["ttl_bars"] or 10)
            elapsed = (datetime.now(UTC) - row["timestamp"]).total_seconds()
            if elapsed <= ttl * tf_secs:
                # Still live — skip; let live tracker handle it
                continue
            try:
                await self._replay_signal(row)
            except Exception as error:
                self.logger.exception(
                    "replay_signal_failed",
                    signal_id=str(row["signal_id"]),
                    error=str(error),
                )

        # Refresh north-star gauge after batch (writes are async, slight lag ok)
        cnt = await self._count_unresolved()
        delta = cnt - self._last_unresolved_count
        SIGNAL_REPLAY_UNRESOLVED_GAUGE.add(float(delta))
        self._last_unresolved_count = cnt
        self.logger.info("replay_cycle_complete", unresolved_gauge=cnt)

    async def _run(self) -> None:
        while self.running:
            try:
                await self._cycle()
            except Exception as error:
                self.logger.exception("replay_cycle_failed", error=str(error))
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.settings.replay_interval_seconds
                )
            except TimeoutError:
                pass  # Normal — wake up for next cycle

    async def main(self) -> int:
        await self.start()
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(SignalReplayAuditor().main()))
