#!/usr/bin/env python3
"""Known Corrupt OHLCV Print Cleanup -- todo 151 (residual cleanup deferred by todo 148).

Todo 148 shipped a measurement-layer guard on `forward_returns` (return_{scale}_suspect
columns, sqrt-scaled per-tf plausibility ceilings) that protects mean-based consumers of
DERIVED forward returns. It deliberately did NOT touch the underlying corrupt prints in
`market_data_ohlcv` -- e.g. UUP 5m 2007-06-20 19:00: open=1000, high=1000, low=28.97,
close=28.97, volume=200 on a ~$25 ETF. Because volume > 0, that row passes
`market_data_ohlcv_tradeable` (which guards against synthetic calendar-filler bars, not
bad prices) and flows into every feature computed directly from raw OHLCV
(momentum_z_*, volatility_rank, etc.) -- exposure `forward_returns`' guard does nothing
for. This script closes that residual exposure.

Design (see .planning/todos/pending/151-known-corrupt-ohlcv-print-cleanup.md and
.planning/todos/completed/148-forward-return-corrupt-print-guard.md for full background):

1. Candidate discovery: reuse the ALREADY-SHIPPED todo 148 suspect flags on
   `forward_returns` (return_{fast,mid,slow,extended}_suspect) to get the current,
   authoritative set of (symbol, tf) pairs with an implausible forward return --
   this generalizes the Q4 forensic corpus scan
   (docs/research/fable-2026-07-19-emission-threshold-alpha-verdict.md) rather than
   re-deriving an ad hoc `abs(return_fast) > 0.5` cutoff.
2. Precise localization + verification: for each candidate (symbol, tf), scan
   `market_data_ohlcv_tradeable` (NOT the raw table -- the corrupt rows all have
   volume > 0, so they already pass the tradeable filter) ordered by timestamp,
   comparing each bar's open/high/low/close against its immediate neighbors'
   close/open (LAG/LEAD). A genuine corrupt print is an ISOLATED spike-and-immediate-
   revert: this bar deviates from the neighbor reference by an order of magnitude
   (>= --magnitude-threshold, default 10x) or more, while the neighbors themselves
   agree closely with each other (<= --neighbor-agreement-threshold, default 2x
   apart) -- confirming they are a trustworthy reference. Classified CONFIRMED_CORRUPT.
   When the bar is implausible but the neighbors themselves disagree by more than the
   agreement threshold (untrustworthy reference -- could be a genuine continuation of
   an already-volatile move), classified AMBIGUOUS rather than forcing a call.
3. Correction (--apply only): for CONFIRMED_CORRUPT rows, set price_sanity_status='confirmed_corrupt'.
   Per Renaissance data-retention principle, the row itself is NEVER deleted and price
   columns are NEVER modified. The price_sanity_status column (added in todo 149's
   migration) provides the single, unified signal for "known bad bar," replacing the
   prior volume=0 mechanism, and only after an `integrity_monitor` audit record
   captures the original volume plus full OHLC logged via structlog.

Safety (non-negotiable): defaults to --dry-run behavior (report only, zero DB writes).
Mutating a row or writing an integrity_monitor record REQUIRES the explicit --apply
flag. This script must never be invoked with --apply by an unsupervised agent -- a
human reviews the CONFIRMED_CORRUPT table in the dry-run report first.

Usage:
    python scripts/ops/corpus/ops_known_corrupt_print_cleanup.py
    python scripts/ops/corpus/ops_known_corrupt_print_cleanup.py --symbols UUP XRT --tf 5m
    python scripts/ops/corpus/ops_known_corrupt_print_cleanup.py --apply   # human-reviewed only
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncpg
import structlog

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async
from src.config.settings import Settings
from src.core.service_utils import format_iso_ts, setup_service_logging
from src.intelligence.statistics.price_sanity import (
    _MAGNITUDE_THRESHOLD_DEFAULT,
    _NEIGHBOR_AGREEMENT_THRESHOLD_DEFAULT,
    CandidateVerdict,
    apply_cross_symbol_downgrade,
    build_subject_key,
    classify_candidate_bar,
)
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers

setup_service_logging("logs/known_corrupt_print_cleanup.log")
_logger = structlog.get_logger(__name__)

_JOB = "known-corrupt-print-cleanup"

_MONITOR_TYPE = "price_sanity_ohlcv_correction"
_METRIC_NAME = "original_volume"

_ALL_TFS = ("5m", "15m", "1h", "1d")


# ---------------------------------------------------------------------------
# Row model + SQL builders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateRow:
    symbol: str
    tf: str
    timestamp: str  # ISO string (format_iso_ts) -- display + subject-key use only
    open: float
    high: float
    low: float
    close: float
    volume: float
    prev_close: float | None
    next_open: float | None
    verdict: CandidateVerdict


# Stamps price_sanity_status directly (todo 149) -- price columns are NEVER modified
# (Renaissance retention: never delete the row, never touch price data) and volume is
# no longer touched either as of todo 149's unification: a corrected row now carries
# exactly one signal (price_sanity_status), the same one BarAuditor's live audit task
# writes, so there is one query surface for "which bars are known bad" rather than two
# independent, divergence-prone mechanisms for the same fact.
_CORRECTION_UPDATE_SQL = """
UPDATE market_data_ohlcv
SET price_sanity_status = 'confirmed_corrupt'
WHERE symbol = $1 AND timeframe = $2 AND timestamp = $3
"""

# monitor_type='price_sanity_ohlcv_correction', threshold_value=NULL (a correction
# record, not a threshold gate), passed=true (always -- this fact records what WAS
# corrected, it is not a pass/fail check). training_window_end=NULL -- this
# correction is not tied to any specific corpus run/vintage.
_AUDIT_INSERT_SQL = """
INSERT INTO integrity_monitor
    (monitor_type, subject, metric_name, metric_value, threshold_value, passed, training_window_end)
VALUES ($1, $2, $3, $4, NULL, true, NULL)
ON CONFLICT (monitor_type, training_window_end, metric_name, COALESCE(subject, ''), evaluated_at) DO NOTHING
"""

_CANDIDATE_TF_PAIRS_SQL = """
    SELECT DISTINCT symbol, tf
    FROM forward_returns
    WHERE return_type = 'executable_open_to_open'
      AND (return_fast_suspect OR return_mid_suspect OR return_slow_suspect OR return_extended_suspect)
    ORDER BY symbol, tf
"""

# Reads market_data_ohlcv_tradeable (CLAUDE.md-mandated volume>0 view) -- corrupt
# rows all have volume > 0 (that's precisely why they slip past the view's guard),
# so this is not a gap in coverage. Bounded to one (symbol, tf) pair per call --
# cheap, not a full-corpus scan.
_NEIGHBOR_SCAN_SQL = """
    WITH ordered AS (
        SELECT
            symbol, timeframe AS tf, timestamp, open, high, low, close, volume,
            LAG(close) OVER w AS prev_close,
            LEAD(open) OVER w AS next_open
        FROM market_data_ohlcv_tradeable
        WHERE symbol = $1 AND timeframe = $2
        WINDOW w AS (ORDER BY timestamp)
    )
    SELECT * FROM ordered ORDER BY timestamp
"""

_LATEST_TRAINING_WINDOW_END_SQL = "SELECT max(training_window_end) FROM feature_ic_scores"


# ---------------------------------------------------------------------------
# Report rendering -- unit-tested without a DB
# ---------------------------------------------------------------------------


def render_dry_run_report(rows: list[CandidateRow]) -> str:
    confirmed = [r for r in rows if r.verdict.verdict == "CONFIRMED_CORRUPT"]
    ambiguous = [r for r in rows if r.verdict.verdict == "AMBIGUOUS"]
    plausible = [r for r in rows if r.verdict.verdict == "PLAUSIBLE"]
    market_event = [r for r in rows if r.verdict.verdict == "MARKET_EVENT"]

    lines = [
        "# Known Corrupt OHLCV Print Cleanup -- Dry-Run Report (todo 151)",
        "",
        f"Candidates scanned: {len(rows)}",
        f"CONFIRMED_CORRUPT: {len(confirmed)}",
        f"AMBIGUOUS: {len(ambiguous)}",
        f"MARKET_EVENT (real crisis event, cross-symbol corroborated -- excluded from apply): {len(market_event)}",
        f"PLAUSIBLE (ruled out by neighbor cross-check): {len(plausible)}",
        "",
    ]

    header = (
        "| symbol | tf | timestamp | open | high | low | close | volume | "
        "prev_close | next_open | max_ratio | neighbor_ratio | implausible_fields | reason |"
    )
    divider = "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"

    for group_name, group in (
        ("CONFIRMED_CORRUPT", confirmed),
        ("AMBIGUOUS", ambiguous),
        ("MARKET_EVENT", market_event),
    ):
        lines.append(f"## {group_name} ({len(group)})")
        lines.append("")
        if group:
            lines.append(header)
            lines.append(divider)
            for r in group:
                neighbor_ratio_str = (
                    f"{r.verdict.neighbor_ratio:.3f}"
                    if r.verdict.neighbor_ratio is not None
                    else "n/a"
                )
                lines.append(
                    f"| {r.symbol} | {r.tf} | {r.timestamp} | {r.open} | {r.high} | {r.low} | "
                    f"{r.close} | {r.volume} | {r.prev_close} | {r.next_open} | "
                    f"{r.verdict.max_ratio:.2f} | {neighbor_ratio_str} | "
                    f"{','.join(r.verdict.implausible_fields)} | {r.verdict.reason} |"
                )
        lines.append("")

    return "\n".join(lines)


def render_followup_commands(confirmed: list[CandidateRow], training_window_end: str | None) -> str:
    if not confirmed:
        return "No CONFIRMED_CORRUPT rows -- no follow-up needed."

    symbols = sorted({r.symbol for r in confirmed})
    tfs = sorted({r.tf for r in confirmed})
    twe = training_window_end or (
        "<none found -- run: SELECT max(training_window_end) FROM feature_ic_scores>"
    )
    symbols_sql_list = ", ".join(f"'{s}'" for s in symbols)
    tfs_sql_list = ", ".join(f"'{t}'" for t in tfs)

    lines = [
        "## Recommended Follow-Up (human review required -- NOT executed by this script)",
        "",
        "1. Review the CONFIRMED_CORRUPT table above, then apply the corrections:",
        "",
        "   python scripts/ops/corpus/ops_known_corrupt_print_cleanup.py --apply "
        f"--symbols {' '.join(symbols)} --tf {' '.join(tfs)}",
        "",
        "2. IMPORTANT -- forward_returns and feature_vectors both insert with "
        "ON CONFLICT DO NOTHING (idempotent-replay semantics): re-running the writers "
        "below will NOT overwrite rows that already exist for the corrected "
        "neighborhood. Delete the stale rows first (widen the timestamp window to "
        "cover the corrected bar's forward-return lookahead plus any feature "
        "rolling-window lookback -- review before running):",
        "",
        f"   DELETE FROM forward_returns WHERE symbol IN ({symbols_sql_list}) "
        f"AND tf IN ({tfs_sql_list}) AND bar_ts BETWEEN <window_start> AND <window_end>;",
        f"   DELETE FROM feature_vectors WHERE symbol IN ({symbols_sql_list}) "
        f"AND tf IN ({tfs_sql_list}) AND bar_ts BETWEEN <window_start> AND <window_end>;",
        "",
        "3. Re-run forward_return_writer for the affected symbols/tfs:",
        "",
        f"   python services/forward_return_writer.py --symbols {' '.join(symbols)} "
        f"--tf {' '.join(tfs)} --training-window-end {twe}",
        "",
        "4. Re-run feature computation (compute-only, no live IBKR fetch):",
        "",
        "   python services/backfill_feature_factory.py --compute-only "
        f"--symbols {','.join(symbols)}",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DB-touching steps
# ---------------------------------------------------------------------------


async def _fetch_candidate_tf_pairs(
    pool: asyncpg.Pool, symbols: list[str] | None, tfs: list[str] | None
) -> list[tuple[str, str]]:
    rows = await pool.fetch(_CANDIDATE_TF_PAIRS_SQL)
    pairs = [(r["symbol"], r["tf"]) for r in rows]
    if symbols:
        symbol_set = set(symbols)
        pairs = [p for p in pairs if p[0] in symbol_set]
    if tfs:
        tf_set = set(tfs)
        pairs = [p for p in pairs if p[1] in tf_set]
    return pairs


_CROSS_SYMBOL_NEIGHBOR_SQL = """
    WITH neighbors AS (
        SELECT
            symbol, timestamp, open, high, low, close,
            LAG(close) OVER w AS prev_close,
            LEAD(open) OVER w AS next_open
        FROM market_data_ohlcv_tradeable
        WHERE timeframe = $1
          AND symbol != $2
          AND timestamp BETWEEN $3::timestamptz - INTERVAL '7 days'
                             AND $3::timestamptz + INTERVAL '7 days'
        WINDOW w AS (PARTITION BY symbol ORDER BY timestamp)
    )
    SELECT symbol, open, high, low, close, prev_close, next_open
    FROM neighbors
    -- Exact timestamp match, deliberately -- NOT a +/- window like
    -- forward_return_writer.py's corroboration fix (todo 152). Raw OHLCV bars are the
    -- event itself: the confirmed Flash Crash cluster's collapse landed on the SAME
    -- 5m bar across CWB/ITA/RSP/VTV/VUG/VYM (a coincident-collapse, textbook
    -- stub-quote signature per the original investigation), unlike forward_returns'
    -- DERIVED, LEAD()-computed suspect flags, which staggered across bars because
    -- each scale's exit price anchors at a different lookahead. Residual risk: a
    -- market-wide event whose raw prints straddle two adjacent bars would
    -- under-corroborate here and stay CONFIRMED_CORRUPT -- bounded, since this script
    -- is dry-run-only and --apply is human-gated (a human reviewing the report is the
    -- backstop, not this function alone).
    WHERE timestamp = $3
"""


async def count_corroborating_symbols(
    pool: asyncpg.Pool,
    tf: str,
    subject_symbol: str,
    timestamp: Any,
    magnitude_threshold: float,
    neighbor_agreement_threshold: float,
) -> int:
    """Count OTHER symbols with an implausible bar (per classify_candidate_bar, same
    thresholds) at the exact same (tf, timestamp) as a CONFIRMED_CORRUPT candidate --
    todo 152's signal, reused here so a genuine market-wide event isn't misclassified.
    Each neighbor symbol is classified against ITS OWN prev/next reference, exactly as
    the subject row was -- symmetric reuse of classify_candidate_bar, no new
    classification logic. The +/-7 day window is generous slack for LAG/LEAD accuracy
    across weekends/holidays on 1d bars; cheap since this only runs per CONFIRMED_CORRUPT
    candidate (~27 total), not per-row over the corpus.

    A neighbor counts as corroborating whenever its OWN verdict is NOT "PLAUSIBLE" --
    AMBIGUOUS counts too, deliberately: a real event's OTHER affected symbols often
    land AMBIGUOUS themselves (a V-shaped recovery need not fully revert within one
    bar, and ITA/VUG's own Flash Crash rows classify AMBIGUOUS under
    classify_candidate_bar for exactly that reason). Tightening this to
    `== "CONFIRMED_CORRUPT"` only would silently weaken corroboration for the exact
    cluster this function exists to catch.
    """
    rows = await pool.fetch(_CROSS_SYMBOL_NEIGHBOR_SQL, tf, subject_symbol, timestamp)
    n_corroborating = 0
    for r in rows:
        neighbor_verdict = classify_candidate_bar(
            open_=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            prev_close=float(r["prev_close"]) if r["prev_close"] is not None else None,
            next_open=float(r["next_open"]) if r["next_open"] is not None else None,
            magnitude_threshold=magnitude_threshold,
            neighbor_agreement_threshold=neighbor_agreement_threshold,
        )
        if neighbor_verdict.verdict != "PLAUSIBLE":
            n_corroborating += 1
    return n_corroborating


async def _scan_and_classify(
    pool: asyncpg.Pool,
    symbol: str,
    tf: str,
    magnitude_threshold: float,
    neighbor_agreement_threshold: float,
    min_corroborating_symbols: int,
) -> list[CandidateRow]:
    rows = await pool.fetch(_NEIGHBOR_SCAN_SQL, symbol, tf)
    results: list[CandidateRow] = []
    for r in rows:
        verdict = classify_candidate_bar(
            open_=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            prev_close=float(r["prev_close"]) if r["prev_close"] is not None else None,
            next_open=float(r["next_open"]) if r["next_open"] is not None else None,
            magnitude_threshold=magnitude_threshold,
            neighbor_agreement_threshold=neighbor_agreement_threshold,
        )
        if verdict.verdict == "CONFIRMED_CORRUPT":
            n_corroborating = await count_corroborating_symbols(
                pool,
                tf,
                symbol,
                r["timestamp"],
                magnitude_threshold,
                neighbor_agreement_threshold,
            )
            verdict = apply_cross_symbol_downgrade(
                verdict, n_corroborating, min_corroborating_symbols
            )
        if verdict.verdict == "PLAUSIBLE":
            continue
        results.append(
            CandidateRow(
                symbol=symbol,
                tf=tf,
                timestamp=format_iso_ts(r["timestamp"]),
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=float(r["volume"]),
                prev_close=float(r["prev_close"]) if r["prev_close"] is not None else None,
                next_open=float(r["next_open"]) if r["next_open"] is not None else None,
                verdict=verdict,
            )
        )
    return results


async def _apply_correction(conn: asyncpg.Connection, row: CandidateRow, bar_ts) -> None:
    """Write the integrity_monitor audit record BEFORE mutating, then mark price_sanity_status.

    Full original OHLC logged via structlog (metric_value only fits one number --
    the audit trail's human-readable detail lives in the log line, not the column).
    """
    subject = build_subject_key(row.symbol, row.tf, row.timestamp)
    await conn.execute(_AUDIT_INSERT_SQL, _MONITOR_TYPE, subject, _METRIC_NAME, row.volume)
    _logger.info(
        "known_corrupt_print_cleanup.correcting_row",
        symbol=row.symbol,
        tf=row.tf,
        timestamp=row.timestamp,
        original_open=row.open,
        original_high=row.high,
        original_low=row.low,
        original_close=row.close,
        original_volume=row.volume,
        prev_close=row.prev_close,
        next_open=row.next_open,
        max_ratio=row.verdict.max_ratio,
        implausible_fields=row.verdict.implausible_fields,
    )
    await conn.execute(_CORRECTION_UPDATE_SQL, row.symbol, row.tf, bar_ts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols", nargs="*", default=None, help="Restrict scan to these symbols."
    )
    parser.add_argument(
        "--tf", nargs="*", choices=_ALL_TFS, default=None, help="Restrict scan to these timeframes."
    )
    parser.add_argument(
        "--magnitude-threshold",
        type=float,
        default=None,
        help=f"Order-of-magnitude ratio vs. neighbor reference to flag a field implausible "
        f"(default: {_MAGNITUDE_THRESHOLD_DEFAULT}x, loaded from APR).",
    )
    parser.add_argument(
        "--neighbor-agreement-threshold",
        type=float,
        default=None,
        help="Max ratio between prev_close and next_open for neighbors to be trusted as a "
        f"reference (default: {_NEIGHBOR_AGREEMENT_THRESHOLD_DEFAULT}x, loaded from APR).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Mutate CONFIRMED_CORRUPT rows (price_sanity_status='confirmed_corrupt') and write integrity_monitor audit "
        "records. DEFAULT IS DRY-RUN (report only, zero DB writes). A human must review "
        "the dry-run's CONFIRMED_CORRUPT table before ever passing this flag.",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)

    try:
        # apr and pairs have no data dependency on each other -- fetch concurrently
        # rather than back-to-back round trips.
        apr, pairs = await asyncio.gather(
            load_apr_dict_async(pool),
            _fetch_candidate_tf_pairs(pool, args.symbols, args.tf),
        )
        min_corroborating_symbols = int(
            _cfg(apr, "alpha.quant.cross_symbol_corroboration.min_symbols", 4)
        )
        magnitude_threshold = (
            args.magnitude_threshold
            if args.magnitude_threshold is not None
            else float(
                _cfg(
                    apr,
                    "alpha.quant.price_sanity.magnitude_threshold",
                    _MAGNITUDE_THRESHOLD_DEFAULT,
                )
            )
        )
        neighbor_agreement_threshold = (
            args.neighbor_agreement_threshold
            if args.neighbor_agreement_threshold is not None
            else float(
                _cfg(
                    apr,
                    "alpha.quant.price_sanity.neighbor_agreement_threshold",
                    _NEIGHBOR_AGREEMENT_THRESHOLD_DEFAULT,
                )
            )
        )
        _logger.info("known_corrupt_print_cleanup.candidate_pairs", n_pairs=len(pairs), pairs=pairs)

        all_rows: list[CandidateRow] = []
        for symbol, tf in pairs:
            rows = await _scan_and_classify(
                pool,
                symbol,
                tf,
                magnitude_threshold,
                neighbor_agreement_threshold,
                min_corroborating_symbols,
            )
            all_rows.extend(rows)

        report = render_dry_run_report(all_rows)
        print(report)  # noqa: T201

        confirmed = [r for r in all_rows if r.verdict.verdict == "CONFIRMED_CORRUPT"]
        training_window_end = await pool.fetchval(_LATEST_TRAINING_WINDOW_END_SQL)
        twe_str = format_iso_ts(training_window_end) if training_window_end is not None else None

        if not args.apply:
            print(render_followup_commands(confirmed, twe_str))  # noqa: T201
            print(  # noqa: T201
                "\nDRY-RUN MODE (default) -- zero DB writes made. Pass --apply after "
                "reviewing the CONFIRMED_CORRUPT table above to mutate rows."
            )
            return 0

        # --apply: mutate only CONFIRMED_CORRUPT rows. AMBIGUOUS rows are never
        # auto-corrected -- they require human judgment (see module docstring).
        if not confirmed:
            print(
                "--apply passed but zero CONFIRMED_CORRUPT rows found -- nothing to do."
            )  # noqa: T201
            return 0

        # Need the raw timestamp (not the display ISO string) for the UPDATE's
        # WHERE clause -- re-fetch alongside the scan would duplicate the query;
        # simplest is to re-resolve per (symbol, tf) pair scoped to confirmed rows.
        n_corrected = 0
        async with pool.acquire() as conn:
            async with conn.transaction():
                for symbol, tf in pairs:
                    tf_confirmed = [r for r in confirmed if r.symbol == symbol and r.tf == tf]
                    if not tf_confirmed:
                        continue
                    bar_rows = await conn.fetch(
                        "SELECT timestamp FROM market_data_ohlcv_tradeable "
                        "WHERE symbol = $1 AND timeframe = $2",
                        symbol,
                        tf,
                    )
                    ts_by_iso = {format_iso_ts(r["timestamp"]): r["timestamp"] for r in bar_rows}
                    for row in tf_confirmed:
                        bar_ts = ts_by_iso.get(row.timestamp)
                        if bar_ts is None:
                            _logger.error(
                                "known_corrupt_print_cleanup.bar_ts_resolve_failed",
                                symbol=symbol,
                                tf=tf,
                                timestamp=row.timestamp,
                            )
                            continue
                        await _apply_correction(conn, row, bar_ts)
                        n_corrected += 1

        _logger.info("known_corrupt_print_cleanup.apply_complete", n_corrected=n_corrected)
        print(
            f"\nAPPLIED: {n_corrected} row(s) corrected (price_sanity_status set to 'confirmed_corrupt')."
        )  # noqa: T201
        print(render_followup_commands(confirmed, twe_str))  # noqa: T201
        return 0
    finally:
        await pool.close()


def main() -> None:
    args = _parse_args()

    try:
        init_otel_providers(service_name=_JOB)
    except OTelInitError as error:
        _logger.warning("known_corrupt_print_cleanup.otel_init_failed", error=str(error))

    status = "success"
    try:
        exit_code = asyncio.run(_run(args))
    except Exception as error:
        status = "failure"
        _logger.error("known_corrupt_print_cleanup.fatal_error", error=str(error))
        raise
    finally:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
