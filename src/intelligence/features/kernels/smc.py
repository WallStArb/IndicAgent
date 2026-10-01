"""Smart money concept kernels: order blocks, fair value gaps, liquidity sweeps and pools,
supply and demand zones, BOS/CHoCH and the AMD cycle (D-25).

The helpers are the ones `feature_factory` used to hold, moved unchanged. A stateless kernel
slices the same causal window the batch loop sliced, `[max(0, i - lookback + 1) : i + 1]`, and
reads the loop's `atr_val` (the ATR padded series at row i). The zones kernel consumes the FVG
midpoint and pool premium flag as intermediate outputs, so its declared memory chains through
theirs. The AMD kernel replays a fresh `FeatureCache` with the loop's overnight-range update and
is path dependent. Every helper returns a float for every key, never None.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np

from src.intelligence.features.contract.registry import Kernel
from src.intelligence.features.kernels._cache_state import FeatureCache
from src.intelligence.features.kernels._primitives import (
    ATR_RAW_PADDED,
    KeyGroup,
    _is_valid_atr,
    window_start,
)
from src.intelligence.utils import clamp, find_peaks, find_troughs
from src.intelligence.utils.gradient_utils import freshness_decay, linear_ramp

if TYPE_CHECKING:
    from src.intelligence.feature_factory import FeatureFactoryConfig


# ---------------------------------------------------------------------------
# Smart Money Concepts — Order Blocks + Breaker/Mitigation (Phase 164 Plan 02)
# ---------------------------------------------------------------------------


def _dist_to_midpoint(close_: float, boundary_a: float, boundary_b: float) -> float:
    """abs distance from close_ to the midpoint of [boundary_a, boundary_b],
    shared by order blocks' nearest-candidate ranking and supply/demand
    zones' nearest-zone ranking (both reduce to the same top/bottom
    midpoint distance, just under different dict key names)."""
    return abs(close_ - (boundary_a + boundary_b) / 2.0)


def _suffix_min(arr: np.ndarray) -> np.ndarray:
    """suffix_min[k] = min(arr[k:]) for every k, computed once in O(n).

    Answers "has any value at or after index k dropped to/below a level" in
    O(1) via suffix_min[k] <= level -- exact, not an approximation, since
    np.any(arr[k:] <= level) is true iff arr[k:].min() <= level. Lets a
    per-candidate O(window) forward scan collapse to an O(1) lookup after
    one O(n) precompute, instead of O(window) work repeated per candidate.
    """
    return np.minimum.accumulate(arr[::-1])[::-1]


def _suffix_max(arr: np.ndarray) -> np.ndarray:
    """Mirror of _suffix_min: suffix_max[k] = max(arr[k:]), answering "has
    any value at or after index k risen to/above a level" in O(1) via
    suffix_max[k] >= level (exact, same min/max-vs-any equivalence)."""
    return np.maximum.accumulate(arr[::-1])[::-1]


def _level_breached_since(
    suffix_extreme: np.ndarray, start: int, level: float, bearish: bool
) -> float:
    """Shared O(1) primitive for "has the series described by suffix_extreme
    crossed `level` at or after index `start`?" -- a pure geometric query,
    parameterized entirely by which suffix-extrema array and comparison
    direction the caller passes in:

    - bearish=True: rise to/above `level`. Pass suffix_extreme=_suffix_max(highs).
    - bearish=False: drop to/below `level`. Pass suffix_extreme=_suffix_min(lows).

    start >= len(suffix_extreme) (nothing left to scan) returns 0.0.

    Used by order blocks' mitigation test (bearish OB checks highs for a
    rise to/above its own high; bullish OB checks lows for a drop to/below
    its own low) and FVG's fill test (same shape, gap edges instead of OB
    edges) -- previously two independent implementations of this identical
    check: a Python for-loop here, a fresh np.any() slice there. The
    `bearish` name follows this file's established bullish/bearish SMC
    vocabulary (inherited from the order-block scan this replaced) rather
    than an abstract direction enum, since every caller in this file already
    thinks in those terms.

    Equivalence with the original per-call forward-scan/np.any
    implementations proven by fuzz test across 20,000 random trials before
    this refactor was applied (zero mismatches).
    """
    n = len(suffix_extreme)
    if start >= n:
        return 0.0
    if bearish:
        return 1.0 if suffix_extreme[start] >= level else 0.0
    return 1.0 if suffix_extreme[start] <= level else 0.0


_OB_FALLBACK: dict[str, float] = {
    "ob_bull_dist_atr": 0.0,
    "ob_bear_dist_atr": 0.0,
    "ob_strength": 0.0,
    "ob_mitigated_flag": 0.0,
    "breaker_dist_atr": 0.0,
    "breaker_block_active": 0.0,
    "ob_mitigation_pct": 0.0,
}


def _compute_order_blocks(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    close_: float,
    atr_val: float,
    config: FeatureFactoryConfig,
) -> dict[str, float]:
    """Order Blocks + stateless Breaker/Mitigation, one pure pass (Phase 164 Plan 02).

    Ports order_blocks.py / breaker_blocks.py / mitigation_blocks.py's detection
    geometry as ONE stateless full-window scan, per 164-RESEARCH.md's mandated
    order_blocks -> breaker/mitigation sequencing and its explicit correction
    that both archived plugins' self._state cross-call memory must NOT survive
    the port: every order block found during the scan (mitigated or not) is
    retained in-pass as `candidates`; breaker/mitigation derive directly from
    that same list, never from a FeatureCache mutator or module-level state.

    Bullish OB: last bearish candle before an impulse_bars-long bullish
    impulse. Bearish OB: mirror image. An OB is "mitigated" once a later
    bar's wick fully trades through its own zone (_level_breached_since,
    shared with FVG's fill test -- both reduce to the same "has this level
    been wicked through since bar X" primitive).
    nearest_bull_ob / nearest_bear_ob track the closest-by-price candidate of
    each direction (mitigated or not -- a broken zone's location is still
    informative, unlike the archived plugin, which only ever reports the
    single most-recently-scanned unmitigated OB across both directions); the
    single closest candidate overall drives ob_strength/ob_mitigated_flag/
    ob_mitigation_pct. A breaker is the most-recently-formed (by bar index)
    mitigated OB, polarity-flipped (a mitigated bull OB becomes a bearish
    breaker zone, and vice versa); active when price sits inside its zone or
    has approached from the flip-relevant side -- matches breaker_blocks.py's
    _from_state logic exactly, just recomputed in-pass instead of read from
    self._state. ob_mitigation_pct is 1.0 when the nearest-overall OB is
    itself already fully mitigated, else the max fractional overlap between
    every bar's [low, high] since its formation and its own [bottom, top]
    zone (mitigation_blocks.py's running-max logic, recomputed in-pass).

    Falls back to _OB_FALLBACK (never raises, never NaN/Inf) when atr_val is
    invalid or the window has too few bars to run the impulse scan.
    """
    atr_valid = _is_valid_atr(atr_val, close_, config.atr_normalization_min_pct)
    if not atr_valid:
        return dict(_OB_FALLBACK)

    lookback = config.smc_order_blocks_lookback
    o = opens[-lookback:]
    h = highs[-lookback:]
    lo = lows[-lookback:]
    c = closes[-lookback:]
    v = volumes[-lookback:]
    n_bars = len(c)

    impulse_bars = config.smc_order_blocks_impulse_bars
    opposing_lookback = config.smc_order_blocks_opposing_candle_lookback
    significant_move_pct = config.smc_order_blocks_significant_move_pct

    if n_bars < impulse_bars + opposing_lookback + 1:
        return dict(_OB_FALLBACK)

    # Precomputed ONCE for the whole window (O(n_bars)), not per candidate --
    # every candidate's mitigation check below is an O(1) lookup into these
    # instead of its own O(window) forward scan (previously O(candidates *
    # window) worst case).
    suf_min_lo = _suffix_min(lo)
    suf_max_h = _suffix_max(h)

    avg_volume = float(v.mean()) if v.size else 0.0

    def _ob_strength(impulse_vol: float) -> float:
        if avg_volume > 0:
            return min(1.0, impulse_vol / avg_volume)
        return config.smc_order_blocks_strength_fallback

    candidates: list[dict[str, float]] = []

    i = impulse_bars
    while i < n_bars:
        impulse_start = i - impulse_bars

        if all(c[j] > o[j] for j in range(impulse_start, i)):
            impulse_move = c[i - 1] - o[impulse_start]
            if abs(impulse_move) > close_ * significant_move_pct:
                ob_idx = None
                for k in range(impulse_start - 1, max(0, impulse_start - opposing_lookback), -1):
                    if c[k] < o[k]:
                        ob_idx = k
                        break
                if ob_idx is not None:
                    strength = _ob_strength(float(v[impulse_start:i].mean()))
                    mitigated = _level_breached_since(
                        suf_min_lo, i, float(lo[ob_idx]), bearish=False
                    )
                    candidates.append(
                        {
                            "type": 1.0,
                            "top": float(h[ob_idx]),
                            "bottom": float(lo[ob_idx]),
                            "strength": float(strength),
                            "mitigated": mitigated,
                            "idx": float(ob_idx),
                            "impulse_end": float(i),
                        }
                    )

        if all(c[j] < o[j] for j in range(impulse_start, i)):
            impulse_move = c[i - 1] - o[impulse_start]
            if abs(impulse_move) > close_ * significant_move_pct:
                ob_idx = None
                for k in range(impulse_start - 1, max(0, impulse_start - opposing_lookback), -1):
                    if c[k] > o[k]:
                        ob_idx = k
                        break
                if ob_idx is not None:
                    strength = _ob_strength(float(v[impulse_start:i].mean()))
                    mitigated = _level_breached_since(suf_max_h, i, float(h[ob_idx]), bearish=True)
                    candidates.append(
                        {
                            "type": -1.0,
                            "top": float(h[ob_idx]),
                            "bottom": float(lo[ob_idx]),
                            "strength": float(strength),
                            "mitigated": mitigated,
                            "idx": float(ob_idx),
                            "impulse_end": float(i),
                        }
                    )

        i += 1

    if not candidates:
        return dict(_OB_FALLBACK)

    def _dist(cand: dict[str, float]) -> float:
        return _dist_to_midpoint(close_, cand["top"], cand["bottom"])

    bull_candidates = [cand for cand in candidates if cand["type"] == 1.0]
    bear_candidates = [cand for cand in candidates if cand["type"] == -1.0]
    nearest_bull = min(bull_candidates, key=_dist) if bull_candidates else None
    nearest_bear = min(bear_candidates, key=_dist) if bear_candidates else None
    nearest_overall = min(candidates, key=_dist)

    ob_bull_dist_atr = _dist(nearest_bull) / atr_val if nearest_bull is not None else 0.0
    ob_bear_dist_atr = _dist(nearest_bear) / atr_val if nearest_bear is not None else 0.0
    ob_strength = float(nearest_overall["strength"])
    ob_mitigated_flag = float(nearest_overall["mitigated"])

    ob_mitigation_pct = 0.0
    if ob_mitigated_flag == 1.0:
        ob_mitigation_pct = 1.0
    else:
        m_top = nearest_overall["top"]
        m_bottom = nearest_overall["bottom"]
        ob_range = m_top - m_bottom
        if ob_range > 0:
            # Scan from impulse_end (matching _level_breached_since's own
            # start-index convention above), NOT idx+1 -- the impulse bars
            # themselves naturally span the OB zone as price transits away
            # from it (their own formation), which is not a genuine later
            # retest/erosion.
            overlap_start = int(nearest_overall["impulse_end"])
            max_pct = 0.0
            for j in range(overlap_start, n_bars):
                overlap_low = max(float(lo[j]), m_bottom)
                overlap_high = min(float(h[j]), m_top)
                overlap = max(0.0, overlap_high - overlap_low)
                bar_pct = overlap / ob_range
                if bar_pct > max_pct:
                    max_pct = bar_pct
            ob_mitigation_pct = min(1.0, max_pct)

    # Breaker (RESEARCH.md: derive statelessly from the same in-pass
    # candidates list, never self._state). Candidate = the most-recently-
    # formed mitigated OB; its polarity flips (breaker_blocks.py's rule).
    breaker_dist_atr = 0.0
    breaker_block_active = 0.0
    mitigated_obs = [cand for cand in candidates if cand["mitigated"] == 1.0]
    if mitigated_obs:
        breaker_ob = max(mitigated_obs, key=lambda cand: cand["idx"])
        b_top = breaker_ob["top"]
        b_bottom = breaker_ob["bottom"]
        breaker_direction = -breaker_ob["type"]  # flipped polarity vs. the mitigated OB
        b_mid = (b_top + b_bottom) / 2.0
        in_zone = b_bottom <= close_ <= b_top
        if in_zone:
            breaker_block_active = 1.0
        elif breaker_direction > 0.0 and close_ < b_bottom:
            breaker_block_active = 1.0
        elif breaker_direction < 0.0 and close_ > b_top:
            breaker_block_active = 1.0
        breaker_dist_atr = abs(close_ - b_mid) / atr_val

    return {
        "ob_bull_dist_atr": float(ob_bull_dist_atr),
        "ob_bear_dist_atr": float(ob_bear_dist_atr),
        "ob_strength": float(ob_strength),
        "ob_mitigated_flag": float(ob_mitigated_flag),
        "breaker_dist_atr": float(breaker_dist_atr),
        "breaker_block_active": float(breaker_block_active),
        "ob_mitigation_pct": float(ob_mitigation_pct),
    }


# ---------------------------------------------------------------------------
# Smart Money Concepts — Fair Value Gaps (Phase 164 Plan 03)
# ---------------------------------------------------------------------------

_FVG_FALLBACK: dict[str, float] = {
    "fvg_dist_atr": 0.0,
    "fvg_size_atr": 0.0,
    "fvg_open_count": 0.0,
    "fvg_midpoint": 0.0,
}

# fvg_midpoint is an in-memory-only intermediate for the supply/demand zones: the group registers
# it as `_fvg_midpoint` and it never reaches _build_feature_vector. The persisted subset of
# _compute_fvg()'s return dict derives from the group, so _FVG_FALLBACK is the one source of truth
# for its key set.
_FVG_MIDPOINT = "_fvg_midpoint"
FVG = KeyGroup.from_fallback(_FVG_FALLBACK, {"fvg_midpoint": _FVG_MIDPOINT})
_FVG_OUTPUT_KEYS = frozenset(FVG.public_keys)


def _compute_fvg(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    close_: float,
    atr_val: float,
    config: FeatureFactoryConfig,
) -> dict[str, float]:
    """Fair Value Gaps -- stateless 3-candle imbalance scan (Phase 164 Plan 03).

    Ports fair_value_gap.py's geometry: a bullish FVG forms when bar3's low
    sits above bar1's high (the impulsive bar2 leaves an untraded gap);
    bearish is the mirror (bar3's high below bar1's low). A gap is "filled"
    once a later bar's wick trades back through its near edge. Unlike the
    archived plugin (whose descending-index scan order makes its returned
    open_fvgs[-1] the OLDEST still-open gap, not the newest -- see Phase 164
    Plan 03 commit notes), this selects the MOST RECENT unfilled gap by
    formation index (largest bar3 index), matching order_blocks.py's
    nearest-by-recency convention and the literal meaning of "most recent."
    fvg_open_count is the full count of unfilled gaps in-window, independent
    of which one is selected.

    fvg_midpoint is returned as an extra, NON-persisted key -- an in-pass
    local for Plan 04's supply/demand-zones block (soft dependency per
    164-RESEARCH.md), never threaded into _build_feature_vector.

    Falls back to _FVG_FALLBACK (never raises, never NaN/Inf) when atr_val is
    invalid or the window has fewer than 3 bars.
    """
    atr_valid = _is_valid_atr(atr_val, close_, config.atr_normalization_min_pct)
    if not atr_valid:
        return dict(_FVG_FALLBACK)

    lookback = config.smc_fvg_lookback
    h = highs[-lookback:]
    lo = lows[-lookback:]
    n_bars = len(h)
    if n_bars < 3:
        return dict(_FVG_FALLBACK)

    # Precomputed ONCE for the whole window (O(n_bars)), not per candidate --
    # same shared primitive as order blocks' mitigation check (_level_breached_since).
    suf_min_lo = _suffix_min(lo)
    suf_max_h = _suffix_max(h)

    candidates: list[dict[str, float]] = []
    for i in range(2, n_bars):
        bar1_high = h[i - 2]
        bar1_low = lo[i - 2]
        bar3_high = h[i]
        bar3_low = lo[i]

        fvg_type = 0.0
        top = 0.0
        bottom = 0.0
        if bar3_low > bar1_high:
            fvg_type = 1.0
            top = float(bar3_low)
            bottom = float(bar1_high)
        elif bar3_high < bar1_low:
            fvg_type = -1.0
            top = float(bar1_low)
            bottom = float(bar3_high)

        if fvg_type == 0.0:
            continue

        if fvg_type == 1.0:
            filled = bool(_level_breached_since(suf_min_lo, i + 1, bottom, bearish=False))
        else:
            filled = bool(_level_breached_since(suf_max_h, i + 1, top, bearish=True))

        if not filled:
            candidates.append({"type": fvg_type, "top": top, "bottom": bottom, "idx": float(i)})

    if not candidates:
        return dict(_FVG_FALLBACK)

    nearest = max(candidates, key=lambda cand: cand["idx"])
    midpoint = (nearest["top"] + nearest["bottom"]) / 2.0

    return {
        "fvg_dist_atr": float(abs(close_ - midpoint) / atr_val),
        "fvg_size_atr": float((nearest["top"] - nearest["bottom"]) / atr_val),
        "fvg_open_count": float(len(candidates)),
        "fvg_midpoint": float(midpoint),
    }


# ---------------------------------------------------------------------------
# Smart Money Concepts — Liquidity Sweeps + Liquidity Pools (Phase 164 Plan 03)
# ---------------------------------------------------------------------------

_SWEEP_FALLBACK: dict[str, float] = {
    "sweep_detected": 0.0,
    "sweep_strength": 0.0,
    "reclaim_velocity": 0.0,
    "bars_since_last_sweep": 0.0,
}

_POOL_FALLBACK: dict[str, float] = {
    "bsl_dist_atr": 0.0,
    "ssl_dist_atr": 0.0,
    "bsl_touches": 0.0,
    "ssl_touches": 0.0,
    "pool_count": 0.0,
    "price_in_premium": 0.0,
}

# price_in_premium is an in-memory-only intermediate for the supply/demand zones, handled like
# fvg_midpoint above.
_PRICE_IN_PREMIUM = "_price_in_premium"
POOL = KeyGroup.from_fallback(_POOL_FALLBACK, {"price_in_premium": _PRICE_IN_PREMIUM})
_POOL_OUTPUT_KEYS = frozenset(POOL.public_keys)


def _compute_liquidity_sweeps(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    close_: float,
    atr_val: float,
    config: FeatureFactoryConfig,
) -> dict[str, float]:
    """Liquidity Sweeps -- stateless wick-beyond-swing + reclaim scan (Plan 03).

    Ports liquidity_sweeps.py's geometry directly: a bullish sweep wicks
    below a swing low then closes back above it (smart money grabs sell
    stops before reversing); bearish is the mirror. sweep_strength and
    reclaim_velocity keep the archived plugin's linear_ramp bounding
    ([0,1], via config's ramp-max APR keys). bars_since_last_sweep is new
    (not in the archived output) -- bars from the most recent sweep's
    formation bar to the current bar, causal, non-negative.

    "Most recent sweep" = the sweep with the largest bar_idx (matches the
    archived plugin's own max-by-bar_idx selection, unlike FVG's port which
    corrected an inverted selection -- liquidity_sweeps.py's logic was
    already right).

    Falls back to _SWEEP_FALLBACK (never raises, never NaN/Inf, 0.0 bars-
    since-last-sweep when no sweep is ever found in-window -- same "absence
    has no defined age" convention as resistance_age_bars/support_age_bars)
    when atr_val is invalid or the window is too short for swing detection.
    """
    atr_valid = _is_valid_atr(atr_val, close_, config.atr_normalization_min_pct)
    if not atr_valid:
        return dict(_SWEEP_FALLBACK)

    lookback = config.smc_liquidity_sweeps_lookback
    h = highs[-lookback:]
    lo = lows[-lookback:]
    c = closes[-lookback:]
    n_bars = len(c)

    neighbor = config.smc_liquidity_sweeps_swing_neighbor
    if n_bars < 2 * neighbor + 1:
        return dict(_SWEEP_FALLBACK)

    # NOT shared with _compute_bos_choch's own find_peaks/find_troughs call
    # below, even though both default to lookback=120/neighbor=5 today:
    # smc_liquidity_sweeps_lookback/swing_neighbor and
    # smc_bos_choch_lookback/swing_neighbor are deliberately separate APR
    # keys (migration 266) precisely so liquidity-sweep detection and
    # BOS/CHoCH detection can be tuned independently. Sharing one scan would
    # either silently break correctness the moment either key is retuned
    # away from the other, or need a same-params-else-fallback branch that
    # only pays off in the coincidental case they still match -- a special
    # case bought with a real design invariant, not a clean optimization.
    swing_highs = find_peaks(h, n=neighbor)
    swing_lows = find_troughs(lo, n=neighbor)
    if not swing_highs and not swing_lows:
        return dict(_SWEEP_FALLBACK)

    reclaim_bars = config.smc_liquidity_sweeps_reclaim_bars
    depth_ramp_max = config.smc_liquidity_sweeps_depth_ramp_max_pct
    reclaim_ramp_max = config.smc_liquidity_sweeps_reclaim_velocity_ramp_max

    sweeps: list[dict[str, float]] = []

    for sl_idx in swing_lows:
        sl_price = float(lo[sl_idx])
        for i in range(sl_idx + neighbor + 1, n_bars):
            if lo[i] < sl_price and c[i] > sl_price:
                depth_pct = (sl_price - float(lo[i])) / sl_price * 100.0
                reclaimed = 0.0
                if i + reclaim_bars < n_bars and all(
                    c[i + k] > sl_price for k in range(1, reclaim_bars + 1)
                ):
                    reclaimed = 1.0
                sweep_strength = linear_ramp(depth_pct, 0.0, depth_ramp_max)
                reclaim_velocity = (
                    linear_ramp(1.0 / max(1, reclaim_bars), 0.0, reclaim_ramp_max)
                    if reclaimed
                    else 0.0
                )
                sweeps.append(
                    {
                        "sweep_strength": sweep_strength,
                        "reclaim_velocity": reclaim_velocity,
                        "bar_idx": float(i),
                    }
                )

    for sh_idx in swing_highs:
        sh_price = float(h[sh_idx])
        for i in range(sh_idx + neighbor + 1, n_bars):
            if h[i] > sh_price and c[i] < sh_price:
                depth_pct = (float(h[i]) - sh_price) / sh_price * 100.0
                reclaimed = 0.0
                if i + reclaim_bars < n_bars and all(
                    c[i + k] < sh_price for k in range(1, reclaim_bars + 1)
                ):
                    reclaimed = 1.0
                sweep_strength = linear_ramp(depth_pct, 0.0, depth_ramp_max)
                reclaim_velocity = (
                    linear_ramp(1.0 / max(1, reclaim_bars), 0.0, reclaim_ramp_max)
                    if reclaimed
                    else 0.0
                )
                sweeps.append(
                    {
                        "sweep_strength": sweep_strength,
                        "reclaim_velocity": reclaim_velocity,
                        "bar_idx": float(i),
                    }
                )

    if not sweeps:
        return dict(_SWEEP_FALLBACK)

    latest = max(sweeps, key=lambda s: s["bar_idx"])
    return {
        "sweep_detected": 1.0,
        "sweep_strength": float(latest["sweep_strength"]),
        "reclaim_velocity": float(latest["reclaim_velocity"]),
        "bars_since_last_sweep": float(n_bars - 1 - int(latest["bar_idx"])),
    }


def _compute_liquidity_pools(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    close_: float,
    atr_val: float,
    config: FeatureFactoryConfig,
) -> dict[str, float]:
    """Liquidity Pools -- single-timeframe-descoped port (Phase 164 Plan 03).

    Ports liquidity_pools.py's equal-highs/equal-lows + session-high/low
    detection only -- named prior-week/prior-day high/low levels are DESCOPED
    per 164-RESEARCH.md: they require a second daily-timeframe frame the live
    compute(bars, symbol, tf, cache, config) single-timeframe signature
    cannot provide. bsl_dist_atr/
    ssl_dist_atr reuse the already-correct ATR-normalized formula from the
    archived source (only the raw bsl_level/ssl_level/bsl_type/ssl_type are
    dropped, per the field-by-field audit). bsl_touches/ssl_touches derive
    from the selected level's cluster-size type string, same as the archived
    plugin's _touches_for(). price_in_premium is returned as an extra,
    NON-persisted key -- an in-pass local for Plan 04's supply/demand-zones
    block (soft dependency), never threaded into _build_feature_vector.

    Nearest-level selection: highest significance first (config's
    significance_weights dict), then nearest by distance -- matches
    liquidity_pools.py's own _nearest() tie-break rule exactly.

    Falls back to _POOL_FALLBACK (never raises, never NaN/Inf) when atr_val
    is invalid or the window is too short for swing detection.
    """
    atr_valid = _is_valid_atr(atr_val, close_, config.atr_normalization_min_pct)
    if not atr_valid:
        return dict(_POOL_FALLBACK)

    lookback = config.smc_liquidity_pools_lookback
    h = highs[-lookback:]
    lo = lows[-lookback:]
    n_bars = len(h)

    neighbor = config.smc_liquidity_pools_swing_neighbor
    if n_bars < 2 * neighbor + 1:
        return dict(_POOL_FALLBACK)

    weights = config.smc_liquidity_pools_significance_weights
    tolerance = atr_val * config.smc_liquidity_pools_equal_level_tolerance_atr_mult

    swing_high_idx = find_peaks(h, n=neighbor)
    swing_low_idx = find_troughs(lo, n=neighbor)

    eq_highs = _find_equal_price_clusters([float(h[i]) for i in swing_high_idx], tolerance)
    eq_lows = _find_equal_price_clusters([float(lo[i]) for i in swing_low_idx], tolerance)

    bsl_candidates: list[tuple[float, str, float]] = []
    ssl_candidates: list[tuple[float, str, float]] = []

    for level, touches in eq_highs:
        if level > close_:
            lvl_type = "eq_highs_3" if touches >= 3 else "eq_highs_2"
            bsl_candidates.append((level, lvl_type, weights.get(lvl_type, 0.0)))

    for level, touches in eq_lows:
        if level < close_:
            lvl_type = "eq_lows_3" if touches >= 3 else "eq_lows_2"
            ssl_candidates.append((level, lvl_type, weights.get(lvl_type, 0.0)))

    session_bars = config.smc_liquidity_pools_session_bars
    session_high = float(np.max(h[-session_bars:])) if n_bars >= session_bars else float(np.max(h))
    session_low = float(np.min(lo[-session_bars:])) if n_bars >= session_bars else float(np.min(lo))
    if session_high > close_:
        bsl_candidates.append((session_high, "session_high", weights.get("session_high", 0.0)))
    if session_low < close_:
        ssl_candidates.append((session_low, "session_low", weights.get("session_low", 0.0)))

    pool_count = float(len(bsl_candidates) + len(ssl_candidates))

    bsl = (
        min(bsl_candidates, key=lambda cand: (-cand[2], abs(cand[0] - close_)))
        if bsl_candidates
        else None
    )
    ssl = (
        min(ssl_candidates, key=lambda cand: (-cand[2], abs(cand[0] - close_)))
        if ssl_candidates
        else None
    )

    bsl_dist_atr = abs(bsl[0] - close_) / atr_val if bsl is not None else 0.0
    bsl_touches = _pool_touches_for(bsl[1]) if bsl is not None else 0.0
    ssl_dist_atr = abs(close_ - ssl[0]) / atr_val if ssl is not None else 0.0
    ssl_touches = _pool_touches_for(ssl[1]) if ssl is not None else 0.0

    range_high = float(np.max(h))
    range_low = float(np.min(lo))
    midpoint = (range_high + range_low) / 2.0
    price_in_premium = 1.0 if close_ >= midpoint else 0.0

    return {
        "bsl_dist_atr": float(bsl_dist_atr),
        "ssl_dist_atr": float(ssl_dist_atr),
        "bsl_touches": float(bsl_touches),
        "ssl_touches": float(ssl_touches),
        "pool_count": pool_count,
        "price_in_premium": float(price_in_premium),
    }


def _find_equal_price_clusters(prices: list[float], tolerance: float) -> list[tuple[float, int]]:
    """Cluster prices within tolerance -> (mean_price, touch_count) for clusters >=2.

    Ported from liquidity_pools.py's _find_equal_levels: single-pass O(N)
    clustering over sorted prices (each price joins the last open cluster if
    within tolerance of that cluster's mean, else starts a new one).
    """
    if not prices:
        return []
    sorted_prices = sorted(prices)
    clusters: list[list[float]] = []
    for p in sorted_prices:
        if clusters and abs(p - float(np.mean(clusters[-1]))) <= tolerance:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return [(float(np.mean(c)), len(c)) for c in clusters if len(c) >= 2]


def _pool_touches_for(lvl_type: str) -> float:
    """Touch count implied by a liquidity-pool level's type label.

    Ported from liquidity_pools.py's _touches_for(): "_3" suffix -> 3
    touches, "_2" suffix -> 2 touches, else (session_high/session_low) -> 1.
    """
    if "3" in lvl_type:
        return 3.0
    if "2" in lvl_type:
        return 2.0
    return 1.0


# ---------------------------------------------------------------------------
# Smart Money Concepts — Supply/Demand Zones + BOS/CHoCH + AMD Cycle (Plan 04)
# ---------------------------------------------------------------------------

_ZONE_FALLBACK: dict[str, float] = {
    "demand_dist_atr": 0.0,
    "supply_dist_atr": 0.0,
    "demand_freshness": 0.0,
    "supply_freshness": 0.0,
    "active_demand_zones": 0.0,
    "active_supply_zones": 0.0,
    "zone_friction_score": 0.0,
}

_BOS_FALLBACK: dict[str, float] = {
    "bos_strength": 0.0,
    "choch_strength": 0.0,
    "bos_direction": 0.0,
    "choch_direction": 0.0,
    "smc_trend_direction": 0.0,
    "bars_since_last_shift": 0.0,
}

_AMD_PHASE_UNKNOWN = 0.0
_AMD_PHASE_ACCUMULATION = 1.0
_AMD_PHASE_MANIPULATION = 2.0
_AMD_PHASE_DISTRIBUTION = 3.0


def _compute_supply_demand_zones(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    close_: float,
    atr_val: float,
    config: FeatureFactoryConfig,
    fvg_midpoint: float,
    price_in_premium: float,
) -> dict[str, float]:
    """Supply/Demand Zones -- stateless Rally-Base-Drop/Drop-Base-Rally scan (Plan 04).

    Ports supply_demand_zones.py's geometry: an impulsive close-to-close move
    (>= atr_val * impulse_atr_mult) with low overlap against the immediately
    preceding bar, preceded by a run of small-body/small-range "base" bars,
    forms a zone at the base bars' own high/low. Bullish impulses (direction
    +1) form demand zones; bearish impulses (direction -1) form supply zones.
    A zone is "active" (unmitigated) while price has never closed beyond its
    distal edge since formation; freshness decays with each subsequent touch
    (freshness_decay, matching the archived plugin's k parameter) and resets
    to a fresh 1.0 for a never-touched zone.

    fvg_midpoint (Plan 03's FVG local) and price_in_premium (Plan 03's
    Liquidity Pools local) are a SOFT dependency per 164-RESEARCH.md: zone
    strength gets an alignment boost when the nearest zone contains
    fvg_midpoint or sits on the correct side of price_in_premium, but the
    function still returns a complete result if both are 0.0 (their
    respective fallback sentinels) -- no zones ever go undetected because of
    this. zone_friction_score = freshness * strength * 1/(1+dist_atr) for
    whichever of demand/supply is nearer (matching the archived plugin's
    Phase 126-06 formalization); only demand_dist_atr/supply_dist_atr/
    demand_freshness/supply_freshness/active_demand_zones/active_supply_zones/
    zone_friction_score are persisted -- demand_strength/supply_strength/
    in_demand_zone/in_supply_zone/nearest_*_high/low never leave this
    function (raw-price + redundant-strength-copy audit, 164-RESEARCH.md).

    Falls back to _ZONE_FALLBACK (never raises, never NaN/Inf) when atr_val
    is invalid or the window is too short to run the base+impulse scan.
    """
    atr_valid = _is_valid_atr(atr_val, close_, config.atr_normalization_min_pct)
    if not atr_valid:
        return dict(_ZONE_FALLBACK)

    lookback = config.smc_zones_lookback
    o = opens[-lookback:]
    h = highs[-lookback:]
    lo = lows[-lookback:]
    c = closes[-lookback:]
    n_bars = len(c)

    max_base_bars = config.smc_zones_max_base_bars
    if n_bars < max_base_bars + 3:
        return dict(_ZONE_FALLBACK)

    impulse_atr_mult = config.smc_zones_impulse_atr_mult
    overlap_atr_mult = config.smc_zones_impulse_overlap_atr_mult
    base_body_ratio = config.smc_zones_base_body_ratio
    base_atr_mult = config.smc_zones_base_atr_mult
    height_cap_mult = config.smc_zones_zone_height_cap_atr_mult

    zones: list[dict[str, float]] = []
    for i in range(max_base_bars + 2, n_bars - 1):
        cc_move = abs(float(c[i]) - float(c[i - 1]))
        if cc_move < atr_val * impulse_atr_mult:
            continue
        overlap = max(0.0, min(float(h[i]), float(h[i - 1])) - max(float(lo[i]), float(lo[i - 1])))
        if overlap > atr_val * overlap_atr_mult:
            continue
        direction = 1.0 if float(c[i]) > float(c[i - 1]) else -1.0

        base_bars: list[int] = []
        for b in range(i - 1, max(i - max_base_bars - 1, 0), -1):
            bar_range = float(h[b]) - float(lo[b])
            bar_body = abs(float(c[b]) - float(o[b]))
            if bar_range <= 0:
                continue
            if bar_body / bar_range < base_body_ratio and bar_range < atr_val * base_atr_mult:
                base_bars.append(b)
            else:
                break
        if not base_bars:
            continue

        zone_high = float(max(h[b] for b in base_bars))
        zone_low = float(min(lo[b] for b in base_bars))
        if zone_high - zone_low > atr_val * height_cap_mult:
            zone_high = zone_low + atr_val * height_cap_mult

        zones.append({"type": direction, "high": zone_high, "low": zone_low, "idx": float(i)})

    if not zones:
        return dict(_ZONE_FALLBACK)

    freshness_k = config.smc_zones_freshness_decay_k
    premium_mult = config.smc_zones_strength_premium_align_mult
    fvg_mult = config.smc_zones_strength_fvg_align_mult
    age_floor = config.smc_zones_age_penalty_floor
    age_window = config.smc_zones_age_penalty_window_bars
    age_max_pct = config.smc_zones_age_penalty_max_pct
    max_tracked = config.smc_zones_max_tracked_zones

    # NOT rewritten with _level_breached_since/suffix-extrema (unlike order
    # blocks/FVG above): test_count needs the actual NUMBER of touches, not
    # just whether one occurred, so price_in_zone's O(window) scan can't be
    # skipped regardless -- and mitigated is only ever evaluated after that
    # same scan already ran. Precomputing a suffix-extrema shortcut for
    # `mitigated` alone would add a second mechanism without removing any
    # work, since the O(window) per-zone cost is already paid by test_count.
    # Zone count itself is bounded by the base+impulse pattern's rarity, not
    # O(window), so this loop is not the O(n^2) hazard order blocks/FVG were.
    active: list[dict[str, float]] = []
    for zone in zones:
        mitigated = False
        test_count = 0
        start = int(zone["idx"]) + 1
        if start < n_bars:
            price_in_zone = (lo[start:] <= zone["high"]) & (h[start:] >= zone["low"])
            if bool(np.any(price_in_zone)):
                test_count = int(np.sum(price_in_zone))
                if zone["type"] > 0.0:
                    mitigated = bool(np.any(c[start:] < zone["low"]))
                else:
                    mitigated = bool(np.any(c[start:] > zone["high"]))
        if mitigated:
            continue
        zone["freshness"] = freshness_decay(test_count, k=freshness_k)
        active.append(zone)

    if not active:
        return dict(_ZONE_FALLBACK)

    def _zone_dist(z: dict[str, float]) -> float:
        return _dist_to_midpoint(close_, z["high"], z["low"])

    demand_zones = sorted((z for z in active if z["type"] > 0.0), key=_zone_dist)[:max_tracked]
    supply_zones = sorted((z for z in active if z["type"] < 0.0), key=_zone_dist)[:max_tracked]

    def _zone_strength(z: dict[str, float]) -> float:
        s = z["freshness"]
        if z["type"] > 0.0 and price_in_premium == 0.0:
            s = min(1.0, s * premium_mult)
        elif z["type"] < 0.0 and price_in_premium == 1.0:
            s = min(1.0, s * premium_mult)
        if fvg_midpoint and z["low"] <= fvg_midpoint <= z["high"]:
            s = min(1.0, s * fvg_mult)
        age = n_bars - z["idx"]
        age_penalty = max(age_floor, 1.0 - (age / age_window) * age_max_pct)
        return min(1.0, s * age_penalty)

    demand_dist_atr = 0.0
    demand_freshness = 0.0
    zf_demand: float | None = None
    if demand_zones:
        dz = demand_zones[0]
        demand_dist_atr = _zone_dist(dz) / atr_val
        demand_freshness = dz["freshness"]
        zf_demand = demand_freshness * _zone_strength(dz) * (1.0 / (1.0 + demand_dist_atr))

    supply_dist_atr = 0.0
    supply_freshness = 0.0
    zf_supply: float | None = None
    if supply_zones:
        sz = supply_zones[0]
        supply_dist_atr = _zone_dist(sz) / atr_val
        supply_freshness = sz["freshness"]
        zf_supply = supply_freshness * _zone_strength(sz) * (1.0 / (1.0 + supply_dist_atr))

    if zf_demand is not None and zf_supply is not None:
        zone_friction_score = max(zf_demand, zf_supply)
    elif zf_demand is not None:
        zone_friction_score = zf_demand
    elif zf_supply is not None:
        zone_friction_score = zf_supply
    else:
        zone_friction_score = 0.0

    return {
        "demand_dist_atr": float(demand_dist_atr),
        "supply_dist_atr": float(supply_dist_atr),
        "demand_freshness": float(demand_freshness),
        "supply_freshness": float(supply_freshness),
        "active_demand_zones": float(len(demand_zones)),
        "active_supply_zones": float(len(supply_zones)),
        "zone_friction_score": float(zone_friction_score),
    }


def _compute_bos_choch(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    close_: float,
    atr_val: float,
    config: FeatureFactoryConfig,
) -> dict[str, float]:
    """Break of Structure / Change of Character -- stateless swing-break scan (Plan 04).

    Ports bos_choch.py's geometry directly: the prevailing trend is read from
    the last 2 swing highs and last 2 swing lows (both ascending -> uptrend
    +1, both descending -> downtrend -1, else neutral 0); a BOS fires the
    first bar after the most recent swing point whose close breaks beyond the
    last swing high (bullish, +1) or last swing low (bearish, -1). A CHoCH is
    a BOS whose direction opposes the prevailing trend. bos_strength/
    choch_strength keep the archived plugin's ATR-normalized break-distance
    formula unchanged. bars_since_last_shift is new (not in the archived
    output) -- causal bar count from the break bar to the current bar, 0.0
    when no break is found in-window (same "absence has no defined age"
    convention as resistance_age_bars/support_age_bars).

    The archived source's raw break-price field and its confidence field
    (byte-identical to bos_strength there) are both dropped per the
    field-by-field raw-price/redundancy audit -- neither is returned here.

    Falls back to _BOS_FALLBACK (never raises, never NaN/Inf) when atr_val is
    invalid or fewer than 2 swing highs/lows exist in-window.
    """
    atr_valid = _is_valid_atr(atr_val, close_, config.atr_normalization_min_pct)
    if not atr_valid:
        return dict(_BOS_FALLBACK)

    lookback = config.smc_bos_choch_lookback
    h = highs[-lookback:]
    lo = lows[-lookback:]
    c = closes[-lookback:]
    n_bars = len(c)

    neighbor = config.smc_bos_choch_swing_neighbor
    swing_highs = find_peaks(h, n=neighbor)
    swing_lows = find_troughs(lo, n=neighbor)
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return dict(_BOS_FALLBACK)

    hh = 1.0 if h[swing_highs[-1]] > h[swing_highs[-2]] else -1.0
    hl = 1.0 if lo[swing_lows[-1]] > lo[swing_lows[-2]] else -1.0
    if hh == 1.0 and hl == 1.0:
        trend = 1.0
    elif hh == -1.0 and hl == -1.0:
        trend = -1.0
    else:
        trend = 0.0

    last_sh_price = float(h[swing_highs[-1]])
    last_sl_price = float(lo[swing_lows[-1]])
    check_from = max(swing_highs[-1], swing_lows[-1]) + 1

    bos_direction = 0.0
    bos_strength = 0.0
    shift_idx: int | None = None
    for i in range(check_from, n_bars):
        if c[i] > last_sh_price:
            bos_direction = 1.0
            bos_strength = max(0.0, (float(c[i]) - last_sh_price) / atr_val)
            shift_idx = i
            break
        if c[i] < last_sl_price:
            bos_direction = -1.0
            bos_strength = max(0.0, (last_sl_price - float(c[i])) / atr_val)
            shift_idx = i
            break

    choch_direction = 0.0
    choch_strength = 0.0
    if bos_direction != 0.0 and trend != 0.0 and bos_direction != trend:
        choch_direction = bos_direction
        choch_strength = bos_strength

    bars_since_last_shift = float(n_bars - 1 - shift_idx) if shift_idx is not None else 0.0

    return {
        "bos_strength": float(bos_strength),
        "choch_strength": float(choch_strength),
        "bos_direction": float(bos_direction),
        "choch_direction": float(choch_direction),
        "smc_trend_direction": float(trend),
        "bars_since_last_shift": bars_since_last_shift,
    }


def _amd_phase_ordinal(bar_ts: datetime | None, config: FeatureFactoryConfig) -> float:
    """Ordinal-encode the current AMD cycle phase from bar_ts's UTC hour (Plan 04).

    0.0=unknown (no timestamp), 1.0=accumulation, 2.0=manipulation,
    3.0=distribution -- matches migration 266's column COMMENT and
    164-RESEARCH.md's Anti-patterns A2 mapping. Ported from AMDCyclePlugin's
    phase determination (archive/smc_context/amd_cycle.py); boundaries are
    the same 4 APR-backed UTC hours FeatureCache.update_overnight_range()
    already uses for its own cycle-key derivation.
    """
    if bar_ts is None:
        return _AMD_PHASE_UNKNOWN
    ts = bar_ts if bar_ts.tzinfo is not None else bar_ts.replace(tzinfo=UTC)
    hour = ts.hour
    accum_start = config.smc_amd_accum_start_utc_hour
    manip_end = config.smc_amd_manip_end_utc_hour
    dist_end = config.smc_amd_dist_end_utc_hour
    if hour >= accum_start:
        return _AMD_PHASE_ACCUMULATION
    if hour < manip_end:
        return _AMD_PHASE_MANIPULATION
    if hour < dist_end:
        return _AMD_PHASE_DISTRIBUTION
    return _AMD_PHASE_ACCUMULATION


def _derive_amd_cycle(
    cache: FeatureCache,
    bar_ts: datetime | None,
    config: FeatureFactoryConfig,
) -> dict[str, float]:
    """Derive the 4 clamped/ordinal AMD FeatureVector fields from FeatureCache state (Plan 04).

    Reads FeatureCache's overnight-range/manipulation state (set by
    update_overnight_range(), called once per bar by the caller before
    compute()/inside compute_batch()'s loop) -- never recomputes overnight
    range itself, matching _derive_session_vp()'s "read raw cache state,
    derive bounded output" shape. amd_phase is ordinal-encoded here (see
    _amd_phase_ordinal); manip_strength is clamped to [0,1]
    (164-RESEARCH.md Pitfall 3 -- the mutator's raw breach-depth ratio can
    exceed 1.0 on an overshoot breach). amd_distribution_direction is gated
    to the distribution phase only, matching AMDCyclePlugin's own
    "dist_direction only meaningful during distribution" semantics --
    FeatureCache's raw amd_distribution_direction stays set from the
    manipulation breach bar through the rest of the cycle for the mutator's
    own internal bookkeeping, but this derivation only surfaces it once the
    cycle has actually reached distribution.

    Never raises: a cold cache (no update_overnight_range() call yet) reads
    back its dataclass defaults (all 0.0), which this function treats as
    "no manipulation detected yet" -- a genuine neutral reading, not an
    error state.
    """
    phase = _amd_phase_ordinal(bar_ts, config)
    amd_distribution_direction = (
        cache.amd_distribution_direction if phase == _AMD_PHASE_DISTRIBUTION else 0.0
    )
    return {
        "amd_phase": phase,
        "amd_manipulation_detected": float(cache.amd_manipulation_detected),
        "amd_distribution_direction": float(amd_distribution_direction),
        "manip_strength": clamp(cache.manip_strength, 0.0, 1.0),
    }


# ---------------------------------------------------------------------------
# Kernels
# ---------------------------------------------------------------------------

# One (keys, nullable) spec per key group (FVG and POOL are defined beside their fallbacks above).
OB = KeyGroup.from_fallback(_OB_FALLBACK)
SWEEP = KeyGroup.from_fallback(_SWEEP_FALLBACK)
ZONE = KeyGroup.from_fallback(_ZONE_FALLBACK)
BOS = KeyGroup.from_fallback(_BOS_FALLBACK)
AMD = KeyGroup(
    (
        "amd_phase",
        "amd_manipulation_detected",
        "amd_distribution_direction",
        "manip_strength",
    )
)


def _lookback_of(name: str):
    """Accessor for one declared lookback: the compute and the Kernel's memory both call it, so
    declared memory cannot drift from the window the compute slices."""
    return lambda config: getattr(config, name)


_OB_LOOKBACK = _lookback_of("smc_order_blocks_lookback")
_FVG_LOOKBACK = _lookback_of("smc_fvg_lookback")
_SWEEP_LOOKBACK = _lookback_of("smc_liquidity_sweeps_lookback")
_POOL_LOOKBACK = _lookback_of("smc_liquidity_pools_lookback")
_ZONE_LOOKBACK = _lookback_of("smc_zones_lookback")
_BOS_LOOKBACK = _lookback_of("smc_bos_choch_lookback")


def _compute_order_blocks_columns(x, config):
    opens, highs, lows, closes, volumes = (x[f] for f in ("open", "high", "low", "close", "volume"))
    atr = x[ATR_RAW_PADDED]

    def row(i):
        s = window_start(i, _OB_LOOKBACK(config))
        return _compute_order_blocks(
            opens[s : i + 1],
            highs[s : i + 1],
            lows[s : i + 1],
            closes[s : i + 1],
            volumes[s : i + 1],
            float(closes[i]),
            float(atr[i]),
            config,
        )

    return OB.columns(len(closes), row)


def _compute_fvg_columns(x, config):
    highs, lows, closes, atr = x["high"], x["low"], x["close"], x[ATR_RAW_PADDED]

    def row(i):
        s = window_start(i, _FVG_LOOKBACK(config))
        return _compute_fvg(
            highs[s : i + 1],
            lows[s : i + 1],
            closes[s : i + 1],
            float(closes[i]),
            float(atr[i]),
            config,
        )

    return FVG.columns(len(closes), row)


def _compute_sweeps_columns(x, config):
    highs, lows, closes, atr = x["high"], x["low"], x["close"], x[ATR_RAW_PADDED]

    def row(i):
        s = window_start(i, _SWEEP_LOOKBACK(config))
        return _compute_liquidity_sweeps(
            highs[s : i + 1],
            lows[s : i + 1],
            closes[s : i + 1],
            float(closes[i]),
            float(atr[i]),
            config,
        )

    return SWEEP.columns(len(closes), row)


def _compute_pools_columns(x, config):
    highs, lows, closes, atr = x["high"], x["low"], x["close"], x[ATR_RAW_PADDED]

    def row(i):
        s = window_start(i, _POOL_LOOKBACK(config))
        return _compute_liquidity_pools(
            highs[s : i + 1],
            lows[s : i + 1],
            closes[s : i + 1],
            float(closes[i]),
            float(atr[i]),
            config,
        )

    return POOL.columns(len(closes), row)


def _compute_zones_columns(x, config):
    opens, highs, lows, closes = (x[f] for f in ("open", "high", "low", "close"))
    atr, midpoint, premium = x[ATR_RAW_PADDED], x[_FVG_MIDPOINT], x[_PRICE_IN_PREMIUM]

    def row(i):
        s = window_start(i, _ZONE_LOOKBACK(config))
        return _compute_supply_demand_zones(
            opens[s : i + 1],
            highs[s : i + 1],
            lows[s : i + 1],
            closes[s : i + 1],
            float(closes[i]),
            float(atr[i]),
            config,
            float(midpoint[i]),
            float(premium[i]),
        )

    return ZONE.columns(len(closes), row)


def _compute_bos_columns(x, config):
    highs, lows, closes, atr = x["high"], x["low"], x["close"], x[ATR_RAW_PADDED]

    def row(i):
        s = window_start(i, _BOS_LOOKBACK(config))
        return _compute_bos_choch(
            highs[s : i + 1],
            lows[s : i + 1],
            closes[s : i + 1],
            float(closes[i]),
            float(atr[i]),
            config,
        )

    return BOS.columns(len(closes), row)


def _compute_amd_columns(x, config):
    highs, lows, ts = x["high"], x["low"], x["ts_dt"]
    cache = FeatureCache()
    rows: dict[int, dict[str, float]] = {}
    for i in range(1, len(highs)):
        cache.update_overnight_range(ts[i], float(highs[i]), float(lows[i]), config)
        rows[i] = _derive_amd_cycle(cache, ts[i], config)
    return AMD.columns(len(highs), rows.__getitem__)


def _stateless(name, group, inputs, lookback, compute):
    return Kernel(
        name=name,
        outputs=group.outputs,
        inputs=inputs,
        memory=lambda config: lookback(config) - 1,
        compute=compute,
    )


KERNELS = (
    _stateless(
        "order_blocks",
        OB,
        ("open", "high", "low", "close", "volume", ATR_RAW_PADDED),
        _OB_LOOKBACK,
        _compute_order_blocks_columns,
    ),
    _stateless(
        "fair_value_gaps",
        FVG,
        ("high", "low", "close", ATR_RAW_PADDED),
        _FVG_LOOKBACK,
        _compute_fvg_columns,
    ),
    _stateless(
        "liquidity_sweeps",
        SWEEP,
        ("high", "low", "close", ATR_RAW_PADDED),
        _SWEEP_LOOKBACK,
        _compute_sweeps_columns,
    ),
    _stateless(
        "liquidity_pools",
        POOL,
        ("high", "low", "close", ATR_RAW_PADDED),
        _POOL_LOOKBACK,
        _compute_pools_columns,
    ),
    _stateless(
        "supply_demand_zones",
        ZONE,
        ("open", "high", "low", "close", ATR_RAW_PADDED, _FVG_MIDPOINT, _PRICE_IN_PREMIUM),
        _ZONE_LOOKBACK,
        _compute_zones_columns,
    ),
    _stateless(
        "bos_choch",
        BOS,
        ("high", "low", "close", ATR_RAW_PADDED),
        _BOS_LOOKBACK,
        _compute_bos_columns,
    ),
    Kernel(
        name="amd_cycle",
        outputs=AMD.outputs,
        inputs=("ts_dt", "high", "low"),
        memory=lambda config: 0,
        compute=_compute_amd_columns,
        path_dependent=True,
        path_dependent_reason=(
            "the overnight-range accumulator state and its cycle resets depend on where the "
            "series starts"
        ),
    ),
)
