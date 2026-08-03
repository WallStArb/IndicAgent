"""breadth_vol -- Equity cross-sectional regime signal.

Signal 1 (vix_pct): SPY realized-vol z-score causal expanding percentile rank.
  Low vol -> "low". High vol -> "high". Middle -> "mid".

Signal 2 (breadth_pct): fraction of ref_bars symbols with close > MA, ITSELF converted to a
  causal expanding percentile rank before bucketing (todo 092 fix, 2026-07-24) -- see
  CALIBRATION note below. Majority-above-history -> "bull". Majority-below-history -> "bear".
  Middle -> "neutral".

Label format: {vix_tier}_{breadth_tier}  e.g. "low_bull", "high_bear", "mid_neutral".
9 possible labels (3 x 3).

Logic ported from services/equity_regime_model.py -- no DB calls here (DB-free pure
functions per the compute != persistence SoC rule).

CORRECTNESS INVARIANT (RESEARCH.md Pitfall 1 / Pattern 4): every signal ranked here MUST use
a causal bisect-based expanding rank, never a whole-series percentile rank (pandas'
`Series.rank` with `pct` True) -- that ranks every point against future values too,
reintroducing the exact look-ahead bias Phase 141's P0-T2 fix removed from
equity_regime_model.py. Rank logic lives in causal_rank.py (shared with curve_credit.py,
todo 092 2026-07-24), guarded by tests/unit/test_regime_signals_causal_rank.py's
causal-property test.

CALIBRATION (todo 092, 2026-07-24): breadth_frac (raw fraction of symbols above their MA)
used to be bucketed directly against a fixed alpha.equity_regime.breadth_bear/breadth_bull
= 0.40/0.60 -- guessed defaults, never checked against the real distribution, unlike
vix_pct (already rank-based, so 0.33/0.67 was population-balanced by construction). Measured
directly: this universe's breadth_frac has median ~0.70 (intraday) / ~0.76 (1d), heavily
right-skewed above the guessed 0.60 "bull" cutoff -- equities spend most of their time with
most symbols above their own trailing MA, so >50% of all bars were pre-classified "bull"
before the regime logic ever ran. Confirmed via market_regimes.regime_label population
counts: low_bull was 12-17x more populated than low_bear across all 4 tfs. Fix: apply the
SAME causal expanding-rank transform already proven for vix_pct to breadth_frac too, then
cut both axes symmetrically at 0.33/0.67. This is self-calibrating (the rank distribution is
population-balanced by construction, permanently, not just at whatever snapshot a new fixed
number was chosen against) rather than a one-time replacement of one guessed number with
another. Changing this changes every downstream market_regimes label, feature_ic_scores
regime stratum, and ensemble_weights/ensemble_alpha regime assignment -- requires a full
historical market_regimes recompute, not just a config flip.

TF-scaling convention (RESEARCH.md Pattern 5): `compute()` receives ALREADY-bar-scaled
window ints in `params` -- the dispatcher (services/cross_sectional_regime_model.py,
Plan 04) pre-scales day-denominated APR window values via `_tf_window()` before calling
this module. This module stays TF-agnostic; it does not call `_tf_window()` itself.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.intelligence.regime_signals.causal_rank import (
    causal_expanding_rank as _causal_expanding_rank,
)

PROB_KEYS: tuple[str, str] = ("vix_pct", "breadth_pct")


def compute(
    ref_bars: dict[str, pd.DataFrame],
    params: dict[str, Any],
) -> tuple[pd.Series, pd.Series] | None:
    """Compute (vix_pct_rank, breadth_pct_rank) series from pre-fetched peer bars.

    SPY must be present in ref_bars (used for realized-vol VIX proxy).
    All symbols in ref_bars contribute to the breadth signal.

    Returns None if SPY bars are missing or insufficient for warmup.
    Both returned series are indexed by timestamp and share the same index.
    NaN values indicate warmup bars -- caller drops them before dispatch.

    ref_bars/params are the only inputs -- no psycopg import, no DB access.
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
    breadth_pct = _causal_expanding_rank(breadth.reindex(vix_pct.index))

    return vix_pct, breadth_pct


def build_tiers(params: dict[str, Any]) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Return threshold tier lists for the generic label worker.

    tiers1: VIX percentile-rank buckets.
    tiers2: breadth percentile-rank buckets (todo 092: rank-based, same construction as
    tiers1, since 2026-07-24 -- see module CALIBRATION note).
    Each list: [(tier_name, upper_bound), ...] sorted ascending; last upper_bound = inf.
    """
    vix_low = float(params.get("vix_low_pct", 0.33))
    vix_high = float(params.get("vix_high_pct", 0.67))
    bread_bear = float(params.get("breadth_bear", 0.33))
    bread_bull = float(params.get("breadth_bull", 0.67))
    return (
        [("low", vix_low), ("mid", vix_high), ("high", float("inf"))],
        [("bear", bread_bear), ("neutral", bread_bull), ("bull", float("inf"))],
    )


def _compute_vix_pct_rank(
    spy_close: pd.Series, realized_vol_window: int, vix_z_window: int
) -> pd.Series:
    """SPY realized-vol z-score causal expanding percentile rank."""
    log_ret = np.log(spy_close / spy_close.shift(1))
    realized_vol = log_ret.rolling(
        window=realized_vol_window, min_periods=realized_vol_window
    ).std()
    rv_mean = realized_vol.rolling(window=vix_z_window, min_periods=vix_z_window).mean()
    rv_std = realized_vol.rolling(window=vix_z_window, min_periods=vix_z_window).std()
    vix_z = (realized_vol - rv_mean) / rv_std.where(rv_std > 1e-10)
    return _causal_expanding_rank(vix_z)


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
