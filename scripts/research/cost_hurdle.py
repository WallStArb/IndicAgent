"""Personal-scale cost band: the pre-registered minimum-viable-IC hurdle math (plan 186-04).

Promoted from scripts/analysis/personal_cost_hurdle.py (workstream 0b of
docs/plans/2026-09-02-personal-scale-edge-determination-plan.md) and
scripts/analysis/personal_cost_hurdle_by_tf.py, deduplicated into one module of pure
functions plus the pre-registered constants so it survives 186-16's deletion of
scripts/analysis/. The originals' git history keeps the IBKR live-quote validation pull,
the feature_vectors/feature_ic_scores readers and both mains, which read table shapes
phase 186 replaces; they are deliberately NOT promoted (R-13: phase 186 starts no IBKR
jobs; the rebuild replaces those tables).

Hurdle math (standard fundamental-law accounting, stated so it can be checked):

    one_way_cost = spread/2 + commission_frac          (half-spread + commission each way)
    drag_annual  = rebal_per_year * 2 * TO * one_way   (long + short legs, per rebalance)
    net_IR       = IC * sqrt(breadth_total) - drag_annual / sigma
    IC_min       = drag_annual / (sigma * sqrt(breadth_total))

The constants are pre-registered in
docs/plans/2026-09-02-personal-scale-edge-determination-plan.md: they were committed
BEFORE any candidate placement, so changing one after a placement invalidates every
placement made with it. That is why they stay module constants rather than APR keys
(scripts/ is outside the APR mandate's src/ and services/ scope): an APR key is meant to
be tuned, and these numbers must not be.

Under evidence rule E18 these numbers gate PROMOTION (positive net expectation), never
the edge search: test statistics stay gross, and a construction is refused capital, not
refused measurement, when it fails this band.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import psycopg

# --- pre-registered constants (docs/plans/2026-09-02-personal-scale-edge-determination-
# plan.md, workstream 0b; do not retune -- see module docstring) ---
SIGMA_TARGET = 0.16
COMMISSION_PER_SHARE = 0.0035
ASSUMED_PRICE = 50.0
COMMISSION_FRAC = COMMISSION_PER_SHARE / ASSUMED_PRICE
LIVE_SPREAD_ANCHOR = 0.00014  # 1.4bp, measured 0b, validated against live quotes
TRADING_DAYS_PER_YEAR = 252
CS_VALIDATION_BAND = (0.5, 3.0)
SPREAD_SENSITIVITY_BAND = (0.5, 1.0, 2.0)
UNIVERSE_BREADTHS = (4.5, 8.4)  # 0a's measured range
LIBRARY_RANKS = (3.0, 10.0)  # 0b's sensitivity range when not pinned


def corwin_schultz_daily(high: np.ndarray, low: np.ndarray) -> np.ndarray:
    """Daily Corwin-Schultz (2012) high-low spread estimates, negative values floored at
    0; length is len(high) - 1 because the two-day estimator's roll-artifact first row is
    dropped. Body copied unchanged from personal_cost_hurdle.py's `_corwin_schultz_daily`."""
    log_hl = np.log(np.maximum(high, 1e-10) / np.maximum(low, 1e-10))
    beta = log_hl**2 + np.roll(log_hl, 1) ** 2
    beta[0] = log_hl[0] ** 2
    h2 = np.maximum(high, np.roll(high, 1))
    l2 = np.minimum(low, np.roll(low, 1))
    gamma = np.log(np.maximum(h2, 1e-10) / np.maximum(l2, 1e-10)) ** 2
    gamma[0] = log_hl[0] ** 2
    k = 3 - 2 * np.sqrt(2)
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
    spread = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    return np.clip(spread, 0.0, None)[1:]  # drop the roll-artifact first row


def estimate_cs_spreads(
    conn: psycopg.Connection, lookback: str = "2 years", min_bars: int = 250
) -> pd.Series:
    """Per-symbol time-averaged Corwin-Schultz spread over trailing 1d OHLC
    (market_data_ohlcv_tradeable only, per the compute-read boundary). Symbols with fewer
    than `min_bars` bars are skipped. `lookback` is passed as a bound parameter cast
    `%s::interval`, never formatted into the SQL. Callers pass their own connection; this
    module never opens one."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT symbol, timestamp, high, low
            FROM market_data_ohlcv_tradeable
            WHERE timeframe = '1d' AND timestamp >= now() - %s::interval
            ORDER BY symbol, timestamp
            """,
            (lookback,),
        )
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["symbol", "ts", "high", "low"])
    out = {}
    for symbol, g in df.groupby("symbol"):
        arr = g.sort_values("ts")[["high", "low"]].to_numpy()
        if len(arr) < min_bars:
            continue
        daily = corwin_schultz_daily(arr[:, 0], arr[:, 1])
        out[symbol] = float(np.mean(daily))
    return pd.Series(out, name="cs_spread")


def rank_turnover(ranks: pd.DataFrame, horizon: int) -> float | None:
    """Mean absolute cross-sectional rank change per H-unit rebalance (per side).

    Generic over the index unit: `ranks` may be indexed by calendar date (the 1d
    original's per-date percent_rank pivot) or by bar (the intraday original's per-bar
    matrix); `horizon` is measured in the same unit. Body identical to both originals'
    `_turnover`. Returns None when there is not enough history (len(ranks) <= horizon +
    5) or no usable (non-NaN) differences."""
    if len(ranks) <= horizon + 5:
        return None
    diff = (ranks - ranks.shift(horizon)).abs()
    vals = diff.dropna(how="all").to_numpy().ravel()
    vals = vals[~np.isnan(vals)]
    if len(vals) == 0:
        return None
    return float(vals.mean())


def one_way_cost(spread: float, commission_frac: float = COMMISSION_FRAC) -> float:
    """Per-side cost: half-spread plus commission fraction (IBKR tiered 0.0035/share at the
    stated USD 50/share assumption by default)."""
    return spread / 2 + commission_frac


def annual_drag(rebalances_per_year: float, turnover: float, one_way: float) -> float:
    """Annual cost drag. The operation order (`rebalances_per_year * 2 * turnover *
    one_way`) is load-bearing: it keeps `annual_drag(252 / h, ...)` and
    `annual_drag(bars_per_year / h, ...)` bit-identical to the two originals' inline drag
    computations (252/H calendar-day and bars-per-year annualization respectively)."""
    return rebalances_per_year * 2 * turnover * one_way


def ic_min(drag: float, bets: float, sigma: float = SIGMA_TARGET) -> float:
    """Minimum viable gross cross-sectional IC: the IC a construction must exceed to break
    even at this drag and breadth (`bets` = library effective rank x universe breadth)."""
    return drag / (sigma * np.sqrt(bets))
