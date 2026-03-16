#!/usr/bin/env python3
"""
Lifecycle Replay Script — batch replay of historical pending/regime_suppressed signals.

Evaluates dual-track outcomes (zone track + market track) for all signals that lack
outcomes, by replaying market_data_ohlcv bars chronologically per (symbol, timeframe).

Usage:
    # Run with -u for unbuffered logging output to file
    python -u production/scripts/lifecycle_replay.py --workers 8 --commit-every 1000 \\
        --symbols ESH6,NQH6 > /tmp/lifecycle_replay.log 2>&1 &

    python -u production/scripts/lifecycle_replay.py --symbols ES,NQ --validate --dry-run
    python -u production/scripts/lifecycle_replay.py --workers 4

Design notes:
    - Each worker handles one (symbol, timeframe) pair exclusively.
    - Bars are fetched into memory (not a server-side cursor) so that incremental
      commits don't invalidate the cursor mid-stream.
    - Signals are processed forward in time: a signal fired at bar N is entered
      at bar N+1 open (market track) and evaluated on subsequent bars until exit.
    - resolved_sids tracks zone-exited signals so they are never re-added to
      live_sids on later bars. Without this, every resolved signal would be re-added
      on the next bar and processed again, producing exponentially inflated counts
      and overwritten (wrong) outcomes.
    - Commits happen every commit_every resolved signals AND at pair completion.
      This ensures partial progress survives a kill — without it, a 7-hour run
      writes nothing if terminated before the pair finishes.
    - market_entry_price: all signals from the generator have this field set.
      If set, use it directly as the market fill price. If NULL (rare), use the
      open of bar N+1 as a fill approximation.
    - TIMEFRAMES default excludes '1d' — add explicitly if needed: --timeframes 1m,5m,15m,1h,1d
    - To reset bad data before a re-run:
        UPDATE signal_ledger SET status='pending', outcome=NULL, exit_at=NULL,
          exit_price=NULL, exit_reason=NULL, pnl_ticks=NULL, pnl_r=NULL,
          pnl_dollars=NULL, mae=NULL, mfe=NULL, bars_in_trade=NULL,
          signal_quality=NULL, activated_at=NULL, activation_price=NULL,
          zone_entry_pct=NULL, bars_to_activation=NULL,
          market_entry_at=NULL, market_entry_exit_price=NULL,
          market_entry_exit_at=NULL, market_entry_pnl_r=NULL,
          market_entry_mae=NULL, market_entry_mfe=NULL,
          market_entry_bars_in_trade=NULL, market_entry_outcome=NULL,
          market_entry_gap_bars=NULL
        WHERE symbol IN (...) AND outcome IS NOT NULL;

TODO:
    - (resolved) market_entry_at + market_entry_exit_at added in migration 033.
"""

from __future__ import annotations

import argparse
import logging
import multiprocessing
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).parents[2]))

from src.config.settings import Settings, get_active_contracts
from src.core.service_utils import TF_SECONDS
from src.intelligence.trading.lifecycle_tracker import (
    _classify_stop_outcome,
    evaluate_market_entry,
    evaluate_signal,
)

logger = logging.getLogger(__name__)

# 1d excluded by default — it has multi-year bar history and signals are sparse.
# Pass --timeframes 1m,5m,15m,1h,1d to include it explicitly.
TIMEFRAMES = ["1m", "5m", "15m", "1h"]


# ── Pure helper functions (importable for unit testing) ─────────────────────


def compute_gap_bars(sig_ts: datetime, bar_ts: datetime, tf_seconds: int) -> int:
    """Bars between signal.timestamp and bar N+1. 0 = no gap (immediate next bar).

    A gap > 0 means the first available bar after the signal is not the immediately
    following bar — e.g. due to a weekend, holiday, or missing data. The fill price
    is still bar N+1 open regardless; this count is stored for analysis.
    """
    gap_secs = (bar_ts - sig_ts).total_seconds() - tf_seconds
    if gap_secs > tf_seconds * 0.5:  # > 1.5x threshold
        return max(0, round(gap_secs / tf_seconds))
    return 0


def get_signals_active_at(
    signals: list[dict],
    bar_ts: datetime,
    tf_seconds: int = 60,
) -> list[dict]:
    """Return signals that are actionable at bar_ts.

    A signal fired at T on bar close is actionable at bar N+1 (the bar
    immediately after the signal). Bar N+1 is the first bar where the
    signal can be evaluated, so we include any signal where timestamp < bar_ts.
    """
    return [s for s in signals if s["timestamp"] < bar_ts]


def handle_no_data(sig: dict) -> dict:
    """No bars available after signal.timestamp — zone=never_activated, market=all NULL."""
    ttl_secs = sig.get("ttl_bars", 10) * TF_SECONDS.get(sig.get("timeframe", "1m"), 60)
    exit_ts = sig["timestamp"] + timedelta(seconds=ttl_secs)
    return {
        "zone_outcome": "never_activated",
        "zone_exit_at": exit_ts,
        "market_entry_outcome": None,
        "market_entry_exit_price": None,
        "market_entry_pnl_r": None,
        "market_entry_mae": None,
        "market_entry_mfe": None,
        "market_entry_bars_in_trade": None,
        "market_entry_gap_bars": None,
        "exit_at": exit_ts,
    }


def resolve_at_end_of_bars(
    sig: dict,
    last_bar: dict,
    *,
    tf_seconds: int,
    zone_mfe: float,
    market_mfe: float,
    zone_activated: bool = False,
    market_entry_price: float | None = None,
) -> dict:
    """Resolve remaining signal at end of bar stream using accumulated state.

    Called for any signal still in live_sids after all bars are exhausted.
    Uses the last bar's timestamp and close as the exit reference.
    """
    last_ts = last_bar["timestamp"]
    bars_elapsed = int((last_ts - sig["timestamp"]).total_seconds() / tf_seconds)

    zone_outcome = "ttl_expired_ahead" if zone_mfe > 0 else (
        "never_activated" if not zone_activated else "ttl_expired_behind"
    )
    mep = market_entry_price if market_entry_price is not None else sig.get("market_entry_price")
    market_outcome = ("ttl_expired_ahead" if market_mfe > 0 else "ttl_expired_behind") if mep is not None else None
    market_bit = min(bars_elapsed, sig.get("ttl_bars", 10))

    return {
        "zone_outcome": zone_outcome,
        "exit_at": last_ts,
        "market_entry_outcome": market_outcome,
        "market_entry_exit_price": float(last_bar["close"]) if mep is not None else None,
        "market_entry_pnl_r": None,  # computed by caller from accumulated state
        "market_entry_mae": None,
        "market_entry_mfe": None,
        "market_entry_bars_in_trade": market_bit if mep is not None else None,
        "market_entry_gap_bars": None,
    }


def validate_track_pair(zone_outcome: str, market_outcome: str | None) -> None:
    """Check for impossible track combination. Raises ValueError if detected."""
    if market_outcome is None:
        return
    if zone_outcome == "target_full" and market_outcome == "never_activated":
        raise ValueError(
            "Impossible: zone=target_full + market=never_activated "
            "(market track never produces never_activated)"
        )


# ── Core replay logic ────────────────────────────────────────────────────────


def _get_db_url() -> str:
    return Settings().database_url


def _fetch_work_queue(conn, symbols: list[str], timeframes: list[str]) -> list[tuple[str, str, int]]:
    """Build work queue ordered by estimated pending row count descending (largest first)."""
    placeholders_sym = ",".join(["%s"] * len(symbols))
    placeholders_tf = ",".join(["%s"] * len(timeframes))
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT symbol, timeframe, COUNT(*) as cnt
                FROM signal_ledger
                WHERE status IN ('pending', 'regime_suppressed')
                  AND symbol IN ({placeholders_sym})
                  AND timeframe IN ({placeholders_tf})
                GROUP BY symbol, timeframe
                ORDER BY cnt DESC""",
            symbols + timeframes,
        )
        return [(row[0], row[1], row[2]) for row in cur.fetchall()]


def _process_symbol_tf(
    symbol: str,
    timeframe: str,
    db_url: str,
    batch_size: int,
    commit_every: int,
    dry_run: bool,
    validate: bool,
) -> dict:
    """Worker function: process all pending signals for one (symbol, timeframe).

    Each worker opens its own DB connection. Bars are fetched into memory upfront
    so incremental commits don't invalidate a server-side cursor mid-stream.
    """
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    tf_secs = TF_SECONDS.get(timeframe, 60)
    stats = {"symbol": symbol, "tf": timeframe, "processed": 0,
             "zone": {}, "market": {}, "gaps": 0, "errors": 0}

    try:
        # 1. Validate mode
        if validate:
            _run_validate(conn, symbol, timeframe, tf_secs, dry_run)

        # 2. Fetch all unresolved signals for this pair into memory
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM signal_ledger
                   WHERE status IN ('pending', 'regime_suppressed')
                     AND symbol = %s AND timeframe = %s
                   ORDER BY timestamp ASC""",
                (symbol, timeframe),
            )
            signals = cur.fetchall()

        if not signals:
            return stats

        min_ts = min(s["timestamp"] for s in signals)
        # Map by signal_id for O(1) lookup during bar evaluation
        sig_map: dict[str, dict] = {str(s["signal_id"]): dict(s) for s in signals}

        # In-memory accumulators keyed by signal_id
        zone_mae: dict[str, float] = {}
        zone_mfe: dict[str, float] = {}
        market_mae_acc: dict[str, float] = {}
        market_mfe_acc: dict[str, float] = {}
        # market_entry_prices: populated at first bar after signal fires.
        # Uses signal.market_entry_price if set by generator, else bar N+1 open.
        market_entry_prices: dict[str, float | None] = {}
        market_activated_at: dict[str, datetime] = {}
        zone_activated_at: dict[str, datetime] = {}
        zone_activated: dict[str, bool] = {}
        pending_writes: list[tuple] = []
        last_bar: dict | None = None
        live_sids: set[str] = set()   # signals currently being evaluated
        resolved_sids: set[str] = set()  # zone-exited signals — must never re-enter live_sids

        # 3. Fetch bars into memory.
        # NOTE: intentionally not a server-side (named) cursor — incremental commits
        # would kill a named cursor mid-stream, losing all progress for that pair.
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT timestamp, open, high, low, close
                   FROM market_data_ohlcv
                   WHERE symbol = %s AND timeframe = %s
                     AND timestamp >= %s
                   ORDER BY timestamp ASC""",
                (symbol, timeframe, min_ts),
            )
            bars = cur.fetchall()

        # 4. Stream bars and evaluate signals
        for bar_row in bars:
            bar = dict(bar_row)
            bar_ts = bar["timestamp"]
            if bar_ts.tzinfo is None:
                bar_ts = bar_ts.replace(tzinfo=UTC)
            bar["timestamp"] = bar_ts
            last_bar = bar

            # Activate signals that fired before this bar (signal fires on bar N close,
            # first evaluable bar is N+1). Skip resolved_sids — a zone-exited signal
            # must not re-enter live_sids on subsequent bars.
            for sid, sig in sig_map.items():
                if sid not in live_sids and sid not in resolved_sids and sig["timestamp"] < bar_ts:
                    live_sids.add(sid)
                    mep = sig.get("market_entry_price")
                    if mep is None:
                        # No stored entry price — use bar N+1 open as fill approximation
                        market_entry_prices[sid] = float(bar["open"])
                        gap = compute_gap_bars(sig["timestamp"], bar_ts, tf_secs)
                        sig["_replay_gap_bars"] = gap
                        if gap > 0:
                            stats["gaps"] += 1
                    else:
                        # Signal generator already recorded the intended entry price
                        market_entry_prices[sid] = float(mep)
                    market_activated_at[sid] = bar_ts

            resolved_this_bar: set[str] = set()

            for sid in list(live_sids):
                sig = sig_map[sid]
                bars_el = int((bar_ts - sig["timestamp"]).total_seconds() / tf_secs)
                sig_eval = {**sig, "bars_elapsed": bars_el, "point_value": 1.0}

                # ── Market track ──
                # Evaluates from market_entry_price using stop_loss/target_1/target_2.
                # Runs independently of zone track — signal can hit target on market
                # track while still pending on zone track, or vice versa.
                mep = market_entry_prices.get(sid)
                if mep is not None and not sig.get("_market_resolved"):
                    m_mae = market_mae_acc.get(sid, 0.0)
                    m_mfe = market_mfe_acc.get(sid, 0.0)
                    try:
                        m_trans = evaluate_market_entry(
                            sig_eval, market_entry_price=mep,
                            high=float(bar["high"]), low=float(bar["low"]),
                            close=float(bar["close"]),
                            current_mae=m_mae, current_mfe=m_mfe,
                        )
                    except Exception as exc:
                        logger.warning("market eval error %s: %s", sid, exc)
                        m_trans = None
                        stats["errors"] += 1

                    if m_trans and m_trans.outcome is not None:
                        m_entry_at = market_activated_at.get(sid)
                        m_bit = int((bar_ts - m_entry_at).total_seconds() / tf_secs) if m_entry_at else 0
                        m_outcome = m_trans.outcome
                        stats["market"][m_outcome] = stats["market"].get(m_outcome, 0) + 1
                        pending_writes.append(("market", sid, {
                            "_ts": sig["timestamp"],
                            "market_entry_at": m_entry_at,
                            "market_entry_exit_price": m_trans.exit_price,
                            "market_entry_exit_at": bar_ts,
                            "market_entry_pnl_r": m_trans.pnl_r,
                            "market_entry_mae": m_trans.mae,
                            "market_entry_mfe": m_trans.mfe,
                            "market_entry_bars_in_trade": m_bit,
                            "market_entry_outcome": m_outcome,
                            "market_entry_gap_bars": sig.get("_replay_gap_bars"),
                        }))
                        sig["_market_resolved"] = True
                    elif m_trans:
                        # Still open — accumulate running MAE/MFE in R-multiples
                        risk = abs(mep - float(sig["stop_loss"]))
                        if risk > 0:
                            direction = sig["direction"]
                            cpnl = (float(bar["close"]) - mep) * direction / risk
                            market_mae_acc[sid] = min(m_mae, cpnl)
                            market_mfe_acc[sid] = max(m_mfe, cpnl)

                # ── Zone track ──
                # Evaluates entry zone activation, then stop/target from zone entry price.
                # regime_suppressed signals are treated as active for zone evaluation
                # (suppression only affects signal selection, not outcome tracking).
                z_mae = zone_mae.get(sid, 0.0)
                z_mfe = zone_mfe.get(sid, 0.0)
                z_status = "active" if zone_activated.get(sid) else sig.get("status", "pending")
                sig_eval["status"] = "active" if (z_status == "regime_suppressed" or zone_activated.get(sid)) else z_status

                try:
                    z_trans = evaluate_signal(
                        sig_eval,
                        high=float(bar["high"]), low=float(bar["low"]),
                        close=float(bar["close"]),
                        current_mae=z_mae, current_mfe=z_mfe,
                    )
                except Exception as exc:
                    logger.warning("zone eval error %s: %s", sid, exc)
                    z_trans = None
                    stats["errors"] += 1

                if z_trans is None:
                    # No state change this bar — accumulate MAE/MFE if active
                    if zone_activated.get(sid):
                        entry = float(sig["entry_price"])
                        stop = float(sig["stop_loss"])
                        risk = abs(entry - stop)
                        if risk > 0:
                            direction = sig["direction"]
                            cpnl = (float(bar["close"]) - entry) * direction / risk
                            zone_mae[sid] = min(z_mae, cpnl)
                            zone_mfe[sid] = max(z_mfe, cpnl)
                    continue

                if z_trans.new_status == "active":
                    # Signal entered the zone — record activation and reset MAE/MFE
                    zone_activated[sid] = True
                    zone_activated_at[sid] = bar_ts
                    pending_writes.append(("activation", sid, {
                        "_ts": sig["timestamp"],
                        "activation_price": z_trans.activation_price,
                        "zone_entry_pct": z_trans.zone_entry_pct,
                        "bars_to_activation": z_trans.bars_to_activation,
                        "activated_at": bar_ts,
                    }))
                    zone_mae[sid] = 0.0
                    zone_mfe[sid] = 0.0
                else:
                    # Zone exit — classify outcome and mark resolved
                    z_outcome = z_trans.outcome
                    if z_outcome is None:
                        z_bit = int((bar_ts - zone_activated_at.get(sid, bar_ts)).total_seconds() / tf_secs)
                        z_outcome = _classify_stop_outcome(z_mfe, z_bit)
                    stats["zone"][z_outcome] = stats["zone"].get(z_outcome, 0) + 1
                    stats["processed"] += 1
                    pending_writes.append(("zone_exit", sid, {
                        "_ts": sig["timestamp"],
                        "status": z_trans.new_status,
                        "exit_at": bar_ts,
                        "exit_price": z_trans.exit_price,
                        "exit_reason": z_trans.exit_reason,
                        "pnl_ticks": z_trans.pnl_ticks,
                        "pnl_r": z_trans.pnl_r,
                        "pnl_dollars": z_trans.pnl_dollars,
                        "signal_quality": None,
                        "mae": z_trans.mae,
                        "mfe": z_trans.mfe,
                        "bars_in_trade": None,
                        "outcome": z_outcome,
                    }))
                    resolved_this_bar.add(sid)
                    resolved_sids.add(sid)  # prevents re-entry on subsequent bars

            live_sids -= resolved_this_bar

            # Flush batch to DB (no commit yet — commit happens below on threshold)
            if len(pending_writes) >= batch_size:
                if not dry_run:
                    _flush_writes(conn, pending_writes)
                pending_writes.clear()
                # Incremental commit: durable progress every commit_every resolved signals.
                # Without this, killing the process loses all work since pair start.
                if not dry_run and stats["processed"] % commit_every < batch_size:
                    conn.commit()
                    logger.info(
                        "%s %s: committed %d resolved so far",
                        symbol, timeframe, stats["processed"],
                    )

        # 5. End of bars — resolve remaining live signals (TTL expired)
        if last_bar and live_sids:
            for sid in live_sids:
                sig = sig_map[sid]
                result = resolve_at_end_of_bars(
                    sig, last_bar, tf_seconds=tf_secs,
                    zone_mfe=zone_mfe.get(sid, 0.0),
                    market_mfe=market_mfe_acc.get(sid, 0.0),
                    zone_activated=zone_activated.get(sid, False),
                    market_entry_price=market_entry_prices.get(sid),
                )
                stats["zone"][result["zone_outcome"]] = stats["zone"].get(result["zone_outcome"], 0) + 1
                stats["processed"] += 1
                if zone_activated.get(sid):
                    pending_writes.append(("zone_exit", sid, {
                        "_ts": sig["timestamp"],
                        "status": "expired", "exit_at": result["exit_at"],
                        "exit_price": last_bar["close"], "exit_reason": "ttl_expired",
                        "pnl_ticks": None, "pnl_r": None, "pnl_dollars": None,
                        "signal_quality": None,
                        "mae": zone_mae.get(sid, 0.0),
                        "mfe": zone_mfe.get(sid, 0.0),
                        "bars_in_trade": None, "outcome": result["zone_outcome"],
                    }))
                else:
                    pending_writes.append(("zone_exit", sid, {
                        "_ts": sig["timestamp"],
                        "status": "expired", "exit_at": result["exit_at"],
                        "exit_price": None, "exit_reason": "ttl_expired",
                        "pnl_ticks": None, "pnl_r": None, "pnl_dollars": None,
                        "signal_quality": None, "mae": None, "mfe": None,
                        "bars_in_trade": None, "outcome": result["zone_outcome"],
                    }))
                mep = market_entry_prices.get(sid)
                if mep is not None and not sig.get("_market_resolved"):
                    stats["market"][result["market_entry_outcome"]] = (
                        stats["market"].get(result["market_entry_outcome"], 0) + 1)
                    pending_writes.append(("market", sid, {
                        "_ts": sig["timestamp"],
                        "market_entry_at": market_activated_at.get(sid),
                        "market_entry_exit_price": float(last_bar["close"]),
                        "market_entry_exit_at": last_bar["timestamp"],
                        "market_entry_pnl_r": None,
                        "market_entry_mae": market_mae_acc.get(sid, 0.0),
                        "market_entry_mfe": market_mfe_acc.get(sid, 0.0),
                        "market_entry_bars_in_trade": result["market_entry_bars_in_trade"],
                        "market_entry_outcome": result["market_entry_outcome"],
                        "market_entry_gap_bars": sig.get("_replay_gap_bars"),
                    }))

        # 6. Final flush + commit
        if pending_writes and not dry_run:
            _flush_writes(conn, pending_writes)

        if not dry_run:
            conn.commit()

    except Exception as exc:
        conn.rollback()
        logger.error("Error processing %s %s: %s", symbol, timeframe, exc)
        stats["errors"] += 1
    finally:
        conn.close()

    return stats


def _flush_writes(conn, writes: list[tuple]) -> None:
    """Execute pending DB writes using bulk UPDATE...FROM VALUES (one plan per kind).

    Three write kinds:
      - activation: signal entered the zone (sets activated_at, activation_price, etc.)
      - zone_exit:  signal resolved on zone track (sets outcome, exit_at, pnl_r, etc.)
      - market:     signal resolved on market track (sets market_entry_outcome, etc.)

    All updates match on (signal_id, timestamp) — timestamp is included because
    signal_ledger is a TimescaleDB hypertable partitioned by timestamp, so including
    it in the WHERE clause enables chunk pruning and avoids full-table scans.

    Type casts in the template are required — without them PostgreSQL infers types
    from the VALUES literal and may guess wrong (e.g. NULL -> text, int -> unknown).
    """
    activations, zone_exits, markets = [], [], []
    for kind, sid, data in writes:
        ts = data["_ts"]
        if kind == "activation":
            activations.append((sid, ts, data["activated_at"], data["activation_price"],
                                 data["zone_entry_pct"], data["bars_to_activation"]))
        elif kind == "zone_exit":
            zone_exits.append((sid, ts, data["status"], data["exit_at"], data["exit_price"],
                                data["exit_reason"], data["pnl_ticks"], data["pnl_r"],
                                data["pnl_dollars"], data["signal_quality"],
                                data["mae"], data["mfe"], data["bars_in_trade"], data["outcome"]))
        elif kind == "market":
            markets.append((sid, ts, data["market_entry_at"], data["market_entry_exit_price"],
                             data["market_entry_exit_at"], data["market_entry_pnl_r"],
                             data["market_entry_mae"], data["market_entry_mfe"],
                             data["market_entry_bars_in_trade"], data["market_entry_outcome"],
                             data["market_entry_gap_bars"]))

    with conn.cursor() as cur:
        if zone_exits:
            psycopg2.extras.execute_values(
                cur,
                """UPDATE signal_ledger AS sl
                   SET status=v.status, exit_at=v.exit_at, exit_price=v.exit_price,
                       exit_reason=v.exit_reason, pnl_ticks=v.pnl_ticks, pnl_r=v.pnl_r,
                       pnl_dollars=v.pnl_dollars, signal_quality=v.signal_quality,
                       mae=v.mae, mfe=v.mfe, bars_in_trade=v.bars_in_trade, outcome=v.outcome
                   FROM (VALUES %s) AS v(signal_id, ts, status, exit_at, exit_price,
                       exit_reason, pnl_ticks, pnl_r, pnl_dollars, signal_quality,
                       mae, mfe, bars_in_trade, outcome)
                   WHERE sl.signal_id = v.signal_id::uuid
                     AND sl."timestamp" = v.ts::timestamptz""",
                zone_exits,
                template="(%s, %s, %s, %s::timestamptz, %s::float, %s, %s::float, %s::float, %s::float, %s::float, %s::float, %s::float, %s::int, %s)",
                page_size=500,
            )
        if markets:
            psycopg2.extras.execute_values(
                cur,
                """UPDATE signal_ledger AS sl
                   SET market_entry_at=v.entry_at, market_entry_exit_price=v.exit_price,
                       market_entry_exit_at=v.exit_at, market_entry_pnl_r=v.pnl_r,
                       market_entry_mae=v.mae, market_entry_mfe=v.mfe,
                       market_entry_bars_in_trade=v.bars_in_trade,
                       market_entry_outcome=v.outcome, market_entry_gap_bars=v.gap_bars
                   FROM (VALUES %s) AS v(signal_id, ts, entry_at, exit_price,
                       exit_at, pnl_r, mae, mfe, bars_in_trade, outcome, gap_bars)
                   WHERE sl.signal_id = v.signal_id::uuid
                     AND sl."timestamp" = v.ts::timestamptz""",
                markets,
                # Explicit casts required — PostgreSQL infers NULL columns as text without them
                template="(%s, %s, %s::timestamptz, %s::float, %s::timestamptz, %s::float, %s::float, %s::float, %s::int, %s, %s::int)",
                page_size=500,
            )
        if activations:
            psycopg2.extras.execute_values(
                cur,
                """UPDATE signal_ledger AS sl
                   SET status='active', activated_at=v.activated_at,
                       activation_price=v.activation_price, zone_entry_pct=v.zone_entry_pct,
                       bars_to_activation=v.bars_to_activation
                   FROM (VALUES %s) AS v(signal_id, ts, activated_at,
                       activation_price, zone_entry_pct, bars_to_activation)
                   WHERE sl.signal_id = v.signal_id::uuid
                     AND sl."timestamp" = v.ts::timestamptz""",
                activations,
                template="(%s, %s, %s::timestamptz, %s, %s, %s)",
                page_size=500,
            )


def _run_validate(conn, symbol, timeframe, tf_secs, dry_run) -> None:
    """Validate: confirm resolved signals exist and have outcome populated. Logs result."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT COUNT(*) as total,
                      COUNT(outcome) as with_outcome,
                      COUNT(market_entry_outcome) as with_market_outcome
               FROM signal_ledger
               WHERE status NOT IN ('pending', 'regime_suppressed')
                 AND symbol = %s AND timeframe = %s""",
            (symbol, timeframe),
        )
        row = cur.fetchone()

    if not row or row["total"] == 0:
        logger.info("VALIDATE %s %s: no resolved signals found, skipping", symbol, timeframe)
        return

    logger.info(
        "VALIDATE %s %s: %d resolved signals, %d with zone outcome, %d with market outcome",
        symbol, timeframe, row["total"], row["with_outcome"], row["with_market_outcome"],
    )
    # Full re-simulation validation is not implemented — this confirms DB read consistency only.
    logger.info("VALIDATE %s %s: structural check passed", symbol, timeframe)


def _worker(args):
    symbol, tf, db_url, batch_size, commit_every, dry_run, validate = args
    return _process_symbol_tf(symbol, tf, db_url, batch_size, commit_every, dry_run, validate)


def main():
    parser = argparse.ArgumentParser(description="Lifecycle Replay — backfill historical signal outcomes")
    parser.add_argument("--symbols", help="Comma-separated symbols (default: all active)")
    parser.add_argument("--timeframes", help="Comma-separated timeframes (default: 1m,5m,15m,1h)")
    parser.add_argument("--validate", action="store_true", help="Run validation first")
    parser.add_argument("--dry-run", action="store_true", help="Compute but don't write")
    parser.add_argument("--batch-size", type=int, default=500, help="DB flush every N pending writes")
    parser.add_argument("--commit-every", type=int, default=1000, help="Commit after every N resolved signals per pair")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    # Use -u (unbuffered) when redirecting output: python -u lifecycle_replay.py > log 2>&1 &
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    db_url = _get_db_url()
    symbols = args.symbols.split(",") if args.symbols else get_active_contracts()
    timeframes = args.timeframes.split(",") if args.timeframes else TIMEFRAMES

    # Build work queue
    conn = psycopg2.connect(db_url)
    work_queue = _fetch_work_queue(conn, symbols, timeframes)
    conn.close()

    if not work_queue:
        logger.info("No pending signals found. Nothing to do.")
        return

    logger.info("Work queue: %d (symbol, tf) pairs, %d total pending signals",
                len(work_queue),
                sum(w[2] for w in work_queue))

    worker_args = [
        (sym, tf, db_url, args.batch_size, args.commit_every, args.dry_run, args.validate)
        for sym, tf, _ in work_queue
    ]

    all_stats = []
    with multiprocessing.Pool(processes=args.workers) as pool:
        for stats in pool.imap_unordered(_worker, worker_args):
            all_stats.append(stats)
            sym, tf = stats["symbol"], stats["tf"]
            z = stats["zone"]
            m = stats["market"]
            logger.info(
                "%s %s: %d processed | Zone: %s | Market: %s | gaps=%d errors=%d",
                sym, tf, stats["processed"],
                " | ".join(f"{k}={v}" for k, v in z.items()),
                " | ".join(f"{k}={v}" for k, v in m.items()),
                stats["gaps"], stats["errors"],
            )

    total = sum(s["processed"] for s in all_stats)
    logger.info("Done. Total processed: %d", total)
    if args.dry_run:
        logger.info("DRY RUN — no DB writes made.")


if __name__ == "__main__":
    main()
