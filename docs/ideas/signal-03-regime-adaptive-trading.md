# Regime-Adaptive Trading (Research)

**Version:** 1.0.0
**Status:** draft
**Priority:** medium
**Milestone:** future (post-v2.8)
**Last Updated:** 2026-02-27
**Tags:** regime, hmm, random-forest, signal-gating, adaptive, trading, ml, intelligence

**Source:** [QuantInsti — Step-by-Step Python Guide for Regime-Specific Trading Using HMM and Random Forest](https://blog.quantinsti.com/regime-adaptive-trading-python)

---

## Core Concept

**HMM finds the regime → regime-specific model exploits it.**

A single model trained across all market conditions is always a compromise. The key insight is to split the problem: use HMM to detect which market regime is active, then use a separate specialist model (Random Forest, logistic regression, or rule set) trained *only* on data from that regime. Each specialist learns what patterns matter in its specific market condition.

---

## What the Article Does

### Regime Detection (HMM)
- `GaussianHMM` with `n_components=2` (low-vol vs high-vol)
- Input: daily returns only (1-dimensional)
- Trained on 4-year rolling window
- `covariance_type="diag"`, `n_iter=100`
- Regime probabilities via `predict_proba()`; next-day forecast via `last_state_probs @ transmat_`

### Regime-Specific ML (Random Forest)
- Two separate RF classifiers: Model 0 (trained on regime-0 bars only), Model 1 (regime-1 bars only)
- Features: 100+ technical indicators from the `ta` library (RSI, MACD, Bollinger, momentum, volume)
- Target: `1` if next N-day return > 0, else `0`
- Signal selection: use Model 0 if regime-0 is more probable tomorrow; use Model 1 otherwise
- Output: `predict_proba()` → probability of upward move

### Conviction Threshold
- Raw probability alone is not enough — a `limit=0.03` buffer filters weak signals
- Long: prob > 0.53 → signal = +1
- Neutral: 0.47–0.53 → signal = 0
- Short: prob < 0.47 → signal = -1
- Eliminates marginal-probability trades that get whipsawed

### Walk-Forward Retraining
- Rolling 4-year window retrains every period (not a static train/test split)
- Train = first (4yr − 90d), test/predict = last 90 days
- Minimum 60 bars with both regime classes required before models are deployed (neutral otherwise)

### Stationarity (Critical for ML features)
- ADF test on every feature before feeding to RF
- p ≤ 0.05: already stationary → use as-is
- p > 0.05: non-stationary → convert to `pct_change()`
- ADF fails entirely: drop indicator
- Non-stationary features mislead ML models; this step is non-optional

---

## Key Insights

1. **Regime-specific models beat generalist models.** Even simple RFs trained on regime-labeled data outperform a single model trained on everything. The regime acts as a curriculum separator.

2. **Conviction thresholds are not optional.** Without them you trade on 51% probability and get whipsawed. The 0.03 buffer meaningfully reduces noise.

3. **Walk-forward evaluation is essential.** Static train/test falsely validates strategies. Continuous retraining on expanding windows catches real-world drift and regime shift.

4. **Stationarity is non-negotiable for ML inputs.** RSI is stationary; raw price levels are not. Always ADF-test features before feeding a classifier.

5. **Regime duration and confidence matter as much as the regime label.** A just-started regime (duration < 5 bars) or a low-confidence label (prob < 0.55) is unreliable — don't trade off it.

6. **Position sizing per regime is more impactful than signal selection.** Even with the same entry signal, adapting stop width and size to regime volatility dramatically changes outcomes:
   - Ranging: tight stops (ATR × 1.0), smaller size
   - Trending: wide stops (ATR × 2.0–2.5), full size

---

## Application to IndicAgent

We already have 3-regime HMM (`hmm_regime`: 0=ranging, 1=trend↑, 2=trend↓) and `hmm_regime_prob` + `hmm_regime_duration` in the SMC tier of every `IntelligenceEvent`. The gaps are in how I7 setups *use* that information.

### Near-Term (I7 signal gating) — fits existing architecture

**1. Regime filter per I7 plugin**

Each I7 setup should check regime before firing:

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
| SupplyDemandSetup | any | Reduce size if regime_prob < 0.60 |

**2. `hmm_regime_prob` as conviction gate**

Don't emit a signal when the regime is uncertain:
```python
if hmm_regime_prob < 0.60:
    return {}  # skip — uncertain regime, risk of false signal
```

**3. `hmm_regime_duration` as stability gate**

New regimes may be false starts — require confirmation:
```python
if hmm_regime_duration < 5:
    return {}  # regime just started, wait for confirmation
```

**4. Regime-adaptive ATR multiplier in position sizer**

Current `position_sizer` uses a fixed ATR multiplier. Adapt it:
```python
ATR_MULT = {0: 1.0, 1: 2.0, 2: 2.0}  # ranging tight, trending wide
stop_distance = atr_14 * ATR_MULT[hmm_regime]
```

### Medium-Term (dedicated regime-adaptive plugin) — Phase 7+

A `RegimeAdaptiveSignal` I7 plugin that:
- Reads `hmm_regime` + `hmm_regime_prob` from the `IntelligenceEvent`
- Runs a lightweight logistic regression (not full RF) per regime, trained on `intelligence_features` + `signal_ledger` outcomes
- Outputs a blended signal confidence score: `regime_signal_quality ∈ [0, 1]`
- The signal aggregator weights other I7 signals by this quality score

Training cadence (walk-forward):
- **1h timeframe**: weekly retraining on last 1008 bars (~6 weeks of 1h bars)
- **5m timeframe**: daily retraining on last 2016 bars (~1 week of 5m bars)

Feature engineering for futures (replaces the article's `ta` library):
- Use existing I1 indicators (23 plugins) — already stationary at plugin level
- Add I6 SMC features: `sweep_detected`, `fvg_size_pct`, `bos_detected`
- Add multi-timeframe: 1m regime vs 5m regime agreement
- Stationarity: I1 outputs are already incremental/normalized; verify with ADF before adding any raw price-level features

### Long-Term (full regime-adaptive ML layer) — Phase 8+

Full article pattern applied to futures:
- Separate RF per regime (3 models: ranging, trend-up, trend-down)
- Train on `intelligence_features` hypertable (ML training dataset already collecting)
- Target: signal outcome from `signal_ledger` (win/loss after T1/T2/T3)
- Walk-forward retraining via scheduled job (Sunday 5pm EST for weekly cadence)
- Output: `regime_model_signal` fed into signal aggregator with regime-weighted confidence

---

## Implementation Notes

- **Don't trade uncertain regimes**: `hmm_regime_prob < 0.55` → neutral
- **Don't trade new regimes**: `hmm_regime_duration < 5` → wait
- **Match timeframe to regime lookback**: 1m HMM regime is noisy; use 5m or 15m regime as the authority for signal gating
- **Regime agreement across TFs is a strong signal**: if 1m, 5m, and 15m all agree on regime → high confidence
- **`intelligence_features` is already the training dataset** — every bar since Phase 5 has been collecting the full feature vector needed for offline ML training

---

## Related Ideas

- `.planning/IDEAS.md` — see "Phase 7: Composite Intelligence Score" for the ML scoring layer
- `docs/ideas/jim-simons-renaissance-principles.md` — regime detection is a core Renaissance principle
- `src/intelligence/smart_money/hmm_regime.py` — current 3-regime HMM implementation (5D observations: log_return, realized_vol, rsi_norm, adx_norm, macd_norm)
- `src/intelligence/i7/` — I7 signal plugins that would receive regime gates
