"""Bid-ask spread estimators from OHLC bars (todo 553): Corwin-Schultz and Roll.

Both outputs are proportional spreads (a fraction of price, 0.01 = 1%), so they compare across
names and price levels. Amihud illiquidity, the third OHLCV liquidity proxy, is `amihud_illiq_z`
in kernels/volume.py.

Input contract. The kernels are pure functions of the bars they are handed and never fill. The
caller hands them tradeable bars only (`market_data_ohlcv_tradeable`, volume > 0: no
synthetic-fill or carry-forward placeholder bar reaches them, because a placeholder's flat
high == low == previous close would read as a zero-spread bar). A value the definition leaves
undefined is NaN (no_fill): a window holding an unusable bar, rows inside the declared memory,
and the Roll estimate whenever the serial covariance is not negative.

Windows are counted in bars at every timeframe. One APR key per estimator serves 5m, 15m, 1h
and 1d alike; the window rationale (21 = a month of daily estimates, 252 = a year of daily
returns) holds only on 1d. Consequences a reader must carry:

- Levels are not comparable across timeframes: an intraday spread estimate from 5m ranges is not
  the 1d estimate at a finer clock, so compare a column within one timeframe only.
- An intraday Roll window spans session boundaries, so it holds overnight returns, whose serial
  covariance is not the bid-ask bounce Roll models.
- A flat bar (high == low, about 1.7% of 15m bars since 2024) has a zero one-bar range, which
  pushes its Corwin-Schultz pairs toward a negative estimate, floored to 0 (always when both
  bars of a pair are flat and the prices moved).

Roll coverage. `roll_spread` is NaN on a large share of rows after warmup: on canonical 1d about
40% (per-name median 0.41, p95 0.63 over 145 names), and about 15% even on a simulated series
with a clean 1% spread. The missingness is informative, not random: a non-negative serial
covariance is what trending regimes produce, so the NaN rows select on the return process.
Research must never treat a missing `roll_spread` as missing at random (no listwise deletion or
imputation without conditioning on it).

Vendor seam (D-191-Q, D-191-P). Canonical 1d and 5m bars are Alpaca SIP from 2016-01-04 and
IBKR before (with dated per-name policy rows as exceptions). Neither kernel branches on the
vendor (asset_agnostic): a window that spans the seam is computed like any other window, from
whichever bars canonical holds. The seam is disclosed, not corrected:

- Both estimators read only ratios of prices (log high/low ranges, log close-to-close changes),
  so a constant price-level difference between two vendors cancels within each era. What can
  move at the seam is the range basis: SMART TRADES highs and lows against consolidated SIP.
  Measured on raw 1d over the full vendor overlap (1,162 names, 560,005 sessions): the IBKR over
  Alpaca ratio of ln(high / low) has median 1.000, p05 to p95 0.975 to 1.018 and p99 1.062. The
  per-name level ratio of the estimates is 0.991 to 1.018 for Corwin-Schultz and 0.985 to 1.025
  for Roll, so the seam moves either level by about 2% at most.
- A price-level step between the last IBKR bar and the first Alpaca bar is not a property of
  the seam but a data defect the D-191-Q three-vendor arbitration owns (an IBKR symbol row or
  an owner hold for the span). Where one survives, every cross-bar statistic sees it, these two
  included: the spurious return enters every Roll window that holds it (up to `window` rows),
  and the shifted Corwin-Schultz pair (bounded by the overnight adjustment, never undefined)
  enters up to `window` window means (21 at the seed). The worst case in canonical 1d today is
  AXSM on 2016-01-04 at a level ratio of 1.31, and 4 steps above 10% exist. The kernels do not
  detect or repair it.
- Volume is not an input here, so the 2016 volume-basis step does not touch either output.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from src.intelligence.features.kernels._primitives import _k

# Corwin and Schultz (2012) eq. 18 denominator, 3 - 2 * sqrt(2): a constant of the estimator.
_CS_K = 3.0 - 2.0 * math.sqrt(2.0)


def _high_low_spread_series_full(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, window: int
) -> np.ndarray:
    """Corwin-Schultz (2012) high-low spread, averaged over the trailing `window` two-bar pairs.

    For the pair of bars (t-1, t):

        beta  = ln(H[t-1] / L[t-1])^2 + ln(H[t] / L[t])^2
        gamma = ln(max(H[t-1], H[t]) / min(L[t-1], L[t]))^2
        alpha = (sqrt(2 beta) - sqrt(beta)) / (3 - 2 sqrt 2) - sqrt(gamma / (3 - 2 sqrt 2))
        S     = 2 (e^alpha - 1) / (1 + e^alpha)

    Overnight adjustment (the paper's own correction for non-trading periods): when bar t's low is above bar t-1's close,
    bar t's high and low are both lowered by the difference; when bar t's high is below that
    close, both are raised by it. The adjustment keeps an overnight move from reading as range.

    Negative estimates are set to 0 before averaging, the paper's main convention (it sets
    negative two-day spreads to zero before taking monthly averages and reports the variant
    that keeps them only as a robustness check). S < 0 exactly when
    alpha < 0, which happens when the two-bar range is large against the one-bar ranges (an
    overnight move the adjustment does not catch, or volatility dominating the spread). A
    negative spread is not a spread, and NaN would be wrong in a different way: dropping only
    the low estimates and averaging the rest biases the window mean upward. Zero keeps the
    pair in the average as "no measurable spread", which is what the paper does.

    Output row t is the mean of the `window` pair estimates ending at t, so it reads bars
    t - window .. t (declared memory `window`). Rows t < window are NaN. A pair is NaN when a
    price it reads is not positive or a high is below its low (including after the overnight
    adjustment against a zero close), when bar t-1's close is not finite (the adjustment cannot
    be made, and an unadjusted pair would be a silent wrong answer), and a window holding a NaN pair is NaN: never averaged
    over fewer pairs.
    """
    n = len(closes)
    out = np.full(n, np.nan)
    if window < 1:
        raise ValueError(f"high_low_spread window must be >= 1, got {window}")
    if n < window + 1:
        return out
    h = highs.astype(float)
    lo = lows.astype(float)
    c = closes.astype(float)
    h0, l0 = h[:-1], lo[:-1]
    h1, l1, prev_close = h[1:], lo[1:], c[:-1]
    shift = np.where(l1 > prev_close, l1 - prev_close, 0.0) + np.where(
        h1 < prev_close, h1 - prev_close, 0.0
    )
    h1 = h1 - shift
    l1 = l1 - shift
    valid = np.isfinite(prev_close) & (l0 > 0.0) & (l1 > 0.0) & (h0 >= l0) & (h1 >= l1)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        beta = np.log(h0 / l0) ** 2 + np.log(h1 / l1) ** 2
        gamma = np.log(np.maximum(h0, h1) / np.minimum(l0, l1)) ** 2
        alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / _CS_K - np.sqrt(gamma / _CS_K)
        e = np.exp(alpha)
        pair = 2.0 * (e - 1.0) / (1.0 + e)
    pair = np.where(valid, np.maximum(pair, 0.0), np.nan)
    out[window:] = sliding_window_view(pair, window).mean(axis=1)
    return out


def _roll_spread_series_full(closes: np.ndarray, window: int) -> np.ndarray:
    """Roll (1984) implied spread from the serial covariance of log close changes.

        r[t]   = ln(C[t] / C[t-1])
        cov[t] = sample covariance (ddof 1) of r[j] and r[j-1] over j = t - window + 1 .. t
        S[t]   = 2 sqrt(-cov[t])   when cov[t] < 0, else NaN

    Roll's model implies a negative serial covariance; a covariance >= 0 has no implied spread,
    so the value is NaN (missing), never 0 and never a sign-flipped root. This is frequent (about
    40% of 1d rows after warmup) and informative: see the module docstring's Roll coverage. Using log changes makes
    the spread proportional to price rather than in price units.

    Output row t reads closes t - window - 1 .. t (declared memory `window + 1`). Rows
    t <= window are NaN. A window holding a non-positive close is NaN.
    """
    n = len(closes)
    out = np.full(n, np.nan)
    if window < 2:
        raise ValueError(f"roll_spread window must be >= 2, got {window}")
    if n < window + 2:
        return out
    c = closes.astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        log_c = np.log(np.where(c > 0.0, c, np.nan))
    r = np.diff(log_c)
    x = sliding_window_view(r[1:], window)
    y = sliding_window_view(r[:-1], window)
    dx = x - x.mean(axis=1, keepdims=True)
    dy = y - y.mean(axis=1, keepdims=True)
    cov = (dx * dy).sum(axis=1) / (window - 1)
    with np.errstate(invalid="ignore"):
        out[window + 1 :] = np.where(
            cov < 0.0, 2.0 * np.sqrt(np.where(cov < 0.0, -cov, 0.0)), np.nan
        )
    return out


def _compute_high_low_spread(x, config):
    return {
        "high_low_spread": _high_low_spread_series_full(
            x["high"], x["low"], x["close"], config.high_low_spread_window
        )
    }


def _compute_roll_spread(x, config):
    return {"roll_spread": _roll_spread_series_full(x["close"], config.roll_spread_window)}


KERNELS = (
    _k(
        "high_low_spread",
        ("high_low_spread",),
        ("high", "low", "close"),
        lambda c: c.high_low_spread_window,
        _compute_high_low_spread,
    ),
    _k(
        "roll_spread",
        ("roll_spread",),
        ("close",),
        lambda c: c.roll_spread_window + 1,
        _compute_roll_spread,
    ),
)
