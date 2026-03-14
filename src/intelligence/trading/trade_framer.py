"""TradeFramer — structural stop/target resolver for I7 signals.

Resolves stop placement and profit targets from structural levels in the
features dict, rather than using raw ATR multiples. Enforces a minimum
RR gate before publishing a signal.

Renaissance principles applied:
- Instrument everything: epsilon tolerance for all floating-point comparisons
- Segment relentlessly: explicit structural levels over hidden constants
- Degrade gracefully: emergency ATR fallback prevents crash

Entry offset logic by setup_type:
  - sweep_reclaim_*, liquidity_hunt_*  → at_reclaim (current close)
  - supply_demand_*                    → zone_proximal (proximal edge)
  - momentum_breakout_*                → at_limit (swing_high/low broken structure)
  - squeeze_expansion_*                → at_limit (bb_middle squeeze centre)
  - trend_long/short                   → at_pullback (nearest_support/resistance)
  - mtf_alignment_*                    → at_pullback (nearest S/R as CTF proxy)
  - all others                         → at_close (current close)

Stop placement hierarchy (longs):
  1. in_demand_zone  → nearest_demand_low - ATR×0.25
  2. sweep_detected  → sweep_level - ATR×0.30
  3. ob_type==1 and ob_bottom < entry  → ob_bottom - ATR×0.20
  4. swing_low > 0 and < entry         → swing_low - ATR×0.25
  5. sr_nearest_support < entry        → sr_nearest_support - ATR×0.50
  Fallback: entry - ATR×2.0

Target level collection (longs, candidates above entry):
  nearest_resistance, bsl_level (if bsl_significance>=0.5), vwap_upper_1,
  vwap_upper_2, fvg_top (if fvg_type==1), ob_top (if ob_type==1 and above entry),
  kalman_upper, nearest_demand_high (if above entry)
  Filtered to entry+ATR×0.5 < level < entry+ATR×8.
  T1 = first with rr >= 1.5, T2 = first after T1 with rr >= 2.5.
  Fallback: ATR-based T1=+2.0×risk, T2=+3.5×risk.

RR gate: if T1 rr < 1.5 → viable=False.
Pullback-entry staleness gate: for at_pullback entries, if close has already passed T1
  in the signal direction (short: close < T1; long: close > T1) → viable=False
  with rejection_reason="pullback_entry_price_past_t1".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EPSILON_TOLERANCE = (
    1e-9  # Tolerance for floating-point comparisons (Renaissance: instrument everything)
)

# ATR multipliers for stop placement (Renaissance: explicit structural levels over hidden constants)
ATR_STOP_DEMAND_MULTIPLIER = 0.25  # Demand zone: nearest_demand_low - ATR×0.25
ATR_STOP_SWEEP_MULTIPLIER = 0.30  # Sweep detected: sweep_level - ATR×0.30
ATR_STOP_OB_MULTIPLIER = 0.20  # Order block: ob_bottom/top ± ATR×0.20
ATR_STOP_SWING_MULTIPLIER = 0.25  # Swing: swing_low/high ± ATR×0.25
ATR_STOP_SR_MULTIPLIER = 0.50  # S/R: nearest_support/resistance ± ATR×0.50
ATR_STOP_FALLBACK_MULTIPLIER = 2.0  # Fallback: entry ± ATR×2.0

# ATR multipliers for zone and target bounds
ATR_ZONE_SWEEP_MULTIPLIER = 0.5  # Sweep/reclaim zone: entry ± ATR×0.5
ATR_ZONE_LOW_MULTIPLIER = 1.0  # Zone lower bound: entry - ATR×1.0
ATR_ZONE_HIGH_MULTIPLIER = 0.5  # Zone upper bound: entry + ATR×0.5
ATR_TARGET_MIN_MULTIPLIER = 0.5  # Minimum target distance: entry ± ATR×0.5
ATR_TARGET_MAX_MULTIPLIER = 8.0  # Maximum target distance: entry ± ATR×8.0

# ATR target multipliers for fallback (RR-based)
ATR_FALLBACK_T1_MULTIPLIER = 2.0  # T1: risk × 2.0
ATR_FALLBACK_T2_MULTIPLIER = 3.5  # T2: risk × 3.5
ATR_FALLBACK_T3_MULTIPLIER = 5.5  # T3: risk × 5.5

# Emergency ATR fallback (Renaissance: degrade gracefully)
ATR_EMERGENCY_FALLBACK_PCT = 0.001  # 0.1% of price as emergency ATR

# RR and stop distance constants (Renaissance: minimum viable thresholds)
MIN_STOP_ATR_MULTIPLIER = 1.0  # Minimum stop distance: at least 1×ATR from entry
MIN_RR_T1 = 1.5  # Minimum reward-to-risk for T1: signals below this are rejected


@dataclass
class TradeTarget:
    price: float
    label: str  # e.g. "BSL 4521.25", "VWAP+1σ 4530"
    level_type: str
    # "bsl" | "ssl" | "vwap_1sigma" | "vwap_2sigma" | "sr" | "fvg"
    # | "ob" | "kalman" | "atr" | "demand_zone"
    rr: float  # reward-to-risk ratio for this target


@dataclass
class TradeFrame:
    entry: float
    entry_type: str  # "at_close"|"at_reclaim"|"zone_proximal"|"at_limit"|"at_pullback"
    stop: float
    stop_type: str  # "demand_zone" | "sweep_level" | "ob_bottom" | "swing_low"
    # | "sr_support" | "atr"
    targets: list[TradeTarget] = field(default_factory=list)
    rr_t1: float = 0.0
    rr_t2: float = 0.0
    rr_t3: float = 0.0
    method: str = "atr_fallback"  # "structural" | "atr_fallback"
    viable: bool = True
    rejection_reason: str | None = None
    zone_low: float = 0.0  # lower bound of entry zone (zone_low < zone_high always)
    zone_high: float = 0.0  # upper bound of entry zone


def _fval(features: dict[str, Any], key: str, default: float = 0.0) -> float:
    """Safe float extraction from features dict."""
    v = features.get(key)
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _reject_frame(
    reason: str,
    entry: float,
    entry_type: str,
    stop: float,
    stop_type: str,
    zone_low: float,
    zone_high: float,
    targets: list[TradeTarget] | None = None,
    rr_t1: float = 0.0,
    rr_t2: float = 0.0,
    rr_t3: float = 0.0,
    method: str = "atr_fallback",
) -> TradeFrame:
    """Return a non-viable TradeFrame with the given rejection reason."""
    return TradeFrame(
        entry=entry,
        entry_type=entry_type,
        stop=stop,
        stop_type=stop_type,
        targets=targets if targets is not None else [],
        rr_t1=rr_t1,
        rr_t2=rr_t2,
        rr_t3=rr_t3,
        method=method,
        viable=False,
        rejection_reason=reason,
        zone_low=zone_low,
        zone_high=zone_high,
    )


def _resolve_zone_bounds(
    setup_type: str,
    direction: int,
    entry: float,
    features: dict[str, Any],
    atr: float,
) -> tuple[float, float]:
    """Return (zone_low, zone_high) for the entry zone.

    Uses structural levels when available; falls back to entry ± ATR multiples.
    zone_low < zone_high always (independent of direction).
    """
    st = setup_type.lower()

    # Supply/Demand zone entries — use the demand/supply zone bounds
    if st.startswith("supply_demand"):
        if direction == 1:
            low = _fval(features, "nearest_demand_low")
            high = _fval(features, "nearest_demand_high")
        else:
            low = _fval(features, "nearest_supply_low")
            high = _fval(features, "nearest_supply_high")
        if EPSILON_TOLERANCE < low < high:
            return low, high

    # FVG fill — use FVG bottom/top
    if st.startswith("fvg"):
        fvg_bottom = _fval(features, "fvg_bottom")
        fvg_top = _fval(features, "fvg_top")
        if EPSILON_TOLERANCE < fvg_bottom < fvg_top:
            return fvg_bottom, fvg_top

    # Order block entries — use OB bottom/top
    if st.startswith("choch") or "ob" in st:
        ob_bottom = _fval(features, "ob_bottom")
        ob_top = _fval(features, "ob_top")
        if EPSILON_TOLERANCE < ob_bottom < ob_top:
            return ob_bottom, ob_top

    # Sweep/reclaim — tight zone ± 0.5×ATR around entry
    if st.startswith("sweep") or st.startswith("liquidity_hunt"):
        return entry - atr * ATR_ZONE_SWEEP_MULTIPLIER, entry + atr * ATR_ZONE_SWEEP_MULTIPLIER

    # ATR fallback — standard ±ATR band
    return entry - atr * ATR_ZONE_LOW_MULTIPLIER, entry + atr * ATR_ZONE_HIGH_MULTIPLIER


def _resolve_entry(
    setup_type: str,
    direction: int,
    entry_price: float,
    features: dict[str, Any],
) -> tuple[float, str]:
    """Return (entry_price, entry_type) based on setup type."""
    st = setup_type.lower()
    if st.startswith("sweep_reclaim") or st.startswith("liquidity_hunt"):
        return entry_price, "at_reclaim"
    if st.startswith("supply_demand"):
        if direction == 1:
            # Long: enter at demand zone proximal (zone high)
            zone_high = _fval(features, "nearest_demand_high")
            if zone_high > EPSILON_TOLERANCE:
                return zone_high, "zone_proximal"
        else:
            # Short: enter at supply zone proximal (zone low)
            zone_low = _fval(features, "nearest_supply_low")
            if zone_low > EPSILON_TOLERANCE:
                return zone_low, "zone_proximal"

    # momentum_breakout → at_limit at broken structure level (swing_high/low)
    if st.startswith("momentum_breakout"):
        if direction == 1:
            level = _fval(features, "swing_high")
            if (
                level > EPSILON_TOLERANCE and level <= entry_price
            ):  # limit below current price for long
                return level, "at_limit"
        else:
            level = _fval(features, "swing_low")
            if (
                level > EPSILON_TOLERANCE and level >= entry_price
            ):  # limit above current price for short
                return level, "at_limit"

    # squeeze_expansion → at_limit at bb_middle (squeeze centre)
    if st.startswith("squeeze_expansion") or st.startswith("squeeze"):
        bb_middle = _fval(features, "bb_middle")
        if bb_middle > EPSILON_TOLERANCE:
            return bb_middle, "at_limit"

    # trend → at_pullback at nearest_support/resistance
    if st.startswith("trend_"):
        if direction == 1:
            level = _fval(features, "nearest_support") or _fval(features, "sr_nearest_support")
            if level > EPSILON_TOLERANCE and level < entry_price:  # pullback below current for long
                return level, "at_pullback"
        else:
            level = _fval(features, "nearest_resistance") or _fval(
                features, "sr_nearest_resistance"
            )
            if (
                level > EPSILON_TOLERANCE and level > entry_price
            ):  # pullback above current for short
                return level, "at_pullback"

    # mtf_alignment → at_pullback using nearest_support/resistance as CTF level proxy
    # Decision: no ctf_level price field exists in schema; using nearest S/R as structural proxy
    if st.startswith("mtf_alignment"):
        if direction == 1:
            level = _fval(features, "nearest_support") or _fval(features, "sr_nearest_support")
            if level > EPSILON_TOLERANCE and level < entry_price:
                return level, "at_pullback"
        else:
            level = _fval(features, "nearest_resistance") or _fval(
                features, "sr_nearest_resistance"
            )
            if level > EPSILON_TOLERANCE and level > entry_price:
                return level, "at_pullback"

    return entry_price, "at_close"


def _resolve_stop_long(entry: float, atr: float, features: dict[str, Any]) -> tuple[float, str]:
    """Stop placement hierarchy for long trades."""
    min_stop = entry - atr * MIN_STOP_ATR_MULTIPLIER

    # Priority 1: in demand zone
    in_demand = _fval(features, "in_demand_zone")
    nearest_demand_low = _fval(features, "nearest_demand_low")
    if in_demand == 1.0 and nearest_demand_low > EPSILON_TOLERANCE:
        stop = nearest_demand_low - atr * ATR_STOP_DEMAND_MULTIPLIER
        if stop < entry - EPSILON_TOLERANCE:
            return min(stop, min_stop), "demand_zone"

    # Priority 2: sweep detected
    sweep_detected = _fval(features, "sweep_detected")
    sweep_level = _fval(features, "sweep_level")
    if sweep_detected == 1.0 and sweep_level > EPSILON_TOLERANCE:
        stop = sweep_level - atr * ATR_STOP_SWEEP_MULTIPLIER
        if stop < entry - EPSILON_TOLERANCE:
            return min(stop, min_stop), "sweep_level"

    # Priority 3: order block bottom
    ob_type = _fval(features, "ob_type")
    ob_bottom = _fval(features, "ob_bottom")
    if ob_type == 1.0 and ob_bottom > EPSILON_TOLERANCE and ob_bottom < entry:
        stop = ob_bottom - atr * ATR_STOP_OB_MULTIPLIER
        return min(stop, min_stop), "ob_bottom"

    # Priority 4: swing low
    swing_low = _fval(features, "swing_low")
    if swing_low > EPSILON_TOLERANCE and swing_low < entry:
        stop = swing_low - atr * ATR_STOP_SWING_MULTIPLIER
        return min(stop, min_stop), "swing_low"

    # Priority 5: S/R nearest support
    sr_support = _fval(features, "sr_nearest_support") or _fval(features, "nearest_support")
    if sr_support > EPSILON_TOLERANCE and sr_support < entry:
        stop = sr_support - atr * ATR_STOP_SR_MULTIPLIER
        return min(stop, min_stop), "sr_support"

    # Fallback: ATR×2.0
    return entry - atr * ATR_STOP_FALLBACK_MULTIPLIER, "atr"


def _resolve_stop_short(entry: float, atr: float, features: dict[str, Any]) -> tuple[float, str]:
    """Stop placement hierarchy for short trades (mirror of long)."""
    max_stop = entry + atr * MIN_STOP_ATR_MULTIPLIER

    # Priority 1: in supply zone
    in_supply = _fval(features, "in_supply_zone")
    nearest_supply_high = _fval(features, "nearest_supply_high")
    if in_supply == 1.0 and nearest_supply_high > EPSILON_TOLERANCE:
        stop = nearest_supply_high + atr * ATR_STOP_DEMAND_MULTIPLIER
        if stop > entry + EPSILON_TOLERANCE:
            return max(stop, max_stop), "supply_zone"

    # Priority 2: sweep detected
    sweep_detected = _fval(features, "sweep_detected")
    sweep_level = _fval(features, "sweep_level")
    if sweep_detected == 1.0 and sweep_level > EPSILON_TOLERANCE:
        stop = sweep_level + atr * ATR_STOP_SWEEP_MULTIPLIER
        if stop > entry + EPSILON_TOLERANCE:
            return max(stop, max_stop), "sweep_level"

    # Priority 3: order block top
    ob_type = _fval(features, "ob_type")
    ob_top = _fval(features, "ob_top")
    if ob_type == -1.0 and ob_top > EPSILON_TOLERANCE and ob_top > entry:
        stop = ob_top + atr * ATR_STOP_OB_MULTIPLIER
        return max(stop, max_stop), "ob_top"

    # Priority 4: swing high
    swing_high = _fval(features, "swing_high")
    if swing_high > EPSILON_TOLERANCE and swing_high > entry:
        stop = swing_high + atr * ATR_STOP_SWING_MULTIPLIER
        return max(stop, max_stop), "swing_high"

    # Priority 5: S/R nearest resistance
    sr_resistance = _fval(features, "sr_nearest_resistance") or _fval(
        features, "nearest_resistance"
    )
    if sr_resistance > EPSILON_TOLERANCE and sr_resistance > entry:
        stop = sr_resistance + atr * ATR_STOP_SR_MULTIPLIER
        return max(stop, max_stop), "sr_resistance"

    # Fallback: ATR×2.0
    return entry + atr * ATR_STOP_FALLBACK_MULTIPLIER, "atr"


def _collect_targets_long(
    entry: float, stop: float, atr: float, features: dict[str, Any]
) -> list[TradeTarget]:
    """Collect and rank candidate target levels above entry for longs."""
    risk = abs(entry - stop)
    if risk <= EPSILON_TOLERANCE:
        return []

    min_level = entry + atr * ATR_TARGET_MIN_MULTIPLIER
    max_level = entry + atr * ATR_TARGET_MAX_MULTIPLIER

    candidates: list[tuple[float, str, str]] = []  # (price, label, level_type)

    # S/R resistance
    nearest_resistance = _fval(features, "nearest_resistance") or _fval(
        features, "sr_nearest_resistance"
    )
    if nearest_resistance > EPSILON_TOLERANCE:
        candidates.append((nearest_resistance, f"S/R {nearest_resistance:.2f}", "sr"))

    # BSL level (if significant)
    bsl_level = _fval(features, "bsl_level")
    bsl_significance = _fval(features, "bsl_significance")
    if bsl_level > EPSILON_TOLERANCE and bsl_significance >= 0.5:
        candidates.append((bsl_level, f"BSL (sig={bsl_significance:.2f}) {bsl_level:.2f}", "bsl"))

    # VWAP bands (stored as extras in i1)
    vwap_upper_1 = _fval(features, "vwap_upper_1")
    if vwap_upper_1 > EPSILON_TOLERANCE:
        candidates.append((vwap_upper_1, f"VWAP+1σ {vwap_upper_1:.2f}", "vwap_1sigma"))

    vwap_upper_2 = _fval(features, "vwap_upper_2")
    if vwap_upper_2 > EPSILON_TOLERANCE:
        candidates.append((vwap_upper_2, f"VWAP+2σ {vwap_upper_2:.2f}", "vwap_2sigma"))

    # FVG top (bullish FVG: type==1)
    fvg_type = _fval(features, "fvg_type")
    fvg_top = _fval(features, "fvg_top")
    if fvg_type == 1.0 and fvg_top > EPSILON_TOLERANCE:
        candidates.append((fvg_top, f"FVG top {fvg_top:.2f}", "fvg"))

    # OB top (bullish OB: type==1)
    ob_type = _fval(features, "ob_type")
    ob_top = _fval(features, "ob_top")
    if ob_type == 1.0 and ob_top > entry:
        candidates.append((ob_top, f"OB top {ob_top:.2f}", "ob"))

    # Kalman upper
    kalman_upper = _fval(features, "kalman_upper")
    if kalman_upper > EPSILON_TOLERANCE:
        candidates.append((kalman_upper, f"Kalman upper {kalman_upper:.2f}", "kalman"))

    # Demand zone high (if above entry — targeting into supply)
    nearest_demand_high = _fval(features, "nearest_demand_high")
    if nearest_demand_high > entry:
        candidates.append(
            (
                nearest_demand_high,
                f"Demand zone {nearest_demand_high:.2f}",
                "demand_zone",
            )
        )

    # Filter to valid range
    valid = [
        (price, label, ltype) for price, label, ltype in candidates if min_level < price < max_level
    ]
    # Sort by distance ascending
    valid.sort(key=lambda x: x[0])

    # Convert to TradeTarget with RR
    return [
        TradeTarget(price=price, label=label, level_type=ltype, rr=round((price - entry) / risk, 2))
        for price, label, ltype in valid
    ]


def _collect_targets_short(
    entry: float, stop: float, atr: float, features: dict[str, Any]
) -> list[TradeTarget]:
    """Collect and rank candidate target levels below entry for shorts."""
    risk = abs(stop - entry)
    if risk <= EPSILON_TOLERANCE:
        return []

    min_level = entry - atr * ATR_TARGET_MAX_MULTIPLIER
    max_level = entry - atr * ATR_TARGET_MIN_MULTIPLIER

    candidates: list[tuple[float, str, str]] = []

    # S/R support
    nearest_support = _fval(features, "nearest_support") or _fval(features, "sr_nearest_support")
    if nearest_support > EPSILON_TOLERANCE:
        candidates.append((nearest_support, f"S/R {nearest_support:.2f}", "sr"))

    # SSL level (if significant)
    ssl_level = _fval(features, "ssl_level")
    ssl_significance = _fval(features, "ssl_significance")
    if ssl_level > EPSILON_TOLERANCE and ssl_significance >= 0.5:
        candidates.append((ssl_level, f"SSL (sig={ssl_significance:.2f}) {ssl_level:.2f}", "ssl"))

    # VWAP bands
    vwap_lower_1 = _fval(features, "vwap_lower_1")
    if vwap_lower_1 > EPSILON_TOLERANCE:
        candidates.append((vwap_lower_1, f"VWAP-1σ {vwap_lower_1:.2f}", "vwap_1sigma"))

    vwap_lower_2 = _fval(features, "vwap_lower_2")
    if vwap_lower_2 > EPSILON_TOLERANCE:
        candidates.append((vwap_lower_2, f"VWAP-2σ {vwap_lower_2:.2f}", "vwap_2sigma"))

    # FVG bottom (bearish FVG: type==-1)
    fvg_type = _fval(features, "fvg_type")
    fvg_bottom = _fval(features, "fvg_bottom")
    if fvg_type == -1.0 and fvg_bottom > EPSILON_TOLERANCE:
        candidates.append((fvg_bottom, f"FVG bottom {fvg_bottom:.2f}", "fvg"))

    # OB bottom (bearish OB: type==-1)
    ob_type = _fval(features, "ob_type")
    ob_bottom = _fval(features, "ob_bottom")
    if ob_type == -1.0 and ob_bottom > EPSILON_TOLERANCE and ob_bottom < entry:
        candidates.append((ob_bottom, f"OB bottom {ob_bottom:.2f}", "ob"))

    # Kalman lower
    kalman_lower = _fval(features, "kalman_lower")
    if kalman_lower > EPSILON_TOLERANCE:
        candidates.append((kalman_lower, f"Kalman lower {kalman_lower:.2f}", "kalman"))

    # Supply zone low (if below entry)
    nearest_supply_low = _fval(features, "nearest_supply_low")
    if EPSILON_TOLERANCE < nearest_supply_low < entry:
        candidates.append(
            (
                nearest_supply_low,
                f"Supply zone {nearest_supply_low:.2f}",
                "supply_zone",
            )
        )

    # Filter to valid range
    valid = [
        (price, label, ltype) for price, label, ltype in candidates if min_level < price < max_level
    ]
    # Sort by distance ascending (closest first = largest price value for shorts)
    valid.sort(key=lambda x: x[0], reverse=True)

    return [
        TradeTarget(price=price, label=label, level_type=ltype, rr=round((entry - price) / risk, 2))
        for price, label, ltype in valid
    ]


def _pick_targets(
    candidates: list[TradeTarget],
    entry: float,
    stop: float,
    atr: float,
    direction: int,
    min_rr_t1: float = 1.5,
    min_rr_t2: float = 2.5,
    min_rr_t3: float = 4.0,
) -> tuple[list[TradeTarget], bool]:
    """Pick T1/T2/T3 from candidates. Returns (targets, is_structural)."""
    risk = abs(entry - stop)

    t1: TradeTarget | None = None
    t2: TradeTarget | None = None
    t3: TradeTarget | None = None

    for cand in candidates:
        if t1 is None and cand.rr >= min_rr_t1:
            t1 = cand
        elif t1 is not None and t2 is None and cand.rr >= min_rr_t2:
            t2 = cand
        elif t2 is not None and cand.rr >= min_rr_t3:
            t3 = cand
            break

    if t1 is not None:
        targets = [t1]
        if t2 is not None:
            targets.append(t2)
        if t3 is not None:
            targets.append(t3)
        return targets, True

    # ATR fallback — always 3 levels
    sign = 1 if direction == 1 else -1
    return [
        TradeTarget(
            price=round(entry + sign * risk * ATR_FALLBACK_T1_MULTIPLIER, 2),
            label="ATR T1",
            level_type="atr",
            rr=ATR_FALLBACK_T1_MULTIPLIER,
        ),
        TradeTarget(
            price=round(entry + sign * risk * ATR_FALLBACK_T2_MULTIPLIER, 2),
            label="ATR T2",
            level_type="atr",
            rr=ATR_FALLBACK_T2_MULTIPLIER,
        ),
        TradeTarget(
            price=round(entry + sign * risk * ATR_FALLBACK_T3_MULTIPLIER, 2),
            label="ATR T3",
            level_type="atr",
            rr=ATR_FALLBACK_T3_MULTIPLIER,
        ),
    ], False


def frame_trade(
    setup_type: str,
    direction: int,
    entry: float,
    features: dict[str, Any],
    atr: float,
) -> TradeFrame:
    """Resolve structural stop/targets for a signal.

    Parameters
    ----------
    setup_type:
        Signal type string (e.g. "trend_long", "sweep_reclaim_long")
    direction:
        1 for long, -1 for short
    entry:
        Raw entry price from plugin (current close)
    features:
        Full features dict from _build_features_from_event()
    atr:
        ATR value (ATR×14 from I1)

    Returns
    -------
    TradeFrame with stop, targets, RR values, and viability flag.
    """
    if atr <= EPSILON_TOLERANCE:
        atr = abs(entry) * ATR_EMERGENCY_FALLBACK_PCT  # 0.1% of price as emergency fallback

    # Resolve entry with setup-specific offset
    resolved_entry, entry_type = _resolve_entry(setup_type, direction, entry, features)

    # Resolve stop
    if direction == 1:
        stop, stop_type = _resolve_stop_long(resolved_entry, atr, features)
        candidates = _collect_targets_long(resolved_entry, stop, atr, features)
    else:
        stop, stop_type = _resolve_stop_short(resolved_entry, atr, features)
        candidates = _collect_targets_short(resolved_entry, stop, atr, features)

    # Resolve entry zone bounds (used by signal_lifecycle_service for activation)
    zone_low, zone_high = _resolve_zone_bounds(setup_type, direction, resolved_entry, features, atr)

    risk = abs(resolved_entry - stop)
    if risk <= EPSILON_TOLERANCE:
        return _reject_frame(
            "zero_risk: stop == entry",
            resolved_entry,
            entry_type,
            stop,
            stop_type,
            zone_low,
            zone_high,
        )

    targets, is_structural = _pick_targets(candidates, resolved_entry, stop, atr, direction)

    if not targets:
        return _reject_frame(
            "no_targets_found",
            resolved_entry,
            entry_type,
            stop,
            stop_type,
            zone_low,
            zone_high,
        )

    rr_t1 = targets[0].rr
    rr_t2 = targets[1].rr if len(targets) > 1 else 0.0
    rr_t3 = targets[2].rr if len(targets) > 2 else 0.0
    method = "structural" if is_structural else "atr_fallback"

    # Pullback-entry staleness gate: reject if current price has already moved past T1.
    # For at_pullback entries the close price ≠ entry (price must rally/fall to entry).
    # If close has already passed T1 in the signal direction, the trade is unreachable:
    # price would need to reverse N points just to enter, having already exceeded the target.
    close_price = _fval(features, "close_price")
    if close_price > EPSILON_TOLERANCE and entry_type == "at_pullback":
        t1_price = targets[0].price
        price_past_t1 = (direction == -1 and close_price < t1_price) or (  # short: close below T1
            direction == 1 and close_price > t1_price
        )  # long: close above T1
        if price_past_t1:
            return _reject_frame(
                "pullback_entry_price_past_t1",
                resolved_entry,
                entry_type,
                stop,
                stop_type,
                zone_low,
                zone_high,
                targets=targets,
                rr_t1=rr_t1,
                rr_t2=rr_t2,
                rr_t3=rr_t3,
                method=method,
            )

    if rr_t1 < MIN_RR_T1:
        return _reject_frame(
            f"rr_below_{MIN_RR_T1}: {rr_t1:.2f}",
            resolved_entry,
            entry_type,
            stop,
            stop_type,
            zone_low,
            zone_high,
            targets=targets,
            rr_t1=rr_t1,
            rr_t2=rr_t2,
            rr_t3=rr_t3,
            method=method,
        )

    return TradeFrame(
        entry=resolved_entry,
        entry_type=entry_type,
        stop=round(stop, 2),
        stop_type=stop_type,
        targets=targets,
        rr_t1=rr_t1,
        rr_t2=rr_t2,
        rr_t3=rr_t3,
        method=method,
        viable=True,
        rejection_reason=None,
        zone_low=zone_low,
        zone_high=zone_high,
    )
