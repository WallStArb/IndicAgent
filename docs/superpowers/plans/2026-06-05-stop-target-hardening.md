# Stop/Target Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace discrete GARCH stop scaling with continuous adaptive buffering, unify and expand target candidates with institutional levels, and add a T1-gated chandelier floor to prevent giving back profit after T1.

**Architecture:** Three independent changes across two files. Task 1 adds `_adaptive_buffer()` and wires it into stop resolution, removing `GARCH_MULTIPLIERS`. Task 2 replaces the duplicated long/short target functions with a unified function that adds institutional levels. Task 3 adds `be_floor` to `chandelier_state` in the lifecycle tracker so the chandelier can never trail below entry after T1 is hit.

**Tech Stack:** Python 3.11, pytest, structlog. No new dependencies.

---

## File Map

| File | Change |
|------|--------|
| `src/intelligence/trading/trade_framer.py` | Tasks 1 + 2: add `_adaptive_buffer`, remove `GARCH_MULTIPLIERS`/`effective_atr`, unify target collection, add institutional candidates |
| `src/intelligence/trading/lifecycle_tracker.py` | Task 3: add `be_floor` advancement + chandelier floor clamp |
| `tests/unit/intelligence/test_trade_framer.py` | Tasks 1 + 2: add tests, update imports |
| `tests/unit/intelligence/test_lifecycle_tracker.py` | Task 3: add floor tests |

---

## Task 1: Adaptive Buffer — `_adaptive_buffer` + remove GARCH_MULTIPLIERS

**Files:**
- Modify: `src/intelligence/trading/trade_framer.py`
- Modify: `tests/unit/intelligence/test_trade_framer.py`

- [ ] **Step 1.1: Write failing tests for `_adaptive_buffer`**

Add to `tests/unit/intelligence/test_trade_framer.py` — import will fail until implementation:

```python
from src.intelligence.trading.trade_framer import (
    _adaptive_buffer,  # add to existing import block
    ...
)

class TestAdaptiveBuffer:
    def test_anchor_quiet_regime(self):
        # vol_ratio=0.70 → garch_mult=0.80 → result = base * 0.80
        f = {"garch_vol_ratio": 0.70}
        assert _adaptive_buffer(f, 1.0) == pytest.approx(0.80, rel=1e-4)

    def test_anchor_normal_regime(self):
        # vol_ratio=1.00 → garch_mult=1.00 → result = base * 1.00
        f = {"garch_vol_ratio": 1.00}
        assert _adaptive_buffer(f, 1.0) == pytest.approx(1.00, rel=1e-4)

    def test_anchor_high_regime(self):
        # vol_ratio=1.50 → garch_mult=1.35 → result = base * 1.35
        f = {"garch_vol_ratio": 1.50}
        assert _adaptive_buffer(f, 1.0) == pytest.approx(1.35, rel=1e-4)

    def test_interpolates_between_anchors(self):
        # vol_ratio=0.85 is midpoint of [0.70, 1.00] → garch_mult midpoint of [0.80, 1.00] = 0.90
        f = {"garch_vol_ratio": 0.85}
        assert _adaptive_buffer(f, 1.0) == pytest.approx(0.90, rel=1e-4)

    def test_missing_vol_ratio_defaults_to_normal(self):
        # None → vol_ratio defaults to 1.0 → garch_mult=1.0
        f = {}
        assert _adaptive_buffer(f, 1.0) == pytest.approx(1.00, rel=1e-4)

    def test_shock_floor_applied(self):
        # garch_shock > 3.0 → floor at base * 1.35
        f = {"garch_vol_ratio": 0.70, "garch_shock": 3.5}
        result = _adaptive_buffer(f, 1.0)
        assert result == pytest.approx(1.35, rel=1e-4)

    def test_hard_cap_limits_expansion(self):
        # vol_ratio clipped to 1.50 max → garch_mult=1.35; cap=1.40; 1.35 < 1.40 so cap not hit
        f = {"garch_vol_ratio": 2.0}  # clipped to 1.50
        assert _adaptive_buffer(f, 1.0) == pytest.approx(1.35, rel=1e-4)

    def test_hurst_tightens_trend_signal(self):
        # H=0.75 with trend signal → tighten by (0.75-0.55)*0.16 = 0.032
        f = {"garch_vol_ratio": 1.0, "hurst_exponent": 0.75}
        result = _adaptive_buffer(f, 1.0, regime_type="trend")
        assert result == pytest.approx(1.0 * (1.0 - (0.75 - 0.55) * 0.16), rel=1e-4)

    def test_hurst_tightens_mean_reversion_signal(self):
        # H=0.25 with mean_reversion signal → tighten by (0.45-0.25)*0.16 = 0.032
        f = {"garch_vol_ratio": 1.0, "hurst_exponent": 0.25}
        result = _adaptive_buffer(f, 1.0, regime_type="mean_reversion")
        assert result == pytest.approx(1.0 * (1.0 - (0.45 - 0.25) * 0.16), rel=1e-4)

    def test_hurst_conflict_no_adjustment(self):
        # H=0.25 (mean-reverting) with trend signal → no adjustment
        f = {"garch_vol_ratio": 1.0, "hurst_exponent": 0.25}
        assert _adaptive_buffer(f, 1.0, regime_type="trend") == pytest.approx(1.0, rel=1e-4)

    def test_regime_type_none_no_hurst_adjustment(self):
        f = {"garch_vol_ratio": 1.0, "hurst_exponent": 0.75}
        assert _adaptive_buffer(f, 1.0, regime_type=None) == pytest.approx(1.0, rel=1e-4)

    def test_base_mult_scaling(self):
        # base_mult=0.25, normal vol → 0.25 * 1.0 = 0.25
        f = {"garch_vol_ratio": 1.0}
        assert _adaptive_buffer(f, 0.25) == pytest.approx(0.25, rel=1e-4)
```

- [ ] **Step 1.2: Run tests — verify they fail**

```bash
.venv/bin/pytest tests/unit/intelligence/test_trade_framer.py::TestAdaptiveBuffer -v
```
Expected: `ImportError` or `NameError` on `_adaptive_buffer`.

- [ ] **Step 1.3: Add `ADAPTIVE_BUFFER_HARD_CAP` constant and `_adaptive_buffer` function**

In `src/intelligence/trading/trade_framer.py`, delete lines 98-101 (the `GARCH_MULTIPLIERS` block) and replace with:

```python
ADAPTIVE_BUFFER_HARD_CAP = 1.40  # maximum vol-driven multiplier expansion


def _adaptive_buffer(
    features: dict, base_mult: float, regime_type: str | None = None
) -> float:
    """GARCH-continuous ATR buffer with Hurst regime-confirmation tightening.

    Replaces the discrete GARCH_MULTIPLIERS step function. Piecewise-linear
    through the three calibrated regime anchors (0.70→0.80, 1.00→1.00,
    1.50→1.35) so behaviour at anchor points is preserved.

    regime_type: the calling plugin's regime_type ("trend" | "mean_reversion" | "any").
        None or "any" → no Hurst adjustment.
    """
    vol_ratio = float(features.get("garch_vol_ratio") or 1.0)
    vol_ratio = max(0.70, min(1.50, vol_ratio))

    if vol_ratio <= 1.0:
        garch_mult = 0.80 + (vol_ratio - 0.70) * (0.20 / 0.30)
    else:
        garch_mult = 1.00 + (vol_ratio - 1.00) * (0.35 / 0.50)

    result = base_mult * garch_mult

    # Hurst regime-confirmation tightening (only narrows — never widens).
    hurst = features.get("hurst_exponent")
    if hurst is not None and regime_type in ("trend", "mean_reversion"):
        h = float(hurst)
        if regime_type == "trend" and h >= 0.55:
            result *= 1.0 - (h - 0.55) * 0.16
        elif regime_type == "mean_reversion" and h <= 0.45:
            result *= 1.0 - (0.45 - h) * 0.16

    # Shock floor: single extreme bar forces at least regime-2 anchor.
    if float(features.get("garch_shock") or 0.0) > 3.0:
        result = max(result, base_mult * 1.35)

    return min(result, base_mult * ADAPTIVE_BUFFER_HARD_CAP)
```

- [ ] **Step 1.4: Run tests — verify they pass**

```bash
.venv/bin/pytest tests/unit/intelligence/test_trade_framer.py::TestAdaptiveBuffer -v
```
Expected: all PASS.

- [ ] **Step 1.5: Add `regime_type` parameter to stop resolution functions**

In `_resolve_stop_long` (line 454), change signature and replace every `atr * ATR_STOP_*` literal with `_adaptive_buffer`:

```python
def _resolve_stop_long(
    entry: float, atr: float, features: dict[str, Any], regime_type: str | None = None
) -> tuple[float, str]:
    """Stop placement hierarchy for long trades."""
    min_stop = entry - atr * _adaptive_buffer(features, MIN_STOP_ATR_MULTIPLIER, regime_type)

    fvg_type = _fval(features, "fvg_type")
    fvg_bottom = _fval(features, "fvg_bottom")
    if fvg_type == 1.0 and fvg_bottom > EPSILON_TOLERANCE and fvg_bottom < entry:
        stop = fvg_bottom - atr * _adaptive_buffer(features, ATR_STOP_OB_MULTIPLIER, regime_type)
        if stop < entry - EPSILON_TOLERANCE:
            return min(stop, min_stop), "fvg_low"

    in_demand = _fval(features, "in_demand_zone")
    nearest_demand_low = _fval(features, "nearest_demand_low")
    if in_demand == 1.0 and nearest_demand_low > EPSILON_TOLERANCE:
        stop = nearest_demand_low - atr * _adaptive_buffer(features, ATR_STOP_DEMAND_MULTIPLIER, regime_type)
        if stop < entry - EPSILON_TOLERANCE:
            return min(stop, min_stop), "demand_zone"

    sweep_detected = _fval(features, "sweep_detected")
    sweep_level = _fval(features, "sweep_level")
    if sweep_detected == 1.0 and sweep_level > EPSILON_TOLERANCE:
        stop = sweep_level - atr * _adaptive_buffer(features, ATR_STOP_SWEEP_MULTIPLIER, regime_type)
        if stop < entry - EPSILON_TOLERANCE:
            return min(stop, min_stop), "sweep_level"

    ob_type = _fval(features, "ob_type")
    ob_bottom = _fval(features, "ob_bottom")
    if ob_type == 1.0 and ob_bottom > EPSILON_TOLERANCE and ob_bottom < entry:
        stop = ob_bottom - atr * _adaptive_buffer(features, ATR_STOP_OB_MULTIPLIER, regime_type)
        return min(stop, min_stop), "ob_bottom"

    swing_low = _fval(features, "swing_low")
    if swing_low > EPSILON_TOLERANCE and swing_low < entry:
        stop = swing_low - atr * _adaptive_buffer(features, ATR_STOP_SWING_MULTIPLIER, regime_type)
        return min(stop, min_stop), "swing_low"

    ema_21 = _fval(features, "ema_21")
    if ema_21 > EPSILON_TOLERANCE and ema_21 < entry:
        stop = ema_21 - atr * _adaptive_buffer(features, ATR_STOP_SWING_MULTIPLIER, regime_type)
        return min(stop, min_stop), "ema_21_support"

    sr_support = _fval(features, "sr_nearest_support") or _fval(features, "nearest_support")
    if sr_support > EPSILON_TOLERANCE and sr_support < entry:
        stop = sr_support - atr * _adaptive_buffer(features, ATR_STOP_SR_MULTIPLIER, regime_type)
        return min(stop, min_stop), "sr_support"

    return entry - atr * _adaptive_buffer(features, ATR_STOP_FALLBACK_MULTIPLIER, regime_type), "atr"
```

Apply the same pattern to `_resolve_stop_short` (line 511) — mirror the long function, same constants, `+` instead of `-`.

- [ ] **Step 1.6: Update `frame_trade()` — remove `effective_atr`, add `regime_type`**

Change the `frame_trade` signature:
```python
def frame_trade(
    setup_type: str,
    direction: int,
    entry: float,
    features: dict[str, Any],
    atr: float,
    regime_type: str | None = None,
) -> TradeFrame:
```

Delete the `effective_atr` block (lines 876-883):
```python
# DELETE these lines:
# garch_vol_regime = features.get("garch_vol_regime")
# garch_regime_int = int(garch_vol_regime) if garch_vol_regime is not None else None
# if garch_regime_int is not None:
#     effective_atr = atr * GARCH_MULTIPLIERS.get(garch_regime_int, 1.0)
# else:
#     effective_atr = atr
```

Update the stop/target calls immediately after:
```python
if direction == 1:
    stop, stop_type = _resolve_stop_long(resolved_entry, atr, features, regime_type)
    candidates = _collect_targets_long(resolved_entry, stop, atr, features)
else:
    stop, stop_type = _resolve_stop_short(resolved_entry, atr, features, regime_type)
    candidates = _collect_targets_short(resolved_entry, stop, atr, features)

zone_low, zone_high, zone_source = _resolve_zone_bounds(
    setup_type, direction, resolved_entry, stop, features, atr
)
```

Update the `_classify_stop_basis` call (currently line 975) — replace `effective_atr` with the adaptive representative:
```python
stop_basis, stop_structure_type, structural_stop_distance_atr = _classify_stop_basis(
    stop_type, stop, resolved_entry,
    atr * _adaptive_buffer(features, 1.0, regime_type),
    None,  # garch_regime_int no longer needed — adaptive buffer subsumes it
    direction,
)
```

- [ ] **Step 1.7: Run all trade_framer tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_trade_framer.py -v
```
Expected: all PASS. Fix any failures before continuing.

- [ ] **Step 1.8: Commit**

```bash
git add src/intelligence/trading/trade_framer.py tests/unit/intelligence/test_trade_framer.py
git commit -m "feat(trade_framer): replace discrete GARCH_MULTIPLIERS with continuous _adaptive_buffer"
```

---

## Task 2: Unified Target Collection + Institutional Candidates

**Files:**
- Modify: `src/intelligence/trading/trade_framer.py`
- Modify: `tests/unit/intelligence/test_trade_framer.py`

- [ ] **Step 2.1: Write failing tests for institutional candidates**

Add to `tests/unit/intelligence/test_trade_framer.py` — import `_collect_target_candidates` will fail until implementation:

```python
from src.intelligence.trading.trade_framer import (
    _collect_target_candidates,  # add; remove _collect_targets_long, _collect_targets_short
    ...
)

ENTRY = 5000.0
ATR = 10.0

class TestCollectTargetCandidates:
    def test_weekly_pivot_r1_long(self):
        f = {"weekly_r1": 5020.0, "timeframe": "5m"}
        candidates = _collect_target_candidates(ENTRY, ENTRY - 20.0, 1, ATR, f)
        prices = [c.price for c in candidates]
        assert 5020.0 in prices

    def test_weekly_pivot_s1_short(self):
        f = {"weekly_s1": 4980.0, "timeframe": "5m"}
        candidates = _collect_target_candidates(ENTRY, ENTRY + 20.0, -1, ATR, f)
        prices = [c.price for c in candidates]
        assert 4980.0 in prices

    def test_weekly_pivot_wrong_side_excluded(self):
        # weekly_r1 above entry should not appear for shorts
        f = {"weekly_r1": 5020.0, "timeframe": "5m"}
        candidates = _collect_target_candidates(ENTRY, ENTRY + 20.0, -1, ATR, f)
        prices = [c.price for c in candidates]
        assert 5020.0 not in prices

    def test_fib_cluster_included_if_strength_meets_gate(self):
        f = {"nearest_fib_level": 5015.0, "fib_cluster_strength": 0.5, "timeframe": "5m"}
        candidates = _collect_target_candidates(ENTRY, ENTRY - 20.0, 1, ATR, f)
        prices = [c.price for c in candidates]
        assert 5015.0 in prices

    def test_fib_cluster_excluded_if_below_gate(self):
        f = {"nearest_fib_level": 5015.0, "fib_cluster_strength": 0.4, "timeframe": "5m"}
        candidates = _collect_target_candidates(ENTRY, ENTRY - 20.0, 1, ATR, f)
        prices = [c.price for c in candidates]
        assert 5015.0 not in prices

    def test_asian_high_long(self):
        f = {"asian_session_high": 5012.0, "timeframe": "5m"}
        candidates = _collect_target_candidates(ENTRY, ENTRY - 20.0, 1, ATR, f)
        prices = [c.price for c in candidates]
        assert 5012.0 in prices

    def test_asian_low_short(self):
        f = {"asian_session_low": 4988.0, "timeframe": "5m"}
        candidates = _collect_target_candidates(ENTRY, ENTRY + 20.0, -1, ATR, f)
        prices = [c.price for c in candidates]
        assert 4988.0 in prices

    def test_avwap_upper_long(self):
        f = {"avwap_upper_band": 5018.0, "timeframe": "5m"}
        candidates = _collect_target_candidates(ENTRY, ENTRY - 20.0, 1, ATR, f)
        prices = [c.price for c in candidates]
        assert 5018.0 in prices

    def test_avwap_lower_short(self):
        f = {"avwap_lower_band": 4982.0, "timeframe": "5m"}
        candidates = _collect_target_candidates(ENTRY, ENTRY + 20.0, -1, ATR, f)
        prices = [c.price for c in candidates]
        assert 4982.0 in prices

    def test_atr_range_filter_excludes_too_close(self):
        # weekly_r1 too close (< entry + atr * 0.5) should be excluded
        f = {"weekly_r1": ENTRY + ATR * 0.3, "timeframe": "5m"}
        candidates = _collect_target_candidates(ENTRY, ENTRY - 20.0, 1, ATR, f)
        prices = [c.price for c in candidates]
        assert ENTRY + ATR * 0.3 not in prices

    def test_existing_sr_resistance_still_collected(self):
        # Regression: existing levels must still work
        f = {"nearest_resistance": 5025.0, "timeframe": "5m"}
        candidates = _collect_target_candidates(ENTRY, ENTRY - 20.0, 1, ATR, f)
        prices = [c.price for c in candidates]
        assert 5025.0 in prices
```

- [ ] **Step 2.2: Run tests — verify they fail**

```bash
.venv/bin/pytest tests/unit/intelligence/test_trade_framer.py::TestCollectTargetCandidates -v
```
Expected: `ImportError` on `_collect_target_candidates`.

- [ ] **Step 2.3: Add `_collect_target_candidates` and delete the old long/short functions**

Replace `_collect_targets_long` (line 570) and `_collect_targets_short` (line 682) entirely with the unified function. Delete both old functions. Add this function in their place:

```python
def _collect_target_candidates(
    entry: float,
    stop: float,
    direction: int,
    atr: float,
    features: dict[str, Any],
    regime_type: str | None = None,
) -> list[TradeTarget]:
    """Collect candidate target levels for longs (direction=1) or shorts (direction=-1).

    All candidates pass through an ATR range filter. VP priority candidates bypass it.
    """
    risk = abs(entry - stop)
    if risk <= EPSILON_TOLERANCE:
        return []

    tf = features.get("timeframe", "")
    tf_max_mult = ATR_TARGET_MAX_MULTIPLIER_BY_TF.get(tf, ATR_TARGET_MAX_MULTIPLIER)

    if direction == 1:
        min_level = entry + atr * ATR_TARGET_MIN_MULTIPLIER
        max_level = entry + atr * tf_max_mult
    else:
        min_level = entry - atr * tf_max_mult
        max_level = entry - atr * ATR_TARGET_MIN_MULTIPLIER

    candidates: list[tuple[float, str, str]] = []

    # --- Existing structural levels ---

    if direction == 1:
        nearest_sr = _fval(features, "nearest_resistance") or _fval(features, "sr_nearest_resistance")
        if nearest_sr > EPSILON_TOLERANCE:
            candidates.append((nearest_sr, f"S/R {nearest_sr:.2f}", "sr"))

        bsl_level = _fval(features, "bsl_level")
        bsl_significance = _fval(features, "bsl_significance")
        if bsl_level > EPSILON_TOLERANCE and bsl_significance >= 0.5:
            candidates.append((bsl_level, f"BSL (sig={bsl_significance:.2f}) {bsl_level:.2f}", "bsl"))

        vwap_upper_1 = _fval(features, "vwap_upper_1")
        if vwap_upper_1 > EPSILON_TOLERANCE:
            candidates.append((vwap_upper_1, f"VWAP+1σ {vwap_upper_1:.2f}", "vwap_1sigma"))

        vwap_upper_2 = _fval(features, "vwap_upper_2")
        if vwap_upper_2 > EPSILON_TOLERANCE:
            candidates.append((vwap_upper_2, f"VWAP+2σ {vwap_upper_2:.2f}", "vwap_2sigma"))

        fvg_type = _fval(features, "fvg_type")
        fvg_top = _fval(features, "fvg_top")
        if fvg_type == 1.0 and fvg_top > EPSILON_TOLERANCE:
            candidates.append((fvg_top, f"FVG top {fvg_top:.2f}", "fvg"))

        ob_type = _fval(features, "ob_type")
        ob_top = _fval(features, "ob_top")
        if ob_type == 1.0 and ob_top > entry:
            candidates.append((ob_top, f"OB top {ob_top:.2f}", "ob"))

        kalman_upper = _fval(features, "kalman_upper")
        if kalman_upper > EPSILON_TOLERANCE:
            candidates.append((kalman_upper, f"Kalman upper {kalman_upper:.2f}", "kalman"))

        nearest_demand_high = _fval(features, "nearest_demand_high")
        if nearest_demand_high > entry:
            candidates.append((nearest_demand_high, f"Demand zone {nearest_demand_high:.2f}", "demand_zone"))

        prior_day_high = _fval(features, "prior_day_high")
        if prior_day_high > entry:
            candidates.append((prior_day_high, f"Prior Day H {prior_day_high:.2f}", "prior_day"))

        overnight_high = _fval(features, "overnight_high")
        if overnight_high > entry:
            candidates.append((overnight_high, f"Overnight H {overnight_high:.2f}", "overnight"))

    else:  # short
        nearest_sr = _fval(features, "nearest_support") or _fval(features, "sr_nearest_support")
        if nearest_sr > EPSILON_TOLERANCE:
            candidates.append((nearest_sr, f"S/R {nearest_sr:.2f}", "sr"))

        ssl_level = _fval(features, "ssl_level")
        ssl_significance = _fval(features, "ssl_significance")
        if ssl_level > EPSILON_TOLERANCE and ssl_significance >= 0.5:
            candidates.append((ssl_level, f"SSL (sig={ssl_significance:.2f}) {ssl_level:.2f}", "ssl"))

        vwap_lower_1 = _fval(features, "vwap_lower_1")
        if vwap_lower_1 > EPSILON_TOLERANCE:
            candidates.append((vwap_lower_1, f"VWAP-1σ {vwap_lower_1:.2f}", "vwap_1sigma"))

        vwap_lower_2 = _fval(features, "vwap_lower_2")
        if vwap_lower_2 > EPSILON_TOLERANCE:
            candidates.append((vwap_lower_2, f"VWAP-2σ {vwap_lower_2:.2f}", "vwap_2sigma"))

        fvg_type = _fval(features, "fvg_type")
        fvg_bottom = _fval(features, "fvg_bottom")
        if fvg_type == -1.0 and fvg_bottom > EPSILON_TOLERANCE:
            candidates.append((fvg_bottom, f"FVG bottom {fvg_bottom:.2f}", "fvg"))

        ob_type = _fval(features, "ob_type")
        ob_bottom = _fval(features, "ob_bottom")
        if ob_type == -1.0 and ob_bottom < entry and ob_bottom > EPSILON_TOLERANCE:
            candidates.append((ob_bottom, f"OB bottom {ob_bottom:.2f}", "ob"))

        kalman_lower = _fval(features, "kalman_lower")
        if kalman_lower > EPSILON_TOLERANCE:
            candidates.append((kalman_lower, f"Kalman lower {kalman_lower:.2f}", "kalman"))

        nearest_supply_low = _fval(features, "nearest_supply_low")
        if nearest_supply_low > EPSILON_TOLERANCE and nearest_supply_low < entry:
            candidates.append((nearest_supply_low, f"Supply zone {nearest_supply_low:.2f}", "supply_zone"))

        prior_day_low = _fval(features, "prior_day_low")
        if prior_day_low > EPSILON_TOLERANCE and prior_day_low < entry:
            candidates.append((prior_day_low, f"Prior Day L {prior_day_low:.2f}", "prior_day"))

        overnight_low = _fval(features, "overnight_low")
        if overnight_low > EPSILON_TOLERANCE and overnight_low < entry:
            candidates.append((overnight_low, f"Overnight L {overnight_low:.2f}", "overnight"))

    # --- Institutional levels (direction-symmetric logic) ---

    # Weekly pivots
    if direction == 1:
        for field in ("weekly_r1", "weekly_r2"):
            lvl = features.get(field)
            if lvl and lvl > entry:
                candidates.append((float(lvl), f"Weekly {field.upper()} {lvl:.2f}", "weekly_pivot"))
    else:
        for field in ("weekly_s1", "weekly_s2"):
            lvl = features.get(field)
            if lvl and lvl < entry:
                candidates.append((float(lvl), f"Weekly {field.upper()} {lvl:.2f}", "weekly_pivot"))

    # Fibonacci cluster (strength gate: lone levels are noise)
    fib_lvl = features.get("nearest_fib_level")
    fib_strength = float(features.get("fib_cluster_strength") or 0.0)
    if fib_lvl is not None and float(fib_lvl) > EPSILON_TOLERANCE and fib_strength >= 0.5:
        fib = float(fib_lvl)
        if direction == 1 and fib > entry:
            candidates.append((fib, f"Fib cluster {fib:.2f}", "fib"))
        elif direction == -1 and fib < entry:
            candidates.append((fib, f"Fib cluster {fib:.2f}", "fib"))

    # Asian session H/L
    if direction == 1:
        asian_h = features.get("asian_session_high")
        if asian_h and float(asian_h) > entry:
            candidates.append((float(asian_h), f"Asian H {float(asian_h):.2f}", "asian_session"))
    else:
        asian_l = features.get("asian_session_low")
        if asian_l and float(asian_l) < entry:
            candidates.append((float(asian_l), f"Asian L {float(asian_l):.2f}", "asian_session"))

    # AVWAP bands
    if direction == 1:
        avwap_upper = features.get("avwap_upper_band")
        if avwap_upper and float(avwap_upper) > entry:
            candidates.append((float(avwap_upper), f"AVWAP upper {float(avwap_upper):.2f}", "avwap"))
    else:
        avwap_lower = features.get("avwap_lower_band")
        if avwap_lower and float(avwap_lower) < entry:
            candidates.append((float(avwap_lower), f"AVWAP lower {float(avwap_lower):.2f}", "avwap"))

    # --- VP priority candidates (bypass ATR range filter) ---
    priority_candidates: list[tuple[float, str, str]] = []
    vp = _select_vp(features, tf)
    if vp is not None and _vp_regime_active(features):
        poc, vah, val = vp
        price_in_va = _fval(features, "price_in_value_area")
        if direction == 1:
            if price_in_va == 1.0:
                if vah > entry:
                    priority_candidates.append((vah, f"VP VAH {vah:.2f}", "vp_vah"))
            else:
                if poc > entry:
                    priority_candidates.append((poc, f"VP POC {poc:.2f}", "vp_poc"))
                if vah > entry:
                    priority_candidates.append((vah, f"VP VAH {vah:.2f}", "vp_vah"))
        else:
            if price_in_va == 1.0:
                if val < entry:
                    priority_candidates.append((val, f"VP VAL {val:.2f}", "vp_val"))
            else:
                if poc < entry:
                    priority_candidates.append((poc, f"VP POC {poc:.2f}", "vp_poc"))
                if val < entry:
                    priority_candidates.append((val, f"VP VAL {val:.2f}", "vp_val"))

    # ATR range filter on standard candidates
    if direction == 1:
        valid = [(p, l, t) for p, l, t in candidates if min_level < p < max_level]
        valid.sort(key=lambda x: x[0])
    else:
        valid = [(p, l, t) for p, l, t in candidates if min_level < p < max_level]
        valid.sort(key=lambda x: x[0], reverse=True)

    all_candidates = priority_candidates + valid
    return [
        TradeTarget(price=price, label=label, level_type=ltype, rr=round(abs(price - entry) / risk, 2))
        for price, label, ltype in all_candidates
    ]
```

- [ ] **Step 2.4: Update `frame_trade()` to call the unified function**

Replace the long/short conditional for target collection in `frame_trade()`:

```python
if direction == 1:
    stop, stop_type = _resolve_stop_long(resolved_entry, atr, features, regime_type)
else:
    stop, stop_type = _resolve_stop_short(resolved_entry, atr, features, regime_type)

candidates = _collect_target_candidates(
    resolved_entry, stop, direction, atr, features, regime_type
)
```

- [ ] **Step 2.5: Update test imports**

In `tests/unit/intelligence/test_trade_framer.py`, replace `_collect_targets_long, _collect_targets_short` in the import block with `_collect_target_candidates`. Update any existing tests that called the old functions to use the unified signature `(entry, stop, direction, atr, features)`.

Existing tests that called `_collect_targets_long(entry, stop, atr, features)` become:
```python
_collect_target_candidates(entry, stop, 1, atr, features)
```

Existing tests that called `_collect_targets_short(entry, stop, atr, features)` become:
```python
_collect_target_candidates(entry, stop, -1, atr, features)
```

- [ ] **Step 2.6: Run all trade_framer tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_trade_framer.py -v
```
Expected: all PASS.

- [ ] **Step 2.7: Commit**

```bash
git add src/intelligence/trading/trade_framer.py tests/unit/intelligence/test_trade_framer.py
git commit -m "feat(trade_framer): unify target collection with institutional levels (weekly pivots, Fib, Asian H/L, AVWAP)"
```

---

## Task 3: Chandelier Floor — be_floor in lifecycle_tracker

**Files:**
- Modify: `src/intelligence/trading/lifecycle_tracker.py`
- Modify: `tests/unit/intelligence/test_lifecycle_tracker.py`

- [ ] **Step 3.1: Write failing tests for the chandelier floor**

Add to `tests/unit/intelligence/test_lifecycle_tracker.py`:

```python
class TestChandelierFloor:
    """be_floor: T1 advances to entry, T2 advances to target_1. Chandelier clamped."""

    def _signal(self, entry=5000.0, stop=4980.0, targets=None) -> dict:
        return {
            "signal_id": "test-floor-1",
            "status": "active",
            "direction": 1,
            "entry_price": entry,
            "stop_loss": stop,
            "targets": targets or [5020.0, 5040.0, 5060.0],
            "expires_at": None,
            "point_value": 50.0,
            "activated_at": "2026-01-01T10:00:00Z",
        }

    def _chandelier(self, trailing_stop=None, be_floor=None) -> dict:
        return {
            "trailing_stop": trailing_stop,
            "highest_high": 5010.0,
            "lowest_low": 4990.0,
            "vol": 5.0,
            "be_floor": be_floor,
        }

    def test_t1_hit_sets_be_floor_to_entry(self):
        sig = self._signal()
        state = self._chandelier(trailing_stop=4990.0)  # below price — won't trigger
        # high reaches T1 (5020.0)
        result = evaluate_signal(sig, high=5022.0, low=5001.0, close=5018.0,
                                 chandelier_state=state)
        assert result is None  # T1 does not exit
        assert state["be_floor"] == 5000.0  # advanced to entry

    def test_t1_hit_does_not_set_floor_twice(self):
        sig = self._signal()
        state = self._chandelier(trailing_stop=4990.0, be_floor=5000.0)  # already set
        result = evaluate_signal(sig, high=5025.0, low=5001.0, close=5020.0,
                                 chandelier_state=state)
        assert state["be_floor"] == 5000.0  # unchanged

    def test_t2_hit_advances_floor_to_t1(self):
        sig = self._signal()
        state = self._chandelier(trailing_stop=4990.0, be_floor=5000.0)
        # high reaches T2 (5040.0)
        result = evaluate_signal(sig, high=5042.0, low=5005.0, close=5038.0,
                                 chandelier_state=state)
        assert state["be_floor"] == 5020.0  # advanced to target_1

    def test_chandelier_clamped_at_entry_after_t1(self):
        sig = self._signal()
        # trailing_stop is below entry (4995) but be_floor = entry (5000)
        # → effective stop = 5000; low=4998 breaches it
        state = self._chandelier(trailing_stop=4995.0, be_floor=5000.0)
        result = evaluate_signal(sig, high=5010.0, low=4998.0, close=5002.0,
                                 chandelier_state=state)
        assert result is not None
        assert result.exit_reason == "chandelier_stop"
        assert result.exit_price == pytest.approx(5000.0)
        assert result.pnl_r == pytest.approx(0.0, abs=1e-4)

    def test_chandelier_above_floor_not_clamped(self):
        sig = self._signal()
        # trailing_stop=5010 > be_floor=5000 → clamp has no effect; stop is 5010
        # low=5008 breaches 5010
        state = self._chandelier(trailing_stop=5010.0, be_floor=5000.0)
        result = evaluate_signal(sig, high=5020.0, low=5008.0, close=5012.0,
                                 chandelier_state=state)
        assert result is not None
        assert result.exit_price == pytest.approx(5010.0)
        assert result.pnl_r > 0  # exited above entry

    def test_no_floor_chandelier_unchanged(self):
        sig = self._signal()
        # be_floor=None → clamp not applied; trailing_stop=4985 below entry
        # low=4984 breaches it
        state = self._chandelier(trailing_stop=4985.0, be_floor=None)
        result = evaluate_signal(sig, high=5010.0, low=4984.0, close=4990.0,
                                 chandelier_state=state)
        assert result is not None
        assert result.exit_price == pytest.approx(4985.0)

    def test_short_t1_sets_floor_to_entry(self):
        sig = self._signal(entry=5000.0, stop=5020.0, targets=[4980.0, 4960.0, 4940.0])
        sig["direction"] = -1
        state = self._chandelier(trailing_stop=5015.0, be_floor=None)
        # low reaches T1 (4980.0)
        result = evaluate_signal(sig, high=4999.0, low=4978.0, close=4982.0,
                                 chandelier_state=state)
        assert result is None
        assert state["be_floor"] == pytest.approx(5000.0)

    def test_short_chandelier_clamped_at_entry_after_t1(self):
        sig = self._signal(entry=5000.0, stop=5020.0, targets=[4980.0, 4960.0, 4940.0])
        sig["direction"] = -1
        # trailing_stop=5005 > entry=5000 but be_floor=5000 → effective stop=5000
        # high=5001 breaches it
        state = self._chandelier(trailing_stop=5005.0, be_floor=5000.0)
        result = evaluate_signal(sig, high=5001.0, low=4990.0, close=4995.0,
                                 chandelier_state=state)
        assert result is not None
        assert result.exit_reason == "chandelier_stop"
        assert result.exit_price == pytest.approx(5000.0)
```

- [ ] **Step 3.2: Run tests — verify they fail**

```bash
.venv/bin/pytest tests/unit/intelligence/test_lifecycle_tracker.py::TestChandelierFloor -v
```
Expected: failures (T1 currently exits; no be_floor logic exists).

- [ ] **Step 3.3: Add be_floor advancement before `_check_active_exit` in `evaluate_signal()`**

In `evaluate_signal()`, add this block immediately **before** the `_check_active_exit` call (currently around line 285):

```python
# Advance chandelier be_floor on T1/T2 detection (T1 does not exit — floor advances instead)
if status == SignalStatus.ACTIVE and chandelier_state is not None:
    target_1 = targets[0] if targets else None
    target_2 = targets[1] if len(targets) > 1 else None
    t1_hit = target_1 is not None and (
        (direction == 1 and high >= target_1) or (direction == -1 and low <= target_1)
    )
    t2_hit = target_2 is not None and (
        (direction == 1 and high >= target_2) or (direction == -1 and low <= target_2)
    )
    if t1_hit and chandelier_state.get("be_floor") is None:
        chandelier_state["be_floor"] = entry
    if t2_hit and chandelier_state.get("be_floor") is not None:
        chandelier_state["be_floor"] = target_1
```

- [ ] **Step 3.4: Modify `_check_active_exit` so T1 does not exit**

In `_check_active_exit` (line 491-508), change the target loop:

```python
# Target checks (highest target first for maximum credit)
for i in range(len(targets) - 1, -1, -1):
    target = targets[i]
    hit = (direction == 1 and high >= target) or (direction == -1 and low <= target)
    if hit:
        if i == 0:
            # T1 advances be_floor (handled in evaluate_signal before this call); does not exit
            break
        return _make_exit(
            sid,
            f"target_{i + 1}_hit",
            f"target_{i + 1}",
            target,
            entry,
            direction,
            risk,
            point_value,
            current_mae,
            current_mfe,
            target_index=i,
        )
```

- [ ] **Step 3.5: Apply be_floor clamp in the chandelier check**

In `evaluate_signal()`, replace the chandelier check block (lines 297-321) with:

```python
if status == SignalStatus.ACTIVE and chandelier_state is not None:
    trailing_stop = chandelier_state.get("trailing_stop")
    be_floor = chandelier_state.get("be_floor")
    if trailing_stop is not None:
        # Clamp: chandelier can never trail past the breakeven floor
        if be_floor is not None:
            trailing_stop = max(trailing_stop, be_floor) if direction == 1 else min(trailing_stop, be_floor)
        chandelier_hit = (direction == 1 and low <= trailing_stop) or (
            direction == -1 and high >= trailing_stop
        )
        if chandelier_hit:
            pnl_ticks = (trailing_stop - entry) * direction
            pnl_r = round(pnl_ticks / risk, 4) if risk >= _MIN_RISK else 0.0
            pnl_dollars = round(pnl_ticks * point_value, 2)
            final_mae = min(current_mae, pnl_r)
            final_mfe = max(current_mfe, pnl_r)
            if be_floor is not None:
                import structlog as _sl
                _sl.get_logger().info(
                    "chandelier_floor_exit",
                    signal_id=sid,
                    be_floor=be_floor,
                    trailing_stop=trailing_stop,
                    pnl_r=pnl_r,
                )
            _record_outcome(signal, SignalOutcome.STOPPED_IN_TRADE)
            return Transition(
                signal_id=sid,
                new_status=SignalStatus.EXPIRED,
                exit_reason="chandelier_stop",
                exit_price=trailing_stop,
                pnl_ticks=round(pnl_ticks, 4),
                pnl_r=pnl_r,
                pnl_dollars=pnl_dollars,
                mae=round(final_mae, 4),
                mfe=round(final_mfe, 4),
                outcome=SignalOutcome.STOPPED_IN_TRADE,
            )
```

Note: move the `import structlog` to the top of the file with the other imports (don't leave it inline). Check if structlog is already imported; if so, just use the existing logger reference.

- [ ] **Step 3.6: Fix structlog import**

Check the top of `lifecycle_tracker.py` for an existing structlog import:
```bash
grep -n "import structlog\|get_logger" src/intelligence/trading/lifecycle_tracker.py | head -5
```

If not present, add to the imports at the top of the file:
```python
import structlog

_logger = structlog.get_logger(__name__)
```

Then replace the inline `_sl.get_logger().info(...)` call with:
```python
_logger.info(
    "chandelier_floor_exit",
    signal_id=sid,
    be_floor=be_floor,
    trailing_stop=trailing_stop,
    pnl_r=pnl_r,
)
```

- [ ] **Step 3.7: Run all lifecycle tracker tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_lifecycle_tracker.py -v
```
Expected: all PASS including new `TestChandelierFloor` tests.

- [ ] **Step 3.8: Run full unit test suite**

```bash
.venv/bin/pytest tests/unit/ -q
```
Expected: all green.

- [ ] **Step 3.9: Run verification grep checks from the spec**

```bash
grep -rn "GARCH_MULTIPLIERS\|effective_atr" src/intelligence/trading/trade_framer.py
# → 0 results

grep -n "def _collect_targets_long\|def _collect_targets_short" src/intelligence/trading/trade_framer.py
# → 0 results

grep -n "def _collect_target" src/intelligence/trading/trade_framer.py
# → _collect_target_candidates only

grep -n "weekly_r1\|nearest_fib_level\|asian_session_high\|avwap_upper_band" src/intelligence/trading/trade_framer.py
# → hits in _collect_target_candidates

grep -n "be_floor" src/intelligence/trading/lifecycle_tracker.py
# → multiple hits

grep -n "target_1_hit" src/intelligence/trading/lifecycle_tracker.py
# → 0 results
```

- [ ] **Step 3.10: Commit**

```bash
git add src/intelligence/trading/lifecycle_tracker.py tests/unit/intelligence/test_lifecycle_tracker.py
git commit -m "feat(lifecycle_tracker): add chandelier be_floor — T1 advances floor to entry, T2 to target_1"
```

---

## Done-Coding SOP

After all tasks are committed:

```bash
# 1. code-simplifier agent (invoke automatically)
# 2. /review
# 3. pytest tests/unit/ -q   # must be green
# 4. git checkout main && git merge --ff-only <branch>
# 5. git branch -d <branch>
# 6. git worktree prune
# 7. git push origin main
```
