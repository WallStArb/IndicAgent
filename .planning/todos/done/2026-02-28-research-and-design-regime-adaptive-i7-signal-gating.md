---
created: 2026-02-28T01:31:35.002Z
title: Research and design regime-adaptive I7 signal gating
area: general
files:
  - docs/ideas/regime-adaptive-trading.md
  - src/intelligence/smart_money/hmm_regime.py
  - src/intelligence/i7/
---

## Problem

I7 signal plugins (TrendFollowing, MeanReversion, VWAPDeviation, etc.) currently fire regardless of the active HMM regime. This produces false signals: trend-following setups trigger in ranging markets, mean-reversion setups trigger in strong trends. HMM regime data (`hmm_regime`, `hmm_regime_prob`, `hmm_regime_duration`) is already emitted in every `IntelligenceEvent` but is unused by I7 plugins.

Research from QuantInsti article on regime-adaptive trading (HMM + Random Forest) confirms:
- Regime-specific models outperform generalist models
- Conviction thresholds (probability gates) are essential — without them, marginal-probability signals cause whipsaws
- Position sizing per regime (ATR multiplier) is as impactful as signal selection

## Solution

**Phase 1 — Regime filter per I7 plugin (low effort, high impact):**

Add regime check at top of each I7 plugin's `compute_next()`:

| Plugin | Favored Regimes | Gate |
|--------|----------------|------|
| TrendFollowing | 1 (trend↑), 2 (trend↓) | Skip if regime=0 |
| MomentumBreakout | 1, 2 | Skip if regime=0 |
| LiquidityHunt | 1, 2 | Skip if regime=0 |
| MTFAlignment | 1, 2 | Skip if regime=0 |
| MeanReversion | 0 (ranging) | Skip if regime≠0 |
| VWAPDeviation | 0 | Skip if regime≠0 |
| SqueezeExpansion | any | Require hmm_regime_prob > 0.65 |
| LiquiditySweepReclaim | any | Require hmm_regime_duration > 5 |
| SupplyDemandSetup | any | Reduce size if hmm_regime_prob < 0.60 |

**Phase 2 — Regime-adaptive ATR multiplier in position sizer:**

```python
ATR_MULT = {0: 1.0, 1: 2.0, 2: 2.0}  # ranging tight, trending wide
stop_distance = atr_14 * ATR_MULT[hmm_regime]
```

**Phase 3 (future, Phase 7+) — Regime-specific ML signal quality scoring:**
- Lightweight logistic regression per regime trained on `intelligence_features` + `signal_ledger` outcomes
- Walk-forward retraining (weekly for 1h, daily for 5m)
- Output: `regime_signal_quality ∈ [0,1]` used by signal aggregator

**Key implementation notes:**
- Use 5m or 15m `hmm_regime` as authority for gating 1m signals (1m HMM is noisy)
- Don't gate if `hmm_regime_prob < 0.55` — uncertain regime
- Don't gate on new regimes: `hmm_regime_duration < 5` bars → wait for confirmation
- Multi-TF regime agreement (1m + 5m + 15m all same) is a strong confluence signal

Full research doc: `docs/ideas/regime-adaptive-trading.md`
