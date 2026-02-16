# BOCPD Change Point Detection — I6 Plugin Design

**Date:** 2026-02-14
**Status:** Approved
**Scope:** 1 plugin in `src/intelligence/smart_money/`

## Summary

Add a Bayesian Online Change Point Detection (BOCPD) plugin that detects the exact moment market regime changes, with a probability score. Uses univariate BOCPD on log returns as the core detector, with I1 feature confirmation (ATR, RSI, volume, SMA) to boost/dampen the signal.

## Architecture Decisions

- **Directory:** `src/intelligence/smart_money/` (structural analysis alongside BOS/CHoCH, OB, FVG, sweeps)
- **Protocol:** `PatternPlugin`, registered via `registry.register_pattern()`
- **Incremental:** `supports_incremental = True` — forward pass updates run length distribution in O(R) per bar
- **Core algorithm:** Adams & MacKay 2007, Student-t predictive distribution (conjugate prior for Gaussian with unknown mean/variance)
- **Feature confirmation:** Reads `frames["features"]` for ATR, RSI, volume, SMA when available; degrades gracefully without them
- **capability_tags:** `{"smart_money"}`
- **No external dependencies:** Pure numpy implementation (~80 lines core)

## Algorithm

### BOCPD Core (on log returns)

1. Each bar: compute `x = log(close / prev_close)`
2. For each possible run length r, compute predictive probability `P(x | r)` using Student-t posterior:
   - Sufficient statistics per run length: `mu` (mean), `kappa` (precision scale), `alpha` (shape), `beta` (rate)
   - Prior: `mu0=0, kappa0=1, alpha0=0.1, beta0=0.01`
   - Predictive: Student-t with `df=2*alpha`, `loc=mu`, `scale=sqrt(beta*(kappa+1)/(alpha*kappa))`
3. Update run length distribution:
   - Growth: `P(r+1) = P(x|r) * P(r) * (1 - H)` where H = hazard rate
   - Change point: `P(r=0) = sum(P(x|r) * P(r) * H)` for all r
4. Normalize to posterior over run lengths
5. Change point probability = `P(r=0)`

### Hazard Function

Constant hazard `H = 1/lambda` where lambda = expected regime duration.
Default: `lambda=100` (regimes last ~100 bars on average = ~1.5 hours of 1m bars).

### Run Length Truncation

Cap maximum run length at 200 to bound memory and computation. Probability mass beyond 200 is folded into the last bin.

### Feature Confirmation

When `frames["features"]` is available, compute a confirmation score from 4 signals:

```
confirmation = 0.0
if ATR jumped > 1 percentile quartile in last 5 bars: +0.25
if RSI crossed 50 midline in last 3 bars:             +0.25
if volume > 2x rolling average in last 3 bars:        +0.25
if price crossed SMA-20 in last 3 bars:               +0.25
```

Adjusted probability: `adjusted = raw * (0.5 + 0.5 * confirmation)`

This dampens raw probability by 50% with zero confirmation, keeps full strength with all 4 confirming. Without `frames["features"]`, confirmation defaults to 0.5 (no damping, no boost).

## Outputs

```python
outputs = frozenset({
    "cp_probability",      # Adjusted change point probability (0-1)
    "cp_raw_probability",  # Raw BOCPD probability before confirmation
    "cp_run_length",       # Most likely current run length (bars since last change)
    "cp_confirmation",     # Feature confirmation score (0-1)
    "cp_detected",         # 1.0 if adjusted probability > threshold (default 0.5)
})
```

**min_lookback:** 30

## Incremental State

```python
_state = {
    "run_length_probs": np.ndarray,  # Probability distribution over run lengths
    "mu": np.ndarray,                # Per-run-length mean sufficient statistic
    "kappa": np.ndarray,             # Per-run-length precision scale
    "alpha": np.ndarray,             # Per-run-length shape parameter
    "beta": np.ndarray,              # Per-run-length rate parameter
    "prev_close": float,             # Previous close for log return calculation
}
```

`compute_next()` updates these in-place, producing O(R) per-bar computation where R ≤ 200.

## Data Flow

```
OHLCV (log returns) ──> BOCPD core ──> raw_cp_prob
                                            │
frames["features"]  ──> confirmation ──> adjusted_cp_prob
(ATR, RSI, volume, SMA)    scoring           │
                                        cp_detected (0/1)
```

## Registration

In `src/intelligence/register_plugins.py`:
```python
from .smart_money.bocpd_changepoint import plugin as bocpd_plugin

# Inside register_all_plugins():
    registry.register_pattern(bocpd_plugin)
```

**New totals:** 16 indicators + 15 patterns = **31 total plugins**

## Testing Strategy

Test file: `tests/unit/intelligence/test_smart_money_plugins.py` (append)

1. **Regime change detection** — flat returns then volatile returns, verify cp_probability spikes
2. **No change (steady)** — constant returns, verify cp_probability stays low
3. **Feature confirmation boost** — verify confirmed > unconfirmed probability
4. **Incremental parity** — compute_next matches compute_full on same data
5. **Empty/insufficient input** — returns `{}`
6. **Graceful without features** — works with just OHLCV, no frames["features"]

Estimated: ~6 tests.
