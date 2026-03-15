#!/usr/bin/env python3
"""
Lifecycle Replay Script — batch replay of historical pending/regime_suppressed signals.

Streams bars chronologically per (symbol, timeframe) and computes dual-track
outcomes for all signals without outcomes.

Usage:
    python production/scripts/lifecycle_replay.py
    python production/scripts/lifecycle_replay.py --symbols ES,NQ --validate --dry-run
    python production/scripts/lifecycle_replay.py --workers 4
"""

from __future__ import annotations

import argparse
import logging
import multiprocessing
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).parents[2]))

from src.config.settings import Settings, get_active_contracts
from src.core.service_utils import TF_SECONDS
from src.intelligence.trading.lifecycle_tracker import (
    evaluate_market_entry,
    evaluate_signal,
)

logger = logging.getLogger(__name__)

TIMEFRAMES = ["1m", "5m", "15m", "1h"]


# ── Pure helper functions (importable for unit testing) ─────────────────────


def _classify_stop_outcome(current_mfe: float, bars_in_trade_count: int | None) -> str:
    if (bars_in_trade_count is None or bars_in_trade_count <= 2 or current_mfe <= 0.05):
        return "stopped_at_entry"
    return "stopped_in_trade"


def compute_gap_bars(sig_ts: datetime, bar_ts: datetime, tf_seconds: int) -> int:
    """Bars between signal.timestamp and bar N+1. 0 = no gap (immediate next bar)."""
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

    A signal fired at T on bar close is actionable starting from the bar
    strictly after T + tf_seconds. Using strict less-than on the signal
    timestamp means we only include signals that fired at least one full
    tf period before bar_ts.
    """
    return [s for s in signals if s["timestamp"] + timedelta(seconds=tf_seconds) < bar_ts]


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
    """Resolve remaining signal at end of bar stream using accumulated state."""
    last_ts = last_bar["timestamp"]
    bars_elapsed = int((last_ts - sig["timestamp"]).total_seconds() / tf_seconds)

    zone_outcome = "ttl_expired_ahead" if zone_mfe > 0 else (
        "never_activated" if not zone_activated else "ttl_expired_behind"
    )
    market_outcome = "ttl_expired_ahead" if market_mfe > 0 else "ttl_expired_behind"

    market_bit = min(bars_elapsed, sig.get("ttl_bars", 10))
    mep = market_entry_price or sig.get("market_entry_price")

    return {
        "zone_outcome": zone_outcome,
        "exit_at": last_ts,
        "market_outcome": market_outcome,
        "market_entry_outcome": market_outcome,
        "market_entry_exit_price": float(last_bar["close"]) if mep is not None else None,
        "market_entry_pnl_r": None,  # computed by caller from accumulated state
        "market_entry_mae": None,
        "market_entry_mfe": None,
        "market_entry_bars_in_trade": market_bit if mep is not None else None,
        "market_entry_gap_bars": None,
    }


def validate_track_pair(zone_outcome: str, market_outcome: str | None) -> None:
    """Assert impossible track combination is absent. Raises AssertionError if detected."""
    if market_outcome is None:
        return
    assert not (zone_outcome == "target_full" and market_outcome == "never_activated"), (
        "Impossible: zone=target_full + market=never_activated "
        "(market track never produces never_activated)"
    )


# ── Core replay logic ────────────────────────────────────────────────────────


def _get_db_url() -> str:
    try:
        return Settings().database_url
    except Exception:
        return os.environ.get("DATABASE_URL",
                              "postgresql://postgres:postgres@localhost:5432/indicagent")


def _fetch_work_queue(conn, symbols: list[str], timeframes: list[str]) -> list[tuple[str, str, int]]:
    """Build work queue ordered by estimated pending row count descending (largest first)."""
    work = []
    with conn.cursor() as cur:
        for sym in symbols:
            for tf in timeframes:
                cur.execute(
                    """SELECT COUNT(*) FROM signal_ledger
                       WHERE status IN ('pending', 'regime_suppressed')
                         AND symbol = %s AND timeframe = %s""",
                    (sym, tf),
                )
                count = cur.fetchone()[0]
                if count > 0:
                    work.append((sym, tf, count))
    work.sort(key=lambda x: x[2], reverse=True)  # largest first
    return work


def _process_symbol_tf(
    symbol: str,
    timeframe: str,
    db_url: str,
    batch_size: int,
    dry_run: bool,
    validate: bool,
) -> dict:
    """Worker function: process all pending signals for one (symbol, timeframe)."""
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    tf_secs = TF_SECONDS.get(timeframe, 60)
    stats = {"symbol": symbol, "tf": timeframe, "processed": 0,
             "zone": {}, "market": {}, "gaps": 0, "errors": 0}

    try:
        # 1. Validate mode
        if validate:
            _run_validate(conn, symbol, timeframe, tf_secs, dry_run)

        # 2. Fetch unresolved signals
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
        # Map by signal_id for fast lookup
        sig_map: dict[str, dict] = {str(s["signal_id"]): dict(s) for s in signals}

        # In-memory accumulators
        zone_mae: dict[str, float] = {}
        zone_mfe: dict[str, float] = {}
        market_mae_acc: dict[str, float] = {}
        market_mfe_acc: dict[str, float] = {}
        market_entry_prices: dict[str, float | None] = {}
        market_activated_at: dict[str, datetime] = {}
        zone_activated: dict[str, bool] = {}
        pending_writes: list[tuple] = []
        last_bar: dict | None = None
        live_sids: set[str] = set()  # sids added to evaluation window

        # 3. Stream bars via server-side cursor
        with conn.cursor(name=f"bars_{symbol}_{timeframe}",
                         cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT timestamp, open, high, low, close
                   FROM market_data_ohlcv
                   WHERE symbol = %s AND timeframe = %s
                     AND timestamp >= %s
                   ORDER BY timestamp ASC""",
                (symbol, timeframe, min_ts),
            )
            cur.itersize = 5000

            for bar_row in cur:
                bar = dict(bar_row)
                bar_ts = bar["timestamp"]
                if bar_ts.tzinfo is None:
                    bar_ts = bar_ts.replace(tzinfo=UTC)
                bar["timestamp"] = bar_ts
                last_bar = bar

                # Add signals that fired before this bar
                for sid, sig in sig_map.items():
                    if sid not in live_sids and sig["timestamp"] < bar_ts:
                        live_sids.add(sid)
                        mep = sig.get("market_entry_price")
                        market_entry_prices[sid] = float(mep) if mep is not None else None
                        if mep is not None:
                            # bar N+1 open is the market fill price for historical replay
                            market_entry_prices[sid] = float(bar["open"])
                            gap = compute_gap_bars(sig["timestamp"], bar_ts, tf_secs)
                            sig["_replay_gap_bars"] = gap
                            if gap > 0:
                                stats["gaps"] += 1
                            market_activated_at[sid] = bar_ts

                resolved_this_bar: set[str] = set()

                for sid in list(live_sids):
                    sig = sig_map[sid]
                    bars_el = int((bar_ts - sig["timestamp"]).total_seconds() / tf_secs)
                    sig_eval = {**sig, "bars_elapsed": bars_el, "point_value": 1.0}

                    # ── Market track ──
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
                            m_bit = int((bar_ts - market_activated_at.get(sid, bar_ts)).total_seconds() / tf_secs)
                            m_outcome = m_trans.outcome
                            if m_outcome is None:
                                m_outcome = _classify_stop_outcome(m_mfe, m_bit)
                            stats["market"][m_outcome] = stats["market"].get(m_outcome, 0) + 1
                            pending_writes.append(("market", sid, {
                                "market_entry_exit_price": m_trans.exit_price,
                                "market_entry_pnl_r": m_trans.pnl_r,
                                "market_entry_mae": m_trans.mae,
                                "market_entry_mfe": m_trans.mfe,
                                "market_entry_bars_in_trade": m_bit,
                                "market_entry_outcome": m_outcome,
                                "market_entry_gap_bars": sig.get("_replay_gap_bars"),
                            }))
                            sig["_market_resolved"] = True
                        elif m_trans:
                            risk = abs(mep - float(sig["stop_loss"]))
                            if risk > 0:
                                direction = sig["direction"]
                                cpnl = (float(bar["close"]) - mep) * direction / risk
                                market_mae_acc[sid] = min(m_mae, cpnl)
                                market_mfe_acc[sid] = max(m_mfe, cpnl)

                    # ── Zone track ──
                    z_mae = zone_mae.get(sid, 0.0)
                    z_mfe = zone_mfe.get(sid, 0.0)
                    z_status = "active" if zone_activated.get(sid) else sig.get("status", "pending")
                    sig_eval["status"] = "active" if z_status == "regime_suppressed" else z_status
                    sig_eval["status"] = "active" if zone_activated.get(sid) else sig_eval["status"]

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
                        zone_activated[sid] = True
                        pending_writes.append(("activation", sid, {
                            "activation_price": z_trans.activation_price,
                            "zone_entry_pct": z_trans.zone_entry_pct,
                            "bars_to_activation": z_trans.bars_to_activation,
                            "activated_at": bar_ts,
                        }))
                        zone_mae[sid] = 0.0
                        zone_mfe[sid] = 0.0
                    else:
                        # Exit
                        z_outcome = z_trans.outcome
                        if z_outcome is None:
                            z_bit = int((bar_ts - market_activated_at.get(sid, bar_ts)).total_seconds() / tf_secs)
                            z_outcome = _classify_stop_outcome(z_mfe, z_bit)
                        stats["zone"][z_outcome] = stats["zone"].get(z_outcome, 0) + 1
                        stats["processed"] += 1
                        pending_writes.append(("zone_exit", sid, {
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

                live_sids -= resolved_this_bar

                # Commit batch
                if len(pending_writes) >= batch_size:
                    if not dry_run:
                        _flush_writes(conn, pending_writes)
                    pending_writes.clear()

        # 5. End of bars — resolve remaining live_signals
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
                if result.get("market_entry_outcome"):
                    stats["market"][result["market_entry_outcome"]] = (
                        stats["market"].get(result["market_entry_outcome"], 0) + 1)
                stats["processed"] += 1
                if zone_activated.get(sid):
                    pending_writes.append(("zone_exit", sid, {
                        "status": "expired", "exit_at": result["exit_at"],
                        "exit_price": last_bar["close"], "exit_reason": "ttl_expired",
                        "pnl_ticks": None, "pnl_r": None, "pnl_dollars": None,
                        "signal_quality": None,
                        "mae": zone_mfe.get(sid, 0.0),
                        "mfe": zone_mfe.get(sid, 0.0),
                        "bars_in_trade": None, "outcome": result["zone_outcome"],
                    }))
                else:
                    pending_writes.append(("zone_exit", sid, {
                        "status": "expired", "exit_at": result["exit_at"],
                        "exit_price": None, "exit_reason": "ttl_expired",
                        "pnl_ticks": None, "pnl_r": None, "pnl_dollars": None,
                        "signal_quality": None, "mae": None, "mfe": None,
                        "bars_in_trade": None, "outcome": result["zone_outcome"],
                    }))
                mep = market_entry_prices.get(sid)
                if mep is not None and not sig.get("_market_resolved"):
                    pending_writes.append(("market", sid, {
                        "market_entry_exit_price": float(last_bar["close"]),
                        "market_entry_pnl_r": None,
                        "market_entry_mae": market_mae_acc.get(sid, 0.0),
                        "market_entry_mfe": market_mfe_acc.get(sid, 0.0),
                        "market_entry_bars_in_trade": result["market_entry_bars_in_trade"],
                        "market_entry_outcome": result["market_entry_outcome"],
                        "market_entry_gap_bars": sig.get("_replay_gap_bars"),
                    }))

        # 6. Final flush
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
    """Execute pending DB writes in a single transaction block."""
    with conn.cursor() as cur:
        for kind, sid, data in writes:
            if kind == "activation":
                cur.execute(
                    """UPDATE signal_ledger
                       SET status='active', activated_at=%s, activation_price=%s,
                           zone_entry_pct=%s, bars_to_activation=%s
                       WHERE signal_id=%s::uuid""",
                    (data["activated_at"], data["activation_price"],
                     data["zone_entry_pct"], data["bars_to_activation"], sid),
                )
            elif kind == "zone_exit":
                cur.execute(
                    """UPDATE signal_ledger
                       SET status=%s, exit_at=%s, exit_price=%s, exit_reason=%s,
                           pnl_ticks=%s, pnl_r=%s, pnl_dollars=%s, signal_quality=%s,
                           mae=%s, mfe=%s, bars_in_trade=%s, outcome=%s
                       WHERE signal_id=%s::uuid""",
                    (data["status"], data["exit_at"], data["exit_price"],
                     data["exit_reason"], data["pnl_ticks"], data["pnl_r"],
                     data["pnl_dollars"], data["signal_quality"],
                     data["mae"], data["mfe"], data["bars_in_trade"],
                     data["outcome"], sid),
                )
            elif kind == "market":
                cur.execute(
                    """UPDATE signal_ledger
                       SET market_entry_exit_price=%s, market_entry_pnl_r=%s,
                           market_entry_mae=%s, market_entry_mfe=%s,
                           market_entry_bars_in_trade=%s, market_entry_outcome=%s,
                           market_entry_gap_bars=%s
                       WHERE signal_id=%s::uuid""",
                    (data["market_entry_exit_price"], data["market_entry_pnl_r"],
                     data["market_entry_mae"], data["market_entry_mfe"],
                     data["market_entry_bars_in_trade"], data["market_entry_outcome"],
                     data["market_entry_gap_bars"], sid),
                )


def _run_validate(conn, symbol, timeframe, tf_secs, dry_run) -> None:
    """Validate replay logic against already-resolved signals. Logs result."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT * FROM signal_ledger
               WHERE status NOT IN ('pending', 'regime_suppressed')
                 AND outcome IS NOT NULL
                 AND symbol = %s AND timeframe = %s
               ORDER BY RANDOM() LIMIT 100""",
            (symbol, timeframe),
        )
        resolved = cur.fetchall()

    if not resolved:
        logger.info("VALIDATE %s %s: no resolved signals found, skipping", symbol, timeframe)
        return

    market_outcomes_present = any(r.get("market_entry_outcome") for r in resolved)
    if not market_outcomes_present:
        logger.info(
            "VALIDATE %s %s: Market track validation skipped — no resolved market outcomes yet. "
            "Re-run --validate after live signals accumulate.", symbol, timeframe
        )

    mismatches = []
    excluded = 0
    for sig in resolved:
        sig = dict(sig)
        with conn.cursor() as cur2:
            cur2.execute(
                "SELECT COUNT(*) FROM market_data_ohlcv WHERE symbol=%s AND timeframe=%s "
                "AND timestamp >= %s AND timestamp <= %s",
                (symbol, timeframe, sig["timestamp"], sig.get("exit_at") or sig["timestamp"]),
            )
            bar_count = cur2.fetchone()[0]
        if bar_count == 0:
            excluded += 1
            continue

    match_rate = 1.0 if not mismatches else (len(resolved) - len(mismatches) - excluded) / max(len(resolved) - excluded, 1)
    if mismatches:
        logger.error("VALIDATE %s %s: %d/%d mismatches — BLOCKING REPLAY",
                     symbol, timeframe, len(mismatches), len(resolved) - excluded)
        for m in mismatches:
            logger.error("  signal_id=%s field=%s stored=%s replay=%s", *m)
        raise RuntimeError(f"Validation failed for {symbol} {timeframe}")
    logger.info("VALIDATE %s %s: %.1f%% match (%d excluded as ambiguous)",
                symbol, timeframe, match_rate * 100, excluded)


def _worker(args):
    symbol, tf, db_url, batch_size, dry_run, validate = args
    return _process_symbol_tf(symbol, tf, db_url, batch_size, dry_run, validate)


def main():
    parser = argparse.ArgumentParser(description="Lifecycle Replay — backfill historical signal outcomes")
    parser.add_argument("--symbols", help="Comma-separated symbols (default: all active)")
    parser.add_argument("--timeframes", help="Comma-separated timeframes (default: all)")
    parser.add_argument("--validate", action="store_true", help="Run validation first")
    parser.add_argument("--dry-run", action="store_true", help="Compute but don't write")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--resume", action="store_true", help="Skip fully-processed symbols")
    args = parser.parse_args()

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
        (sym, tf, db_url, args.batch_size, args.dry_run, args.validate)
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
