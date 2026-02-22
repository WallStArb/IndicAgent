# Design: Phase 0 — Wire GARCH/Kalman Outputs into I7 Plugins

**Date:** 2026-02-22
**Status:** Approved — ready for implementation
**Parent:** `docs/plans/2026-02-22-unified-intelligence-data-bus-design.md`

---

## Context

GARCH and Kalman plugins run on every bar and publish 11 fields to the `intelligence:` stream:

- **GARCH:** `garch_sigma`, `garch_vol_ratio`, `garch_vol_regime` (0/1/2/3), `garch_shock`
- **Kalman:** `kalman_trend`, `kalman_slope`, `kalman_price_position`, `kalman_uncertainty`, `kalman_upper`, `kalman_lower`, `kalman_gain`

These fields are already in `frames["features"]` when I7 plugins run (via `signal_generator_service.py` → `parse_intelligence_message`). No infrastructure changes needed — Phase 0 is purely plugin logic.

---

## Scope

3 I7 plugin files only. No service changes, no schema changes, no new files.

---

## Changes

### 1. `src/intelligence/trading/mean_reversion.py`

**Gate:** After the existing `trend_regime` gate, add a Kalman displacement check.

```python
# After: if abs(trend_regime) >= self.regime_threshold: return self._no_signal()

kalman_pos = features.get("kalman_price_position")
if kalman_pos is not None and abs(float(kalman_pos)) < 1.0:
    return self._no_signal()
```

**Rationale:** `kalman_price_position = (close - kalman_trend) / sqrt(P_est)` is a standardized deviation from Kalman's fair-value estimate. Below 1.0σ, price is effectively at fair value — no meaningful extension to revert from. Gate is `None`-safe (skipped when Kalman data absent).

---

### 2. `src/intelligence/trading/vwap_deviation.py`

**Dynamic sigma threshold:** Replace hardcoded 2σ gate with GARCH-adaptive threshold.

```python
# Module-level constant (above class definition)
_VOL_THRESHOLDS: dict[int, float] = {0: 2.0, 1: 2.0, 2: 2.5, 3: 3.0}
```

Replace current gate + direction block:
```python
# OLD:
if vwap_lower_2 <= price <= vwap_upper_2:
    return self._no_signal()
direction = 1 if price < vwap_lower_2 else -1

# NEW:
vol_regime = int(features.get("garch_vol_regime", 1))
effective_threshold = _VOL_THRESHOLDS.get(vol_regime, 2.0)
sigma_deviation = abs(price - vwap) / vwap_std
if sigma_deviation < effective_threshold:
    return self._no_signal()
direction = 1 if price < vwap else -1
```

**Rationale:** In high-vol regimes VWAP can be far from price as noise, not signal. Requiring wider deviation in high-vol conditions reduces false fades. `garch_vol_regime` defaults to `1` (normal) when absent → threshold stays 2.0 → all existing behavior preserved.

---

### 3. `src/intelligence/trading/squeeze_expansion.py`

**Gate:** After the volume expansion gate, block in extreme vol.

```python
# After: if current_volume <= volume_sma_20 * self.volume_expansion_threshold: return ...

vol_regime = int(features.get("garch_vol_regime", 1))
if vol_regime == 3:
    return self._no_signal()
```

**Rationale:** A squeeze breakout during extreme vol (top 5th percentile of GARCH sigma history) is likely a gap/whipsaw rather than a clean expansion. Regimes 0/1/2 all pass through. Defaults to `1` when GARCH absent → backward compatible.

---

## Tests

9 new test cases added to existing test files. No new files.

### `tests/unit/intelligence/test_trading_setups.py` — MeanReversion section

| Test | Input | Expected |
|------|-------|---------|
| `test_no_signal_when_near_kalman_fair_value` | kalman_price_position=0.5 (below 1σ) | no signal |
| `test_signal_fires_when_kalman_price_displaced` | kalman_price_position=1.5 (above 1σ) | signal fires |
| `test_missing_kalman_data_gate_skipped` | no kalman_price_position key | signal fires (backward compat) |

### `tests/unit/intelligence/test_vwap_deviation.py` — VWAPDeviation class

| Test | Input | Expected |
|------|-------|---------|
| `test_no_signal_in_high_vol_at_2sigma` | garch_vol_regime=2, price at 2.0σ | no signal (needs 2.5σ) |
| `test_signal_fires_at_2p6sigma_in_high_vol` | garch_vol_regime=2, price at 2.6σ | signal fires |
| `test_extreme_vol_requires_3sigma` | garch_vol_regime=3, price at 2.9σ | no signal (needs 3.0σ) |

### `tests/unit/intelligence/test_trading_setups.py` — SqueezeExpansion section

| Test | Input | Expected |
|------|-------|---------|
| `test_no_signal_in_extreme_garch_vol` | garch_vol_regime=3 | no signal |
| `test_signal_fires_in_high_vol_not_extreme` | garch_vol_regime=2 | signal fires |
| `test_missing_garch_data_squeeze_passes` | no garch_vol_regime key | signal fires (backward compat) |

---

## Backward Compatibility

All 3 gates are `None`/default-safe:
- Kalman gate: skipped entirely when `kalman_price_position` key is absent
- GARCH vol regime: defaults to `1` (normal) → effective_threshold=2.0 and vol_regime block doesn't trigger

All existing tests (which don't include GARCH/Kalman keys) continue to pass.

---

## Files Modified

| File | Change |
|------|--------|
| `src/intelligence/trading/mean_reversion.py` | +4 lines (Kalman gate) |
| `src/intelligence/trading/vwap_deviation.py` | +5 lines net (replace 2-line gate, add module constant, dynamic threshold) |
| `src/intelligence/trading/squeeze_expansion.py` | +3 lines (GARCH extreme vol block) |
| `tests/unit/intelligence/test_trading_setups.py` | +~50 lines (6 new test cases) |
| `tests/unit/intelligence/test_vwap_deviation.py` | +~30 lines (3 new test cases) |
