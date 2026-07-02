#!/usr/bin/env python3
"""Equity Regime Model — oneshot that populates market_regimes with cross-sectional labels.

Computes one cross-sectional equity regime label per (asset_class='equity', tf, ts) from:
  - VIX proxy: SPY realized-vol z-score percentile rank over full corpus history
  - Breadth signal: fraction of equity ETFs (instrument_tags eq_* or intl_*) with close > 200MA

Regime label = {vix_bucket}_{breadth_signal} (e.g. low_bull, high_bear, mid_neutral).
9 possible labels from 3 vix buckets x 3 breadth buckets.

CORRECTNESS INVARIANTS:
- Warmup bars (NaN in vix_pct_rank or breadth_fraction) are excluded automatically.
- 200MA computation is causal: pandas rolling(200).mean() = rolling window over past 200 bars.
- VIX z-score percentile rank is causal: bisect-based expanding rank against only prior
  values (see `_compute_vix_pct_rank`, fixed 2026-06-29 per todo 026 P1a). This docstring
  previously described the pre-fix `.rank(pct=True)`-over-full-corpus behavior — corrected
  2026-07-02 after that stale claim was mistaken for current behavior during an audit.
- No DB calls inside _compute_tf_regimes() worker function.
- Workers receive compact numpy arrays (vix_pct_arr, breadth_arr, ts_arr) — NOT raw ETF data.
  Main process computes breadth/VIX from raw data, passes compact pre-computed arrays to workers.
  This avoids pickling 27M-row ETF datasets across process boundaries.
- ProcessPoolExecutor with submit() pattern; one task per TF.
- JSONB written via json.dumps (psycopg2 requires explicit serialization for JSONB).

Data flow:
  Main process: fetch raw data → compute vix_pct + breadth_fraction → compact params → workers
  Workers: receive compact params, assign labels (vectorized numpy), return result tuples
  Main process: collect worker results → INSERT INTO market_regimes

DAG invariant note: this oneshot is exempt from the "only writer subclasses touch DB"
rule exactly as backfill_feature_factory.py is — it is a batch labeling tool, not a
real-time daemon.

Usage:
    python services/equity_regime_model.py
    python services/equity_regime_model.py --tf 5m 1h
    python services/equity_regime_model.py --dry-run
    python services/equity_regime_model.py --workers 2
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
import structlog

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import load_config_service_sync as _load_config_service
from src.config.settings import Settings
from src.core.service_utils import setup_service_logging
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers

setup_service_logging("logs/equity_regime_model.log")

_logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_JOB = "equity-regime-model"
_DEFAULT_TFS: list[str] = ["5m", "15m", "1h", "1d"]
_REALIZED_VOL_WINDOW = 20  # rolling std of log-returns for VIX proxy
_VIX_Z_WINDOW = 252  # rolling mean/std for VIX z-score normalization
_MA_WINDOW = 200  # 200MA window for breadth signal

# Trading-session bars per daily bar — used to scale daily window parameters.
# 1d is already in daily bars; 1h: 6.5h/day (NYSE); 15m: 26 bars/day; 5m: 78 bars/day.
_BARS_PER_DAY: dict[str, int] = {
    "1d": 1,
    "1h": 7,  # rounded: 6.5 → 7 for conservative warmup
    "15m": 26,
    "5m": 78,
}


def _tf_window(daily_window: int, tf: str) -> int:
    """Convert a daily-bar window count to the equivalent bar count for a given TF.

    Examples:
        _tf_window(200, '5m')  → 200 * 78 = 15600
        _tf_window(252, '1h')  → 252 * 7  = 1764
        _tf_window(20, '1d')   → 20
    """
    bars_per_day = _BARS_PER_DAY.get(tf, 1)
    return daily_window * bars_per_day


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------


def _connect_db(settings: Settings) -> Any:
    conn = psycopg2.connect(settings.database_url)
    conn.autocommit = False
    return conn


# ---------------------------------------------------------------------------
# Worker function — NO DB CALLS, receives compact pre-computed arrays
# ---------------------------------------------------------------------------


def _compute_tf_regimes(params: dict) -> list[tuple]:
    """Assign cross-sectional regime labels for one TF.

    NO DB calls. Receives compact pre-computed arrays from the main process:
      - vix_pct_arr: SPY realized-vol z-score percentile rank per timestamp
      - breadth_arr: fraction of ETFs above 200MA per timestamp
      - ts_arr: aligned timestamps (same length as vix_pct_arr, breadth_arr)

    Main process computes these from raw DB data before dispatching. Workers only
    do the vectorized label assignment — no pandas/DB needed here.

    Returns list of (tf, ts, regime_label, regime_prob_vector_dict).
    """
    tf: str = params["tf"]
    ts_arr: list = params["ts_arr"]
    vix_pct_arr: list[float] = params["vix_pct_arr"]
    breadth_arr: list[float] = params["breadth_arr"]
    vix_low_pct: float = params["vix_low_pct"]
    vix_high_pct: float = params["vix_high_pct"]
    breadth_bear: float = params["breadth_bear"]
    breadth_bull: float = params["breadth_bull"]

    n = len(ts_arr)
    if n == 0:
        return []

    vix_np = np.asarray(vix_pct_arr, dtype=float)
    breadth_np = np.asarray(breadth_arr, dtype=float)

    # Vectorized VIX bucket: 'low' | 'mid' | 'high'
    vix_buckets = np.where(
        vix_np < vix_low_pct,
        "low",
        np.where(vix_np > vix_high_pct, "high", "mid"),
    )

    # Vectorized breadth signal: 'bull' | 'neutral' | 'bear'
    breadth_signals = np.where(
        breadth_np > breadth_bull,
        "bull",
        np.where(breadth_np < breadth_bear, "bear", "neutral"),
    )

    results: list[tuple] = [
        (
            tf,
            ts_arr[i],
            f"{vix_buckets[i]}_{breadth_signals[i]}",
            {
                "vix_bucket": str(vix_buckets[i]),
                "breadth_signal": str(breadth_signals[i]),
                "vix_pct": float(vix_np[i]),
                "breadth_frac": float(breadth_np[i]),
            },
        )
        for i in range(n)
    ]

    return results


# ---------------------------------------------------------------------------
# Main-process computation helpers (DB calls OK; not passed to workers)
# ---------------------------------------------------------------------------


def _compute_vix_pct_rank(
    spy_ts: list,
    spy_close: list[float],
    tf: str = "1d",
    rv_window_days: int = _REALIZED_VOL_WINDOW,
    z_window_days: int = _VIX_Z_WINDOW,
) -> pd.Series:
    """Compute SPY realized-vol z-score causal expanding percentile rank.

    Returns a pd.Series indexed by spy_ts with NaN for warmup bars.
    Uses a bisect-based expanding rank (see body below) — each position ranked
    only against prior values, no look-ahead.

    Parameters
    ----------
    spy_ts:
        Timestamps aligned to SPY bars for the given TF.
    spy_close:
        SPY close prices aligned to spy_ts.
    tf:
        Timeframe string (e.g. '5m', '1h', '1d'). Used to scale daily window
        parameters into TF-equivalent bar counts via _tf_window().
    rv_window_days:
        Rolling window in daily bars for realized vol (log-return std).
        Scaled to TF bars internally.
    z_window_days:
        Rolling window in daily bars for VIX z-score normalization.
        Scaled to TF bars internally.
    """
    rv_window = _tf_window(rv_window_days, tf)
    z_window = _tf_window(z_window_days, tf)
    spy_s = pd.Series(spy_close, index=spy_ts, dtype=float)
    spy_log_ret = np.log(spy_s / spy_s.shift(1))
    realized_vol = spy_log_ret.rolling(window=rv_window, min_periods=rv_window).std()
    rv_mean = realized_vol.rolling(window=z_window, min_periods=z_window).mean()
    rv_std = realized_vol.rolling(window=z_window, min_periods=z_window).std()
    vix_z = (realized_vol - rv_mean) / rv_std.where(rv_std > 1e-10)

    # Causal bisect-based expanding rank (no look-ahead bias).
    # Each position's rank is computed against all PRIOR valid values only.
    # NaN guard: skip NaN values (do not insert into window — preserves bisect sort invariant).
    # Tie handling: average rank = (bisect_left + bisect_right) / 2 / n.
    #   Two equal values produce rank 0.5 (matches pandas 'average' tie behavior).
    sorted_window: list[float] = []  # sorted; never contains NaN
    causal_ranks: list[float] = []

    for val in vix_z:
        if math.isnan(val):
            # NaN input -> NaN output; do NOT insert into window
            causal_ranks.append(float("nan"))
            continue

        if not sorted_window:
            # First valid value: rank 1.0 (it's both min and max of a 1-element set)
            bisect.insort(sorted_window, val)
            causal_ranks.append(1.0)
            continue

        # Rank against PRIOR window (causal: insert AFTER computing)
        left = bisect.bisect_left(sorted_window, val)
        right = bisect.bisect_right(sorted_window, val)
        rank = (left + right) / 2 / len(sorted_window)
        bisect.insort(sorted_window, val)
        causal_ranks.append(rank)

    return pd.Series(causal_ranks, index=spy_ts, dtype=float)


def _compute_breadth_fraction(
    dsn: str, tf: str, spy_ts: list, ma_window_days: int = _MA_WINDOW
) -> pd.Series:
    """Compute cross-sectional breadth: fraction of equity ETFs above 200MA.

    Opens a FRESH connection per call to avoid idle-connection termination between
    the long-running ETF fetches across TFs. The 5m fetch takes ~90s; a shared
    connection can be terminated by the server between TF calls.

    Fetches each ETF's bars (all symbols, full history), computes 200MA per symbol,
    aggregates by timestamp. Returns a pd.Series indexed by spy_ts.

    Breadth universe = symbols with instrument_tags tag LIKE 'eq_%' OR 'intl_%'.
    This excludes fixed income (fi_*), crypto, commodity_metals, real_estate, and
    preferred — which trade as equities but represent orthogonal economic exposures
    that would contaminate the breadth signal (e.g. TLT falling below 200MA during
    a risk-on rate-rise would incorrectly reduce breadth).
    """
    sql = """
        SELECT m.symbol, m.timestamp, m.close
        FROM market_data_ohlcv m
        JOIN instruments i ON i.symbol = m.symbol
        WHERE m.timeframe = %s
          AND i.is_active = true
          AND EXISTS (
              SELECT 1 FROM instrument_tags t
              WHERE t.symbol = m.symbol
                AND (t.tag LIKE 'eq_%%' OR t.tag LIKE 'intl_%%')
          )
        ORDER BY m.symbol, m.timestamp ASC
    """
    fresh_conn = psycopg2.connect(dsn)
    fresh_conn.autocommit = True  # read-only; no transactions needed
    try:
        with fresh_conn.cursor() as cur:
            cur.execute(sql, (tf,))
            rows = cur.fetchall()
    finally:
        fresh_conn.close()

    if not rows:
        return pd.Series(dtype=float, name="breadth")

    # Build per-symbol above-200MA series, then concat and mean
    above_ma_by_sym: dict[str, pd.Series] = {}
    current_sym = None
    sym_ts: list = []
    sym_close: list = []

    ma_window = _tf_window(ma_window_days, tf)

    def _process_sym(sym: str, ts_list: list, close_list: list) -> None:
        if len(ts_list) < ma_window:
            return
        s = pd.Series(close_list, index=ts_list, dtype=float)
        ma_series = s.rolling(window=ma_window, min_periods=ma_window).mean()
        above_ma = (s > ma_series).where(ma_series.notna()).astype(float)
        above_ma_by_sym[sym] = above_ma.rename(sym)

    for sym, ts, close in rows:
        if sym != current_sym:
            if current_sym is not None:
                _process_sym(current_sym, sym_ts, sym_close)
            current_sym = sym
            sym_ts = [ts]
            sym_close = [float(close)]
        else:
            sym_ts.append(ts)
            sym_close.append(float(close))

    if current_sym is not None:
        _process_sym(current_sym, sym_ts, sym_close)

    if not above_ma_by_sym:
        return pd.Series(dtype=float, name="breadth")

    breadth_df = pd.concat(list(above_ma_by_sym.values()), axis=1)
    return breadth_df.mean(axis=1, skipna=True).rename("breadth")


def _fetch_spy_bars(dsn: str, tf: str) -> tuple[list, list[float]]:
    """Fetch SPY close prices and timestamps for a given TF.

    Opens a fresh connection to avoid state pollution between TF fetches.
    """
    sql = """
        SELECT timestamp, close
        FROM market_data_ohlcv
        WHERE symbol = 'SPY' AND timeframe = %s
        ORDER BY timestamp ASC
    """
    fresh_conn = psycopg2.connect(dsn)
    fresh_conn.autocommit = True
    try:
        with fresh_conn.cursor() as cur:
            cur.execute(sql, (tf,))
            rows = cur.fetchall()
    finally:
        fresh_conn.close()

    if not rows:
        return [], []
    return [r[0] for r in rows], [float(r[1]) for r in rows]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Equity Regime Model — populate market_regimes with cross-sectional labels"
    )
    parser.add_argument(
        "--tf",
        nargs="*",
        default=_DEFAULT_TFS,
        help="Timeframes to process (default: 5m 15m 1h 1d)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute regime labels but do not write to market_regimes",
    )
    args = parser.parse_args()

    try:
        init_otel_providers(service_name=_JOB)
    except OTelInitError as error:
        _logger.warning("equity_regime_model.otel_init_failed", error=str(error))

    t0 = time.monotonic()
    status = "success"
    exit_code = 0

    settings = Settings()
    conn = None

    try:
        dsn = settings.database_url
        conn = _connect_db(settings)

        # ----------------------------------------------------------
        # Load APR thresholds
        # ----------------------------------------------------------
        cfg = _load_config_service(conn)
        vix_low_pct = float(cfg.get_sync("alpha.regime.vix_low_pct", 0.33))
        vix_high_pct = float(cfg.get_sync("alpha.regime.vix_high_pct", 0.67))
        breadth_bear = float(cfg.get_sync("alpha.regime.breadth_bear", 0.40))
        breadth_bull = float(cfg.get_sync("alpha.regime.breadth_bull", 0.60))
        realized_vol_window = int(cfg.get_sync("alpha.regime.realized_vol_window", 20))
        vix_z_window = int(cfg.get_sync("alpha.regime.vix_z_window", 252))
        ma_window_days = int(cfg.get_sync("alpha.regime.ma_window", 200))

        _logger.info(
            "equity_regime_model.apr_loaded",
            vix_low_pct=vix_low_pct,
            vix_high_pct=vix_high_pct,
            breadth_bear=breadth_bear,
            breadth_bull=breadth_bull,
            realized_vol_window=realized_vol_window,
            vix_z_window=vix_z_window,
            ma_window_days=ma_window_days,
        )

        tfs = args.tf

        # ----------------------------------------------------------
        # For each TF: fetch raw data, compute compact signals in main process,
        # then dispatch only compact arrays to workers.
        # ----------------------------------------------------------
        worker_params: dict[str, dict] = {}

        for tf in tfs:
            _logger.info("equity_regime_model.fetching_data", tf=tf)

            spy_ts, spy_close = _fetch_spy_bars(dsn, tf)
            if not spy_ts:
                _logger.warning("equity_regime_model.no_spy_bars", tf=tf)
                continue

            # Compute VIX proxy percentile rank (fast, SPY only)
            vix_pct_rank = _compute_vix_pct_rank(
                spy_ts,
                spy_close,
                tf=tf,
                rv_window_days=realized_vol_window,
                z_window_days=vix_z_window,
            )

            _logger.info("equity_regime_model.vix_computed", tf=tf, spy_bars=len(spy_ts))

            # Compute breadth fraction (slow: fetches all ETF bars for this TF)
            # Uses a fresh connection per TF to avoid server-side idle termination
            breadth_fraction = _compute_breadth_fraction(
                dsn, tf, spy_ts, ma_window_days=ma_window_days
            )

            _logger.info("equity_regime_model.breadth_computed", tf=tf)

            # Align both signals to SPY timestamps, drop NaN warmup rows
            combined = pd.DataFrame(
                {"vix_pct": vix_pct_rank, "breadth": breadth_fraction.reindex(spy_ts)},
                index=spy_ts,
            ).dropna()

            if combined.empty:
                _logger.warning("equity_regime_model.no_valid_rows", tf=tf)
                continue

            # Pass compact arrays to worker (not raw ETF data)
            worker_params[tf] = {
                "tf": tf,
                "ts_arr": combined.index.tolist(),
                "vix_pct_arr": combined["vix_pct"].tolist(),
                "breadth_arr": combined["breadth"].tolist(),
                "vix_low_pct": vix_low_pct,
                "vix_high_pct": vix_high_pct,
                "breadth_bear": breadth_bear,
                "breadth_bull": breadth_bull,
            }

            _logger.info(
                "equity_regime_model.params_prepared",
                tf=tf,
                n_valid_rows=len(combined),
            )

        if not worker_params:
            _logger.error("equity_regime_model.no_data_any_tf")
            status = "failure"
            exit_code = 1
            return

        # ----------------------------------------------------------
        # Dispatch to ProcessPoolExecutor — one label-assignment task per TF
        # Workers receive compact pre-computed arrays, no DB access
        # ----------------------------------------------------------
        _logger.info(
            "equity_regime_model.starting_workers",
            n_tfs=len(worker_params),
            n_workers=args.workers,
        )

        all_results: dict[str, list[tuple]] = {}

        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(_compute_tf_regimes, params): tf for tf, params in worker_params.items()
            }
            for future in as_completed(futures):
                tf = futures[future]
                try:
                    rows = future.result()
                    all_results[tf] = rows
                    _logger.info(
                        "equity_regime_model.tf_computed",
                        tf=tf,
                        n_rows=len(rows),
                    )
                except Exception as error:
                    _logger.error(
                        "equity_regime_model.worker_failed",
                        tf=tf,
                        error=str(error),
                    )
                    status = "failure"
                    exit_code = 1

        if args.dry_run:
            for tf, rows in sorted(all_results.items()):
                distinct_labels = {r[2] for r in rows}
                _logger.info(
                    "equity_regime_model.dry_run_result",
                    tf=tf,
                    n_rows=len(rows),
                    distinct_labels=sorted(distinct_labels),
                )
            _logger.info("equity_regime_model.dry_run_complete")
            return

        # ----------------------------------------------------------
        # Write results to market_regimes (main process)
        # Reconnect: the original conn may have been idle long enough that
        # the server closed it (5m+15m ETF fetches can take 2+ minutes).
        # ----------------------------------------------------------
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        conn = _connect_db(settings)

        insert_sql = """
            INSERT INTO market_regimes (asset_class, tf, ts, regime_label, regime_prob_vector)
            VALUES ('equity', %(tf)s, %(ts)s, %(regime_label)s, %(regime_prob_vector)s::jsonb)
            ON CONFLICT (asset_class, tf, ts)
            DO UPDATE SET
                regime_label = EXCLUDED.regime_label,
                regime_prob_vector = EXCLUDED.regime_prob_vector
        """

        total_written = 0
        for tf in sorted(all_results.keys()):
            rows = all_results[tf]
            if not rows:
                _logger.warning("equity_regime_model.no_rows_for_tf", tf=tf)
                continue

            # psycopg2 JSONB requires json.dumps
            batch_dicts = [
                {
                    "tf": r[0],
                    "ts": r[1],
                    "regime_label": r[2],
                    "regime_prob_vector": json.dumps(r[3]),
                }
                for r in rows
            ]

            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(cur, insert_sql, batch_dicts)
            conn.commit()

            distinct_labels = {r[2] for r in rows}
            total_written += len(batch_dicts)
            _logger.info(
                "equity_regime_model.tf_written",
                tf=tf,
                n_rows=len(batch_dicts),
                distinct_labels=sorted(distinct_labels),
            )

        elapsed = time.monotonic() - t0
        _logger.info(
            "equity_regime_model.complete",
            total_written=total_written,
            elapsed_s=round(elapsed, 2),
            status=status,
        )

    except Exception as error:
        _logger.error("equity_regime_model.run_failed", error=str(error))
        status = "failure"
        exit_code = 1
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
