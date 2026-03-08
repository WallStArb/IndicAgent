# Renaissance-Style I7/I8 Refinement Ideas
**Status:** Future Research
**Created:** 2026-03-07
**Updated:** 2026-03-07
## Overview
This document captures Renaissance Capital-inspired ideas for I7/I8 refinement.
**Priority Legend:**
- ⭐⭐⭐ **HIGH** — Core signal intelligence, immediate alpha impact
- ⭐⭐ **MEDIUM** — Enhances existing signals, requires infrastructure
- ⭐ **LOW** — Future product (TradeAgent/PrimeAgent), execution optimization
---
## SIGNAL INTELLIGENCE PRIORITY
### ⭐⭐⭐ 1. Alpha Decay & Signal Perishability
**Renaissance Principle:** Alpha has a half-life. Old signals underperform.
#### 1.1 Momentum Half-Life Decay ⭐⭐⭐
```python
# New I4 feature
alpha_half_life = 5  # bars until signal alpha decays 50%

# Decay formula
alpha_decay_rate = 1.0 - (bars_since_signal / alpha_half_life)
adjusted_confidence = base_confidence * alpha_decay_rate
```
**Why:** TrendFollowing signals fire every bar in strong trends. But the 5th consecutive signal has less alpha than the 1st. Decay modeling captures this.
**Implementation:** Add `alpha_decay_rate` to CIS bucket scoring.
#### 1.2 Vol-of-Vol Decay Accelerator ⭐⭐⭐
```python
# When vol_of_vol is high, alpha decays faster
vol_adjusted_half_life = base_half_life / (1 + vol_of_vol)
```
**Why:** In unstable regimes (high vol-of-vol), signals lose predictive power faster. This gates signal frequency dynamically.
**Implementation:** Modify `signal_generator_service._build_all_ranked()` to include decay factor.
#### 1.3 Time-of-Day Structure Changes ⭐⭐
```python
# First 30min: momentum spillover from overnight
# Last 30min: mean-reversion as day traders exit
# Midday: trend continuation
session_alpha_multiplier = {
    "first_30min": 1.2,   # Boost trend
    "last_30min": 0.8,    # Reduce trend, boost MR
    "midday": 1.0,
}
```
**Why:** Intraday patterns are real. First 30min has higher volatility and trend continuation. Last 30min has mean-reversion as positions are squared up.
**Implementation:** Add `session_alpha_multiplier` to `SessionContext` I4 plugin.
#### 1.4 Killzone Acceleration Signals ⭐⭐⭐
```python
# AMD Killzone (14:00-16:00 UTC): London/NY overlap
# London Open (08:00-10:00 UTC): European momentum
# NYC Close (20:00-21:00 UTC): US momentum
killzone_alpha_boost = {
    "amd_killzone": 1.3,    # Highest volume, highest alpha
    "london_open": 1.15,
    "nyc_close": 1.1,
}
```
**Why:** Killzones are high-activity periods where signals have higher win rates. Boosting confidence during killzones and suppressing outside improves signal quality.
**Implementation:** Gate signals on `ict_killzones` I6 plugin output.
#### 1.5 Cross-TF Signal Synchronization ⭐⭐⭐
```python
# When 1m signal aligns with 5m/15m signal, boost confidence
if signal_1m.direction == signal_5m.direction == signal_15m.direction:
    confidence *= 1.3  # 30% boost for 3-TF alignment
```
**Why:** Multi-timeframe alignment is a stronger signal. 1m signals that agree with 5m/15m context have higher win rates.
**Implementation:** Already partially in `MTFAlignment` I7 plugin. Extend to all plugins via CIS `ctf_score` bucket.
---
### ⭐⭐⭐ 2. Hidden Alpha & Data Infrastructure
**Renaissance Principle:** Alpha hides in data others don't have or don't use.
#### 2.1 Order Flow Imbalance ⭐⭐⭐
```python
# New I4 feature
order_flow_imbalance = (bid_size - ask_size) / (bid_size + ask_size)
# Range: [-1, +1]
# Positive = buying pressure, negative = selling pressure
```
**Why:** When bid size > ask size, market makers are short gamma and will buy to hedge. This creates upward pressure. The reverse for ask > bid.
**Implementation:** Requires bid/ask size from IBKR tick data. Add to `IntelligenceEvent.i4` JSONB.
**Data Source:** IBKR `tickOptionality` field (requires `marketDataType=Options`)
#### 2.2 Volume-Weighted Price Momentum (VWAP Slope) ⭐⭐⭐
```python
# New I4 feature
vwap_slope = (vwap - vwap.shift(5)) / atr  # Normalized by volatility
# Positive = institutional buying, negative = institutional selling
```
**Why:** Price movement on high volume is institutional. Price movement on low volume is retail. VWAP slope distinguishes the two.
**Implementation:** Already have `vwap` from I1. Compute rolling slope and add to `IntelligenceEvent.i4`.
#### 2.3 Tick Frequency Analysis ⭐⭐
```python
# New I4 feature
tick_rate = len(ticks_last_60s) / 60  # Ticks per second
tick_acceleration = tick_rate - tick_rate.shift(10)  # Change in tick rate
```
**Why:** Increasing tick rate = market activity accelerating. Decreasing tick rate = activity subsiding. High tick rate + price move = sustained move. High tick rate + no price move = absorption (reversal likely).
**Implementation:** Requires tick-level data from IBKR. Store in `MarketDataContext`.
#### 2.4 Relative Volume (vs SPY) ⭐⭐⭐
```python
# New I4 feature
relative_volume = symbol_volume / spy_volume_rolling_20
# > 1.5 = idiosyncratic activity (stock-specific news/flow)
# < 0.7 = systematic activity (index-driven)
```
**Why:** When a stock's volume is high relative to SPY, it's experiencing idiosyncratic activity (earnings, news, sector rotation). This is alpha-rich. When volume is index-driven, it's beta.
**Implementation:** Requires SPY volume stream. Add to `CrossAssetContext` I4 plugin.
#### 2.5 Funding Rate Changes (Crypto/Futures) ⭐
```python
# New I4 feature (futures only)
funding_rate_acceleration = funding_rate - funding_rate.shift(8)  # 8-hour change
# Large positive = long squeeze risk
# Large negative = short squeeze opportunity
```
**Why:** In perpetual futures, funding rate changes predict squeezes. High positive funding = crowded longs = short squeeze setup.
**Implementation:** Requires exchange API (Binance/Bybit). Future product for crypto trading.
---
### ⭐⭐⭐ 3. Adaptive Learning & Optimization
**Renaissance Principle:** The market changes. The system must adapt.
#### 3.1 Signal Recycling Window ⭐⭐⭐
```python
# Prevent signal clustering
recycle_cooldown_bars = 10  # Minimum bars between same-setup signals
if bars_since_last_signal[setup_plugin] < recycle_cooldown_bars:
    confidence *= 0.5  # Heavy penalty for recycled signals
```
**Why:** When a setup fires, it shouldn't fire again for N bars. The alpha was captured. Repeated signals are redundant bets.
**Implementation:** Add `bars_since_last_signal` tracking to `signal_generator_service`.
#### 3.2 Counterfactual Logging ⭐⭐⭐
```python
# Log what-if scenarios
if confidence < 0.5:
    log_counterfactual(
        setup_plugin=plugin_name,
        direction=direction,
        would_have_fired=True,
        reason="low_confidence",
        confidence=confidence,
    )
```
**Why:** To learn, we need to know what we *didn't* do and whether it would have worked. Counterfactual analysis enables continuous improvement.
**Implementation:** Add `counterfactual_signals` table. Log suppressed signals for later analysis.
#### 3.3 Regime-Specific Performance Weights ⭐⭐⭐
```python
# Load regime-specific weights from DB
if regime == "trending":
    perf_weights = load_weights("trending")
elif regime == "ranging":
    perf_weights = load_weights("ranging")
```
**Why:** TrendFollowing performs well in trends, poorly in ranges. MeanReversion is the opposite. Regime-specific weights adapt to market conditions.
**Implementation:** Already have `setup_performance` table. Extend with `regime` column and load regime-specific weights.
#### 3.4 Adaptive CIS Bucket Weights ⭐⭐
```python
# Learn CIS weights from outcome data
# Start with bootstrap weights, adapt as data accumulates
learned_weights = exponential_moving_average(
    historical_bucket_returns,
    alpha=0.1,  # Slow learning
)
```
**Why:** Fixed bootstrap weights are a guess. Learned weights are evidence-based. As outcomes accumulate, the system learns which buckets matter.
**Implementation:** Add `cis_weights` table. Update weights weekly based on bucket-attributed returns.
#### 3.5 Outcome-Attributed Feature Importance ⭐⭐
```python
# Track which features actually contributed to outcomes
feature_importance = compute_shap_values(signal, outcome)
# Update rolling feature importance per setup
update_feature_importance(setup_plugin, feature_importance)
```
**Why:** We assume features matter. But do they? SHAP analysis on outcomes reveals which features actually drive returns.
**Implementation:** Requires 6+ months of outcomes. Add `feature_importance` table.
---
### ⭐⭐ 4. Structural Pattern Enhancements
**Renaissance Principle:** Hidden relationships between assets contain alpha.
#### 4.1 Lead-Lag Cross-Asset Architecture ⭐⭐
```python
# New I4 plugin: CrossAssetContext
outputs = frozenset({
    "lead_lag_es_spy",      # ES → SPY lead coefficient (~100ms)
    "lead_lag_nq_qqq",      # NQ → QQQ lead coefficient
    "sector_momentum_spill", # XLK/XLE/XLF → component momentum
    "vix_term_spread",      # VIX9D - VIX (negative = fear subsiding)
})
```
**Why:** ES leads SPY by ~100ms. NQ leads QQQ. VIX inversion predicts ES mean-reversion. Cross-asset spillovers are structural alpha.
**Implementation:** Requires parallel IBKR subscriptions for ES, NQ, SPY, QQQ. Add `CrossAssetContext` I4 plugin.
**Open Questions:**
- VIX9D/VIX3M source: Yahoo Finance? CBOE direct?
- How to handle data gaps when futures are closed?
#### 4.2 Multi-Asset Volatility Surface ⭐⭐
```python
# Cross-asset vol correlation matrix
vol_correlation = compute_rolling_correlation(
    [es_vol, spy_vol, vix, vxn, vvix],
    window=60,
)
# Detect when one asset's vol regime differs from others
vol_divergence = es_vol - spy_vol  # Futures vol vs equity vol
```
**Why:** When ES vol is high but SPY vol is low, there's an arbitrage opportunity. Cross-asset vol divergence predicts mean-reversion.
**Implementation:** Compute rolling vol correlation matrix. Add to `CrossAssetContext`.
#### 4.3 Signal Co-Occurrence Matrix ⭐⭐
```python
# Track which signals tend to fire together
cooccurrence = {
    ("TrendFollowing", "MTFAlignment"): 0.7,  # High co-occurrence
    ("MeanReversion", "DivergenceStack"): 0.6,
    ("SweepReclaim", "FVGFill"): 0.4,
}
# Use for consolidation and orthogonal decomposition
```
**Why:** Signals that fire together are redundant. Co-occurrence matrix identifies clusters for consolidation.
**Implementation:** Add `signal_cooccurrence` table. Update on each signal fire.
#### 4.4 Regime Transition Timing ⭐⭐
```python
# Detect when regime is about to change
regime_transition_probability = hmm_transition_prob[current_regime][other_regimes]
if regime_transition_probability > 0.3:
    # Reduce position size before transition
    confidence *= 0.7
```
**Why:** Regime transitions are high-risk periods. Reducing exposure before transitions improves Sharpe.
**Implementation:** Use HMM transition matrix to compute transition probability. Gate signals on transition probability.
---
## FUTURE PRODUCT: TRADE EXECUTION
*These ideas are valuable for TradeAgent/PrimeAgent but are NOT core intelligence features.*
### ⭐ 5. Position Sizing Optimization
#### 5.1 Kelly-Optimal Position Sizing
```python
# Kelly criterion based on historical Sharpe
kelly_fraction = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
# Apply fractional Kelly for safety
position_size = kelly_fraction * 0.25  # Quarter Kelly
```
**Why:** Kelly sizing maximizes long-term geometric return. But requires accurate win rate / avg win estimates.
**Implementation:** Compute Kelly per setup from `setup_performance` table. Apply to position sizing in execution layer.
#### 5.2 Dynamic Risk Parity (Intraday)
```python
# Adjust position sizing based on current risk
current_risk = portfolio_volatility * correlation_to_market
if current_risk > target_risk:
    reduce_position_sizes(current_risk / target_risk)
```
**Why:** Risk parity ensures consistent risk exposure across positions. Dynamic adjustment adapts to changing correlations.
**Implementation:** Compute rolling portfolio risk. Adjust sizes to maintain target risk.
### ⭐ 6. Execution Optimization
#### 6.1 Perishable Signal Priority Queue
```python
# Execute high-decay signals first
PERISHABLE_PLUGINS = ["LeadLagSetup", "MicrostructureImbalance"]
for plugin in PERISHABLE_PLUGINS:
    result = plugin.compute(windows, timeout_ms=150)
    if result:
        return result  # Early exit on perishable alpha
```
**Why:** Perishable alpha decays in milliseconds. Priority queue captures it before it's gone.
**Implementation:** Categorize plugins by perishability. Execute in priority order.
#### 6.2 Parallel Plugin Execution
```python
# Run independent plugins in parallel
independent_plugins = ["TrendFollowing", "MeanReversion", "MomentumBreakout"]
results = await asyncio.gather(*[
    plugin.compute(windows) for plugin in independent_plugins
])
```
**Why:** Sequential execution takes ~200ms. Parallel execution reduces to ~50ms (max plugin time).
**Implementation:** Identify plugins with no shared mutable state. Execute in parallel with `asyncio.gather`.
#### 6.3 Pre-Computed Regime Authority
```python
# Cache higher-TF regime at service start
_regime_cache = load_regime_from_db()
# Update every 30s instead of per-bar
async def regime_refresh_loop():
    while True:
        await asyncio.sleep(30)
        _regime_cache = load_regime_from_db()
```
**Why:** Regime data doesn't change per-bar. Caching reduces DB load and latency.
**Implementation:** Add regime cache to `signal_generator_service`. Refresh on interval, not per-bar.
#### 6.4 Feature Lookup Skipping
```python
# Only load features needed by each plugin
plugin_features = {
    "TrendFollowing": ["trend_regime", "swing_pattern", "atr_14"],
    "MeanReversion": ["rsi_14", "bb_20_2_mid", "sr_nearest_support"],
}
features = load_features(plugin_features[plugin_name])
```
**Why:** Loading all features for all plugins is wasteful. Selective loading reduces latency.
**Implementation:** Define feature dependencies per plugin. Load only what's needed.
#### 6.5 Batched Redis Publishing
```python
# Accumulate signals for 1s, publish in batch
signal_buffer = []
async def publish_loop():
    while True:
        await asyncio.sleep(1)
        if signal_buffer:
            pipe = redis.pipeline()
            for signal in signal_buffer:
                pipe.xadd(stream_key, signal)
            await pipe.execute()
            signal_buffer.clear()
```
**Why:** Individual xadd calls have latency. Batching amortizes network overhead.
**Implementation:** Add signal buffer to `signal_generator_service`. Flush on interval.
---
## Research Projects
| Project | Priority | Duration | Outcome |
|---------|----------|----------|---------|
| Alpha Decay Rate Analysis | ⭐⭐⭐ | 2 weeks | Half-life per setup |
| Lead-Lag Coefficient Drift | ⭐⭐ | 1 week | Coefficient stability analysis |
| Regime-Specific Weight Optimization | ⭐⭐⭐ | 2 weeks | Optimal weights per regime |
| Orthogonal Factor Extraction | ⭐⭐ | 4 weeks | PCA/ICA factor decomposition |
| Counterfactual Value Analysis | ⭐⭐⭐ | 2 weeks | What-if signal value |
---
## Implementation Priority
### Phase 1: Immediate (Week 1-4)
1. ⭐⭐⭐ **Alpha Decay Rate** — Add to I4, wire into CIS
2. ⭐⭐⭐ **Killzone Acceleration** — Gate signals on killzones
3. ⭐⭐⭐ **Signal Recycling Window** — Prevent clustering
4. ⭐⭐⭐ **Counterfactual Logging** — Enable learning
### Phase 2: Near-Term (Month 2-3)
5. ⭐⭐⭐ **Order Flow Imbalance** — Requires tick data
6. ⭐⭐⭐ **Relative Volume** — Requires SPY stream
7. ⭐⭐⭐ **Regime-Specific Weights** — Load from DB
8. ⭐⭐ **Lead-Lag Architecture** — Requires multi-symbol data
### Phase 3: Long-Term (Month 6+)
9. ⭐⭐⭐ **Orthogonal Decomposition** — Requires 6 months outcomes
10. ⭐⭐ **Adaptive CIS Weights** — Requires outcome data
11. ⭐⭐ **Signal Co-Occurrence** — Requires signal history
12. ⭐ **Kelly Sizing** — TradeAgent integration
---
## Dependencies
| Idea | Requires |
|------|----------|
| Order Flow Imbalance | IBKR tick data with bid/ask size |
| Relative Volume | SPY volume stream |
| Lead-Lag Architecture | ES/NQ/SPY/QQQ parallel streams |
| VIX Term Structure | VIX9D/VIX3M data source |
| Orthogonal Decomposition | 6+ months outcome data |
| Adaptive CIS Weights | 6+ months outcome data |
