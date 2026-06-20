---
phase: 124
plan: 06
status: complete
---

# 124-06 Summary: AnchoredVWAPReversion Structural Rewrite

## What was done

Rewrote `trad_AnchoredVWAPReversion` to fire on **departure + return** structural event, not displacement threshold alone.

### Implementation

**`src/intelligence/trading/anchored_vwap_reversion.py`**
- Added `VWAPReversionState` dataclass with `sigma_buffer: deque(maxlen=50)`, `departure_sigma: float | None`, `departure_bars: int`
- `_get_state()` factory method per `(symbol, tf)` key
- Gate ordering (6 stages):
  1. **Departure FIRST**: `abs(sigma) >= sigma_min` (default 1.5) - clears `departure_sigma` if not met
  2. **Return velocity SECOND**: velocity toward VWAP (`velocity < 0` for short, `velocity > 0` for long)
  3. **Reclaim confirmation THIRD**: `current_close < vwap` (short) or `current_close > vwap` (long) - close must cross, wick-only rejected
  4. **HMM regime FOURTH**: `hmm_regime == 0` (ranging only)
  5. **Hurst FIFTH**: `hurst_exponent < hurst_max` (mean-reverting regime)
  6. **`deduplicate_event`** with `(departure_sigma, reclaim_level)` - prevents re-fire on same displacement episode
- Removed `onset_guard(condition_active)` - superseded by structural departure+return pattern

### Tests

**`tests/unit/intelligence/trading/test_anchored_vwap_reversion.py`** - 11 tests, all passing:
- `test_fires_short_when_above_sigma_threshold`: departure + velocity + reclaim below VWAP fires direction=-1
- `test_fires_long_when_below_sigma_threshold`: departure + velocity + reclaim above VWAP fires direction=1
- `test_no_signal_when_sigma_too_small`: abs(sigma) < 1.5 - no signal
- `test_no_signal_when_trending_regime`: hmm_regime=1 - suppressed
- `test_no_signal_when_hurst_too_high`: hurst=0.60 - no signal
- `test_confidence_is_in_range`: confidence in (0.0, 1.0]
- `test_targets_include_session_vwap`: T1 = session_vwap
- `test_regime_type_is_mean_reversion`: class attribute check
- `test_no_signal_when_required_features_missing`: missing sigma - no signal
- `test_plugin_module_instance`: module-level plugin name
- `test_tf_guard_returns_no_signal_on_1h`: TF guard (1m only)

## Verification

```
pytest tests/unit/intelligence/trading/test_anchored_vwap_reversion.py -q
# 11 passed
```

## Must-haves achieved

- [x] Fires only on departure + return structure (`abs(sigma) >= sigma_min` AND velocity toward VWAP)
- [x] Rejection/reclaim candle confirmation required (close crosses VWAP, not wick-only)
- [x] Continuous displacement alone produces no signal without return velocity
- [x] `deduplicate_event` with `(departure_sigma, reclaim_level)` prevents re-fire
