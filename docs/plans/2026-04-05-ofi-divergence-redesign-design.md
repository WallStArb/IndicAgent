# OFI Divergence Redesign — Design Doc

**Date:** 2026-04-05
**Status:** Approved
**Milestone:** v2.2

## Problem

The existing `ofi_divergence` I1 field and `OFIDivergencePlugin` I7 signal are near-useless:

- `ofi_divergence` is computed as `float(ofi_dir - price_dir)` where both inputs are ternary `{-1, 0, 1}`. Output is discrete `{-2, -1, 0, 1, 2}`.
- The I7 gate requires `abs(ofi_divergence) >= 1.5`, which — given the discrete scale — is effectively `abs == 2` only. This fires on ~0.4% of bars.
- All magnitude information in the raw OFI is discarded before the signal even evaluates it.
- ORB15/ORB30 also never fired due to a separate bug (`plugin_input` missing `__symbol__`/`__timeframe__` keys — already fixed).

## Hypothesis

**H1 (price-discovery):** Informed order flow leads price. When OFI is aggressively directional but price has not followed, price will close the gap in the direction of OFI within the signal TTL window.

This is a price-discovery signal, not mean-reversion. We do not pre-commit to regime assumptions — let observed outcomes decide.

## Design

### Layer 1: I1 — `ofi.py`

Replace the discrete divergence with a continuous factor:

```python
price_return = close[-1] - close[-2]
price_return_z = (price_return - mean(price_return_history)) / (std(price_return_history) + ε)

ofi_divergence = ofi_spike_z - price_return_z
```

- `ofi_spike_z` is already computed (z-score of raw OFI vs 100-bar history).
- `price_return_z` is computed from a new **100-bar** rolling price return history stored in plugin `_state` — same window as OFI history so both z-scores share the same distributional basis before subtraction.
- Result: continuous z-score units. `+2.5` = OFI is 2.5σ more bullish than price. Scale: roughly `{-6…+6}` in practice.
- Same output key `ofi_divergence` — no schema change needed (`I1Indicators` has `extra='allow'`).

**State keying:** all `_state` entries in `OFIPlugin` must be keyed by `(symbol, tf)`. Currently the state is a flat dict shared across all symbols — adding price return history to the same flat state would corrupt divergence calculations in multi-symbol deployments (ES and MNQ polluting each other's history). Derive `(symbol, tf)` from the df's index metadata or the symbol injected via frames. This is a pre-existing bug being fixed as part of this change.

### Layer 2: I7 — `ofi_divergence.py`

Full rewrite of `OFIDivergencePlugin`.

**Gate (all must pass):**
```
abs(ofi_divergence) >= 1.5              # 1.5σ minimum — recalibrate from data
sign(ofi_divergence) stable >= 2 bars  # persistence via state_utils
```

The persistence filter is critical: a single-bar divergence is noise. Two consecutive bars with consistent sign is a pattern. State is keyed on `(symbol, tf)` using `frames.get("__symbol__")` / `frames.get("__timeframe__")`.

**State per `(symbol, tf)`:** `{div_sign, count, peak_abs}` — `peak_abs` is the running max of `abs(ofi_divergence)` across the persistence window. Resets when sign flips.

**Direction:** `sign(ofi_divergence)` — H1, price follows order flow.

**Confidence:**
```
mag = peak_abs_ofi_div   # peak across persistence window, not just current bar
base = 0.42
+ 0.25 * tanh(mag / 3.0)                              # magnitude, principled soft cap
+ 0.08 if sign(ofi_ewma_5) == sign(ofi_divergence)    # fast EWMA agrees → boost
- 0.04 if sign(ofi_ewma_5) != sign(ofi_divergence)    # fast EWMA disagrees → reduce
+ 0.06 if sign(ofi_ewma_5) == sign(ofi_ewma_20)       # slow EWMA also confirms
+ 0.06 if rel_volume >= 1.5                            # volume validates OFI spike
+ 0.06 if hmm_regime == 0 else -0.06 if hmm_regime in (1, 2) else 0  # soft hint
→ compose_confidence(result)                           # clamp [0.10, 0.95]
```

Coefficients rationale:
- `tanh(mag / 3.0)`: at 1.5σ → ~0.46; at 3σ → ~0.76; at 6σ → ~0.96. Monotonic, bounded, no arbitrary cap.
- EWMA fast alignment `+0.08 / -0.04`: not a hard gate — a strong signal with a slightly negative ewma_5 still fires but at lower conviction. Asymmetric (boost > penalty) because the divergence magnitude already captures the core edge.
- EWMA slow alignment `+0.06`: sustained OFI pressure (slow EWMA agrees) is meaningfully stronger.
- Volume `+0.06`: validates the spike is real, not thin-book noise.
- Regime `±0.06`: soft hint only. `regime_type = "any"` means aggregator does not suppress in any regime.

**`regime_type = "any"`** — we don't pre-commit to mean-reversion or trend. The aggregator regime gate does not suppress this signal. The `±0.06` regime hint inside the confidence value is the only regime influence.

**Supporting factors logged:**
`ofi_divergence`, `ofi_spike_z`, `peak_abs_ofi_div`, `bars_persistent`, `ofi_ewma_5`, `ofi_ewma_20`, `hmm_regime`, `rel_volume`

**`_shadow` metadata:** `capture_signal_features()` as usual — 15 fields including I6 CTF scores, for v2.3 ML layer.

### Downstream consumers — `dual_divergence.py`, `cvd_divergence.py`

No changes. Both consume `abs(ofi_divergence) >= 1.0`. In the new continuous z-score scale, `1.0` is a legitimate 1σ threshold — more meaningful than before. Both are `IS_SHADOW=True`; behavioral changes go into shadow data automatically. Revisit thresholds after sufficient observations.

## Files Changed

| File | Change |
|------|--------|
| `src/intelligence/features/i1_indicators/ofi.py` | Add price return history to `_state`; compute `price_return_z`; redefine `ofi_divergence` as continuous factor |
| `src/intelligence/trading/ofi_divergence.py` | Full rewrite: new gate, persistence via `state_utils`, peak magnitude tracking, tanh confidence, `regime_type = "any"` |
| `tests/unit/intelligence/test_ofi_divergence.py` | Update thresholds; add persistence, EWMA alignment, and peak magnitude test cases |

## What Does Not Change

- No schema changes — `I1Indicators` `extra='allow'` passes the continuous value through unchanged
- No pipeline changes — `__symbol__`/`__timeframe__` injection already fixed
- `dual_divergence.py` and `cvd_divergence.py` — no threshold changes at this time
- All other I7 plugins — unaffected

## Calibration Plan

Thresholds (`1.5σ` gate, persistence `>= 2`) are initial values. Recalibrate based on observed signal frequency and outcome data. Target: ~5-8% of 1m bars fire, dropping to lower frequency on higher timeframes via the persistence filter.
