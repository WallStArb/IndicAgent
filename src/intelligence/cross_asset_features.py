"""Cross-asset feature computation — pure-function module.

No Kafka, no DB, no side effects. All I/O lives in the service layer.
Computes spread z-scores, correlation break, and volume imbalance
for the EQ_INDEX group (ES, NQ, RTY, YM).

Version: 1.0.0
Last Updated: 2026-03-18
"""

from __future__ import annotations

import math
from collections import deque
from datetime import datetime

_EQ_INDEX_BASES: frozenset[str] = frozenset({"ES", "NQ", "RTY", "YM"})

# Number of bars used in the 5-bar log-return window
_SHORT_WINDOW: int = 5
# Default z-score baseline window
_Z_SCORE_WINDOW: int = 20
# Z-score clamp bounds
_Z_CLAMP: float = 10.0
# Threshold below which rolling std is considered near-zero
_LOW_VOL_THRESHOLD: float = 1e-8
# Threshold for a pair to be considered "confirming" a spread divergence
_CONFIRMING_Z_THRESHOLD: float = 2.0


def resolve_eq_index_base(symbol: str) -> str | None:
    """Return the EQ_INDEX base for a full contract symbol, or None if not in the group.

    Matches contract symbols like "ESM6", "NQZ5", "RTYU6", "YMH6" to their base.
    Requires len(symbol) > len(base) to reject bare base strings like "ES".
    """
    for base in _EQ_INDEX_BASES:
        if symbol.startswith(base) and len(symbol) > len(base):
            return base
    return None


def _safe_log_return(prices: list[float], short_window: int) -> float | None:
    """Compute short-window log return: ln(close[-1] / close[-1-short_window]).

    Returns None if denominator is <= 0 or list is too short.
    """
    if len(prices) <= short_window:
        return None
    denom = prices[-(short_window + 1)]
    numer = prices[-1]
    if denom <= 0 or numer <= 0:
        return None
    return math.log(numer / denom)


def _compute_spread_series(
    closes_a: list[float],
    closes_b: list[float],
    short_window: int,
) -> list[float]:
    """Compute the rolling spread series: return_A[i] - return_B[i] for each bar i.

    Uses a sliding window approach: for each position i in [short_window, len-1],
    compute the short-window log return for A and B, then difference them.

    Returns a list of spread values (length = len(closes_a) - short_window).
    """
    n = len(closes_a)
    if n < short_window + 1 or len(closes_b) != n:
        return []
    spread = []
    for i in range(short_window, n):
        denom_a = closes_a[i - short_window]
        denom_b = closes_b[i - short_window]
        if denom_a <= 0 or denom_b <= 0 or closes_a[i] <= 0 or closes_b[i] <= 0:
            continue
        ret_a = math.log(closes_a[i] / denom_a)
        ret_b = math.log(closes_b[i] / denom_b)
        spread.append(ret_a - ret_b)
    return spread


def _z_score_last(values: list[float]) -> tuple[float, bool]:
    """Z-score the last value in `values` against the full series.

    Returns (z_score, low_vol_flag).
    low_vol_flag is True when std < _LOW_VOL_THRESHOLD.
    Z-score is clamped to (-_Z_CLAMP, _Z_CLAMP).
    """
    if not values:
        return 0.0, True
    n = len(values)
    mean = sum(values) / n
    var = sum((x - mean) ** 2 for x in values) / n
    std = math.sqrt(var)
    if std < _LOW_VOL_THRESHOLD:
        return 0.0, True
    raw_z = (values[-1] - mean) / std
    clamped = max(-_Z_CLAMP, min(_Z_CLAMP, raw_z))
    return clamped, False


def _pearson_corr(x: list[float], y: list[float]) -> float | None:
    """Pearson correlation between x and y. Returns None if degenerate."""
    n = len(x)
    if n < 2 or len(y) != n:
        return None
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    sx = math.sqrt(sum((v - mx) ** 2 for v in x))
    sy = math.sqrt(sum((v - my) ** 2 for v in y))
    if sx < _LOW_VOL_THRESHOLD or sy < _LOW_VOL_THRESHOLD:
        return None
    return cov / (sx * sy)


def _compute_corr_break(
    returns_by_symbol: dict[str, list[float]],
    short_window: int,
    long_window: int,
) -> float:
    """Compute eq_corr_break: abs difference between short and long Pearson correlations.

    Uses ES vs NQ as the primary pair (most liquid / most correlated).
    Falls back to 0.0 on degenerate inputs.
    """
    es_ret = returns_by_symbol.get("ES", [])
    nq_ret = returns_by_symbol.get("NQ", [])
    if len(es_ret) < long_window or len(nq_ret) < long_window:
        return 0.0

    # Long-window correlation (full window)
    long_corr = _pearson_corr(es_ret[-long_window:], nq_ret[-long_window:])
    # Short-window correlation
    if len(es_ret) < short_window or len(nq_ret) < short_window:
        return 0.0
    short_corr = _pearson_corr(es_ret[-short_window:], nq_ret[-short_window:])

    if long_corr is None or short_corr is None:
        return 0.0
    return float(abs(short_corr - long_corr))


def compute_eq_index_features(
    close_windows: dict[str, deque],
    vol_windows: dict[str, deque],
    tf: str,
    ts: datetime,
    window_bars: int = _Z_SCORE_WINDOW,
) -> dict[str, object]:
    """Compute cross-asset spread features for the EQ_INDEX group.

    Args:
        close_windows: Per-base-symbol deque of close prices (e.g. {"ES": deque([...]), ...}).
        vol_windows: Per-base-symbol deque of volumes.
        tf: Timeframe string (e.g. "1m", "5m").
        ts: Bar timestamp (UTC).
        window_bars: Number of bars for z-score baseline (default 20).

    Returns:
        {"ready": False} when any symbol has insufficient data.
        Full feature dict when all 4 EQ_INDEX symbols have >= window_bars data.
    """
    # Guard: all 4 symbols must be present with sufficient history
    min_needed = window_bars + _SHORT_WINDOW
    for sym in _EQ_INDEX_BASES:
        if sym not in close_windows or len(close_windows[sym]) < min_needed:
            return {"ready": False}
        if sym not in vol_windows or len(vol_windows[sym]) < 1:
            return {"ready": False}

    # Extract lists for computation (most recent window_bars + SHORT_WINDOW)
    closes: dict[str, list[float]] = {}
    vols: dict[str, list[float]] = {}
    for sym in _EQ_INDEX_BASES:
        closes[sym] = list(close_windows[sym])[-min_needed:]
        vols[sym] = vol_windows[sym]  # deque — no copy needed; _vol_ratio only uses [-1] and sum

    # --- Spread z-scores ---
    es_nq_spread = _compute_spread_series(closes["ES"], closes["NQ"], _SHORT_WINDOW)
    es_rty_spread = _compute_spread_series(closes["ES"], closes["RTY"], _SHORT_WINDOW)

    # The spread series has length (min_needed - SHORT_WINDOW) = window_bars
    # Use the full spread series for z-scoring (includes current bar as last element)
    es_nq_z, es_nq_low_vol = _z_score_last(es_nq_spread)
    es_rty_z, es_rty_low_vol = _z_score_last(es_rty_spread)

    low_vol_flag = es_nq_low_vol or es_rty_low_vol

    # --- Per-symbol bar returns for correlation ---
    # Use 1-bar returns for correlation analysis (more responsive)
    returns_by_symbol: dict[str, list[float]] = {}
    for sym in _EQ_INDEX_BASES:
        cl = closes[sym]
        rets = []
        for i in range(1, len(cl)):
            if cl[i - 1] > 0 and cl[i] > 0:
                rets.append(math.log(cl[i] / cl[i - 1]))
            else:
                rets.append(0.0)
        returns_by_symbol[sym] = rets

    # --- Correlation break ---
    eq_corr_break = _compute_corr_break(returns_by_symbol, _SHORT_WINDOW, window_bars)

    # --- Volume imbalance: (ES_last/ES_avg) / (NQ_last/NQ_avg) ---
    def _vol_ratio(sym: str) -> float:
        v = vols[sym]
        if not v:
            return 1.0
        avg = sum(v) / len(v)
        if avg < _LOW_VOL_THRESHOLD:
            return 1.0
        return float(v[-1]) / avg

    es_vr = _vol_ratio("ES")
    nq_vr = _vol_ratio("NQ")
    if nq_vr < _LOW_VOL_THRESHOLD:
        eq_vol_imbalance = 1.0
    else:
        eq_vol_imbalance = es_vr / nq_vr

    # --- Active pair: whichever pair has larger abs z-score ---
    active_pair = "ES_NQ" if abs(es_nq_z) >= abs(es_rty_z) else "ES_RTY"

    # --- Pairs confirming: count pairs with |z| > threshold ---
    pairs_confirming = sum(
        1 for z in [es_nq_z, es_rty_z] if abs(z) > _CONFIRMING_Z_THRESHOLD
    )

    # --- Data quality score: fraction of symbols with data above threshold ---
    fresh_count = sum(
        1 for sym in _EQ_INDEX_BASES if len(close_windows[sym]) >= min_needed
    )
    data_quality_score = float(fresh_count) / len(_EQ_INDEX_BASES)

    return {
        "ready": True,
        "ts": ts.isoformat().replace("+00:00", "Z"),
        "tf": tf,
        "group": "EQ_INDEX",
        "es_nq_spread_z": float(es_nq_z),
        "es_rty_spread_z": float(es_rty_z),
        "eq_corr_break": float(eq_corr_break),
        "eq_vol_imbalance": float(eq_vol_imbalance),
        "active_pair": active_pair,
        "pairs_confirming": int(pairs_confirming),
        "data_quality_score": data_quality_score,
        "low_vol_flag": bool(low_vol_flag),
    }
