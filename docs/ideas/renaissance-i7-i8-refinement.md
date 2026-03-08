# Renaissance-Style I7/I8 Refinement Ideas
**Status:** Future Research
**Created:** 2026-03-07

## Overview
This document captures longer-term Renaissance Capital-inspired ideas for I7/I8 refinement that require more research or data before implementation.

See `docs/plans/2026-03-07-i7-i8-renaissance-refinement-design.md` for the approved hybrid approach (Phase 1 + 3) being actively implemented now.
---
## Future Ideas
### 1. Orthogonal Signal Decomposition (Month 6+)
After 6 months of outcome data, refactor the17 I7 plugins into orthogonal factor bets using PCA/ICA.

**What this would look like:**
```python
# Current: 17 correlated plugins
plugins = ["TrendFollowing", "MeanReversion", "MomentumBreakout", ...]

# Future: Orthogonal factor bets
factors = {
    "F1_trend_momentum": 0.4 * TrendFollowing + 0.3 * MomentumBreakout + 0.3 * MTFAlignment,
    "F2_mean_reversion": 0.6 * MeanReversion + 0.4 * DivergenceStack,
    "F3_institutional_flow": 0.5 * SweepReclaim + 0.3 * FVGFill + 0.2 * SupplyDemandSetup,
    "F4_regime_transition": 0.7 * RegimeTransition + 0.3 * CHoCHReversal,
}
```
**Benefits:**
- Cleaner P&L attribution — know exactly which factor drove returns
- Optimal capital allocation — bet sizing proportional to factor Sharpe
- Removes redundant bets — no more double-counting trend exposure
**Requirements:**
- 6+ months of outcome data (30+ signals per setup minimum)
- Historical feature covariance matrix
- Backtest P&L attribution per plugin
**Open questions:**
- Minimum sample size: 30 signals? 100 signals per setup?
- Factor retraining frequency: Monthly? Quarterly?
- How to handle cold-start period before enough data?
---
### 2. Lead-Lag Cross-Asset Architecture
Add cross-asset spillover detection for ES→SPY, NQ→QQQ, sector ETFs, and VIX term structure.
**What this would look like:**
```python
# New I4 plugin: CrossAssetContext
outputs = frozenset({
    "lead_lag_es_spy",      # ES → SPY lead coefficient (~100ms)
    "lead_lag_nq_qqq",      # NQ → QQQ lead coefficient
    "sector_momentum_spill", # XLK/XLE/XLF → component momentum
    "vix_term_spread",      # VIX9D - VIX (negative = fear subsiding)
    "vix_contango",         # VIX3M - VIX (contango = calm)
})
```
**Computation:**
- Rolling 60-bar lead-lag regression: `leader_t = lag + beta * lagger_{t-k}`
- Sector ETF momentum → component correlation
- VIX term spread: `vix_9d - vix` (negative = fear compression, bullish)
**New I7 plugin: LeadLagSetup**
Fires when:
1. Leader shows momentum acceleration
2. Lagger hasn't moved yet
3. Historical lead-lag window within tolerance
**Benefits:**
- Captures structural alpha that single-symbol systems miss
- VIX spread is proven mean-reversion predictor
- Low correlation to existing signals
**Requirements:**
- Synchronized multi-symbol data (parallel IBKR subscriptions)
- ES, NQ, SPY, QQQ 1m bars
- VIX9D, VIX3M data (not standard IBKR contracts — Yahoo Finance?)
**Open questions:**
- Which symbols? ES/SPY, NQ/QQQ obvious. Sector ETFs (XLK, XLE, XLF)?
- VIX term structure source: Yahoo Finance? CBOE direct?
- How to handle data gaps when futures are closed?
---
### 3. Alpha Perishability Analysis
Classify signals by alpha decay rate and optimize execution priority.
**Perishability Tiers:**
| Tier | Alpha Sources | Latency Budget | Execution Priority |
|------|---------------|-----------------|---------------------|
| **Perishable** | Lead-lag (ES→SPY), Microstructure | <200ms | Parallel, first |
| **Semi-perishable** | SMC sweep, CHoCH, FVG | 1-5 bars | Sequential, early |
| **Structural** | Trend, mean-reversion, patterns | 1-2 bars | Sequential, normal |
**What this would look like:**
```python
# Prioritized plugin execution
PERISHABLE_PLUGINS = ["LeadLagSetup", "MicrostructureImbalance"]
SEMI_PERISHABLE = ["SweepReclaim", "CHoCHReversal", "FVGFill"]

# Execute perishable plugins first with lower timeout tolerance
for plugin in PERISHABLE_PLUGINS:
    result = plugin.compute(windows, timeout_ms=150)
    if result:
        return result  # Early exit on perishable alpha
```
**Benefits:**
- Captures time-sensitive alpha before it decays
- Prioritizes execution based on alpha decay rate
- Cleaner separation of signal types
**Requirements:**
- Alpha decay rate analysis per plugin (research project)
- Execution timing metrics
- Dynamic priority adjustment based on market conditions
**Open questions:**
- How to measure alpha decay rate? Backtest analysis needed
- Should priorities be regime-dependent?
- How to handle warmup period when decay rates are unknown?
---
### 4. Adaptive CIS Weight Learning
Replace fixed bootstrap weights with learned weights from outcome data.
**Current State:**
```python
BOOTSTRAP_WEIGHTS = {
    "trend": 0.20,
    "momentum": 0.20,
    "structure": 0.15,
    "pattern": 0.05,
    "institutional": 0.25,
    "regime": 0.15,
}
```
**Future State:**
```python
# Learned weights from cis_weights table
weights = load_learned_weights_from_db()

# Update weights based on regime-specific performance
if regime == "trending":
    weights["trend"] *= 1.2  # Boost trend in trending regime
    weights["mean_reversion"] *= 0.8  # Reduce MR in trending
```
**Benefits:**
- Adapts to changing market conditions
- Regime-specific weight profiles
- Learns from outcomes, not assumptions
**Requirements:**
- 6+ months of outcome data
- `cis_weights` table with regime-specific weights
- Online learning algorithm (exponential moving average of bucket returns)
**Open questions:**
- Learning rate: How fast to adapt? Daily? Weekly?
- Minimum sample size per regime before adapting weights?
- How to handle regime transitions during weight updates?
---
### 5. Signal Quality Metrics Dashboard
Add real-time signal quality tracking and dashboard visualization.
**Metrics to Track:**
```python
# Per-setup metrics
setup_metrics = {
    "signals_fired_per_bar",
    "bars_with_signal",
    "avg_confidence",
    "num_signals_per_direction",
    "win_rate_30d",
    "avg_pnl_r_30d",
    "sharpe_30d",
}

# Per-bucket metrics
bucket_metrics = {
    "bucket_agreement_rate",
    "bucket_contribution_to_cis",
    "bucket_direction_accuracy",
}
```
**Dashboard Visualization:**
- Signal quality heatmap (setup × regime)
- Bucket contribution waterfall chart
- CIS score distribution histogram
- Orthogonality correlation matrix
**Benefits:**
- Visibility into signal quality trends
- Early detection of regime changes
- Attribution of P&L to signal components
**Requirements:**
- `signal_quality_metrics` table
- Dashboard UI components
- Real-time metrics aggregation service
**Open questions:**
- Metrics refresh rate: Per bar? Per minute?
- Historical retention: 30 days? 90 days?
- How to handle service restarts (metrics continuity)?
---
## Research Projects
1. **Alpha Decay Rate Analysis** — Measure how quickly each signal type's alpha decays
2. **Lead-Lag Coefficient Drift** — How often do ES→SPY lead coefficients change?
3. **Regime-Specific Weight Optimization** — Find optimal CIS weights per regime
4. **Orthogonal Factor Extraction** — PCA/ICA on historical features
---
## Dependencies
- Phase 1 + 2 (from design doc) must complete before most of these ideas can be implemented
- 6+ months of outcome data required for orthogonal decomposition and adaptive weights
