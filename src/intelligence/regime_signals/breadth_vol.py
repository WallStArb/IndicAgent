"""breadth_vol -- Equity cross-sectional regime signal.

Signal 1 (vix_pct): SPY realized-vol z-score causal expanding percentile rank.
  Low vol -> "low". High vol -> "high". Middle -> "mid".

Signal 2 (breadth_frac): Fraction of ref_bars symbols with close > MA.
  Majority above -> "bull". Majority below -> "bear". Mixed -> "neutral".

Label format: {vix_tier}_{breadth_tier}  e.g. "low_bull", "high_bear", "mid_neutral".
9 possible labels (3 x 3).

Logic ported from services/equity_regime_model.py -- no DB calls here (DB-free pure
functions per the compute != persistence SoC rule).

CORRECTNESS INVARIANT (RESEARCH.md Pitfall 1 / Pattern 4): the vix_pct rank MUST use a
causal bisect-based expanding rank, never a whole-series percentile rank (pandas'
`Series.rank` with `pct` True) -- that ranks every point against future values too,
reintroducing the exact look-ahead bias Phase 141's P0-T2 fix removed from
equity_regime_model.py. Ported verbatim from equity_regime_model.py:186-251 (guarded by
tests/unit/test_regime_signals_breadth_vol.py's causal-property test).

TF-scaling convention (RESEARCH.md Pattern 5): `compute()` receives ALREADY-bar-scaled
window ints in `params` -- the dispatcher (services/cross_sectional_regime_model.py,
Plan 04) pre-scales day-denominated APR window values via `_tf_window()` before calling
this module. This module stays TF-agnostic; it does not call `_tf_window()` itself.
"""

from __future__ import annotations

import bisect
import math
from typing import Any

import numpy as np
import pandas as pd

PROB_KEYS: tuple[str, str] = ("vix_pct", "breadth_frac")


def compute(
    ref_bars: dict[str, pd.DataFrame],
    params: dict[str, Any],
) -> tuple[pd.Series, pd.Series] | None:
    """Compute (vix_pct_rank, breadth_fraction) series from pre-fetched peer bars.

    SPY must be present in ref_bars (used for realized-vol VIX proxy).
    All symbols in ref_bars contribute to the breadth signal.

    Returns None if SPY bars are missing or insufficient for warmup.
    Both returned series are indexed by timestamp and share the same index.
    NaN values indicate warmup bars -- caller drops them before dispatch.

    ref_bars/params are the only inputs -- no psycopg2 import, no DB access.
    """
    if "SPY" not in ref_bars:
        return None

    realized_vol_window = int(params.get("realized_vol_window", 20))
    vix_z_window = int(params.get("vix_z_window", 252))
    ma_window = int(params.get("ma_window", 200))

    spy_df = ref_bars["SPY"].set_index("timestamp").sort_index()
    spy_close = spy_df["close"].astype(float)

    if len(spy_close) < realized_vol_window + vix_z_window:
        return None

    vix_pct = _compute_vix_pct_rank(spy_close, realized_vol_window, vix_z_window)
    breadth = _compute_breadth(ref_bars, ma_window)

    return vix_pct, breadth.reindex(vix_pct.index)


def build_tiers(params: dict[str, Any]) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Return threshold tier lists for the generic label worker.

    tiers1: VIX percentile buckets.
    tiers2: breadth fraction buckets.
    Each list: [(tier_name, upper_bound), ...] sorted ascending; last upper_bound = inf.
    """
    vix_low = float(params.get("vix_low_pct", 0.33))
    vix_high = float(params.get("vix_high_pct", 0.67))
    bread_bear = float(params.get("breadth_bear", 0.40))
    bread_bull = float(params.get("breadth_bull", 0.60))
    return (
        [("low", vix_low), ("mid", vix_high), ("high", float("inf"))],
        [("bear", bread_bear), ("neutral", bread_bull), ("bull", float("inf"))],
    )


def _compute_vix_pct_rank(
    spy_close: pd.Series, realized_vol_window: int, vix_z_window: int
) -> pd.Series:
    """SPY realized-vol z-score causal expanding percentile rank.

    Ported verbatim from services/equity_regime_model.py._compute_vix_pct_rank's
    bisect-based logic (Phase 141 P0-T2 look-ahead fix) -- each position is ranked
    only against prior values, never future ones.
    """
    log_ret = np.log(spy_close / spy_close.shift(1))
    realized_vol = log_ret.rolling(
        window=realized_vol_window, min_periods=realized_vol_window
    ).std()
    rv_mean = realized_vol.rolling(window=vix_z_window, min_periods=vix_z_window).mean()
    rv_std = realized_vol.rolling(window=vix_z_window, min_periods=vix_z_window).std()
    vix_z = (realized_vol - rv_mean) / rv_std.where(rv_std > 1e-10)

    # Causal bisect-based expanding rank (no look-ahead bias).
    # Each position's rank is computed against all PRIOR valid values only.
    # NaN guard: skip NaN values (do not insert into window -- preserves bisect sort invariant).
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

    return pd.Series(causal_ranks, index=spy_close.index, dtype=float)


def _compute_breadth(ref_bars: dict[str, pd.DataFrame], ma_window: int) -> pd.Series:
    """Fraction of ref_bars symbols with close > MA, per timestamp.

    Adapted from equity_regime_model.py._compute_breadth_fraction: operates on the
    pre-fetched ref_bars dict (no DB fetch inside this function -- the dispatcher
    fetches bars and passes them in via ref_bars).
    """
    above_ma_cols: list[pd.Series] = []
    for sym, df in ref_bars.items():
        s = df.set_index("timestamp")["close"].astype(float).sort_index()
        if len(s) < ma_window:
            continue
        ma = s.rolling(window=ma_window, min_periods=ma_window).mean()
        above = (s > ma).where(ma.notna()).astype(float)
        above_ma_cols.append(above.rename(sym))
    if not above_ma_cols:
        return pd.Series(dtype=float, name="breadth")
    return pd.concat(above_ma_cols, axis=1).mean(axis=1, skipna=True).rename("breadth")
