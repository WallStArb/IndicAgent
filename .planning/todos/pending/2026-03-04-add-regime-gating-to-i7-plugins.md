---
created: 2026-03-04T00:00:00.000Z
title: Add regime gating to I7 signal plugins
area: intelligence
files:
  - src/intelligence/trading/
  - docs/ideas/regime-adaptive-trading.md
---

## Problem

I7 plugins currently fire regardless of market regime. TrendFollowing and MomentumBreakout firing in a ranging market, MeanReversion and VWAPDeviation firing in a trending market — these are structurally false signals. `hmm_regime`, `hmm_regime_prob`, and `hmm_regime_duration` are already present in every `IntelligenceEvent` (SMC tier) but not used as gates.

## Solution

Per the fully-specced design in `docs/ideas/regime-adaptive-trading.md`:

**1. Per-plugin regime filter:**
| Setup | Favored Regimes | Gate |
|-------|----------------|------|
| TrendFollowing | 1, 2 | Skip if regime=0 |
| MomentumBreakout | 1, 2 | Skip if regime=0 |
| LiquidityHunt | 1, 2 | Skip if regime=0 |
| MTFAlignment | 1, 2 | Skip if regime=0 |
| MeanReversion | 0 | Skip if regime=1 or 2 |
| VWAPDeviation | 0 | Skip if regime=1 or 2 |
| SqueezeExpansion | any | Require regime_prob > 0.65 |
| LiquiditySweepReclaim | any | Require regime_duration > 5 |

**2. Global conviction gate** (all plugins):
```python
if hmm_regime_prob < 0.60:
    return {}  # uncertain regime — skip
```

**3. Global stability gate** (all plugins):
```python
if hmm_regime_duration < 5:
    return {}  # regime just started — wait for confirmation
```

Use 5m or 15m regime as the authority for signal gating (1m HMM is noisy). Regime agreement across TFs (1m + 5m + 15m all agree) is a strong confidence booster.
