#!/usr/bin/env python3
"""Backfill Feature Factory — two-stage oneshot.

Stage 1 (--fetch-only flag): Fetch IBKR OHLCV history for 58 active ETFs
into market_data_ohlcv at target depths. Checkpointed per (symbol, tf) via
backfill_status.fetch_complete.

Stage 2 (--compute-only flag): Read market_data_ohlcv_tradeable in chunked sliding
windows, call FeatureFactory.compute() per bar, batch-insert into
feature_vectors. Checkpointed per (symbol, tf) via backfill_status.status.

Default: both stages run in sequence.

IBKR client-id: 40 (provider uses 35; default 56 exceeds _MAX_CLIENT_ID=50).

Source invariant (T1/D-05): Only market_data_ohlcv (via the market_data_ohlcv_tradeable
view -- todo 124) is read for compute. Never intelligence_features.

Usage:
    python services/backfill_feature_factory.py
    python services/backfill_feature_factory.py --fetch-only
    python services/backfill_feature_factory.py --compute-only
    python services/backfill_feature_factory.py --symbols SPY,TLT
    python services/backfill_feature_factory.py --client-id 40
"""

from __future__ import annotations

import argparse
import asyncio
import bisect
import math
import sys
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
import psycopg
import structlog

# Set up sys.path before project imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


from services._batch_utils import get_dict_config as _get_dict_config
from services._batch_utils import get_list_config as _get_list_config
from services._batch_utils import load_config_service_sync as _load_config_service
from services._batch_utils import make_worker_pool as _make_worker_pool
from src.config.config_service import ConfigService
from src.config.settings import Settings, get_active_contracts
from src.core.market_calendar import get_market_calendar
from src.core.service_utils import setup_service_logging
from src.intelligence.feature_cache import (
    _CTF_HIGHER_TF,
    _HMM_K,
    FeatureCache,
    _hmm_forward_step,
    _wilder_rsi_series,
    _zscore_from_deque,
)
from src.intelligence.feature_factory import (
    FEATURE_FACTORY_VERSION,
    FeatureFactory,
    FeatureFactoryConfig,
)
from src.intelligence.features.cross_asset_series import CrossAssetRecord
from src.intelligence.features.feature_vector_persistence import (
    FEATURE_VECTOR_INSERT_SQL_PSYCOPG,
    FEATURE_VECTOR_UPSERT_SQL_PSYCOPG,
    feature_vector_to_insert_params,
)
from src.intelligence.schemas import FeatureVector
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers
from src.providers import IBKRProvider

setup_service_logging("logs/backfill_feature_factory.log")

_logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_JOB = "backfill-feature-factory"

# Default IBKR client-id — 40 per CLAUDE.md. Provider uses 35. 56+ exceeds cap.
_DEFAULT_CLIENT_ID: int = 40

# Target timeframes for backfill (1m is NOT a backfill target — live pipeline owns 1m,
# confirmed intentional, todo 199). This literal is now only the APR fallback default --
# the live driver is feature.factory.target_timeframes, loaded via _get_target_timeframes()
# below (todo 199: behavioral-list APR migration, CLAUDE.md APR mandate category 2).
_TARGET_TIMEFRAMES_DEFAULT: list[str] = ["5m", "15m", "1h", "1d"]


def _get_target_timeframes(cfg: ConfigService) -> list[str]:
    """Load the APR-backed set of timeframes backfill_feature_factory processes.

    feature.factory.target_timeframes (migration 278, todo 199) -- JSON array,
    default ["5m", "15m", "1h", "1d"], byte-identical to the prior hardcoded
    _TARGET_TIMEFRAMES module constant unless an operator explicitly reconfigures it.

    Validated here against _DEPTH_YEARS.keys() -- every configured tf must have a depth
    entry, or run_fetch_stage's later bare `_DEPTH_YEARS[tf]` subscript would KeyError
    partway through a live IBKR fetch, after some symbols already advanced past
    backfill_status (CLAUDE.md: silent/late failure is worse than a loud one at load time).
    """
    tfs = _get_list_config(
        cfg, "feature.factory.target_timeframes", list(_TARGET_TIMEFRAMES_DEFAULT)
    )
    _unknown = [tf for tf in tfs if tf not in _DEPTH_YEARS]
    if _unknown:
        raise AssertionError(
            f"feature.factory.target_timeframes contains {_unknown!r}, which has no "
            f"_DEPTH_YEARS entry ({sorted(_DEPTH_YEARS)}) -- add one before enabling this tf"
        )
    return tfs


# Depth years per TF (D-09, phase 137 spec)
_DEPTH_YEARS: dict[str, int] = {
    "5m": 5,
    "15m": 10,
    "1h": 15,
    "1d": 20,
}

# Bars per trading day per TF (objective formula)
_BARS_PER_DAY: dict[str, int] = {
    "5m": 78,
    "15m": 26,
    "1h": 6,
    "1d": 1,
}

_TRADING_DAYS_PER_YEAR: int = 252

# Batch size for feature_vectors INSERT — APR fallback default, live value read from
# infra.backfill.insert_batch_size (migration 275, todo 009 Part A).
_INSERT_BATCH_SIZE_DEFAULT: int = 500

# Chunk read size from market_data_ohlcv (T3: never load full history at once)
_READ_CHUNK_BARS: int = 2000

# Warm-up guard: number of bars needed before first valid feature vector.
# Use the momentum_zscore_window (252) as the dominant window + headroom.
# Read from config at runtime via FeatureFactoryConfig.
_FALLBACK_WARM_UP_BARS: int = 252

# Cross-asset symbols for FeatureCache.update_cross_asset()
_SPY = "SPY"
_TLT = "TLT"
_SHY = "SHY"
# Phase 151 Plan 04: TIP/HYG/LQD spread inputs + factor-beta proxy roles.
_TIP = "TIP"
_HYG = "HYG"
_LQD = "LQD"

# _CTF_HIGHER_TF (source TF -> HTF used for CTF features) now lives in
# src.intelligence.feature_cache, shared with feature_vector_pipeline.py's live-path
# update (todo 241). 1d uses itself as HTF: CTF at bar T computed from daily bars up to
# T (causal; bisect_right selects the current bar's CTF which is valid since the bar
# has closed at computation time).

# ---------------------------------------------------------------------------
# DB helpers (psycopg sync — mirrors run_historical_pipeline.py pattern)
# ---------------------------------------------------------------------------

_STORE_OHLCV_SQL = """
INSERT INTO market_data_ohlcv
    (timestamp, symbol, timeframe, open, high, low, close, volume, source)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (timestamp, symbol, timeframe) DO NOTHING
"""

_FETCH_BARS_SQL = """
SELECT timestamp, open, high, low, close, volume
FROM market_data_ohlcv_tradeable
WHERE symbol = %s AND timeframe = %s
ORDER BY timestamp ASC
"""

_FETCH_BARS_SINCE_SQL = """
SELECT timestamp, open, high, low, close, volume
FROM market_data_ohlcv_tradeable
WHERE symbol = %s AND timeframe = %s AND timestamp >= %s
ORDER BY timestamp ASC
"""

_FETCH_BARS_WINDOW_SQL = """
SELECT timestamp, open, high, low, close, volume
FROM market_data_ohlcv_tradeable
WHERE symbol = %s AND timeframe = %s
  AND timestamp >= %s AND timestamp < %s
ORDER BY timestamp ASC
"""

_UPSERT_STATUS_SQL = """
INSERT INTO backfill_status (symbol, tf, status, fetch_complete, started_at)
VALUES (%s, %s, %s, %s, NOW())
ON CONFLICT (symbol, tf) DO UPDATE SET
    status = EXCLUDED.status,
    fetch_complete = GREATEST(backfill_status.fetch_complete, EXCLUDED.fetch_complete),
    started_at = COALESCE(backfill_status.started_at, EXCLUDED.started_at)
"""

_MARK_FETCH_COMPLETE_SQL = """
INSERT INTO backfill_status (symbol, tf, fetch_complete, status)
VALUES (%s, %s, true, 'pending')
ON CONFLICT (symbol, tf) DO UPDATE SET fetch_complete = true
"""

_MARK_COMPUTE_STATUS_SQL = """
INSERT INTO backfill_status (symbol, tf, status, started_at)
VALUES (%s, %s, %s, NOW())
ON CONFLICT (symbol, tf) DO UPDATE SET
    status = EXCLUDED.status,
    started_at = COALESCE(backfill_status.started_at, NOW())
"""

_MARK_COMPUTE_COMPLETE_SQL = """
UPDATE backfill_status
SET status = 'complete',
    rows_written = %s,
    theoretical_max = %s,
    completed_at = NOW()
WHERE symbol = %s AND tf = %s
"""

_MARK_COMPUTE_FAILED_SQL = """
UPDATE backfill_status
SET status = 'failed', error_msg = %s
WHERE symbol = %s AND tf = %s
"""

_SELECT_STATUS_SQL = """
SELECT symbol, tf, status, fetch_complete, rows_written, theoretical_max
FROM backfill_status
WHERE symbol = ANY(%s) AND tf = ANY(%s)
"""

# Canonical INSERT/UPSERT SQL imported from shared persistence module.
# Do not inline SQL here — feature_vector_persistence.py is the single source of truth.
# DO NOTHING (default): idempotent gap-fill, never touches an existing row.
# DO UPDATE (--refresh): todo 176's recompute escape hatch -- ON CONFLICT (symbol,
# tf, bar_ts) DO NOTHING means a naive re-run silently skips every bar that already
# exists, so new columns (e.g. Phase 163's 17 VP/SR fields) never populate on
# pre-existing rows no matter how many times the backfill re-runs.
_INSERT_FEATURE_VECTORS_SQL = FEATURE_VECTOR_INSERT_SQL_PSYCOPG
_UPSERT_FEATURE_VECTORS_SQL = FEATURE_VECTOR_UPSERT_SQL_PSYCOPG


def _build_cross_asset_series(
    spy_bars: list[dict],
    tlt_bars: list[dict],
    shy_bars: list[dict],
    tip_bars: list[dict],
    hyg_bars: list[dict],
    lqd_bars: list[dict],
    config: FeatureFactoryConfig,
) -> dict:
    """Build date -> CrossAssetRecord incrementally in O(D) (Phase 151 Plan 04 extends
    the original 3-field vix_z/flight_quality/yield_slope_z builder with 5 more
    symbol-independent fields: tip_tlt_ret_z, hyg_lqd_ret_z, sb_corr_fast/slow/z).

    Uses a single aligned dict structure (no parallel lists) and maintains
    incremental state instead of re-materializing full bar slices each date.

    Assumption: SPY/TLT/SHY trade the same US calendar days, so min(spy_end, tlt_end)
    equals spy_end for every date. flight_quality anchors to the first available close
    for each symbol (equivalent to the batch formula when all series start together).

    Coverage guard (TIP/HYG/LQD only): TIP/HYG/LQD entered the universe in the
    58->80 ETF expansion (2026-07-01), postdating SPY/TLT/SHY's full history.
    A date with insufficient TIP/HYG/LQD coverage does NOT skip the whole date
    (unlike SPY/TLT/SHY, which continue to gate the entire row as before) --
    only the affected spread(s) emit 0.0 for that date, so vix_z/yield_slope_z
    are never silently dropped for dates that predate the newer ETFs'
    listings. The count of dates with partial TIP/HYG/LQD coverage is logged
    ONCE at the end of the builder (CLAUDE.md's never-log-per-row-over-the-
    corpus rule), never per date.
    """
    symbol_bars: dict[str, list[dict]] = {
        "spy": spy_bars,
        "tlt": tlt_bars,
        "shy": shy_bars,
        "tip": tip_bars,
        "hyg": hyg_bars,
        "lqd": lqd_bars,
    }
    symbol_dates: dict[str, list] = {k: [b["ts"].date() for b in v] for k, v in symbol_bars.items()}
    all_dates = sorted(set().union(*symbol_dates.values()))

    # Incremental state — O(1) per date
    cursors: dict[str, int] = {k: 0 for k in symbol_bars}
    spy_log_rets: deque = deque(maxlen=config.cross_asset_rv_window)
    yield_ratio_history: deque = deque(maxlen=config.yield_curve_zscore_window)
    spy_realized_vol_history: deque = deque(maxlen=config.vix_zscore_window)
    tip_tlt_ratio_history: deque = deque(maxlen=config.tip_tlt_zscore_window)
    hyg_lqd_ratio_history: deque = deque(maxlen=config.hyg_lqd_zscore_window)
    sb_corr_history: deque = deque(maxlen=config.sb_corr_zscore_window)
    sb_spy_ret_hist: deque = deque(
        maxlen=max(config.sb_corr_window_fast, config.sb_corr_window_slow)
    )
    sb_tlt_ret_hist: deque = deque(
        maxlen=max(config.sb_corr_window_fast, config.sb_corr_window_slow)
    )

    prev_close: dict[str, float] = dict.fromkeys(symbol_bars, 0.0)
    spy_first_close: float = 0.0  # flight_quality period-start anchor
    tlt_first_close: float = 0.0

    vix_z: float = 0.0
    flight_quality: float = 0.0
    yield_slope_z: float = 0.0
    tip_tlt_ret_z: float = 0.0
    hyg_lqd_ret_z: float = 0.0
    sb_corr_fast: float = 0.0
    sb_corr_slow: float = 0.0
    sb_corr_z: float = 0.0
    result: dict = {}
    n_partial_coverage_dates = 0

    for d in all_dates:
        for k in symbol_bars:
            cursors[k] = bisect.bisect_right(symbol_dates[k], d)

        spy_end, tlt_end, shy_end = cursors["spy"], cursors["tlt"], cursors["shy"]
        tip_end, hyg_end, lqd_end = cursors["tip"], cursors["hyg"], cursors["lqd"]

        if spy_end < 2 or tlt_end < 2 or shy_end < 2:
            # Advance prev_close trackers even during skip so first diff is correct
            for k, end in (("spy", spy_end), ("tlt", tlt_end), ("shy", shy_end)):
                if end >= 1:
                    prev_close[k] = float(symbol_bars[k][end - 1]["close"])
            continue

        spy_close = float(spy_bars[spy_end - 1]["close"])
        tlt_close = float(tlt_bars[tlt_end - 1]["close"])
        shy_close = float(shy_bars[shy_end - 1]["close"])

        # Set period-start anchors once (first date with ≥2 bars for all three)
        if spy_first_close == 0.0:
            spy_first_close = float(spy_bars[0]["close"])
            tlt_first_close = float(tlt_bars[0]["close"])

        # vix_z: append new SPY log return; compute realized vol; z-score over history
        if prev_close["spy"] > 1e-10:
            spy_ret = math.log(spy_close / prev_close["spy"])
            spy_log_rets.append(spy_ret)
            realized_vol = float(np.std(spy_log_rets))
            spy_realized_vol_history.append(realized_vol)
            vix_z = _zscore_from_deque(spy_realized_vol_history, config.vix_zscore_window)

        # flight_quality: cumulative TLT/SPY divergence from period start (O(1))
        if spy_first_close > 1e-10 and tlt_first_close > 1e-10:
            tlt_ret_total = tlt_close / tlt_first_close - 1.0
            spy_ret_total = spy_close / spy_first_close - 1.0
            flight_quality = tlt_ret_total - spy_ret_total

        # yield_slope_z: one-period TLT/SHY log-return ratio; z-score over history
        if prev_close["tlt"] > 1e-10 and prev_close["shy"] > 1e-10:
            tlt_log_ret = math.log(tlt_close / prev_close["tlt"])
            shy_log_ret = math.log(shy_close / prev_close["shy"])
            yield_ratio_history.append(tlt_log_ret - shy_log_ret)
            yield_slope_z = _zscore_from_deque(
                yield_ratio_history, config.yield_curve_zscore_window
            )

        # sb_corr_fast/slow/z: rolling Pearson correlation of SPY/TLT log
        # returns. Independent of the TIP/HYG/LQD coverage guard below --
        # only needs SPY/TLT, both already gating this date.
        if prev_close["tlt"] > 1e-10:
            sb_spy_ret_hist.append(math.log(spy_close / prev_close["spy"]))
            sb_tlt_ret_hist.append(math.log(tlt_close / prev_close["tlt"]))
            fast_n = min(config.sb_corr_window_fast, len(sb_spy_ret_hist))
            slow_n = min(config.sb_corr_window_slow, len(sb_spy_ret_hist))
            spy_arr = np.array(sb_spy_ret_hist)
            tlt_arr = np.array(sb_tlt_ret_hist)
            sb_corr_fast = _safe_corr_np(spy_arr[-fast_n:], tlt_arr[-fast_n:])
            sb_corr_slow = _safe_corr_np(spy_arr[-slow_n:], tlt_arr[-slow_n:])
            sb_corr_history.append(sb_corr_fast)
            sb_corr_z = _zscore_from_deque(sb_corr_history, config.sb_corr_zscore_window)

        # tip_tlt_ret_z / hyg_lqd_ret_z: coverage-guarded -- 0.0 (not a skip)
        # when TIP/HYG/LQD lack coverage for this date (pre-listing dates).
        partial_coverage = False
        if (
            tip_end >= 2
            and tlt_end >= 2
            and prev_close["tip"] > 1e-10
            and prev_close["tlt"] > 1e-10
        ):
            tip_close = float(tip_bars[tip_end - 1]["close"])
            tip_log_ret = math.log(tip_close / prev_close["tip"])
            tlt_log_ret = math.log(tlt_close / prev_close["tlt"])
            tip_tlt_ratio_history.append(tip_log_ret - tlt_log_ret)
            tip_tlt_ret_z = _zscore_from_deque(tip_tlt_ratio_history, config.tip_tlt_zscore_window)
        else:
            tip_tlt_ret_z = 0.0
            partial_coverage = True

        if (
            hyg_end >= 2
            and lqd_end >= 2
            and prev_close["hyg"] > 1e-10
            and prev_close["lqd"] > 1e-10
        ):
            hyg_close = float(hyg_bars[hyg_end - 1]["close"])
            lqd_close = float(lqd_bars[lqd_end - 1]["close"])
            hyg_log_ret = math.log(hyg_close / prev_close["hyg"])
            lqd_log_ret = math.log(lqd_close / prev_close["lqd"])
            hyg_lqd_ratio_history.append(hyg_log_ret - lqd_log_ret)
            hyg_lqd_ret_z = _zscore_from_deque(hyg_lqd_ratio_history, config.hyg_lqd_zscore_window)
        else:
            hyg_lqd_ret_z = 0.0
            partial_coverage = True

        if partial_coverage:
            n_partial_coverage_dates += 1

        result[d] = CrossAssetRecord(
            vix_z=vix_z,
            flight_quality=flight_quality,
            yield_slope_z=yield_slope_z,
            tip_tlt_ret_z=tip_tlt_ret_z,
            hyg_lqd_ret_z=hyg_lqd_ret_z,
            sb_corr_fast=sb_corr_fast,
            sb_corr_slow=sb_corr_slow,
            sb_corr_z=sb_corr_z,
        )

        for k, close in (
            ("spy", spy_close),
            ("tlt", tlt_close),
            ("shy", shy_close),
        ):
            prev_close[k] = close
        if tip_end >= 1:
            prev_close["tip"] = float(tip_bars[tip_end - 1]["close"])
        if hyg_end >= 1:
            prev_close["hyg"] = float(hyg_bars[hyg_end - 1]["close"])
        if lqd_end >= 1:
            prev_close["lqd"] = float(lqd_bars[lqd_end - 1]["close"])

    if n_partial_coverage_dates:
        _logger.info(
            "cross_asset_series_partial_tip_hyg_lqd_coverage",
            n_dates=n_partial_coverage_dates,
            n_total_dates=len(result),
        )

    return result


def _safe_corr_np(x: np.ndarray, y: np.ndarray) -> float:
    """Pearson correlation coefficient between two equal-length arrays.

    Returns 0.0 for degenerate input (fewer than 2 samples or zero variance
    in either series) rather than NaN. Local copy of feature_cache.py's
    _safe_corr() -- this module is psycopg/Ring-2-shaped and does not import
    from Ring 1 for pure math helpers already duplicated at that boundary
    (e.g. _zscore_from_deque is imported, but this one is small enough and
    array-shaped differently (rolling window slices, not a deque) that a
    local copy avoids an awkward mixed signature).
    """
    if len(x) < 2 or len(y) < 2:
        return 0.0
    xm = x - x.mean()
    ym = y - y.mean()
    denom = float(np.sqrt(np.dot(xm, xm) * np.dot(ym, ym)))
    if denom < 1e-10:
        return 0.0
    return float(np.dot(xm, ym) / denom)


def _build_symbol_beta_series(
    symbol_1d_bars: list[dict],
    spy_1d_bars: list[dict],
    tlt_1d_bars: list[dict],
    symbol: str,
    config: FeatureFactoryConfig,
) -> dict:
    """Build date -> (equity_beta_z, rate_beta_z) incrementally in O(D) for one symbol.

    Rolling OLS slope of the symbol's daily log returns on SPY's (equity_beta) and
    TLT's (rate_beta) daily log returns over config.factor_beta_window bars
    (cov(r_sym, r_factor) / var(r_factor), epsilon-guarded on the denominator),
    z-scored over config.factor_beta_zscore_window. Daily grain, broadcast to all
    timeframes by date -- same cadence contract as vix_z/yield_slope_z (see
    151-04's Interfaces: computing per-tf would require broadcasting a 25.4M-row
    SPY 5m array into every ProcessPoolExecutor worker, which already OOM-killed
    twice at --workers 12).

    equity_beta_z is None at EVERY date when symbol == SPY (self-regression
    against itself is degenerate, beta identically 1); rate_beta_z is None at
    every date when symbol == TLT. Mirrors _build_cross_asset_series' O(D)
    incremental alignment pattern (bisect cursors, prev_close trackers).
    """
    is_spy = symbol == _SPY
    is_tlt = symbol == _TLT

    bars_map = {"sym": symbol_1d_bars, "spy": spy_1d_bars, "tlt": tlt_1d_bars}
    dates_map = {k: [b["ts"].date() for b in v] for k, v in bars_map.items()}
    all_dates = sorted(set().union(*dates_map.values()))

    cursors: dict[str, int] = {k: 0 for k in bars_map}
    prev_close: dict[str, float] = dict.fromkeys(bars_map, 0.0)

    window = config.factor_beta_window
    sym_ret_hist: deque = deque(maxlen=window)
    spy_ret_hist: deque = deque(maxlen=window)
    tlt_ret_hist: deque = deque(maxlen=window)
    equity_beta_hist: deque = deque(maxlen=config.factor_beta_zscore_window)
    rate_beta_hist: deque = deque(maxlen=config.factor_beta_zscore_window)

    equity_beta_z: float = 0.0
    rate_beta_z: float = 0.0
    result: dict = {}

    for d in all_dates:
        for k in bars_map:
            cursors[k] = bisect.bisect_right(dates_map[k], d)

        sym_end, spy_end, tlt_end = cursors["sym"], cursors["spy"], cursors["tlt"]
        if sym_end < 2 or spy_end < 2 or tlt_end < 2:
            for k, end in (("sym", sym_end), ("spy", spy_end), ("tlt", tlt_end)):
                if end >= 1:
                    prev_close[k] = float(bars_map[k][end - 1]["close"])
            continue

        sym_close = float(symbol_1d_bars[sym_end - 1]["close"])
        spy_close = float(spy_1d_bars[spy_end - 1]["close"])
        tlt_close = float(tlt_1d_bars[tlt_end - 1]["close"])

        if prev_close["sym"] > 1e-10 and prev_close["spy"] > 1e-10 and prev_close["tlt"] > 1e-10:
            sym_ret_hist.append(math.log(sym_close / prev_close["sym"]))
            spy_ret_hist.append(math.log(spy_close / prev_close["spy"]))
            tlt_ret_hist.append(math.log(tlt_close / prev_close["tlt"]))

            if len(sym_ret_hist) >= 2:
                sym_arr = np.array(sym_ret_hist)
                if not is_spy:
                    spy_arr = np.array(spy_ret_hist)
                    var_spy = float(np.var(spy_arr))
                    cov_spy = float(np.cov(sym_arr, spy_arr)[0, 1])
                    raw_equity_beta = cov_spy / var_spy if var_spy > 1e-12 else 0.0
                    equity_beta_hist.append(raw_equity_beta)
                    equity_beta_z = _zscore_from_deque(
                        equity_beta_hist, config.factor_beta_zscore_window
                    )
                if not is_tlt:
                    tlt_arr = np.array(tlt_ret_hist)
                    var_tlt = float(np.var(tlt_arr))
                    cov_tlt = float(np.cov(sym_arr, tlt_arr)[0, 1])
                    raw_rate_beta = cov_tlt / var_tlt if var_tlt > 1e-12 else 0.0
                    rate_beta_hist.append(raw_rate_beta)
                    rate_beta_z = _zscore_from_deque(
                        rate_beta_hist, config.factor_beta_zscore_window
                    )

        result[d] = (
            None if is_spy else equity_beta_z,
            None if is_tlt else rate_beta_z,
        )

        prev_close["sym"] = sym_close
        prev_close["spy"] = spy_close
        prev_close["tlt"] = tlt_close

    return result


class CtfValues(NamedTuple):
    """4-field CTF payload keyed by HTF bar timestamp (Phase 151 Plan 05).

    Extends the original 3-field ctf_momentum/ctf_vwap_align/ctf_regime_align
    payload with htf_last_log_ret (the HTF bar's own causal log return),
    consumed by the ret_div_5m_1h/ret_div_1h_1d cross-TF divergences.
    NamedTuple with keyword-construction-only at every call site (mirroring
    CrossAssetRecord, Phase 151 Plan 04) -- positional unpacking of a growing
    tuple is exactly the drift risk both changes remove (Codex review
    precedent, see 151-04-SUMMARY.md).
    """

    ctf_momentum: float
    ctf_vwap_align: float
    ctf_regime_align: float
    htf_last_log_ret: float


def _build_ctf_series(
    htf_bars: list[dict],
    config: FeatureFactoryConfig,
) -> dict:
    """Build {htf_bar_period_start: CtfValues} in O(n).

    Single-pass streaming computation: Wilder RSI + cumulative VWAP + HMM forward
    + causal HTF log return. Avoids O(n²) slice reprocessing. All values are
    causal — bar k uses only bars 0..k. Keys are period-start timestamps,
    matching `htf_bars[k]["ts"]` exactly; callers that need close-time keys (see
    `_compute_symbol_tf`'s todo-243 shift) remap after the fact.
    """
    n = len(htf_bars)
    if n < 2:
        return {}

    closes = np.array([b["close"] for b in htf_bars], dtype=float)
    highs = np.array([b["high"] for b in htf_bars], dtype=float)
    lows = np.array([b["low"] for b in htf_bars], dtype=float)
    volumes = np.array([b["volume"] for b in htf_bars], dtype=float)

    period = config.rsi_mid_period

    # ctf_momentum: Wilder RSI per bar, normalized to [-1, +1]. Single shared impl.
    rsi_series = _wilder_rsi_series(closes, period)
    ctf_mom = np.clip((rsi_series - 50.0) / 50.0, -1.0, 1.0)

    # ctf_vwap_align: sign(close - cumulative VWAP)
    typical = (highs + lows + closes) / 3.0
    cum_tp_vol = np.cumsum(typical * volumes)
    cum_vol = np.cumsum(volumes)
    vwap = np.where(cum_vol > 1e-10, cum_tp_vol / cum_vol, closes)
    ctf_vwap = np.where(closes > vwap + 1e-10, 1.0, np.where(closes < vwap - 1e-10, -1.0, 0.0))

    # ctf_regime_align: HMM forward pass — 0.0 (ranging) or 1.0 (trending)
    ctf_regime = np.zeros(n, dtype=float)
    hmm_alpha = np.full(_HMM_K, 1.0 / _HMM_K, dtype=float)
    log_rets = np.diff(np.log(np.maximum(closes, 1e-10)))
    log_rets = np.where(np.isfinite(log_rets), log_rets, 0.0)
    ret_buf: deque = deque(maxlen=20)
    obs_buf = np.zeros(2, dtype=float)
    for i, ret in enumerate(log_rets):
        ret_buf.append(float(ret))
        obs_buf[0] = float(ret)
        obs_buf[1] = float(np.std(ret_buf)) if len(ret_buf) >= 2 else 0.005
        _hmm_forward_step(obs_buf, hmm_alpha)
        label = int(np.argmax(hmm_alpha))
        ctf_regime[i + 1] = 0.0 if label == 0 else 1.0

    # htf_last_log_ret (Phase 151 Plan 05): the HTF bar's own causal log
    # return, log(close[k] / close[k-1]), 0.0 at k=0 (no prior bar). Feeds
    # ret_div_5m_1h/ret_div_1h_1d -- distinct from ctf_momentum (Wilder RSI,
    # a smoothed multi-bar oscillator) and from log_rets above (that array's
    # length is n-1, unpadded; htf_last_log_ret is n-aligned and padded).
    htf_last_log_ret = np.concatenate(([0.0], log_rets))

    return {
        htf_bars[k]["ts"]: CtfValues(
            ctf_momentum=float(ctf_mom[k]),
            ctf_vwap_align=float(ctf_vwap[k]),
            ctf_regime_align=float(ctf_regime[k]),
            htf_last_log_ret=float(htf_last_log_ret[k]),
        )
        for k in range(n)
    }


def _rekey_ctf_series_to_actual_close(ctf_by_ts: dict, tf: str, htf_tf: str) -> dict:
    """Re-key `_build_ctf_series`'s dict from HTF period-start to each bar's ACTUAL close
    (todo 243) -- the next HTF bar's own start, not a flat nominal-duration offset.

    Only applies to genuine cross-timeframe pairs (`tf != htf_tf`, e.g. 5m/15m->1h,
    1h->1d): the batch join (`bisect.bisect_right(ctf_ts_list, bar_ts) - 1` in
    FeatureFactory.compute_batch) would otherwise select a still-forming HTF bar for LTF
    rows inside its still-open window -- real lookahead. A flat offset (`ts + nominal
    duration`) is wrong for real partial bars: confirmed against production data, the
    RTH-session-opening 1h bar is a genuine 30-minute partial (e.g. 13:30-14:00 UTC), and
    a flat offset would overshoot its true close by 30 minutes, silently routing LTF rows
    in that overshoot window to a stale, older bar instead of the correct, already-closed
    one. The last HTF bar has no known successor in this dict and is dropped -- its true
    close isn't knowable from data on hand; the next backfill run picks it up once its
    successor bar exists.

    1d's self-referential case (`tf == htf_tf`) is returned unchanged: re-keying it would
    select the *prior* day's bar instead of the current, already-closed one -- see
    `_CTF_HIGHER_TF`'s docstring.
    """
    if tf == htf_tf:
        return ctf_by_ts
    ts_sorted = sorted(ctf_by_ts.keys())
    return {ts_sorted[i + 1]: ctf_by_ts[ts_sorted[i]] for i in range(len(ts_sorted) - 1)}


def _build_ltf_return_series(ltf_bars: list[dict], target_ts_list: list) -> dict:
    """Build {target_bar_ts: last 1m log return at-or-before target_bar_ts} in
    O(n+m), Phase 151 Plan 05 (todo 066) -- feeds ret_div_1m_5m.

    Single merge walk over two already-sorted-ascending timestamp lists
    (`ltf_bars` from `_fetch_bars_from_db`, `target_ts_list` the caller's 5m
    bar timestamps -- both fetched oldest-first per that function's own
    contract). Causal: a target timestamp only ever picks up a 1m bar whose
    own `ts` is <= the target timestamp, never one strictly after it -- the
    1m log return itself is `log(close[k] / close[k-1])` for that 1m bar, the
    same causal definitional formula as `_ret_lag_1` elsewhere in this
    codebase. No entry is emitted for a target timestamp with zero eligible
    (at-or-before) 1m bars yet (typically the very start of 1m coverage).
    """
    if not ltf_bars or not target_ts_list:
        return {}

    result: dict = {}
    closes = [float(b["close"]) for b in ltf_bars]
    ts_list = [b["ts"] for b in ltf_bars]
    n = len(ltf_bars)
    j = 0
    prev_close: float | None = None
    last_log_ret: float | None = None

    for target_ts in target_ts_list:
        while j < n and ts_list[j] <= target_ts:
            if prev_close is not None and prev_close > 0.0 and closes[j] > 0.0:
                last_log_ret = math.log(closes[j] / prev_close)
            prev_close = closes[j]
            j += 1
        if last_log_ret is not None:
            result[target_ts] = last_log_ret

    return result


def _connect_db(settings: Settings) -> Any:
    """Synchronous psycopg connection."""
    conn = psycopg.connect(settings.database_url)
    conn.autocommit = True
    # No register_uuid() equivalent needed -- psycopg adapts uuid.UUID (e.g.
    # feature_vector_id, a content-key UUID) natively, unlike psycopg2.
    return conn


def _filter_etf_contracts(contracts: list, symbols: list[str] | None) -> list:
    """Return active ETF contracts, excluding futures and FX, optionally filtered to symbols."""
    etf = [
        c
        for c in contracts
        if not str(getattr(c, "asset_class", "")).lower().startswith("futures")
        and not str(getattr(c, "asset_class", "")).lower().startswith("fx")
    ]
    if symbols:
        wanted = set(symbols)
        etf = [c for c in etf if c.symbol in wanted]
    return etf


def _build_feature_factory_config(cfg: ConfigService) -> FeatureFactoryConfig:
    """Build FeatureFactoryConfig from APR keys. All fields from feature.* namespace."""
    return FeatureFactoryConfig(
        momentum_window_fast=int(cfg.get_sync("feature.momentum.window_fast", 5)),
        momentum_window_mid=int(cfg.get_sync("feature.momentum.window_mid", 20)),
        momentum_window_slow=int(cfg.get_sync("feature.momentum.window_slow", 60)),
        momentum_zscore_window=int(cfg.get_sync("feature.momentum.zscore_window", 252)),
        volume_zscore_window=int(cfg.get_sync("feature.volume.zscore_window", 20)),
        ofi_zscore_window=int(cfg.get_sync("feature.ofi.zscore_window", 20)),
        cvd_slope_bars=int(cfg.get_sync("feature.cvd.slope_bars", 5)),
        cmf_period=int(cfg.get_sync("feature.cmf.period", 20)),
        vol_short_bars=int(cfg.get_sync("feature.vol.short_bars", 5)),
        vol_long_bars=int(cfg.get_sync("feature.vol.long_bars", 20)),
        hma_period=int(cfg.get_sync("feature.hma.period", 20)),
        adx_period=int(cfg.get_sync("feature.adx.period", 14)),
        hurst_window=int(cfg.get_sync("feature.hurst.window", 252)),
        garch_window=int(cfg.get_sync("feature.garch.window", 100)),
        vix_zscore_window=int(cfg.get_sync("feature.vix.zscore_window", 252)),
        yield_curve_zscore_window=int(cfg.get_sync("feature.yield_curve.zscore_window", 252)),
        regime_cache_refresh_bars=int(cfg.get_sync("feature.regime.cache_refresh_bars", 30)),
        rsi_fast_period=int(cfg.get_sync("feature.period.rsi.fast", 7)),
        rsi_mid_period=int(cfg.get_sync("feature.period.rsi.mid", 14)),
        rsi_slow_period=int(cfg.get_sync("feature.period.rsi.slow", 28)),
        cci_fast_period=int(cfg.get_sync("feature.period.cci.fast", 10)),
        cci_mid_period=int(cfg.get_sync("feature.period.cci.mid", 20)),
        cci_slow_period=int(cfg.get_sync("feature.period.cci.slow", 40)),
        aroon_fast_period=int(cfg.get_sync("feature.period.aroon.fast", 14)),
        aroon_slow_period=int(cfg.get_sync("feature.period.aroon.slow", 25)),
        amihud_zscore_window=int(cfg.get_sync("feature.amihud.zscore_window", 252)),
        ret_skew_window=int(cfg.get_sync("feature.ret_skew.window", 60)),
        ret_skew_zscore_window=int(cfg.get_sync("feature.ret_skew.zscore_window", 252)),
        ret_acf_window=int(cfg.get_sync("feature.ret_acf.window", 30)),
        ret_acf_zscore_window=int(cfg.get_sync("feature.ret_acf.zscore_window", 252)),
        high_52w_window=int(cfg.get_sync("feature.high_52w.window", 252)),
        min_bars_warmup=int(cfg.get_sync("feature.cache.min_bars_warmup", 16)),
        cross_asset_rv_window=int(cfg.get_sync("feature.cross_asset.rv_window", 20)),
        ny_session_start_utc_hour=int(cfg.get_sync("feature.session.ny_start_utc_hour", 13)),
        ny_session_start_utc_minute=int(cfg.get_sync("feature.session.ny_start_utc_minute", 30)),
        ny_session_end_utc_hour=int(cfg.get_sync("feature.session.ny_end_utc_hour", 20)),
        overlap_start_utc_hour=int(cfg.get_sync("feature.session.overlap_start_utc_hour", 12)),
        overlap_end_utc_hour=int(cfg.get_sync("feature.session.overlap_end_utc_hour", 15)),
        london_kz_start_utc_hour=int(cfg.get_sync("feature.session.london_kz_start_utc_hour", 7)),
        london_kz_end_utc_hour=int(cfg.get_sync("feature.session.london_kz_end_utc_hour", 10)),
        power_hour_start_utc_hour=int(
            cfg.get_sync("feature.session.power_hour_start_utc_hour", 19)
        ),
        power_hour_end_utc_hour=int(cfg.get_sync("feature.session.power_hour_end_utc_hour", 21)),
        opening_range_start_minute=int(
            cfg.get_sync("feature.session.opening_range_start_minute", 810)
        ),
        opening_range_end_minute=int(cfg.get_sync("feature.session.opening_range_end_minute", 900)),
        ret_lag_fast=int(cfg.get_sync("feature.ret_lag.fast", 5)),
        ret_lag_mid=int(cfg.get_sync("feature.ret_lag.mid", 20)),
        ret_lag_slow=int(cfg.get_sync("feature.ret_lag.slow", 60)),
        overnight_gap_window=int(cfg.get_sync("feature.overnight_gap.window", 20)),
        dollar_vol_window=int(cfg.get_sync("feature.dollar_vol.window", 20)),
        vol_range_ratio_window=int(cfg.get_sync("feature.vol_range_ratio.window", 20)),
        vol_trend_fast=int(cfg.get_sync("feature.vol_trend.fast", 5)),
        vol_trend_slow=int(cfg.get_sync("feature.vol_trend.slow", 20)),
        up_vol_ratio_fast=int(cfg.get_sync("feature.up_vol_ratio.fast", 5)),
        up_vol_ratio_slow=int(cfg.get_sync("feature.up_vol_ratio.slow", 20)),
        vol_percentile_window=int(cfg.get_sync("feature.vol_percentile.window", 20)),
        vol_persistence_window=int(cfg.get_sync("feature.vol_persistence.window", 20)),
        vol_std_window=int(cfg.get_sync("feature.vol_std.window", 20)),
        mfi_fast=int(cfg.get_sync("feature.mfi.fast", 7)),
        mfi_slow=int(cfg.get_sync("feature.mfi.slow", 14)),
        obv_window=int(cfg.get_sync("feature.obv.window", 20)),
        dist_window_fast=int(cfg.get_sync("feature.breakout.dist_window_fast", 20)),
        dist_window_slow=int(cfg.get_sync("feature.breakout.dist_window_slow", 50)),
        range_window_fast=int(cfg.get_sync("feature.breakout.range_window_fast", 20)),
        range_window_slow=int(cfg.get_sync("feature.breakout.range_window_slow", 50)),
        stoch_window_fast=int(cfg.get_sync("feature.breakout.stoch_window_fast", 14)),
        stoch_window_slow=int(cfg.get_sync("feature.breakout.stoch_window_slow", 50)),
        percentile_window_fast=int(cfg.get_sync("feature.breakout.percentile_window_fast", 50)),
        percentile_window_slow=int(cfg.get_sync("feature.breakout.percentile_window_slow", 200)),
        efficiency_window_fast=int(cfg.get_sync("feature.breakout.efficiency_window_fast", 10)),
        efficiency_window_slow=int(cfg.get_sync("feature.breakout.efficiency_window_slow", 50)),
        ret_kurtosis_fast=int(cfg.get_sync("feature.ret_kurtosis.fast", 10)),
        ret_kurtosis_slow=int(cfg.get_sync("feature.ret_kurtosis.slow", 40)),
        ret_kurtosis_zscore_window=int(cfg.get_sync("feature.ret_kurtosis.zscore_window", 20)),
        updown_ratio_fast=int(cfg.get_sync("feature.updown_ratio.fast", 5)),
        updown_ratio_slow=int(cfg.get_sync("feature.updown_ratio.slow", 20)),
        streak_window=int(cfg.get_sync("feature.streak.window", 20)),
        realized_var_fast=int(cfg.get_sync("feature.realized_var.fast", 5)),
        realized_var_slow=int(cfg.get_sync("feature.realized_var.slow", 20)),
        vol_of_vol_window=int(cfg.get_sync("feature.vol_of_vol.window", 20)),
        high_low_corr_window=int(cfg.get_sync("feature.high_low_corr.window", 20)),
        variance_ratio_fast=int(cfg.get_sync("feature.variance_ratio.fast", 5)),
        variance_ratio_slow=int(cfg.get_sync("feature.variance_ratio.slow", 20)),
        vol_asymmetry_window=int(cfg.get_sync("feature.vol_asymmetry.window", 20)),
        bb_pct_b_fast=int(cfg.get_sync("feature.bb_pct_b.fast", 20)),
        bb_pct_b_slow=int(cfg.get_sync("feature.bb_pct_b.slow", 50)),
        hv_fast=int(cfg.get_sync("feature.hv.fast", 10)),
        hv_slow=int(cfg.get_sync("feature.hv.slow", 30)),
        hv_ratio_window=int(cfg.get_sync("feature.hv.ratio_window", 20)),
        parkinson_vol_window=int(cfg.get_sync("feature.parkinson_vol.window", 10)),
        parkinson_vol_zscore_window=int(cfg.get_sync("feature.parkinson_vol.zscore_window", 20)),
        garman_klass_vol_window=int(cfg.get_sync("feature.garman_klass_vol.window", 10)),
        garman_klass_vol_zscore_window=int(
            cfg.get_sync("feature.garman_klass_vol.zscore_window", 20)
        ),
        yang_zhang_vol_window=int(cfg.get_sync("feature.yang_zhang_vol.window", 20)),
        yang_zhang_vol_zscore_window=int(cfg.get_sync("feature.yang_zhang_vol.zscore_window", 20)),
        vol_velocity_window=int(cfg.get_sync("feature.vol_velocity.window", 20)),
        intraday_noise_window=int(cfg.get_sync("feature.intraday_noise.window", 20)),
        price_vol_corr_fast=int(cfg.get_sync("feature.price_vol_corr.fast", 10)),
        price_vol_corr_slow=int(cfg.get_sync("feature.price_vol_corr.slow", 30)),
        momentum_velocity_window=int(cfg.get_sync("feature.momentum_velocity.window", 14)),
        vwap_velocity_window=int(cfg.get_sync("feature.vwap_velocity.window", 14)),
        extreme_move_sigma_threshold=float(
            cfg.get_sync("feature.bars_since_extreme_move.sigma_threshold", 2.0)
        ),
        vol_spike_threshold=float(cfg.get_sync("feature.bars_since_vol_spike.threshold", 2.0)),
        tip_tlt_zscore_window=int(cfg.get_sync("feature.tip_tlt.zscore_window", 252)),
        hyg_lqd_zscore_window=int(cfg.get_sync("feature.hyg_lqd.zscore_window", 252)),
        sb_corr_window_fast=int(cfg.get_sync("feature.sb_corr.window_fast", 30)),
        sb_corr_window_slow=int(cfg.get_sync("feature.sb_corr.window_slow", 60)),
        sb_corr_zscore_window=int(cfg.get_sync("feature.sb_corr.zscore_window", 252)),
        factor_beta_window=int(cfg.get_sync("feature.factor_beta.window", 60)),
        factor_beta_zscore_window=int(cfg.get_sync("feature.factor_beta.zscore_window", 252)),
        canary_rng_seed=int(cfg.get_sync("alpha.ic.canary_rng_seed", 90042)),
        session_vp_value_area_pct=float(cfg.get_sync("feature.session_vp.value_area_pct", 0.70)),
        session_vp_n_buckets=int(cfg.get_sync("feature.session_vp.n_buckets", 50)),
        session_vp_hvn_threshold=float(cfg.get_sync("feature.session_vp.hvn_threshold", 0.80)),
        session_vp_lvn_threshold=float(cfg.get_sync("feature.session_vp.lvn_threshold", 0.20)),
        session_vp_rolling_window=int(cfg.get_sync("feature.session_vp.rolling_window", 480)),
        sr_window=int(cfg.get_sync("feature.sr.window", 10)),
        sr_cluster_atr_mult=float(cfg.get_sync("feature.sr.cluster_atr_mult", 0.5)),
        sr_lookback_by_tf=_get_dict_config(
            cfg, "feature.sr.lookback_by_tf", {"1m": 60, "5m": 60, "15m": 80, "1h": 120, "1d": 60}
        ),
        smc_order_blocks_lookback=int(cfg.get_sync("feature.smc.order_blocks.lookback", 100)),
        smc_order_blocks_impulse_bars=int(cfg.get_sync("feature.smc.order_blocks.impulse_bars", 3)),
        smc_order_blocks_significant_move_pct=float(
            cfg.get_sync("feature.smc.order_blocks.significant_move_pct", 0.003)
        ),
        smc_order_blocks_opposing_candle_lookback=int(
            cfg.get_sync("feature.smc.order_blocks.opposing_candle_lookback", 10)
        ),
        smc_order_blocks_strength_fallback=float(
            cfg.get_sync("feature.smc.order_blocks.strength_fallback", 0.5)
        ),
        smc_fvg_lookback=int(cfg.get_sync("feature.smc.fvg.lookback", 100)),
        smc_liquidity_sweeps_lookback=int(
            cfg.get_sync("feature.smc.liquidity_sweeps.lookback", 120)
        ),
        smc_liquidity_sweeps_swing_neighbor=int(
            cfg.get_sync("feature.smc.liquidity_sweeps.swing_neighbor", 5)
        ),
        smc_liquidity_sweeps_reclaim_bars=int(
            cfg.get_sync("feature.smc.liquidity_sweeps.reclaim_bars", 3)
        ),
        smc_liquidity_sweeps_depth_ramp_max_pct=float(
            cfg.get_sync("feature.smc.liquidity_sweeps.depth_ramp_max_pct", 2.0)
        ),
        smc_liquidity_sweeps_reclaim_velocity_ramp_max=float(
            cfg.get_sync("feature.smc.liquidity_sweeps.reclaim_velocity_ramp_max", 0.5)
        ),
        smc_liquidity_pools_lookback=int(cfg.get_sync("feature.smc.liquidity_pools.lookback", 150)),
        smc_liquidity_pools_swing_neighbor=int(
            cfg.get_sync("feature.smc.liquidity_pools.swing_neighbor", 5)
        ),
        smc_liquidity_pools_equal_level_tolerance_atr_mult=float(
            cfg.get_sync("feature.smc.liquidity_pools.equal_level_tolerance_atr_mult", 0.75)
        ),
        smc_liquidity_pools_session_bars=int(
            cfg.get_sync("feature.smc.liquidity_pools.session_bars", 390)
        ),
        smc_liquidity_pools_significance_weights=_get_dict_config(
            cfg,
            "feature.smc.liquidity_pools.significance_weights",
            {
                "eq_highs_3": 0.75,
                "eq_lows_3": 0.75,
                "eq_highs_2": 0.60,
                "eq_lows_2": 0.60,
                "session_high": 0.50,
                "session_low": 0.50,
            },
        ),
        smc_zones_lookback=int(cfg.get_sync("feature.smc.zones.lookback", 150)),
        smc_zones_impulse_atr_mult=float(cfg.get_sync("feature.smc.zones.impulse_atr_mult", 1.5)),
        smc_zones_base_body_ratio=float(cfg.get_sync("feature.smc.zones.base_body_ratio", 0.5)),
        smc_zones_base_atr_mult=float(cfg.get_sync("feature.smc.zones.base_atr_mult", 1.0)),
        smc_zones_max_base_bars=int(cfg.get_sync("feature.smc.zones.max_base_bars", 5)),
        smc_zones_zone_height_cap_atr_mult=float(
            cfg.get_sync("feature.smc.zones.zone_height_cap_atr_mult", 2.5)
        ),
        smc_zones_impulse_overlap_atr_mult=float(
            cfg.get_sync("feature.smc.zones.impulse_overlap_atr_mult", 0.4)
        ),
        smc_zones_freshness_decay_k=float(cfg.get_sync("feature.smc.zones.freshness_decay_k", 0.5)),
        smc_zones_strength_premium_align_mult=float(
            cfg.get_sync("feature.smc.zones.strength_premium_align_mult", 1.20)
        ),
        smc_zones_strength_fvg_align_mult=float(
            cfg.get_sync("feature.smc.zones.strength_fvg_align_mult", 1.15)
        ),
        smc_zones_age_penalty_floor=float(
            cfg.get_sync("feature.smc.zones.age_penalty_floor", 0.70)
        ),
        smc_zones_age_penalty_window_bars=int(
            cfg.get_sync("feature.smc.zones.age_penalty_window_bars", 200)
        ),
        smc_zones_age_penalty_max_pct=float(
            cfg.get_sync("feature.smc.zones.age_penalty_max_pct", 0.30)
        ),
        smc_zones_max_tracked_zones=int(cfg.get_sync("feature.smc.zones.max_tracked_zones", 5)),
        smc_bos_choch_lookback=int(cfg.get_sync("feature.smc.bos_choch.lookback", 120)),
        smc_bos_choch_swing_neighbor=int(cfg.get_sync("feature.smc.bos_choch.swing_neighbor", 5)),
        smc_amd_accum_start_utc_hour=int(cfg.get_sync("feature.smc.amd.accum_start_utc_hour", 20)),
        smc_amd_manip_end_utc_hour=int(cfg.get_sync("feature.smc.amd.manip_end_utc_hour", 10)),
        smc_amd_dist_end_utc_hour=int(cfg.get_sync("feature.smc.amd.dist_end_utc_hour", 21)),
        swing_pivot_window=int(cfg.get_sync("feature.swing.pivot_window", 5)),
        swing_lookback_bars=int(cfg.get_sync("feature.swing.lookback_bars", 120)),
        trend_structure_atr_strength_divisor=float(
            cfg.get_sync("feature.trend_structure.atr_strength_divisor", 5.0)
        ),
        trend_structure_range_lookback_bars=int(
            cfg.get_sync("feature.trend_structure.range_lookback_bars", 20)
        ),
        swing_momentum_confirm_n=int(cfg.get_sync("feature.swing_momentum.confirm_n", 3)),
        swing_momentum_max_extremes=int(cfg.get_sync("feature.swing_momentum.max_extremes", 6)),
        swing_momentum_lookback_bars=int(cfg.get_sync("feature.swing_momentum.lookback_bars", 60)),
        swing_momentum_reference_bars=int(
            cfg.get_sync("feature.swing_momentum.reference_bars", 20)
        ),
        swing_momentum_speed_factor_min=float(
            cfg.get_sync("feature.swing_momentum.speed_factor_min", 0.1)
        ),
        swing_momentum_speed_factor_max=float(
            cfg.get_sync("feature.swing_momentum.speed_factor_max", 3.0)
        ),
        swing_momentum_energy_divisor=float(
            cfg.get_sync("feature.swing_momentum.energy_divisor", 3.0)
        ),
        swing_momentum_intensity_ramp_lo=float(
            cfg.get_sync("feature.swing_momentum.intensity_ramp_lo", 1.0)
        ),
        swing_momentum_intensity_ramp_hi=float(
            cfg.get_sync("feature.swing_momentum.intensity_ramp_hi", 2.0)
        ),
        fib_cluster_atr_divisor=float(cfg.get_sync("feature.fib.cluster_atr_divisor", 2.0)),
        session_levels_asia_start_et_hour=int(
            cfg.get_sync("feature.session_levels.asia_start_et_hour", 20)
        ),
        session_levels_asia_end_et_hour=int(
            cfg.get_sync("feature.session_levels.asia_end_et_hour", 4)
        ),
    )


def _theoretical_max(tf: str, depth_years: int, warm_up_bars: int) -> int:
    """Compute theoretical max feature rows.

    Formula: (depth_years * 252 * bars_per_trading_day(tf)) - warm_up_bars

    Parameters
    ----------
    tf: Timeframe string (5m/15m/1h/1d)
    depth_years: Fetch depth in years
    warm_up_bars: Bars consumed by rolling window seed (dominant window)
    """
    bars_per_day = _BARS_PER_DAY[tf]
    return max(0, depth_years * _TRADING_DAYS_PER_YEAR * bars_per_day - warm_up_bars)


def _vector_to_params(
    symbol: str,
    tf: str,
    bar_ts: datetime,
    pipeline_version: str,
    regime: str | None,
    fv: FeatureVector,
) -> tuple:
    """Delegate to the canonical shared serializer.

    Backfill rows always use regime_label_source='filtered': all rows are
    computed from market_data_ohlcv with causal forward-filter HMM only (D-07).
    FEATURE_FACTORY_VERSION is injected here so all batch rows are version-stamped.
    """
    return feature_vector_to_insert_params(
        symbol=symbol,
        tf=tf,
        bar_ts=bar_ts,
        pipeline_version=pipeline_version,
        feature_factory_version=FEATURE_FACTORY_VERSION,
        regime=regime,
        regime_label_source="filtered",
        vector=fv,
    )


def _fetch_bars_from_db(
    conn: Any, symbol: str, tf: str, since: datetime | None = None
) -> list[dict]:
    """Fetch OHLCV bars from market_data_ohlcv_tradeable ordered oldest-first."""
    with conn.cursor() as cur:
        if since is not None:
            cur.execute(_FETCH_BARS_SINCE_SQL, (symbol, tf, since))
        else:
            cur.execute(_FETCH_BARS_SQL, (symbol, tf))
        rows = cur.fetchall()
    return [
        {
            "ts": r[0] if r[0].tzinfo else r[0].replace(tzinfo=UTC),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": float(r[5]),
        }
        for r in rows
    ]


def _load_status_map(conn: Any, symbols: list[str], tfs: list[str]) -> dict[tuple[str, str], dict]:
    """Load backfill_status rows for all (symbol, tf) pairs."""
    with conn.cursor() as cur:
        cur.execute(_SELECT_STATUS_SQL, (symbols, tfs))
        rows = cur.fetchall()
    result: dict[tuple[str, str], dict] = {}
    for sym, tf, status, fetch_complete, rows_written, theoretical_max in rows:
        result[(sym, tf)] = {
            "status": status,
            "fetch_complete": fetch_complete,
            "rows_written": rows_written,
            "theoretical_max": theoretical_max,
        }
    return result


# ---------------------------------------------------------------------------
# Stage 1: IBKR Fetch
# ---------------------------------------------------------------------------


async def run_fetch_stage(
    settings: Settings,
    client_id: int,
    symbols: list[str] | None,
    db_conn: Any,
) -> None:
    """Fetch IBKR OHLCV history for ETFs into market_data_ohlcv.

    Skips (symbol, tf) pairs that already have fetch_complete=true.
    On success marks fetch_complete=true BEFORE compute can begin (checkpoint).
    """
    from src.core.bar_normalizer import normalize_bars

    contracts = get_active_contracts(settings)
    etf_contracts = _filter_etf_contracts(contracts, symbols)
    _logger.info("fetch_stage_start", contracts=len(etf_contracts), client_id=client_id)

    cfg = _load_config_service(db_conn)
    target_timeframes = _get_target_timeframes(cfg)

    # Load existing status to skip already-fetched pairs
    all_symbols = [c.symbol for c in etf_contracts]
    status_map = _load_status_map(db_conn, all_symbols, target_timeframes)

    provider = IBKRProvider(
        host=settings.ib_host,
        port=settings.ib_port,
        client_id=client_id,
    )

    connected = await provider.connect()
    if not connected:
        _logger.error("ibkr_connect_failed")
        raise RuntimeError("Cannot connect to IBKR TWS — aborting fetch stage")

    end_dt = datetime.now(tz=UTC)
    total_bars_fetched = 0

    try:
        for instrument in etf_contracts:
            try:
                qualified = await provider.qualify_instrument(instrument)
                if not qualified:
                    _logger.warning("qualify_failed", symbol=instrument.symbol)
                    continue

                for tf in target_timeframes:
                    key = (instrument.symbol, tf)
                    existing = status_map.get(key, {})

                    # Skip if already fetched (checkpoint resume)
                    if existing.get("fetch_complete"):
                        _logger.info(
                            "fetch_skip_complete",
                            symbol=instrument.symbol,
                            tf=tf,
                        )
                        continue

                    depth_years = _DEPTH_YEARS[tf]
                    fetch_days = depth_years * 365
                    start_dt = (end_dt - timedelta(days=fetch_days)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )

                    _logger.info(
                        "fetch_start",
                        symbol=instrument.symbol,
                        tf=tf,
                        depth_years=depth_years,
                    )

                    try:
                        ohlcv_bars = await provider.fetch_historical_bars(
                            symbol=instrument.symbol,
                            timeframe=tf,
                            start=start_dt,
                            end=end_dt,
                            continuous=False,
                        )
                        bar_dicts = [
                            {
                                "timestamp": b.timestamp,
                                "open": b.open,
                                "high": b.high,
                                "low": b.low,
                                "close": b.close,
                                "volume": b.volume,
                                "source": getattr(b, "source", "historical_backfill"),
                            }
                            for b in ohlcv_bars
                        ]

                        canonical = normalize_bars(
                            bar_dicts,
                            symbol=instrument.symbol,
                            timeframe=tf,
                            start=start_dt,
                            end=end_dt,
                        )

                        if canonical:
                            params = [
                                (
                                    b["timestamp"],
                                    instrument.symbol,
                                    tf,
                                    b["open"],
                                    b["high"],
                                    b["low"],
                                    b["close"],
                                    b.get("volume", 0),
                                    b.get("source", "historical_backfill"),
                                )
                                for b in canonical
                            ]
                            with db_conn.cursor() as cur:
                                cur.executemany(_STORE_OHLCV_SQL, params)
                            db_conn.commit()
                            total_bars_fetched += len(params)
                            _logger.info(
                                "fetch_stored",
                                symbol=instrument.symbol,
                                tf=tf,
                                bars=len(params),
                            )

                        # Mark fetch_complete BEFORE starting compute (two-stage checkpoint)
                        with db_conn.cursor() as cur:
                            cur.execute(_MARK_FETCH_COMPLETE_SQL, (instrument.symbol, tf))
                        db_conn.commit()

                    except Exception as error:
                        _logger.error(
                            "fetch_error",
                            symbol=instrument.symbol,
                            tf=tf,
                            error=str(error),
                        )

                    await asyncio.sleep(1)  # IBKR pacing between TFs

            except Exception as error:
                _logger.error("instrument_error", symbol=instrument.symbol, error=str(error))

            await asyncio.sleep(2)  # IBKR pacing between instruments

    finally:
        await provider.disconnect()

    _logger.info("fetch_stage_complete", total_bars=total_bars_fetched)


# ---------------------------------------------------------------------------
# Stage 2: FeatureFactory Compute
# ---------------------------------------------------------------------------


def run_compute_stage(
    settings: Settings,
    symbols: list[str] | None,
    db_conn: Any,
    pipeline_version: str = "3.0.0",
    n_workers: int = 1,
    refresh: bool = False,
) -> tuple[dict[tuple[str, str], dict], float]:
    """Compute FeatureVectors from market_data_ohlcv_tradeable and batch-insert into feature_vectors.

    Reads bars in chunked sliding windows (T3: never full history at once).
    Checkpointed per (symbol, tf): skips status='complete' pairs, unless refresh=True
    (todo 176 recompute mode), which reprocesses every fetched pair regardless of
    checkpoint status and upserts (DO UPDATE) instead of skip-inserting (DO NOTHING).
    Records per-pair coverage vs theoretical_max (D-06 gate).
    Uses ProcessPoolExecutor for symbol-level parallelism when n_workers > 1.

    Returns coverage map: {(symbol, tf): {"rows_written": N, "theoretical_max": M, "pct": P}}
    """
    cfg = _load_config_service(db_conn)
    config = _build_feature_factory_config(cfg)
    target_timeframes = _get_target_timeframes(cfg)
    # todo 178 IN-01: was "threshold.backfill.coverage_threshold", which was never seeded --
    # migration 153 only ever seeded "threshold.backfill.coverage_gate", so the read always
    # fell through to the hardcoded 0.80 default and any dashboard edit to coverage_gate was
    # silently ignored.
    coverage_threshold = float(cfg.get_sync("threshold.backfill.coverage_gate", 0.80))
    insert_batch_size = int(
        cfg.get_sync("infra.backfill.insert_batch_size", _INSERT_BATCH_SIZE_DEFAULT)
    )
    # todo 216: BLAS thread cap, see make_worker_pool()/limit_blas_threads().
    blas_threads_per_worker = int(cfg.get_sync("infra.blas_threads_per_worker", 1))

    # Warm-up bars = dominant rolling window (momentum_zscore_window = 252)
    warm_up_bars = config.momentum_zscore_window

    # Pre-load cross-asset ETF bars and build incremental causal series (once for all symbols).
    # TIP/HYG/LQD (Phase 151 Plan 04) added alongside SPY/TLT/SHY -- _fetch_bars_from_db
    # already reads market_data_ohlcv_tradeable (post todo-124 fix), so extending it to
    # these 3 new symbols inherits that correctness for free.
    spy_bars = _fetch_bars_from_db(db_conn, _SPY, "1d")
    tlt_bars = _fetch_bars_from_db(db_conn, _TLT, "1d")
    shy_bars = _fetch_bars_from_db(db_conn, _SHY, "1d")
    tip_bars = _fetch_bars_from_db(db_conn, _TIP, "1d")
    hyg_bars = _fetch_bars_from_db(db_conn, _HYG, "1d")
    lqd_bars = _fetch_bars_from_db(db_conn, _LQD, "1d")
    _logger.info(
        "cross_asset_loaded",
        spy=len(spy_bars),
        tlt=len(tlt_bars),
        shy=len(shy_bars),
        tip=len(tip_bars),
        hyg=len(hyg_bars),
        lqd=len(lqd_bars),
    )
    cross_asset_by_date = _build_cross_asset_series(
        spy_bars, tlt_bars, shy_bars, tip_bars, hyg_bars, lqd_bars, config
    )
    _logger.info("cross_asset_series_built", dates=len(cross_asset_by_date))

    contracts = get_active_contracts(settings)
    etf_contracts = _filter_etf_contracts(contracts, symbols)
    all_symbols = [c.symbol for c in etf_contracts]
    status_map = _load_status_map(db_conn, all_symbols, target_timeframes)
    coverage: dict[tuple[str, str], dict] = {}
    dsn = settings.database_url

    # Collect symbols that need compute (skip already-complete and unfetched).
    # refresh=True (todo 176) bypasses the status='complete' checkpoint skip --
    # a pair already marked complete still gets reprocessed and upserted, since the
    # whole point of recompute mode is to revisit rows a normal run would treat as done.
    pending_symbols: list[str] = []
    for instrument in etf_contracts:
        symbol = instrument.symbol
        needs_compute = False
        for tf in target_timeframes:
            key = (symbol, tf)
            existing = status_map.get(key, {})
            if existing.get("status") == "complete" and not refresh:
                rows_written = existing.get("rows_written", 0) or 0
                theoretical = existing.get("theoretical_max", 0) or 0
                pct = rows_written / theoretical if theoretical > 0 else 0.0
                coverage[key] = {
                    "rows_written": rows_written,
                    "theoretical_max": theoretical,
                    "pct": pct,
                }
                _logger.info("compute_skip_complete", symbol=symbol, tf=tf)
            elif not existing.get("fetch_complete"):
                _logger.warning("compute_skip_no_fetch", symbol=symbol, tf=tf)
            else:
                needs_compute = True
                # Mark in_progress on main connection before handing off to worker
                with db_conn.cursor() as cur:
                    cur.execute(_MARK_COMPUTE_STATUS_SQL, (symbol, tf, "in_progress"))
                # db_conn.autocommit=True — no explicit commit needed

        if needs_compute:
            pending_symbols.append(symbol)

    if not pending_symbols:
        return coverage, coverage_threshold

    # Close main connection before spawning workers — connections are not picklable
    db_conn.close()

    worker_args = [
        (
            symbol,
            target_timeframes,
            dsn,
            config,
            pipeline_version,
            warm_up_bars,
            cross_asset_by_date,
            refresh,
            insert_batch_size,
        )
        for symbol in pending_symbols
    ]

    _logger.info(
        "compute_stage_parallel",
        pending_symbols=len(pending_symbols),
        n_workers=n_workers,
    )

    with _make_worker_pool(n_workers, blas_threads_per_worker) as pool:
        for result in pool.map(_run_compute_worker, worker_args, chunksize=1):
            symbol = result["symbol"]
            if result["error"]:
                _logger.error(
                    "compute_worker_failed",
                    symbol=symbol,
                    error=result["error"],
                )
            for cell in result["results"]:
                tf = cell["tf"]
                key = (symbol, tf)
                coverage[key] = {
                    "rows_written": cell["rows_written"],
                    "theoretical_max": cell["theoretical_max"],
                    "pct": cell["pct"],
                }
                if cell.get("error"):
                    _logger.error(
                        "compute_cell_failed",
                        symbol=symbol,
                        tf=tf,
                        error=cell["error"],
                    )
                elif cell["pct"] < coverage_threshold:
                    _logger.warning(
                        "coverage_below_threshold",
                        symbol=symbol,
                        tf=tf,
                        rows_written=cell["rows_written"],
                        theoretical_max=cell["theoretical_max"],
                        pct=round(cell["pct"], 4),
                        threshold=coverage_threshold,
                    )
                else:
                    _logger.info(
                        "compute_complete",
                        symbol=symbol,
                        tf=tf,
                        rows_written=cell["rows_written"],
                        theoretical_max=cell["theoretical_max"],
                        pct=round(cell["pct"], 4),
                    )

    return coverage, coverage_threshold


def _run_compute_worker(args: tuple) -> dict:
    """Worker function for ProcessPoolExecutor — runs in subprocess.

    Opens its own psycopg connection (connections are not picklable and
    must not be shared across processes). No OTel tracer — workers log only;
    main process aggregates results and emits metrics.

    Args:
        args: (symbol, tfs, dsn, config, pipeline_version, warm_up_bars,
               cross_asset_by_date, refresh, insert_batch_size)
               Packed as a tuple for ProcessPoolExecutor.map compatibility.

    Returns:
        dict with keys: symbol, results (list of {tf, rows_written, theoretical_max,
        pct, error?}), error (str|None)
    """
    (
        symbol,
        tfs,
        dsn,
        config,
        pipeline_version,
        warm_up_bars,
        cross_asset_by_date,
        refresh,
        insert_batch_size,
    ) = args

    # Initialize logging in subprocess (each process needs its own handler)
    setup_service_logging("logs/backfill_feature_factory.log")
    worker_log = structlog.get_logger(__name__)

    conn = None
    results = []
    error_msg = None

    try:
        conn = psycopg.connect(dsn)
        # autocommit=True prevents InFailedSqlTransaction from poisoning later TFs
        # on per-cell exceptions; no conn.rollback() needed.
        conn.autocommit = True
        # No register_uuid() equivalent needed -- psycopg adapts uuid.UUID natively.

        for tf in tfs:
            try:
                rows_written = _compute_symbol_tf(
                    conn=conn,
                    symbol=symbol,
                    tf=tf,
                    config=config,
                    pipeline_version=pipeline_version,
                    warm_up_bars=warm_up_bars,
                    cross_asset_by_date=cross_asset_by_date,
                    refresh=refresh,
                    insert_batch_size=insert_batch_size,
                )

                depth_years = _DEPTH_YEARS[tf]
                theoretical = _theoretical_max(tf, depth_years, warm_up_bars)
                pct = rows_written / theoretical if theoretical > 0 else 0.0

                with conn.cursor() as cur:
                    cur.execute(
                        _MARK_COMPUTE_COMPLETE_SQL,
                        (rows_written, theoretical, symbol, tf),
                    )

                results.append(
                    {
                        "tf": tf,
                        "rows_written": rows_written,
                        "theoretical_max": theoretical,
                        "pct": pct,
                    }
                )

            except Exception as error:
                error_str = str(error)
                worker_log.error(
                    "worker_cell_failed",
                    symbol=symbol,
                    tf=tf,
                    error=error_str,
                )
                try:
                    with conn.cursor() as cur:
                        cur.execute(_MARK_COMPUTE_FAILED_SQL, (error_str, symbol, tf))
                except Exception:
                    pass
                results.append(
                    {
                        "tf": tf,
                        "rows_written": 0,
                        "theoretical_max": 0,
                        "pct": 0.0,
                        "error": error_str,
                    }
                )

    except Exception as error:
        error_msg = str(error)
        worker_log.error("worker_failed", symbol=symbol, error=error_msg)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    return {"symbol": symbol, "results": results, "error": error_msg}


def _compute_symbol_tf(
    conn: Any,
    symbol: str,
    tf: str,
    config: FeatureFactoryConfig,
    pipeline_version: str,
    warm_up_bars: int,
    cross_asset_by_date: dict,
    refresh: bool = False,
    insert_batch_size: int = _INSERT_BATCH_SIZE_DEFAULT,
) -> int:
    """Compute FeatureVectors for one (symbol, tf) pair.

    Post-injects four groups of corrected values into every FeatureVector:
      1. Cross-asset (vix_z, flight_quality, yield_slope_z, tip_tlt_ret_z,
         hyg_lqd_ret_z, sb_corr_fast/slow/z): from pre-built incremental
         causal series keyed by date.
      2. Factor betas (equity_beta_z, rate_beta_z, Phase 151 Plan 04): from a
         per-symbol O(D) incremental series keyed by date, built fresh for
         each (symbol, tf) call alongside the CTF build below (daily grain,
         broadcast to all timeframes -- rebuilding per tf costs one extra
         O(D) pass over ~5K daily bars, trivial next to the 5m/15m/1h fetch).
      3. CTF (ctf_momentum, ctf_vwap_align, ctf_regime_align): from O(n) single-pass
         series keyed by HTF bar timestamp; looked up by bisect for each source bar.
      4. VP/SR (poc_dist_atr, va_position, + 17 structural fields): computed from OHLCV
         via FeatureCache.update_session_vp() / _compute_sr_dist_atr() (Phase 163), the
         identical mechanism the live path uses (D-05 -- the prior claim that this group
         was uncomputable in batch was a stale, never-verified assumption).
      5. Named Interaction Primitives cross-TF divergences (ret_div_1m_5m/5m_1h/
         1h_1d, Phase 151 Plan 05): ret_div_5m_1h/1h_1d reuse CtfValues'
         htf_last_log_ret (extended alongside CTF above); ret_div_1m_5m reads a
         separate O(n+m) causal merge-walk series (ltf_ret_by_ts, tf=="5m" only).

    Returns total rows inserted into feature_vectors.
    """
    # Build CTF series for this symbol (O(n) single pass over HTF bars)
    htf_tf = _CTF_HIGHER_TF.get(tf)
    ctf_by_ts: dict = {}
    htf_ts_list: list = []
    if htf_tf:
        htf_bars = _fetch_bars_from_db(conn, symbol, htf_tf)
        if htf_bars:
            ctf_by_ts = _rekey_ctf_series_to_actual_close(
                _build_ctf_series(htf_bars, config), tf, htf_tf
            )
            htf_ts_list = sorted(ctf_by_ts.keys())
            _logger.debug(
                "ctf_series_built", symbol=symbol, tf=tf, htf_tf=htf_tf, htf_bars=len(htf_bars)
            )

    # Build per-symbol factor-beta series (O(D) single pass over daily bars,
    # Phase 151 Plan 04). Daily grain regardless of `tf` -- see docstring above.
    symbol_1d_bars = _fetch_bars_from_db(conn, symbol, "1d")
    spy_1d_bars = _fetch_bars_from_db(conn, _SPY, "1d")
    tlt_1d_bars = _fetch_bars_from_db(conn, _TLT, "1d")
    beta_by_date = _build_symbol_beta_series(
        symbol_1d_bars, spy_1d_bars, tlt_1d_bars, symbol, config
    )

    cache = FeatureCache()
    bars = _fetch_bars_from_db(conn, symbol, tf)
    total_bars = len(bars)

    # ret_div_1m_5m's LTF series (Phase 151 Plan 05, todo 066): only built at
    # tf=="5m" -- 1m OHLCV coverage is 2026-03-23..2026-06-23 versus 5m's
    # 2006-06-02..2026-07-07, so this is a real, documented ~1% coverage
    # limitation (migration comment + SUMMARY), not an implementation defect.
    ltf_ret_by_ts: dict = {}
    if tf == "5m":
        ltf_bars = _fetch_bars_from_db(conn, symbol, "1m")
        if ltf_bars:
            ltf_ret_by_ts = _build_ltf_return_series(ltf_bars, [b["ts"] for b in bars])

    if total_bars < warm_up_bars + 2:
        _logger.warning(
            "insufficient_bars",
            symbol=symbol,
            tf=tf,
            bars=total_bars,
            warm_up_bars=warm_up_bars,
        )
        return 0

    _logger.info("compute_bars_loaded", symbol=symbol, tf=tf, total_bars=total_bars)

    batch_results = FeatureFactory.compute_batch(
        bars,
        symbol,
        tf,
        cache,
        config,
        warm_up_bars=warm_up_bars,
        cross_asset_by_date=cross_asset_by_date,
        ctf_by_ts=ctf_by_ts or None,
        ctf_ts_list=htf_ts_list or None,
        beta_by_date=beta_by_date or None,
        ltf_ret_by_ts=ltf_ret_by_ts or None,
    )

    # Coverage log (Phase 151 Plan 05): once per (symbol, tf), never per row
    # (CLAUDE.md's never-log-per-row-over-the-corpus rule). Counts how many
    # emitted vectors carry a non-None value for each of the 3 divergences.
    _n_ret_div_1m_5m = sum(1 for _, fv in batch_results if fv.ret_div_1m_5m is not None)
    _n_ret_div_5m_1h = sum(1 for _, fv in batch_results if fv.ret_div_5m_1h is not None)
    _n_ret_div_1h_1d = sum(1 for _, fv in batch_results if fv.ret_div_1h_1d is not None)
    _logger.info(
        "cross_tf_divergence_coverage",
        symbol=symbol,
        tf=tf,
        total_bars=len(batch_results),
        ret_div_1m_5m_non_none=_n_ret_div_1m_5m,
        ret_div_5m_1h_non_none=_n_ret_div_5m_1h,
        ret_div_1h_1d_non_none=_n_ret_div_1h_1d,
    )

    insert_batch: list[tuple] = []
    total_inserted = 0
    skipped_non_trading = 0

    # Market calendar for trading day filtering (Renaissance: filter at source)
    calendar = get_market_calendar()
    exchange = "NYSE"  # ETFs trade on NYSE/NASDAQ/ARCA with identical hours

    for bar_ts, fv in batch_results:
        if not calendar.is_trading_bar(exchange, bar_ts, tf):
            skipped_non_trading += 1
            continue

        row = _vector_to_params(
            symbol=symbol,
            tf=tf,
            bar_ts=bar_ts,
            pipeline_version=pipeline_version,
            regime=None,
            fv=fv,
        )
        insert_batch.append(row)

        if len(insert_batch) >= insert_batch_size:
            _batch_insert(conn, insert_batch, refresh=refresh)
            total_inserted += len(insert_batch)
            insert_batch = []
            _logger.debug(
                "compute_progress",
                symbol=symbol,
                tf=tf,
                inserted=total_inserted,
                total_bars=total_bars,
            )

    if insert_batch:
        _batch_insert(conn, insert_batch, refresh=refresh)
        total_inserted += len(insert_batch)

    _logger.info(
        "compute_complete",
        symbol=symbol,
        tf=tf,
        total_bars=total_bars,
        inserted=total_inserted,
        skipped_non_trading=skipped_non_trading,
        skip_pct=round(skipped_non_trading / total_bars * 100, 2) if total_bars > 0 else 0,
    )

    return total_inserted


def _batch_insert(conn: Any, rows: list[tuple], refresh: bool = False) -> None:
    """Batch-insert feature_vectors rows via psycopg executemany().

    refresh=True selects the DO UPDATE variant (todo 176 recompute mode) so
    existing rows are actually overwritten instead of silently skipped.
    """
    if not rows:
        return
    sql = _UPSERT_FEATURE_VECTORS_SQL if refresh else _INSERT_FEATURE_VECTORS_SQL
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()


def _log_coverage_report(coverage: dict[tuple[str, str], dict], coverage_threshold: float) -> None:
    """Log per-pair coverage vs theoretical_max; flag pairs below the APR coverage threshold."""
    below_threshold: list[tuple[str, str, int, int, float]] = []
    for (symbol, tf), data in sorted(coverage.items()):
        pct = data.get("pct", 0.0)
        rows = data.get("rows_written", 0)
        theoretical = data.get("theoretical_max", 0)
        if pct < coverage_threshold:
            below_threshold.append((symbol, tf, rows, theoretical, pct))

    _logger.info(
        "coverage_report",
        total_pairs=len(coverage),
        below_threshold=len(below_threshold),
        threshold=coverage_threshold,
    )

    if below_threshold:
        _logger.warning(
            "coverage_below_threshold",
            pairs=[
                {"symbol": s, "tf": t, "rows": r, "theoretical": th, "pct": round(p, 4)}
                for s, t, r, th, p in below_threshold
            ],
            threshold=coverage_threshold,
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill Feature Factory — two-stage IBKR fetch + FeatureFactory compute"
    )
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Only run Stage 1 (IBKR fetch into market_data_ohlcv), skip compute",
    )
    parser.add_argument(
        "--compute-only",
        action="store_true",
        help="Only run Stage 2 (FeatureFactory compute into feature_vectors), skip IBKR fetch",
    )
    parser.add_argument(
        "--client-id",
        type=int,
        default=_DEFAULT_CLIENT_ID,
        help=f"IBKR client ID (default: {_DEFAULT_CLIENT_ID}; provider uses 35; max 50)",
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated symbols to limit scope, e.g. SPY,TLT (default: all active ETFs)",
    )
    parser.add_argument(
        "--pipeline-version",
        default="3.0.0",
        help="Pipeline version string stamped on feature_vectors rows (default: 3.0.0)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: APR infra.feature_factory.workers, fallback 1)",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "Recompute mode (todo 176; naming matches ic_engine.py's --refresh, same "
            "concept -- force full recompute, bypassing the checkpoint): overwrites "
            "existing feature_vectors rows via ON CONFLICT DO UPDATE instead of the "
            "default DO NOTHING skip, and ignores backfill_status.status='complete' "
            "checkpoints so already-computed pairs are reprocessed too. Use when "
            "feature-computation logic or the schema (new columns) changed since the "
            "corpus was last built -- default mode will silently leave new columns "
            "NULL on every pre-existing row otherwise."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    symbols: list[str] | None = None
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    settings = Settings()
    db_conn = _connect_db(settings)

    run_fetch = not args.compute_only
    run_compute = not args.fetch_only

    # Load n_workers from CLI arg or APR. Use a short-lived query on the main
    # connection before workers spawn; run_compute_stage closes db_conn itself.
    n_workers: int = 1
    if args.workers is not None:
        n_workers = args.workers
    elif run_compute:
        cfg_tmp = _load_config_service(db_conn)
        n_workers = int(cfg_tmp.get_sync("infra.feature_factory.workers", 1))

    _logger.info(
        "backfill_start",
        run_fetch=run_fetch,
        run_compute=run_compute,
        client_id=args.client_id,
        symbols=symbols,
        pipeline_version=args.pipeline_version,
        n_workers=n_workers,
    )

    coverage: dict[tuple[str, str], dict] = {}

    try:
        if run_fetch:
            _logger.info("stage1_start")
            asyncio.run(
                run_fetch_stage(
                    settings=settings,
                    client_id=args.client_id,
                    symbols=symbols,
                    db_conn=db_conn,
                )
            )
            _logger.info("stage1_complete")

        if run_compute:
            _logger.info("stage2_start")
            # run_compute_stage closes db_conn before spawning workers.
            # Do not close db_conn in finally when compute ran.
            coverage, coverage_threshold = run_compute_stage(
                settings=settings,
                symbols=symbols,
                db_conn=db_conn,
                pipeline_version=args.pipeline_version,
                n_workers=n_workers,
                refresh=args.refresh,
            )
            db_conn = None  # already closed inside run_compute_stage
            _log_coverage_report(coverage, coverage_threshold)
            _logger.info("stage2_complete", pairs_computed=len(coverage))

        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": "success"})
        _logger.info("backfill_complete")

    except Exception as error:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": "failure"})
        _logger.error("backfill_failed", error=str(error))
        raise
    finally:
        if db_conn is not None:
            db_conn.close()
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    try:
        init_otel_providers("backfill-feature-factory")
    except OTelInitError as error:
        print(f"[warn] OTel init failed — metrics disabled: {error}")
    main()
