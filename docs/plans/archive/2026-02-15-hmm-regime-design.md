# HMM Market Regime Detection — I6 Plugin Design

**Date:** 2026-02-15
**Status:** Approved
**Scope:** 1 plugin in `src/intelligence/smart_money/`

## Summary

Add a Hidden Markov Model (HMM) plugin that classifies market regime with probabilistic confidence. Uses multivariate Gaussian emissions on 5 features (2 from OHLCV + 3 from I1) with 3 hidden states. Offline-trained default parameters with optional JSON override. Pairs with BOCPD for complete regime awareness (what + when).

## Architecture Decisions

- **Directory:** `src/intelligence/smart_money/` (alongside BOCPD and other structural analysis)
- **Protocol:** `PatternPlugin`, registered via `registry.register_pattern()`
- **Incremental:** `supports_incremental = True` — forward algorithm updates alpha in O(K²·D) per bar
- **Core algorithm:** Forward algorithm with multivariate Gaussian diagonal-covariance emissions
- **Training:** Offline EM on historical data. Hardcoded sensible defaults ship with the plugin. Optional JSON override at `config/hmm_parameters.json`.
- **Feature inputs:** 5D observation vector (2 self-contained from OHLCV + 3 from `frames["features"]`). Degrades gracefully to 2D when I1 features unavailable.
- **capability_tags:** `{"smart_money"}`
- **No external dependencies:** Pure numpy implementation

## Hidden States (K=3)

| State | Label | Characteristics |
|-------|-------|----------------|
| 0 | Ranging | Near-zero mean return, low volatility, RSI ~50, low ADX, flat MACD |
| 1 | Trending Up | Positive mean return, moderate volatility, RSI elevated, ADX rising, positive MACD |
| 2 | Trending Down | Negative mean return, higher volatility, RSI depressed, ADX rising, negative MACD |

## Emission Features (D=5)

| Dim | Feature | Source | Computation |
|-----|---------|--------|-------------|
| 0 | `log_return` | OHLCV | `log(close / prev_close)` |
| 1 | `realized_vol` | OHLCV | Rolling std of log returns (last 20 bars) |
| 2 | `rsi_norm` | `frames["features"]` | `(rsi_14 - 50) / 50` → [-1, +1] |
| 3 | `adx_norm` | `frames["features"]` | `adx_14 / 50` → [0, ~1.5] |
| 4 | `macd_hist_norm` | `frames["features"]` | `macd_hist_12_26_9 / atr_14` → ATR-normalized |

**Fallback:** When `frames["features"]` is unavailable, uses only dimensions 0-1 (2D mode). The emission probability computation slices means/variances to match available dimensions.

## Algorithm

### Forward Algorithm (per bar)

1. Extract observation vector `x` (5D or 2D fallback)
2. For each state k, compute emission probability:
   ```
   P(x | k) = product over d of N(x_d; mu[k,d], var[k,d])
   ```
   Using diagonal multivariate Gaussian (independent dimensions).
3. Update forward variable:
   ```
   alpha_new[k] = sum_j(alpha[j] * A[j,k]) * P(x | k)
   ```
4. Normalize: `alpha /= sum(alpha)`
5. Most likely regime = `argmax(alpha)`
6. Track regime duration (bars since last regime change)

### Default Parameters

**Transition Matrix A (3x3):**
```python
A = [[0.95,  0.025, 0.025],   # Ranging: sticky
     [0.03,  0.94,  0.03],    # Trending-up: sticky
     [0.03,  0.03,  0.94]]    # Trending-down: sticky
```

**Emission Means (3x5):**
```python
means = [
    [0.0,    0.005, 0.0,  0.3, 0.0],    # Ranging
    [0.001,  0.008, 0.3,  0.5, 0.2],    # Trending up
    [-0.001, 0.012, -0.3, 0.5, -0.2],   # Trending down
]
```

**Emission Variances (diagonal covariance, 3x5):**
```python
variances = [
    [0.0001, 0.001, 0.04, 0.04, 0.04],  # Ranging: tight
    [0.0002, 0.002, 0.06, 0.06, 0.06],  # Up: moderate
    [0.0003, 0.003, 0.06, 0.06, 0.06],  # Down: wider
]
```

### JSON Override

Optional file `config/hmm_parameters.json`:
```json
{
    "transition_matrix": [[...], [...], [...]],
    "emission_means": [[...], [...], [...]],
    "emission_variances": [[...], [...], [...]]
}
```

Loaded at plugin instantiation if the file exists. Allows retraining without code changes.

## Outputs

```python
outputs = frozenset({
    "hmm_regime",              # Most likely state: 0=ranging, 1=up, 2=down
    "hmm_regime_prob",         # Probability of most likely state (0-1)
    "hmm_prob_ranging",        # P(state=0)
    "hmm_prob_trending_up",    # P(state=1)
    "hmm_prob_trending_down",  # P(state=2)
    "hmm_regime_duration",     # Bars since last regime change
})
```

**min_lookback:** 20 (need rolling window for realized vol)

## Incremental State

```python
_state = {
    "alpha": np.ndarray,        # Forward variable (K=3 probabilities)
    "prev_close": float,        # For log return computation
    "return_buffer": deque,     # Last 20 returns for realized vol
    "prev_regime": int,         # For duration tracking
    "regime_duration": int,     # Bars in current regime
}
```

`compute_next()` updates these in-place, producing O(K²·D) per-bar computation where K=3, D=5.

## Data Flow

```
OHLCV (close) ──> log returns + realized vol ──┐
                                                ├──> 5D observation ──> Forward Algorithm ──> regime probs
frames["features"] ──> RSI, ADX, MACD norm ────┘
(optional, falls back to 2D)
```

## BOCPD Integration

No direct coupling — complementary outputs consumed independently:
- **BOCPD:** "a regime change just happened" (cp_detected, cp_probability)
- **HMM:** "we are in regime X with Y% confidence" (hmm_regime, hmm_regime_prob)
- **Future I6:** combines both for high-confidence regime-aware signals

## Registration

In `src/intelligence/register_plugins.py`:
```python
from .smart_money.hmm_regime import plugin as hmm_plugin

# Inside register_all_plugins():
    registry.register_pattern(hmm_plugin)
```

**New totals:** 16 indicators + 16 patterns = **32 total plugins**

## Testing Strategy

Test file: `tests/unit/intelligence/test_smart_money_plugins.py` (append)

1. **Trending up detection** — rising prices, verify `hmm_regime=1` and `hmm_prob_trending_up` is highest
2. **Trending down detection** — falling prices, verify `hmm_regime=2` and `hmm_prob_trending_down` is highest
3. **Ranging detection** — flat/oscillating prices, verify `hmm_regime=0` and `hmm_prob_ranging` is highest
4. **Incremental parity** — `compute_next()` matches `compute_full()` on same data
5. **Graceful without features** — works with just OHLCV in 2D fallback mode
6. **Empty/insufficient input** — returns `{}` when fewer than 20 bars

Estimated: 6 tests.
