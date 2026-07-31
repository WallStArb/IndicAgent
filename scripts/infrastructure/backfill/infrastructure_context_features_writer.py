#!/usr/bin/env python3
"""
infrastructure_context_features_writer.py — daily-cadence macro features for IC engine

Computes vix_z, flight_quality, and yield_slope_z from SPY/TLT/SHY 1d bars and writes
one row per (feature_date, feature_name) to context_features, preventing IC inflation via bar duplication.
Run daily or after OHLCV backfill to populate cross-asset features for the IC engine.
Requires market_data_ohlcv with daily bars for SPY/TLT/SHY.
"""

from __future__ import annotations

import argparse
import bisect
import math
import sys
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import psycopg2
import psycopg2.extras
import structlog

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import load_config_service_sync as _load_config_service
from src.config.settings import Settings
from src.core.service_utils import setup_service_logging

setup_service_logging("logs/context_features_writer.log")
_logger = structlog.get_logger(__name__)

# Market-wide features computed from SPY/TLT/SHY daily bars.
# symbol='' (empty string sentinel) for all three — market-wide, not symbol-scoped.
_FEATURE_NAMES = ("flight_quality", "vix_z", "yield_slope_z")
_SOURCE = "derived"  # computed from IBKR OHLCV; not fetched directly from IBKR or FRED


# ---------------------------------------------------------------------------
# Helper: z-score of most-recent deque value against rolling window
# (mirrors src/intelligence/feature_cache.py:_zscore_from_deque)
# ---------------------------------------------------------------------------


def _zscore_from_deque(history: deque, window: int) -> float:
    """Compute z-score of most-recent value against rolling window.

    Returns 0.0 if insufficient data or near-zero std.
    """
    if len(history) < window:
        return 0.0
    arr = np.array(list(history)[-window:])
    std = float(arr.std())
    if std < 1e-8:
        return 0.0
    return float((float(history[-1]) - float(arr.mean())) / std)


# ---------------------------------------------------------------------------
# OHLCV fetch
# ---------------------------------------------------------------------------


def _fetch_daily_bars(conn: Any, symbol: str) -> list[dict]:
    """Fetch 1d OHLCV from market_data_ohlcv_tradeable ordered by timestamp ASC.

    Returns list of dicts with keys: ts (date), close (float).

    Tradeable view, not the raw table (todo 124): mirrors backfill_feature_factory.py's
    _fetch_bars_from_db (already migrated) -- a synthetic-fill placeholder daily bar
    (flat close = prev close) would inject a fake zero-return day into vix_z/yield_slope_z's
    rolling z-score, diluting the real signal these context_features feed to the IC engine.
    """
    sql = """
        SELECT timestamp::date AS ts, close
        FROM market_data_ohlcv_tradeable
        WHERE symbol = %s AND timeframe = '1d'
        ORDER BY timestamp ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql, (symbol,))
        rows = cur.fetchall()
    return [{"ts": r[0], "close": float(r[1])} for r in rows]


# ---------------------------------------------------------------------------
# Core computation: mirrors _build_cross_asset_series() from backfill_feature_factory.py
# ---------------------------------------------------------------------------


def _build_cross_asset_series(
    spy_bars: list[dict],
    tlt_bars: list[dict],
    shy_bars: list[dict],
    vix_zscore_window: int,
    yield_curve_zscore_window: int,
    cross_asset_rv_window: int,
) -> dict[Any, tuple[float, float, float]]:
    """Build date -> (vix_z, flight_quality, yield_slope_z) incrementally in O(D).

    Uses bisect-based cursor alignment and deque-based rolling windows for O(1) per date.

    Assumption: SPY/TLT/SHY trade the same US calendar days. flight_quality anchors to the
    first available close for each symbol (equivalent to the batch formula when all series
    start together).

    Returns: dict mapping date -> (vix_z, flight_quality, yield_slope_z).
    Dates with NaN values (warmup period) are excluded from the result.
    Only dates where all three values are non-NaN are included.
    """
    symbol_bars = {"spy": spy_bars, "tlt": tlt_bars, "shy": shy_bars}
    symbol_dates = {k: [b["ts"] for b in v] for k, v in symbol_bars.items()}
    all_dates = sorted(set().union(*symbol_dates.values()))

    # Incremental state
    cursors: dict[str, int] = {k: 0 for k in symbol_bars}
    spy_log_rets: deque = deque(maxlen=cross_asset_rv_window)
    spy_realized_vol_history: deque = deque(maxlen=vix_zscore_window)
    yield_ratio_history: deque = deque(maxlen=yield_curve_zscore_window)

    spy_prev_close: float = 0.0
    tlt_prev_close: float = 0.0
    shy_prev_close: float = 0.0
    spy_first_close: float = 0.0  # flight_quality period-start anchor
    tlt_first_close: float = 0.0

    vix_z: float = 0.0
    flight_quality: float = 0.0
    yield_slope_z: float = 0.0
    result: dict[Any, tuple[float, float, float]] = {}

    for d in all_dates:
        for k in symbol_bars:
            cursors[k] = bisect.bisect_right(symbol_dates[k], d)

        spy_end = cursors["spy"]
        tlt_end = cursors["tlt"]
        shy_end = cursors["shy"]

        if spy_end < 2 or tlt_end < 2 or shy_end < 2:
            # Advance prev_close trackers during skip so first diff is correct.
            if spy_end >= 1:
                spy_prev_close = float(spy_bars[spy_end - 1]["close"])
            if tlt_end >= 1:
                tlt_prev_close = float(tlt_bars[tlt_end - 1]["close"])
            if shy_end >= 1:
                shy_prev_close = float(shy_bars[shy_end - 1]["close"])
            continue

        spy_close = float(spy_bars[spy_end - 1]["close"])
        tlt_close = float(tlt_bars[tlt_end - 1]["close"])
        shy_close = float(shy_bars[shy_end - 1]["close"])

        # Set period-start anchors once (first date with >= 2 bars for all three)
        if spy_first_close == 0.0:
            spy_first_close = float(spy_bars[0]["close"])
            tlt_first_close = float(tlt_bars[0]["close"])

        # vix_z: SPY realized-vol z-score
        # - log_return: log(close / prev_close)
        # - realized_vol: std of log_returns over cross_asset_rv_window bars
        # - vix_z: z-score of realized_vol over vix_zscore_window history
        if spy_prev_close > 1e-10:
            spy_ret = math.log(spy_close / spy_prev_close)
            spy_log_rets.append(spy_ret)
            realized_vol = float(np.std(spy_log_rets))
            spy_realized_vol_history.append(realized_vol)
            vix_z = _zscore_from_deque(spy_realized_vol_history, vix_zscore_window)

        # flight_quality: TLT/SPY cumulative divergence from period start (risk-off signal)
        # - tlt_ret_total: total TLT return from period start
        # - spy_ret_total: total SPY return from period start
        # - flight_quality = tlt_ret_total - spy_ret_total (positive = risk-off)
        if spy_first_close > 1e-10 and tlt_first_close > 1e-10:
            tlt_ret_total = tlt_close / tlt_first_close - 1.0
            spy_ret_total = spy_close / spy_first_close - 1.0
            flight_quality = tlt_ret_total - spy_ret_total

        # yield_slope_z: TLT/SHY log-return ratio z-score (yield curve slope proxy)
        # - tlt_log_ret - shy_log_ret: daily difference in log returns
        # - z-scored over yield_curve_zscore_window history
        if tlt_prev_close > 1e-10 and shy_prev_close > 1e-10:
            tlt_log_ret = math.log(tlt_close / tlt_prev_close)
            shy_log_ret = math.log(shy_close / shy_prev_close)
            yield_ratio_history.append(tlt_log_ret - shy_log_ret)
            yield_slope_z = _zscore_from_deque(yield_ratio_history, yield_curve_zscore_window)

        # Only include dates where all three deques have sufficient history for z-scoring.
        # Before warmup, values are 0.0 (initial), which is not a valid measurement.
        if (
            len(spy_realized_vol_history) >= vix_zscore_window
            and len(yield_ratio_history) >= yield_curve_zscore_window
        ):
            result[d] = (vix_z, flight_quality, yield_slope_z)

        spy_prev_close = spy_close
        tlt_prev_close = tlt_close
        shy_prev_close = shy_close

    return result


# ---------------------------------------------------------------------------
# DB write
# ---------------------------------------------------------------------------

_UPSERT_SQL = """
    INSERT INTO context_features (feature_date, feature_name, symbol, value, source, computed_at)
    VALUES (%(feature_date)s, %(feature_name)s, %(symbol)s, %(value)s, %(source)s, %(computed_at)s)
    ON CONFLICT (feature_date, feature_name, symbol) DO UPDATE
        SET value = EXCLUDED.value, computed_at = EXCLUDED.computed_at
"""


def _write_feature(
    conn: Any,
    feature_name: str,
    date_value_map: dict,
    computed_at: datetime,
    dry_run: bool,
) -> int:
    """Upsert one feature's daily rows into context_features. Returns row count."""
    rows = [
        {
            "feature_date": d,
            "feature_name": feature_name,
            "symbol": "",  # empty-string sentinel for market-wide features
            "value": v,
            "source": _SOURCE,
            "computed_at": computed_at,
        }
        for d, v in date_value_map.items()
        if not math.isnan(v)
    ]
    if dry_run:
        _logger.info(
            "context_features_writer.dry_run",
            feature_name=feature_name,
            n_rows=len(rows),
        )
        return len(rows)

    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, _UPSERT_SQL, rows)
    conn.commit()
    _logger.info(
        "context_features_writer.wrote",
        feature_name=feature_name,
        n_rows=len(rows),
    )
    return len(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Populate context_features table")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print row count without writing to DB",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["SPY", "TLT", "SHY"],
        help="Override symbols for debugging (default: SPY TLT SHY)",
    )
    args = parser.parse_args()

    settings = Settings()
    conn = psycopg2.connect(settings.database_url)

    _logger.info("context_features_writer.start", dry_run=args.dry_run)

    try:
        # Load APR keys for cross-asset computation windows
        cfg = _load_config_service(conn)
        vix_zscore_window = int(cfg.get_sync("feature.vix.zscore_window", 252))
        yield_curve_zscore_window = int(cfg.get_sync("feature.yield_curve.zscore_window", 252))
        cross_asset_rv_window = int(cfg.get_sync("feature.cross_asset.rv_window", 20))

        _logger.info(
            "context_features_writer.config",
            vix_zscore_window=vix_zscore_window,
            yield_curve_zscore_window=yield_curve_zscore_window,
            cross_asset_rv_window=cross_asset_rv_window,
        )

        # Determine which symbols to use
        spy_sym = args.symbols[0] if len(args.symbols) > 0 else "SPY"
        tlt_sym = args.symbols[1] if len(args.symbols) > 1 else "TLT"
        shy_sym = args.symbols[2] if len(args.symbols) > 2 else "SHY"

        _logger.info(
            "context_features_writer.fetching_bars",
            spy=spy_sym,
            tlt=tlt_sym,
            shy=shy_sym,
        )
        spy_bars = _fetch_daily_bars(conn, spy_sym)
        tlt_bars = _fetch_daily_bars(conn, tlt_sym)
        shy_bars = _fetch_daily_bars(conn, shy_sym)

        _logger.info(
            "context_features_writer.bars_loaded",
            n_spy=len(spy_bars),
            n_tlt=len(tlt_bars),
            n_shy=len(shy_bars),
        )

        if not spy_bars or not tlt_bars or not shy_bars:
            _logger.error(
                "context_features_writer.missing_bars",
                n_spy=len(spy_bars),
                n_tlt=len(tlt_bars),
                n_shy=len(shy_bars),
            )
            raise RuntimeError(
                f"Missing 1d bars for one or more symbols: "
                f"SPY={len(spy_bars)}, TLT={len(tlt_bars)}, SHY={len(shy_bars)}"
            )

        series = _build_cross_asset_series(
            spy_bars,
            tlt_bars,
            shy_bars,
            vix_zscore_window=vix_zscore_window,
            yield_curve_zscore_window=yield_curve_zscore_window,
            cross_asset_rv_window=cross_asset_rv_window,
        )

        n_dates = len(series)
        _logger.info("context_features_writer.series_built", n_dates=n_dates)

        if n_dates == 0:
            raise RuntimeError(
                "No dates produced by _build_cross_asset_series — "
                "insufficient OHLCV history or warmup period not met"
            )

        computed_at = datetime.now(UTC)

        # Unpack series into per-feature maps
        vix_z_map = {d: vals[0] for d, vals in series.items()}
        flight_quality_map = {d: vals[1] for d, vals in series.items()}
        yield_slope_z_map = {d: vals[2] for d, vals in series.items()}

        n_vix_z = _write_feature(conn, "vix_z", vix_z_map, computed_at, args.dry_run)
        n_flight_quality = _write_feature(
            conn, "flight_quality", flight_quality_map, computed_at, args.dry_run
        )
        n_yield_slope_z = _write_feature(
            conn, "yield_slope_z", yield_slope_z_map, computed_at, args.dry_run
        )

        total_rows = n_vix_z + n_flight_quality + n_yield_slope_z
        _logger.info(
            "context_features_writer.complete",
            dry_run=args.dry_run,
            n_vix_z=n_vix_z,
            n_flight_quality=n_flight_quality,
            n_yield_slope_z=n_yield_slope_z,
            total_rows=total_rows,
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
