# I7/I8 Renaissance-Style Refinement Design

**Last Updated:** 2026-05-02

**Status:** Draft
**Created:** 2026-03-07
**Author:** Claude + User

## Problem Statement

Current I7/I8 architecture generates signals but lacks Renaissance Capital's rigor in:
1. **Signal orthogonality** — plugins have high correlation clusters
2. **Cross-asset spillovers** — no lead-lag, no sector momentum transfer
3. **Regime-aware feature gating** — features are regime-agnostic

## Current State Analysis
### Signal Correlation Clusters
| Cluster | Plugins | Shared Features | Correlation Risk |
|---------|----------|-----------------|------------------|
| Trend | TrendFollowing, MomentumBreakout, MTFAlignment | trend_regime, swing_pattern, ctf_score | HIGH |
| Mean-Reversion | MeanReversion, DivergenceStack | rsi_14, rsi_div_*, vol_div_* | HIGH |
| Institutional | SweepReclaim, FVGFill, SupplyDemandSetup, CHoCHReversal | ob_type, fvg_type, sweep_* | MEDIUM |

### CIS Bucket Weights (Bootstrap v0)
```
trend:         0.20
momentum:      0.20
structure:     0.15
pattern:       0.05  ← smallest
institutional: 0.25  ← largest
regime:        0.15
```
**Problem:** Fixed weights. No online learning. Pattern bucket underweighted.

### Missing Cross-Asset Features
- No ES→SPY lead-lag coefficients
- No sector rotation signals (XLK → tech names)
- No VIX term structure (VIX9D/VIX/VIX3M spread)
- No cross-timeframe momentum spillover

### Missing Higher-Order Features
Current features are first-order (price, volume, indicators). Missing:
- Return distribution moments (skewness, kurtosis)
- Regime instability metrics
- Microstructure proxies
- Momentum acceleration
---

## Approach 1: Orthogonal Signal Decomposition
**Philosophy:** RenTec's alpha comes from combining *independent* signals, not correlated ones.
### Design
1. **Build feature covariance matrix** from 6+ months of outcome data
2. **Apply PCA/ICA** to decompose features into orthogonal factors
3. **Project each I7 plugin** onto factor subspaces
4. **Replace hand-tuned confidence weights** with factor loadings from backtest P&L attribution
5. **Add signal decay tracking** — decorrelate signals that historically fired together but had divergent outcomes
### Trade-offs
| Pro | Con |
|-----|-----|
| Mathematical rigor — removes redundant bets | Requires 6+ months of outcome data |
| Cleaner P&L attribution — know exactly which factor drove P&L | Loses interpretability ("trend_regime" → "factor_3") |
| Optimal capital allocation | Implementation complexity |

---
## Approach 2: Lead-Lag Cross-Asset Architecture
**Philosophy:** Markets are not independent. ES leads SPY by ~100ms. VIX inversion predicts ES mean-reversion.
### Design
#### 2.1 New I4 Plugin: `CrossAssetContext`
```python
# src/intelligence/context/cross_asset.py

outputs = frozenset({
    "lead_lag_es_spy",      # ES → SPY lead coefficient
    "lead_lag_nq_qqq",      # NQ → QQQ lead coefficient
    "sector_momentum_spill", # XLK/XLE/XLF → component momentum
    "vix_term_spread",      # VIX9D - VIX (negative = fear subsiding)
    "vix_contango",         # VIX3M - VIX (contango = calm, backwardation = panic)
})
```
**Inputs:**
- ES, NQ, SPY, QQQ 1m bars (parallel IBKR subscriptions)
- VIX, VIX9D, VIX3M daily (already in system)
**Computation:**
- Rolling 60-bar lead-lag regression: `leader_t = lag + beta * lagger_{t-k}`
- Sector ETF momentum → component correlation
- VIX term spread: `vix_9d - vix` (negative = fear compression, bullish)
#### 2.2 Extend CIS with 7th Bucket
```python
BUCKET_NAMES = (
    "trend", "momentum", "structure", "pattern",
    "institutional", "regime", "cross_asset",  # NEW
)

BOOTSTRAP_WEIGHTS = {
    "trend": 0.18,        # -0.02
    "momentum": 0.18,     # -0.02
    "structure": 0.15,    # unchanged
    "pattern": 0.07,      # +0.02
    "institutional": 0.22, # -0.03
    "regime": 0.15,       # unchanged
    "cross_asset": 0.05,  # NEW
}
```
#### 2.3 New I7 Plugin: `LeadLagSetup`
```python
# src/intelligence/trading/lead_lag_setup.py

@dataclass
class LeadLagSetupPlugin:
    name: str = "trad_LeadLagSetup"
    regime_type: str = "any"

    # Fires when:
    # 1. Leader shows momentum acceleration
    # 2. Lagger hasn't moved yet
    # 3. Historical lead-lag window within tolerance
```
### Trade-offs
| Pro | Con |
|-----|-----|
| Captures structural alpha | Requires synchronized multi-symbol data |
| VIX spread is proven predictor | Lead-lag coefficients drift over time |
| Low correlation to existing signals | Additional IBKR subscription load |

---
## Approach 3: Regime-Aware Feature Engineering
**Philosophy:** RSI divergence works in ranging markets, fails in trends. Features must be *conditional* on regime.
### Design
#### 3.1 Five Higher-Order Features for I4
Add to `src/intelligence/context/regime_features.py`:
```python
# 1. Return skewness (30-bar) — negative skew = crash risk, positive = momentum
returns_skew_30 = scipy.stats.skew(returns[-30:])

# 2. Regime instability index — HMM prob variance over rolling window
hmm_instability = np.var(hmm_prob_history[-20:])

# 3. Microstructure imbalance proxy — (close - vwap) / atr
#    Positive = buying pressure, negative = selling pressure
microstructure_imbalance = (close - vwap) / atr_14

# 4. Momentum acceleration — ROC(5) - ROC(14)
#    Positive = momentum speeding up, negative = slowing down
momentum_acceleration = roc_5 - roc_14

# 5. Vol-of-vol — rolling std of ATR
#    High vol-of-vol = regime transition risk
vol_of_vol = np.std(atr_history[-20:])
```
#### 3.2 Gate I7 Plugins on Regime-Specific Thresholds
```python
# TrendFollowing requires momentum acceleration
if momentum_acceleration <= 0:
    return self._no_signal()

# MeanReversion requires negative skew (panic mean-reversion)
if returns_skew_30 >= -0.3:
    return self._no_signal()

# Breakouts require vol compression (low vol-of-vol)
if vol_of_vol > threshold:
    return self._no_signal()
```
#### 3.3 RegimeFeatureGate Validation
Add to `signal_generator_service.py`:
```python
def _validate_regime_gate(self, signal: dict, features: dict) -> bool:
    """Reject signals whose supporting features contradict regime state."""
    plugin_name = signal.get("setup_plugin")

    if plugin_name == "trad_TrendFollowing":
        return features.get("momentum_acceleration", 0) > 0

    if plugin_name == "trad_MeanReversion":
        return features.get("returns_skew_30", 0) < -0.3

    # ... etc
```
### Trade-offs
| Pro | Con |
|-----|-----|
| Features become conditional | More hyperparameters to tune |
| Skewness/vol-of-vol are crash predictors | Requires careful backtesting |
| Immediate implementation | Risk of overfitting |

---
## Recommended Hybrid: Approach 1 + Approach 3
### Rationale
Appro 1 (orthogonal decomposition) requires historical outcome data we don't have yet. Approach 3 (regime-aware features) can be implemented immediately and provides the data foundation for Approach 1 later.
This follows the Renaissance principle: **earn the right through proof**.
### Implementation Phases
#### Phase 1: Higher-Order Features (Week 1-2)
- Add 5 regime-aware features to I4
- Wire into CIS bucket scoring
- Log feature values to `intelligence_features` for analysis
#### Phase 2: Regime Gating (Week 3-4)
- Gate existing I7 plugins on feature thresholds
- Add `RegimeFeatureGate` validation in signal_generator
- Backtest impact on signal frequency vs quality
#### Phase 3: Orthogonal Decomposition (Month 6+)
- Build feature covariance matrix from 6 months of outcomes
- Apply PCA/ICA decomposition
- Refactor I7 plugins into orthogonal factor bets
- Implement adaptive weight learning
### Success Metrics
| Metric | Current | Target (Phase 2) | Target (Phase 3) |
|--------|---------|------------------|------------------|
| Signal win rate | ~45% | 50% | 55% |
| Signal orthogonality (avg correlation) | ~0.6 | 0.5 | 0.3 |
| Regime-specific Sharpe | Unknown | Trackable | >1.0 per regime |
| Cross-asset lead-lag capture | 0% | 10% | 25% |
---
## Latency Analysis
Based on signal_generator_service.py code review, latency profiling:
| Pipeline Stage | Latency (ms) | Cumulative | Notes |
|----------------|---------------|------------------|------------------------------------------|
| I1 → I2 indicators | ~15 | Per bar | LOW — sequential loops |
| I3 → I6 structure/SMC | ~50 | Per bar | MEDIUM — depends on swing detection |
| I4 → I8 context/regime | ~50 | Per bar | MEDIUM — GARCH, Kalman, HMM |
| I5 → I7 patterns/setups/aggregation | ~200 | Per bar | HIGH — runs 17 plugins sequentially |
| CIS scoring | ~5 | Per bar | LOW — just weighted sum of 6 buckets |
| Signal selection | ~5 | Per bar | LOW — priority sorting + regime tiebreak |
| DB write (ledger) | ~2 | Per bar | LOW — single INSERT per bar |
| Redis publish (SSE) | ~1 | Per bar | LOW — single xadd per bar |
| **Total pipeline latency** | **~382 ms** | Not a bottleneck for signal quality |
**Key insight:** Total latency of ~382ms is acceptable for intraday trading. However, there's room for optimization
### Latency Bottlenecks
1. **Sequential plugin execution** — 17 plugins run sequentially in `_execute_i7_plugins()`. Could be parallelized, but requires careful dependency management
2. **Multiple-TF loop** — The `for timeframe in timeframes:` loop calls `_execute_i7_plugins()` 4 times (once per TF). This is unavoidable due to feature structure
3. **Warmup delay** — First ~50 bars after service start, no signals fire (bar_history empty)
### Latency Optimization Opportunities
| Optimization | Impact | Complexity |
|---------------|---------|------------|
| Parallelize independent plugins | -50% I7 latency | Medium — thread pool |
| Cache regime data per symbol | -10ms per bar | Low — service-level cache |
| Pre-compute regime authority | -5ms per bar | Low — cache at service start |
| Skip feature lookups for simple signals | -20ms per bar | Low — only read needed fields |
### Alpha Perishability
| Alpha Source | Perishability | Recommendation |
|------------------------|--------------|------------------|
| Lead-lag alpha (ES→SPY) | 100ms | HIGH — Must capture within window |
| SMC sweep reclaim | 5-30s | MEDIUM — Structural, some latency OK |
| TrendFollowing | 1-2 bars | LOW — Aims for multi-hour moves |
| MeanReversion | 1-2 bars | LOW — Aims for short-term reversals |
| FVG fill | 1-5 bars | LOW — Aims for quick scalps |
**Renaissance Principle:** Alpha decays. optimize for decay, not eliminate the latency entirely
---
## Open Questions
1. **Which symbols for lead-lag?** ES/SPY, NQ/QQQ are obvious. What about sector ETFs?
2. **VIX term structure source?** VIX9D and VIX3M aren't standard IBKR contracts. Yahoo Finance API?
3. **Minimum outcome sample size?** 30 signals per setup before orthogonal decomposition? 100?
4. **Feature drift retraining?** How often to recompute PCA factors? Monthly? Quarterly?
---
## Next Steps
1. User approval of hybrid approach
2. Invoke `writing-plans` skill to create detailed implementation plan
3 3. Begin Phase 1 implementation
