"""Macro kernels: cross-asset and factor-beta pass-through plus the two macro products (D-25).

The daily cross-asset record (`build_cross_asset_series`) and the per-symbol beta record
(`build_symbol_beta_series`) are built by the caller from daily bars; a kernel receives them as
external inputs on the row grid. The contract that keeps them causal is in each external's
`alignment` string: the caller aligns them with `daily_asof_indices`, so a row reads only records
that were available at the row's bar end.

The two builders also live here, and `cross_asset_daily` and `factor_beta_daily` register them
as kernels over a daily reference grid (one row per date, the union of the symbols' 1d dates) so
their declared memory and causality are checked like every other kernel. The batch writer keeps
calling the builders directly; 186-25 reads the kernels.
"""

from __future__ import annotations

import bisect
import math
from bisect import bisect_right
from collections import deque
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, NamedTuple
from zoneinfo import ZoneInfo

import numpy as np
import structlog

from src.core.bar_accumulator import _RTH_CLOSE_ET
from src.core.service_utils import TF_DURATIONS
from src.intelligence.features.contract.registry import Alignment, ExternalInput, Kernel
from src.intelligence.features.kernels._cache_state import _zscore_from_deque
from src.intelligence.features.kernels._primitives import constant_value
from src.intelligence.utils import safe_corr

if TYPE_CHECKING:
    from src.intelligence.feature_factory import FeatureFactoryConfig

_logger = structlog.get_logger(__name__)

_NEW_YORK = ZoneInfo("America/New_York")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_NS_PER_S = 1_000_000_000

MACRO_COLUMNS: tuple[str, ...] = (
    "vix_z",
    "flight_quality",
    "yield_slope_z",
    "tip_tlt_ret_z",
    "hyg_lqd_ret_z",
    "sb_corr_fast",
    "sb_corr_slow",
    "sb_corr_z",
    "equity_beta_z",
    "rate_beta_z",
)

# The eight columns a daily cross-asset record carries; the two betas arrive as a separate pair.
RECORD_COLUMNS: tuple[str, ...] = MACRO_COLUMNS[:8]


def _bar_end_offset_seconds(tf: str) -> int:
    """Seconds from a bar's `ts` to the moment its close is known.

    For 5m and up `ts` is the period start (`TF_DURATIONS`). For 1m, `ts` is documented as the
    close time in `service_utils`, so the offset is 0, which is also the conservative reading if
    it were a start. An unknown timeframe raises rather than defaulting to a duration.
    """
    if tf == "1m":
        return 0
    try:
        return TF_DURATIONS[tf]
    except KeyError:
        raise ValueError(f"unknown timeframe {tf!r}; known: 1m, {sorted(TF_DURATIONS)}") from None


def require_supported_timeframes(timeframes: Sequence[str]) -> None:
    """ValueError naming the first timeframe `daily_asof_index` has no bar duration for."""
    for tf in timeframes:
        _bar_end_offset_seconds(tf)


def bar_ts_ns(bar_ts: datetime) -> int:
    """UTC nanoseconds of a bar start by integer arithmetic; a naive datetime is taken as UTC."""
    if bar_ts.tzinfo is None:
        bar_ts = bar_ts.replace(tzinfo=UTC)
    return (bar_ts - _EPOCH) // timedelta(microseconds=1) * 1000


def _daily_close_ns(day: date) -> int:
    """UTC nanoseconds of the 16:00 ET regular-session close on `day`."""
    close = datetime.combine(day, _RTH_CLOSE_ET, tzinfo=_NEW_YORK)
    return (close.astimezone(UTC) - _EPOCH) // timedelta(microseconds=1) * 1000


def daily_close_availability(daily_dates: Sequence[date]) -> list[int]:
    """UTC nanoseconds at which each daily record becomes available: the 16:00 ET close of its
    date. `daily_dates` must be sorted ascending; ValueError otherwise."""
    available = [_daily_close_ns(d) for d in daily_dates]
    if any(later < earlier for earlier, later in zip(available, available[1:], strict=False)):
        raise ValueError("daily_dates must be sorted ascending")
    return available


def daily_asof_index(row_ts_ns: int, tf: str, available_ns: Sequence[int]) -> int:
    """Index of the latest daily record available at the bar's end, else -1.

    The one availability rule for daily records: a record dated d is available from the 16:00 ET
    close of d, and a row (bar start `row_ts_ns`, timeframe `tf`) can read it when that close is
    at or before the row's bar end, `row_ts_ns` plus the bar duration. `daily_asof_indices` (batch)
    and the live pipeline's cross-asset lookup both call this, so live and batch cannot drift.
    """
    return bisect_right(available_ns, row_ts_ns + _bar_end_offset_seconds(tf) * _NS_PER_S) - 1


def daily_asof_indices(row_ts_ns: np.ndarray, tf: str, available_ns: Sequence[int]) -> np.ndarray:
    """`daily_asof_index` for every row at once: an int64 array, -1 where no record is available.

    Same rule and same result as the scalar (`searchsorted(..., side="right") - 1` over the
    bar end), computed once per call so callers can gather any number of per-date columns with
    one fancy index. A record dated d is available at the 16:00 ET close of d; keying a record
    by the row's UTC date instead reads the same day's close from inside the session, which is
    lookahead on intraday rows. Half-day sessions close before 16:00 ET, so the rule is
    conservative on those days: it only withholds a record that was already available, never
    admits one that was not. An unknown timeframe raises even for an empty row set.
    """
    bar_end = np.asarray(row_ts_ns, dtype=np.int64) + _bar_end_offset_seconds(tf) * _NS_PER_S
    return np.searchsorted(np.asarray(available_ns, dtype=np.int64), bar_end, side="right") - 1


# Cross-asset proxy symbols (Phase 151 Plan 04, moved here by Plan 09 Task 1). Single
# definition project-wide -- previously duplicated as _SPY/_TLT/_SHY/_TIP/_HYG/_LQD
# module constants in services/backfill_feature_factory.py. Exported without the
# leading underscore since this is now a public Ring-1 contract, not a private
# Ring-2 script constant.
SPY = "SPY"
TLT = "TLT"
SHY = "SHY"
TIP = "TIP"
HYG = "HYG"
LQD = "LQD"
CROSS_ASSET_SYMBOLS: tuple[str, ...] = (SPY, TLT, SHY, TIP, HYG, LQD)


class CrossAssetRecord(NamedTuple):
    """8 symbol-independent cross-asset/macro values, one per calendar date.

    vix_z/flight_quality/yield_slope_z are the 3 pre-existing macro features
    (todo 222). tip_tlt_ret_z/hyg_lqd_ret_z/sb_corr_fast/sb_corr_slow/sb_corr_z
    are Phase 151 Plan 04's 5 new symbol-independent additions (the 2 remaining
    new fields, equity_beta_z/rate_beta_z, are per-SYMBOL and therefore carried
    separately -- see `build_symbol_beta_series` below, not this tuple).

    All fields default to 0.0 so `cross_asset_by_date.get(date, CrossAssetRecord())`
    degrades to today's cold-start behaviour with no special-casing at the call site.
    """

    vix_z: float = 0.0
    flight_quality: float = 0.0
    yield_slope_z: float = 0.0
    tip_tlt_ret_z: float = 0.0
    hyg_lqd_ret_z: float = 0.0
    sb_corr_fast: float = 0.0
    sb_corr_slow: float = 0.0
    sb_corr_z: float = 0.0


def _cross_asset_records(
    spy_bars: list[dict],
    tlt_bars: list[dict],
    shy_bars: list[dict],
    tip_bars: list[dict],
    hyg_bars: list[dict],
    lqd_bars: list[dict],
    config: FeatureFactoryConfig,
) -> tuple[dict, int]:
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
    only the affected spread(s) are NaN (missing, no_fill) for that date, so vix_z/yield_slope_z
    are never silently dropped for dates that predate the newer ETFs'
    listings. The count of dates with partial TIP/HYG/LQD coverage is returned with
    the records; `build_cross_asset_series` logs it once (CLAUDE.md's
    never-log-per-row-over-the-corpus rule), so this function stays pure for the kernel.

    Moved verbatim from services/backfill_feature_factory.py's
    _build_cross_asset_series (Plan 151-09 Task 1) -- both the batch script and
    the live daemon (Plan 151-09 Task 2) call this same function, so live and
    batch cannot drift apart by construction.
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
            sb_corr_fast = safe_corr(spy_arr[-fast_n:], tlt_arr[-fast_n:])
            sb_corr_slow = safe_corr(spy_arr[-slow_n:], tlt_arr[-slow_n:])
            sb_corr_history.append(sb_corr_fast)
            sb_corr_z = _zscore_from_deque(sb_corr_history, config.sb_corr_zscore_window)

        # tip_tlt_ret_z / hyg_lqd_ret_z: coverage-guarded -- NaN (missing, not a skip and not a
        # fabricated 0.0 z-score) when TIP/HYG/LQD lack coverage for this date (pre-listing dates,
        # and the first record date, before a previous close exists).
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
            tip_tlt_ret_z = math.nan
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
            hyg_lqd_ret_z = math.nan
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

    return result, n_partial_coverage_dates


def build_cross_asset_series(
    spy_bars: list[dict],
    tlt_bars: list[dict],
    shy_bars: list[dict],
    tip_bars: list[dict],
    hyg_bars: list[dict],
    lqd_bars: list[dict],
    config: FeatureFactoryConfig,
) -> dict:
    """date -> CrossAssetRecord for the batch path and the live daemon (the one public builder).

    Runs `_cross_asset_records` and logs the partial TIP/HYG/LQD coverage count once.
    """
    result, n_partial_coverage_dates = _cross_asset_records(
        spy_bars, tlt_bars, shy_bars, tip_bars, hyg_bars, lqd_bars, config
    )
    if n_partial_coverage_dates:
        _logger.info(
            "cross_asset_series_partial_tip_hyg_lqd_coverage",
            n_dates=n_partial_coverage_dates,
            n_total_dates=len(result),
        )
    return result


def build_symbol_beta_series(
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
    every date when symbol == TLT. Mirrors build_cross_asset_series' O(D)
    incremental alignment pattern (bisect cursors, prev_close trackers).

    Moved verbatim from services/backfill_feature_factory.py's
    _build_symbol_beta_series (Plan 151-09 Task 1).
    """
    is_spy = symbol == SPY
    is_tlt = symbol == TLT

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
                    # ddof=1 matches np.cov's default (sample covariance, divides
                    # by N-1) -- a ddof=0 var here would leave the OLS slope
                    # biased high by N/(N-1) (code review WR-01, Phase 151
                    # post-execution review: ~11% at the schema's minimum
                    # factor_beta_window of 10, ~1.7% at the seeded default of 60).
                    var_spy = float(np.var(spy_arr, ddof=1))
                    cov_spy = float(np.cov(sym_arr, spy_arr)[0, 1])
                    raw_equity_beta = cov_spy / var_spy if var_spy > 1e-12 else 0.0
                    equity_beta_hist.append(raw_equity_beta)
                    equity_beta_z = _zscore_from_deque(
                        equity_beta_hist, config.factor_beta_zscore_window
                    )
                if not is_tlt:
                    tlt_arr = np.array(tlt_ret_hist)
                    var_tlt = float(np.var(tlt_arr, ddof=1))  # see WR-01 note above
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


_CLOSE_EXTERNALS: tuple[str, ...] = tuple(f"ref_{s.lower()}_close" for s in CROSS_ASSET_SYMBOLS)
_SYMBOL_CLOSE_EXTERNAL = "ref_sym_close"

EXTERNAL_INPUTS = (
    *(
        ExternalInput(f"ext_{name}", np.dtype(np.float64), Alignment.DAILY_ASOF_CLOSE)
        for name in MACRO_COLUMNS
    ),
    *(
        ExternalInput(name, np.dtype(np.float64), Alignment.DAILY_REFERENCE_GRID)
        for name in (*_CLOSE_EXTERNALS, _SYMBOL_CLOSE_EXTERNAL)
    ),
)


def _compute_pass_through(x, config):
    return {name: np.asarray(x[f"ext_{name}"], dtype=np.float64).copy() for name in MACRO_COLUMNS}


def _compute_products(x, config):
    return {
        "yield_slope_momentum_product": x["yield_slope_z"] * x["momentum_z_fast"],
        "vix_reversion_product": x["vix_z"] * x["momentum_reversal_z"],
    }


_XA_OUTPUTS: tuple[str, ...] = tuple(f"_xa_{name}" for name in RECORD_COLUMNS)
_BETA_OUTPUTS: tuple[str, ...] = ("_beta_equity_z", "_beta_rate_z")


def daily_reference_grid(series: Mapping[str, Sequence[dict]]) -> dict[str, np.ndarray]:
    """The daily-grid kernel inputs for named daily bar lists.

    `series` maps an external name (`ref_spy_close`, ..., `ref_sym_close`) to its 1d bars. The
    grid has one row per distinct `ts.date()` across all lists, ascending, stamped at 00:00 UTC,
    and each close column is NaN on a date its list has no bar.
    """
    dates = sorted({b["ts"].date() for bars in series.values() for b in bars})
    row = {d: i for i, d in enumerate(dates)}
    out: dict[str, np.ndarray] = {
        "ts": np.array([bar_ts_ns(datetime(d.year, d.month, d.day, tzinfo=UTC)) for d in dates]),
    }
    for name, bars in series.items():
        column = np.full(len(dates), np.nan)
        for b in bars:
            column[row[b["ts"].date()]] = float(b["close"])
        out[name] = column
    return out


def _grid_bars(ts_dt: np.ndarray, closes: np.ndarray) -> list[dict]:
    """The bars a builder reads (date and close) from the finite rows of a grid column."""
    return [
        {"ts": ts_dt[i], "close": float(closes[i])} for i in np.flatnonzero(np.isfinite(closes))
    ]


def _compute_cross_asset_daily(x, config):
    ts_dt = x["ts_dt"]
    records, _ = _cross_asset_records(
        *(_grid_bars(ts_dt, x[name]) for name in _CLOSE_EXTERNALS), config
    )
    out = {name: np.full(len(ts_dt), np.nan) for name in _XA_OUTPUTS}
    for i, stamp in enumerate(ts_dt):
        record = records.get(stamp.date())
        if record is not None:
            for field, name in zip(RECORD_COLUMNS, _XA_OUTPUTS, strict=True):
                out[name][i] = getattr(record, field)
    return out


def cross_asset_records(
    dates: Sequence[date], outputs: Mapping[str, np.ndarray]
) -> dict[date, CrossAssetRecord]:
    """The builder's date to CrossAssetRecord dict rebuilt from the `cross_asset_daily` outputs.

    A date the builder emitted no record for is NaN in every column and is dropped; a record
    always has a finite vix_z, so a present record is never all NaN.
    """
    records: dict[date, CrossAssetRecord] = {}
    for i, d in enumerate(dates):
        values = [float(outputs[name][i]) for name in _XA_OUTPUTS]
        if not all(math.isnan(v) for v in values):
            records[d] = CrossAssetRecord(**dict(zip(RECORD_COLUMNS, values, strict=True)))
    return records


def _compute_factor_beta_daily(x, config):
    ts_dt = x["ts_dt"]
    symbol = constant_value(x["symbol"], "symbol")
    records = build_symbol_beta_series(
        _grid_bars(ts_dt, x[_SYMBOL_CLOSE_EXTERNAL]),
        _grid_bars(ts_dt, x["ref_spy_close"]),
        _grid_bars(ts_dt, x["ref_tlt_close"]),
        symbol,
        config,
    )
    out = {name: np.full(len(ts_dt), np.nan) for name in _BETA_OUTPUTS}
    for i, stamp in enumerate(ts_dt):
        pair = records.get(stamp.date())
        if pair is not None:
            for name, value in zip(_BETA_OUTPUTS, pair, strict=True):
                out[name][i] = np.nan if value is None else value
    return out


def beta_records(
    dates: Sequence[date], outputs: Mapping[str, np.ndarray]
) -> dict[date, tuple[float | None, float | None]]:
    """The beta builder's date to (equity_beta_z, rate_beta_z) dict rebuilt from the outputs.

    NaN is None (SPY has no equity beta, TLT no rate beta); a date with both NaN has no record.
    """
    records: dict[date, tuple[float | None, float | None]] = {}
    for i, d in enumerate(dates):
        pair = tuple(
            None if math.isnan(v) else float(v) for v in (outputs[n][i] for n in _BETA_OUTPUTS)
        )
        if pair != (None, None):
            records[d] = pair  # type: ignore[assignment]
    return records


KERNELS = (
    Kernel(
        name="macro_pass_through",
        outputs=MACRO_COLUMNS,
        inputs=tuple(f"ext_{name}" for name in MACRO_COLUMNS),
        # Pass-through: the path dependence of the builders (flight_quality anchors to the
        # first close, the z-scores accumulate) belongs to the builder kernels 186-15 creates.
        memory=lambda config: 0,
        compute=_compute_pass_through,
    ),
    Kernel(
        name="cross_asset_daily",
        outputs=_XA_OUTPUTS,
        inputs=("ts_dt", *_CLOSE_EXTERNALS),
        memory=lambda config: 0,
        compute=_compute_cross_asset_daily,
        path_dependent=True,
        path_dependent_reason=(
            "flight_quality anchors to the first available close of each series, and the running "
            "z-score histories start at the first record date"
        ),
    ),
    Kernel(
        name="factor_beta_daily",
        outputs=_BETA_OUTPUTS,
        inputs=("ts_dt", _SYMBOL_CLOSE_EXTERNAL, "ref_spy_close", "ref_tlt_close", "symbol"),
        memory=lambda config: config.factor_beta_window + config.factor_beta_zscore_window + 2,
        compute=_compute_factor_beta_daily,
    ),
    Kernel(
        name="macro_products",
        outputs=("yield_slope_momentum_product", "vix_reversion_product"),
        inputs=("yield_slope_z", "momentum_z_fast", "vix_z", "momentum_reversal_z"),
        memory=lambda config: 0,
        compute=_compute_products,
    ),
)
