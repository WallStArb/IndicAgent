# Comomentum: Cross-Sectional Crowding Metric for Momentum Regimes

**Status**: Idea / Design Exploration
**Created**: 2026-06-27
**Source**: Lou, Dong, and Christopher Polk (2022) - "Comomentum: The Cross-Section of Crowding in Momentum Strategies"

## Quick Reference: Three Approaches

| Approach | Description | Order | Data Source | Speed | Pros | Cons |
|-----------|-------------|-------|-------------|-------|------|------|
| **A. Deconstructed Index** (RECOMMENDED) | 4 primitives from OHLCV (volume flow, return comovement, trade bursts, price-volume divergence) | 1st + 2nd | Raw OHLCV | Daily/intraday | Transparent, testable, measures CAUSE | More complex to build |
| **B. Paper's Comomentum** | Cross-sectional correlation of abnormal returns after factor regression | 3rd | Returns + factors | Daily | Published research, 50-year validation | Slow signal (1-2 year), black-box |
| **C. 13F Flows** (FUTURE) | Direct institutional positioning from SEC filings | Source | 13F-HR XML | Quarterly | SOURCE of crowding (exact holdings) | 45-day lag, quarterly only |

**Recommendation**: Start with Approach A (deconstructed index). If 13F becomes available, use C to calibrate A's thresholds quarterly.

## Problem Statement

Momentum strategies are vulnerable to **crowding-induced crashes**. When institutional investors pile into the same momentum assets simultaneously, correlations spike and returns collapse. This crowding is invisible to standard momentum metrics until reversal occurs.

**Key risk**: Our v3.0 AlphaEngine will train ensemble models on momentum features. If these features become crowded, IC (Information Coefficient) decays and alpha emissions turn toxic — but we won't detect it until after losses materialize.

## Solution Overview

**Comomentum** = cross-sectional correlation of abnormal returns among momentum winners/losers after stripping out market + asset-class effects.

- **Low comomentum** (≤ 20th percentile): Assets moving independently → healthy momentum
- **High comomentum** (≥ 80th percentile): Assets locked in synchronized flow → impending crash (1-2 year horizon)

**Paper findings (1965-2015 equity data)**:
- Quiet period: 0.037 abnormal correlation
- Crowded period: 0.241 abnormal correlation (6.5× higher)
- Forward returns: -12.7% (year 1), -13.0% (year 2) vs quiet periods
- Volatility spike: -1% days jump from 8.4% → 22.5%

## Technical Approach

### Step 1: Compute Per-Bar Comomentum

For each time bucket across our 58 ETF universe:

```python
# Pseudo-code
def compute_comomentum(etf_returns, lookback_days=252):
    # 1. Rank by past return
    momentum_rank = etf_returns.rolling(lookback_days).mean().rank()
    
    # 2. Identify winners/losers (top/bottom quintile)
    winners = momentum_rank[momentum_rank >= 0.8].index
    losers = momentum_rank[momentum_rank <= 0.2].index
    
    # 3. Regress out market + asset-class effects
    # Market: equal-weight ETF index return
    # Asset-class: equity vs FX vs futures factor loadings
    abnormal_returns = regress_out_factors(etf_returns, factors=[market, asset_class])
    
    # 4. Compute cross-sectional correlation of residuals
    comomentum = abnormal_returns.loc[winners].corr(axis=1).mean()
    
    return comomentum
```

**Output**: Single scalar per time bucket (market-level metric)

### Step 2: Regime Classification

Map comomentum scalar to regime buckets:

```python
# Use historical percentile (rolling 5-year window)
comomentum_percentile = rolling_percentile(comomentum, window=5*252)

if comomentum_percentile >= 80:
    regime = "momentum_crowded"
elif comomentum_percentile >= 60:
    regime = "momentum_transitioning"
elif comomentum_percentile <= 20:
    regime = "momentum_healthy"
else:
    regime = "momentum_neutral"
```

### Step 3: Integration to v3.0 Pipeline

#### Option A: Market Regime Enrichment (RECOMMENDED)

Add comomentum to `market_regimes` table:

```sql
ALTER TABLE market_regimes ADD COLUMN comomentum DOUBLE PRECISION;
ALTER TABLE market_regimes ADD COLUMN comomentum_regime VARCHAR(50);
```

**Benefits**:
- Single source of truth for regime
- Already stratified by VIX × breadth (9 regimes) → add comomentum as 3rd dimension
- ensemble_trainer can read regime + comomentum together

#### Option B: Separate Crowding Table

Create `market_crowding` table (if we want more granular tracking):

```sql
CREATE TABLE market_crowding (
    ts TIMESTAMPTZ NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    comomentum DOUBLE PRECISION,
    comomentum_percentile DOUBLE PRECISION,
    comomentum_regime VARCHAR(50),
    PRIMARY KEY (ts, timeframe)
);
```

**Use case**: If we want to track crowding as independent from VIX/breadth regimes.

## Integration Points

### 1. ensemble_trainer (Phase 141)

**Current behavior**: Trains on all feature_vectors, stratified by market_regimes (9 labels)

**Enhanced behavior**:
```python
# Load regime + comomentum
regime = market_regimes.loc[ts]
comomentum_regime = regime.comomentum_regime

# Filter training data
if comomentum_regime == "momentum_crowded":
    # Suppress momentum features, upweight mean-reversion
    features = [f for f in features if "momentum" not in f.name]
    features.extend([f for f in all_features if "mean_reversion" in f.name])
elif comomentum_regime == "momentum_healthy":
    # Full momentum usage
    features = all_features
```

**Validation**: Measure IC decay by comomentum quartile
- Plot: IC vs comomentum_percentile
- Expect: IC collapses when comomentum ≥ 80th

### 2. Alpha Event Tagging

Tag `alpha_events` with comomentum level:

```sql
ALTER TABLE alpha_events ADD COLUMN comomentum_regime VARCHAR(50);
```

**Backtest value**: Can slice performance by comomentum regime
- "What's our Sharpe when momentum is healthy vs crowded?"
- Detect if ensemble auto-suppresses crowding risk

### 3. Dashboard (Future)

Regime panel showing:
- Comomentum gauge (current value vs percentile)
- Historical comomentum chart (past 5 years)
- Momentum regime status (healthy/neutral/transitioning/crowded)

## Validation Strategy

### Phase 1: Diagnostic Compute

Run comomentum on historical data (5m/15m/1h/1d) across ETF universe:

```python
# production/scripts/comomentum_diagnostic.py
for timeframe in ['5m', '15m', '1h', '1d']:
    df = load_feature_vectors(timeframe)
    comom = compute_comomentum(df)
    save_timeseries(f"comomentum_{timeframe}.csv", comom)
```

**Output**: 
- 4 CSV files with historical comomentum series
- Percentile distributions per timeframe
- Correlation heatmap (comomentum vs VIX vs breadth)

### Phase 2: Regime Filter Backtest

Test ensemble behavior with/without comomentum filter:

| Model | Comomentum Filter | Expected IC | Expected Sharpe |
|-------|-------------------|-------------|-----------------|
| Baseline | None | Baseline | Baseline |
| Suppressed | Exclude momentum when crowded | Higher (exclude toxic periods) | Higher |
| Full | Always include momentum | Lower (include toxic periods) | Lower |

**Success criterion**: Suppressed model shows ≥10% IC improvement when comomentum ≥ 80th

### Phase 3: Production Integration

1. Add computation to corpus pipeline step 2 (regime_writer)
2. Add column to market_regimes
3. Update ensemble_trainer to read comomentum_regime
4. Monitor IC by comomentum quartile in Grafana

## Open Questions

### Q1: Lookback Window Calibration

**Paper**: 12-month momentum ranking  
**Our system**: Multi-timeframe (5m/15m/1h/1d) with varying depths

**Options**:
- **Fixed 252 trading days**: Standard, but what about 5m TF (no 252-day history)?
- **Timeframe-relative**: Use `lookback = 100 * bars_per_year` (100 bars for 1d, ~5000 bars for 5m)
- **Adaptive**: Shorter lookback for shorter TFs (e.g., 1 month for 5m, 12 months for 1d)

**Recommendation**: Start with timeframe-relative lookback; validate against paper's 12-month results on 1d TF.

### Q2: Asset-Class Factor Model

**Paper**: Regresses out Fama-French 3 factors + industry effects  
**Our universe**: 58 ETFs across equities, futures, FX

**Challenge**: How to model "asset-class effects"?

**Options**:
- **Simple**: Equal-weight market return only (ignore asset-class)
- **Factor model**: 3 factors = market_return + equity_beta + fx_beta (estimated from rolling regression)
- **PCA-based**: First 3 PCs of ETF return matrix as factors

**Recommendation**: Start with simple (market only); add sophistication if signal is weak.

### Q3: Threshold Calibration

**Paper**: 80th percentile = "crowded"  
**Our universe**: 58 ETFs vs thousands of stocks

**Question**: Is 80th percentile too aggressive/conservative for ETFs?

**Validation**: After computing historical series, plot:
- Comomentum distribution → identify natural breakpoints
- Forward momentum returns by comomentum decile → find decay point

**Fallback**: Start with 80th; adjust based on ETF-specific data.

### Q4: Computational Cost

**Per-bar operation**:
- Cross-sectional regression across 58 ETFs
- Correlation matrix computation (58×58 → trivial)

**Cost estimate**: Negligible (<10ms per bar)

**Where to compute**: 
- **Option 1**: regime_writer (after regime classification) — minimal overhead
- **Option 2**: Separate batch job (computation_agent.py) — if we want independent lifecycle

**Recommendation**: regime_writer extension — already processes market_regimes per TF.

### Q5: ETF Universe Suitability

**Paper**: High institutional ownership stocks only  
**Our universe**: 58 ETFs (core holdings for institutions)

**Concern**: Are ETFs "crowded" in the same way stocks are?

**Evidence for suitability**:
- ETFs are primary vehicle for institutional momentum exposure
- Flows into ETFs are highly correlated (e.g., SPY + QQQ + IWM move together)
- Crowding manifests as synchronized factor bets, not single-stock picking

**Risk**: ETF dynamics may differ from single-stock crowding. Must validate empirically.

## Risks & Limitations

### 1. Slow Signal Horizon

**Paper**: 1-2 year forward window  
**Our system**: Multi-timeframe (intraday to daily)

**Problem**: Comomentum is useless for high-frequency timing

**Mitigation**:
- Use as **regime filter**, not trading signal
- Exclude momentum features when crowded (long-term bias adjustment)
- Do NOT use for intraday timing

### 2. Sparse History

**Challenge**: Our historical data:
- 5m: 5 years
- 15m: 10 years
- 1h: 15 years
- 1d: 20 years

**Problem**: Small sample for "crowded → crash" validation (paper has 50 years)

**Mitigation**: 
- Cross-timeframe validation (does 5m comomentum predict 15m crashes?)
- Bootstrap confidence intervals around IC estimates
- Flag as "high variance" metric until more data accumulates

### 3. Regime Overfitting

**Risk**: Adding comomentum regime → 9 × 4 = 36 regime buckets (VIX × breadth × comomentum)

**Problem**: Sparse data per regime → unstable IC estimates

**Mitigation**:
- Start with **binary flag** (crowded vs not crowded)
- Only add multi-bucket regime if data supports it
- ensemble_trainer applies Bayesian shrinkage across regimes

### 4. Factor Model Misspecification

**Risk**: Wrong asset-class factors → noisy comomentum estimates

**Mitigation**:
- Start simple (market factor only)
- A/B test different factor specifications
- Monitor comomentum stability (should evolve slowly, not jump around)

## Renaissance Framework Assessment

### Signal Grade

**Overall Grade: B- for risk management, D for alpha generation**

Comomentum is a **negative signal** (what NOT to trade) rather than a positive alpha generator (what TO trade). It addresses a real failure mode (momentum crashes) but operates on a timescale (1-2 years) that mismatches our trading horizons (intraday to daily).

**What Renaissance would ask:**
1. What causes crowding? → Institutional flows
2. Why not measure flows directly? → We don't have flow data
3. Why not trade the reversal? → Signal is too slow
4. What's the mechanism? → Sociological, not structural

### Alternative: Deconstructed Crowding Index (Primitive-Based)

**Renaissance approach**: Measure the CAUSE (flows), not the SYMPTOM (correlation).

Instead of third-order comomentum (regression → correlation → classification), build first/second-order primitives from raw OHLCV:

#### Component 1: Volume Flow Synchronization

```python
# Per symbol per bar (first-order)
volume_z = (volume - rolling_mean(volume, 20)) / rolling_std(volume, 20)

# Cross-sectional correlation (second-order)
volume_flow_correlation = correlation_matrix(volume_z).mean()
```

**Measures**: Are volume spikes synchronized across ETFs? (direct flow signal)

**Expected signal**:
- Low crowding: volume spikes random (low correlation)
- High crowding: volume spikes synchronized (high correlation)

#### Component 2: Return Comovement Index

```python
# Per symbol per bar (first-order)
return_raw = close / close_lag(1) - 1

# Market return (equal-weight ETF index)
market_return = mean(return_raw)

# Abnormal return (second-order)
return_abnormal = return_raw - beta * market_return

# Cross-sectional comovement (third-order, but simpler factor model)
return_comovement = correlation(return_abnormal).mean()
```

**Measures**: Are prices moving together beyond market factor? (simplified vs paper's full factor model)

#### Component 3: Trade Burst Correlation

```python
# Per symbol per bar (first-order)
trade_count_z = (trade_count - rolling_mean(trade_count, 20)) / rolling_std(trade_count, 20)

# Cross-sectional correlation (second-order)
trade_burst_correlation = correlation(trade_count_z).mean()
```

**Measures**: Is trading activity synchronized? (burst detection)

#### Component 4: Volume-Price Divergence

```python
# Per symbol (first-order)
price_momentum = (close / close_lag(20) - 1).zscore()
volume_momentum = (volume.sum(20) / volume.sum(20).lag(20) - 1).zscore()

# Divergence (second-order)
divergence = abs(price_momentum - volume_momentum)

# Cross-sectional average
price_volume_divergence = mean(divergence)
```

**Measures**: Are prices moving without volume justification? (fragility indicator)

#### Composite Crowding Index

```python
crowding_index = (
    0.30 * volume_flow_correlation +      # Flow synchronization
    0.30 * return_comovement +             # Price lockstep
    0.20 * trade_burst_correlation +      # Activity synchronization
    0.20 * price_volume_divergence         # Fragility
)

# Regime classification
if crowding_index >= 80th_percentile:
    regime = "crowded"
elif crowding_index <= 20th_percentile:
    regime = "uncrowded"
else:
    regime = "normal"
```

**Why This Is Renaissance-Grade:**

| Dimension | Paper (Comomentum) | Deconstructed Index |
|-----------|-------------------|-------------------|
| Order | 3rd (regression → correlation) | 1st + 2nd (raw → correlation) |
| Measures | Symptom (correlation) | Cause (flow synchronization) |
| Speed | Slow (1-2 year horizon) | Faster (intraday detection) |
| Transparency | Black-box metric | 4 interpretable components |
| Data required | Returns + factor model | OHLCV only |
| Testability | Single metric | 4 independent primitives |
| Failure mode | Metric fails = zero signal | One component fails, others still work |

**Implementation**: Add 4 primitives to feature_factory, compute crowding_index in regime_writer, validate each component independently in Phase 0.

## Primitive Feature Specifications

### Feature Factory Integration

The following features would be added to `src/intelligence/feature_factory.py` as first/second-order primitives. Each is computed **per-symbol per-bar**, then aggregated cross-sectionally for crowding detection.

### Feature 1: Volume Synchronization Z-Score

**Feature name**: `volume_sync_z`

**Concept**: Measure how much this symbol's volume is moving with the crowd

**Computation** (per-symbol per-bar):

```python
def compute_volume_sync_z(
    volume: np.ndarray,
    market_volume_z: np.ndarray,  # Cross-sectional average at this bar
    window: int = 20
) -> float:
    """
    Volume synchronization z-score.

    High = this symbol's volume spiking when market volume is spiking (crowding)
    Low = this symbol's volume is idiosyncratic (uncrowded)
    """
    # This symbol's volume z-score
    volume_z = (volume - rolling_mean(volume, window)) / rolling_std(volume, window)

    # Correlation with market volume_z over recent window
    correlation = rolling_corr(volume_z, market_volume_z, window=window)

    return correlation
```

**Cross-sectional aggregation** (market-wide metric):

```python
# In regime_writer (per time bucket)
volume_flow_correlation = mean([volume_sync_z for symbol in etf_universe])
```

**APR parameters**:
- `alpha.crowding.volume_sync_window = 20` (lookback for z-score and correlation)

**Column name in feature_vectors**: `volume_sync_z`

**Expected IC behavior**:
- Positive IC in uncrowded regimes (volume leads price)
- Negative IC in crowded regimes (volume spikes are synchronized, less informative)

### Feature 2: Abnormal Return Residual

**Feature name**: `return_abnormal_resid`

**Concept**: Return after removing market factor (is this symbol moving on its own?)

**Computation** (per-symbol per-bar):

```python
def compute_return_abnormal_resid(
    close: np.ndarray,
    market_return: float,  # Equal-weight ETF index return at this bar
    beta_window: int = 252  # 1 year for beta estimation
) -> float:
    """
    Abnormal return residual (market-adjusted return).

    High = this symbol is outperforming market (idiosyncratic alpha)
    Low = this symbol is underperforming (idiosyncratic drag)
    Near zero = moving with market (beta exposure)
    """
    # This symbol's return
    symbol_return = close[-1] / close[-2] - 1

    # Estimate beta from recent history (rolling regression)
    # beta = Cov(symbol_return, market_return) / Var(market_return)
    recent_symbol_returns = close[-beta_window:] / close[-beta_window-1:-1] - 1
    recent_market_returns = market_return_history[-beta_window:]

    beta = rolling_cov(recent_symbol_returns, recent_market_returns) / rolling_var(recent_market_returns)

    # Abnormal return = residual after removing market effect
    abnormal_return = symbol_return - beta * market_return

    return abnormal_return
```

**Cross-sectional aggregation** (market-wide metric):

```python
# In regime_writer (per time bucket)
abnormal_returns = [return_abnormal_resid for symbol in etf_universe]
return_comovement = correlation_matrix(abnormal_returns).mean()
```

**APR parameters**:
- `alpha.crowding.beta_window = 252` (1 year beta estimation)
- `alpha.crowding.beta_update_freq = 20` (re-estimate beta every 20 bars)

**Column name in feature_vectors**: `return_abnormal_resid`

**Expected IC behavior**:
- Positive IC when comovement is low (idiosyncratic returns signal alpha)
- Negative IC when comovement is high (synchronized moves = crowding)

### Feature 3: Trade Burst Z-Score

**Feature name**: `trade_burst_z`

**Concept**: Is trading activity spiking beyond normal variance?

**Computation** (per-symbol per-bar):

```python
def compute_trade_burst_z(
    trade_count: np.ndarray,
    window: int = 20
) -> float:
    """
    Trade burst z-score (activity synchronization).

    High = unusual trading activity (potential institutional flow)
    Low = normal trading activity (retail flow)
    """
    # Trade count z-score
    trade_z = (trade_count[-1] - mean(trade_count[-window:])) / std(trade_count[-window:])

    return trade_z
```

**Cross-sectional aggregation** (market-wide metric):

```python
# In regime_writer (per time bucket)
trade_bursts = [trade_burst_z for symbol in etf_universe]
trade_burst_correlation = correlation_matrix(trade_bursts).mean()
```

**APR parameters**:
- `alpha.crowding.trade_burst_window = 20` (lookback for z-score)

**Column name in feature_vectors**: `trade_burst_z`

**Expected IC behavior**:
- Positive IC when bursts are idiosyncratic (symbol-specific news)
- Negative IC when bursts are synchronized (market-wide institutional flow)

### Feature 4: Volume-Price Divergence

**Feature name**: `volume_price_divergence`

**Concept**: Are prices moving without volume confirmation? (fragility indicator)

**Computation** (per-symbol per-bar):

```python
def compute_volume_price_divergence(
    close: np.ndarray,
    volume: np.ndarray,
    price_window: int = 20,
    volume_window: int = 20
) -> float:
    """
    Volume-price divergence (fragility metric).

    High = price moving without volume confirmation (fragile move)
    Low = price and volume aligned (sustainable move)
    """
    # Price momentum z-score
    price_mom = (close[-1] / close[-price_window] - 1)
    price_mom_z = (price_mom - rolling_mean(price_mom, volume_window)) / rolling_std(price_mom, volume_window)

    # Volume momentum z-score
    vol_mom = sum(volume[-volume_window:]) / sum(volume[-volume_window*2:-volume_window]) - 1
    vol_mom_z = (vol_mom - rolling_mean(vol_mom, volume_window)) / rolling_std(vol_mom, volume_window)

    # Divergence = absolute difference
    divergence = abs(price_mom_z - vol_mom_z)

    return divergence
```

**Cross-sectional aggregation** (market-wide metric):

```python
# In regime_writer (per time bucket)
divergences = [volume_price_divergence for symbol in etf_universe]
price_volume_divergence = mean(divergences)
```

**APR parameters**:
- `alpha.crowding.price_momentum_window = 20` (price momentum lookback)
- `alpha.crowding.volume_momentum_window = 20` (volume momentum lookback)

**Column name in feature_vectors**: `volume_price_divergence`

**Expected IC behavior**:
- Positive IC when divergence is low (price+volume aligned = sustainable)
- Negative IC when divergence is high (fragile moves = crowding unwind risk)

### Feature 5: Cross-Sectional Correlation Rank

**Feature name**: `cross_section_corr_rank`

**Concept**: Where does this symbol sit in the correlation hierarchy? (leader vs follower)

**Computation** (per-symbol per-bar):

```python
def compute_cross_section_corr_rank(
    symbol_returns: np.ndarray,
    all_symbol_returns: Dict[str, np.ndarray],  # All ETFs at this bar
    window: int = 20
) -> float:
    """
    Cross-sectional correlation rank (centrality metric).

    High = this symbol is highly correlated with others (central to crowd)
    Low = this symbol is idiosyncratic (independent of crowd)
    """
    # Compute rolling correlation with every other symbol
    correlations = []
    for other_symbol, other_returns in all_symbol_returns.items():
        if other_symbol != self.symbol:
            corr = rolling_corr(symbol_returns[-window:], other_returns[-window:], window=window)
            correlations.append(corr)

    # Average correlation (centrality)
    avg_correlation = mean(correlations)

    # Rank within cross-section
    all_avg_correlations = [compute_cross_section_corr_rank(s, all_symbol_returns) for s in symbols]
    rank = percentileofscore(all_avg_correlations, avg_correlation)

    return rank / 100  # Normalize to 0-1
```

**Cross-sectional aggregation** (market-wide metric):

```python
# In regime_writer (per time bucket)
# NOT AGGREGATED — this is the per-symbol metric itself
# Use: "Top 20% of symbols by cross_section_corr_rank = crowded leaders"
```

**APR parameters**:
- `alpha.crowding.correlation_window = 20` (lookback for correlation)

**Column name in feature_vectors**: `cross_section_corr_rank`

**Expected IC behavior**:
- Negative IC for high-rank symbols (crowded leaders = toxic)
- Positive IC for low-rank symbols (independent symbols = alpha)

### Feature 6: Market Beta Deviation

**Feature name**: `beta_deviation`

**Concept**: Is this symbol's beta behaving normally? (detects abnormal correlation)

**Computation** (per-symbol per-bar):

```python
def compute_beta_deviation(
    close: np.ndarray,
    market_return: float,
    historical_beta: float,  # Long-term average beta
    beta_window: int = 20
) -> float:
    """
    Beta deviation (abnormal correlation metric).

    High = current beta ≠ historical beta (unusual correlation)
    Low = current beta ≈ historical beta (normal correlation)
    """
    # Current beta (from recent window)
    symbol_return = close[-1] / close[-2] - 1
    recent_returns = close[-beta_window:] / close[-beta_window-1:-1] - 1
    recent_market_returns = market_return_history[-beta_window:]

    current_beta = rolling_cov(recent_returns, recent_market_returns) / rolling_var(recent_market_returns)

    # Deviation from historical
    deviation = abs(current_beta - historical_beta) / historical_beta

    return deviation
```

**Cross-sectional aggregation** (market-wide metric):

```python
# In regime_writer (per time bucket)
beta_deviations = [beta_deviation for symbol in etf_universe]
avg_beta_deviation = mean(beta_deviations)
```

**APR parameters**:
- `alpha.crowding.beta_window = 20` (current beta estimation window)

**Column name in feature_vectors**: `beta_deviation`

**Expected IC behavior**:
- Negative IC when beta deviation is high (unusual correlation = crowding)
- Positive IC when beta deviation is low (normal correlation = healthy)

## Feature Summary Table

| Feature | Order | Input | Output | IC Behavior (Crowded) | IC Behavior (Uncrowded) |
|---------|-------|-------|--------|----------------------|----------------------|
| `volume_sync_z` | 2nd | volume + market_volume_z | correlation | Negative (synchronized flow) | Positive (symbol-specific flow) |
| `return_abnormal_resid` | 2nd | close + market_return | residual | Negative (synchronized moves) | Positive (idiosyncratic alpha) |
| `trade_burst_z` | 1st | trade_count | z-score | Negative (synchronized bursts) | Positive (symbol-specific activity) |
| `volume_price_divergence` | 2nd | close + volume | divergence | Negative (fragile moves) | Positive (sustainable moves) |
| `cross_section_corr_rank` | 2nd | returns + all_returns | percentile | Negative (crowded leaders) | Positive (independent symbols) |
| `beta_deviation` | 2nd | close + market_return + beta | deviation | Negative (abnormal correlation) | Positive (normal correlation) |

## Composite Crowding Index (Final)

```python
# In regime_writer (per time bucket)
def compute_crowding_index(
    volume_sync_z: float,      # From cross-sectional aggregation
    return_comovement: float,  # From correlation of return_abnormal_resid
    trade_burst_corr: float,   # From correlation of trade_burst_z
    price_vol_div: float,      # From mean of volume_price_divergence
    # Weights from APR
    w_volume: float = ConfigService.get("alpha.crowding.w_volume", 0.25),
    w_return: float = ConfigService.get("alpha.crowding.w_return", 0.25),
    w_trade: float = ConfigService.get("alpha.crowding.w_trade", 0.20),
    w_div: float = ConfigService.get("alpha.crowding.w_div", 0.30)
) -> float:
    """
    Composite crowding index (0-100 scale).
    """
    crowding = (
        w_volume * volume_sync_z +
        w_return * return_comovement +
        w_trade * trade_burst_corr +
        w_div * price_vol_div
    )

    # Normalize to 0-100 (using historical percentile)
    percentile = rolling_percentile(crowding, window=5*252)

    return percentile
```

**APR parameters** (weights):
- `alpha.crowding.w_volume = 0.25` (volume flow synchronization)
- `alpha.crowding.w_return = 0.25` (return comovement)
- `alpha.crowding.w_trade = 0.20` (trade burst correlation)
- `alpha.crowding.w_div = 0.30` (volume-price divergence)

**Regime classification**:
- `crowding_index >= 80`: "crowded" → suppress momentum features
- `crowding_index <= 20`: "uncrowded" → full momentum usage
- Else: "normal" → baseline behavior

### Critical Issues

**1. Signal Speed Mismatch**
- Paper: 1-2 year forward window
- Our system: Multi-timeframe (5m to 1d)
- **Problem**: A "don't trade momentum for 18 months" signal is useless at our timeframes

**2. Publication Decay Risk**
- Paper published 2022, widely cited
- If edge is real, why hasn't it been arbitraged away?
- Either: (a) effect size is too small to matter after costs, or (b) we're slower than everyone else

**3. Sample Size Problem**
- Paper: 50 years × thousands of stocks
- Us: 5-20 years × 58 ETFs
- **Problem**: High variance in estimates — we're running on noisy data

**4. Wrong Microstructure**
- Paper studies single stocks (high turnover, thousands of names)
- We're ETFs (different flow dynamics, lower turnover, 58 instruments)
- **Risk**: ETF crowding may not manifest the same way as single-stock crowding

**5. It's a Dashboard Widget, Not a Trading Signal**
- Value is in operator awareness ("momentum is crowded")
- Not in automated execution ("suppress momentum for 18 months")
- Renaissance would classify this as **monitoring, not alpha**

### Architectural Fit

**Not a primitive feature.** Feature classification (v3.0):

```
Tier 1: Raw primitives (OHLCV)
Tier 2: First-order transforms (returns, momentum, volatility)
Tier 3: Second-order composites (regime labels, IC scores)
```

Comomentum requires:
1. Historical momentum rankings (12-month lookback)
2. Factor regression (market + asset-class effects)
3. Cross-sectional correlation computation

**This is a third-order composite by construction.**

**Where it actually belongs:**
- ✅ `market_regimes` table (as proposed) — market-state indicator
- ✅ Dashboard — operator awareness widget
- ✅ Risk management layer (future work) — portfolio construction filter
- ❌ `feature_vectors` — not primitive, not per-symbol
- ❌ Alpha signals — too slow, negative signal only

### Renaissance Alternative Approaches

If Renaissance were solving the "crowding kills momentum" problem, they'd:

1. **Measure the underlying cause directly**
   - Get flow data (ETF creations/redemptions, 13F holdings)
   - Track order book imbalances (depth, spread widening)
   - Monitor institutional positioning changes

2. **Trade the microstructure, not the regime**
   - Detect crowding in real-time (order book stress signals)
   - Trade the unwinding (short crowded names, hedge with alternatives)
   - Exit before the crash, not 18 months before

3. **Build alpha that's robust to crowding**
   - Mean-reversion features that activate when momentum decays
   - Cross-asset momentum (uncorrelated streams)
   - Adaptive ensemble that downweights crowding-sensitive models automatically

### Alternative Data Source: 13F Holdings (Institutional Flows)

**Ultimate crowding measure**: Direct observation of institutional positioning.

**What 13F filings provide:**
- **Source**: SEC EDGARA (13F-HR quarterly filings)
- **Frequency**: Quarterly (45 days after quarter end)
- **Data**: Fund positions (ticker, shares, market value, portfolio weight)
- **Coverage**: Institutions with >$100M AUM (most hedge funds, RIAs, ETF providers)

**Why this is the SOURCE of crowding:**
- Comomentum detects synchronized price movement (symptom)
- 13F shows WHO is crowded and WHAT they're holding (cause)
- Flow analysis: "Did 50 funds suddenly pile into QQQ last quarter?"

**How it would work in v3.0:**

```python
# 13F ingestion pipeline (separate from feature_factory)
# production/services/filings_ingester.py

class FilingsIngester(BaseDaemon):
    """Ingest 13F-HR filings from SEC EDGAR, compute flow metrics."""
    
    def process_filing(self, filing_xml):
        # Parse XML → extract holdings
        holdings = parse_13f(filing_xml)
        
        # Compute flow metrics
        new_positions = holdings.q1 - holdings.q0  # Entries
        exited_positions = holdings.q0 - holdings.q1  # Exits
        weight_changes = holdings.weight.q1 - holdings.weight.q0
        
        # Crowding metric: % of funds holding same asset
        crowding_score = count_funds_holding(ticker) / total_funds
        
        # Flow synchronization: correlation of weight changes across ETFs
        flow_correlation = correlation(weight_changes across ETFs)
        
        # Write to database
        write_institutional_positions(holdings)
        write_flow_metrics(flow_correlation, crowding_score)
```

**Database schema:**

```sql
-- Institutional positions (quarterly snapshot)
CREATE TABLE institutional_positions (
    filing_id VARCHAR(50) PRIMARY KEY,
    fund_name VARCHAR(200),
    filing_date DATE,
    ticker VARCHAR(20),
    shares BIGINT,
    market_value DOUBLE PRECISION,
    portfolio_weight DOUBLE PRECISION,
    CONSTRAINT fk_filing FOREIGN KEY (filing_id) REFERENCES filings(filing_id)
);

-- Flow metrics (quarterly, aggregated per ETF)
CREATE TABLE institutional_flows (
    quarter DATE NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    funds_holding INTEGER,
    crowding_percentile DOUBLE PRECISION,
    avg_weight_change DOUBLE PRECISION,
    flow_correlation DOUBLE PRECISION,
    PRIMARY KEY (quarter, ticker)
);

-- Link to feature vectors (for backtest)
ALTER TABLE feature_vectors ADD COLUMN institutional_crowding DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN institutional_flow_score DOUBLE PRECISION;
```

**Use cases:**

1. **Direct crowding detection**: `institutional_crowding` = % of funds holding ETF
2. **Flow momentum**: `institutional_flow_score` = correlation of weight changes
3. **Positioning extremes**: "90th percentile ownership → overcrowded"

**Integration with ensemble_trainer:**

```python
# Load institutional data (left-join to feature_vectors)
crowding = load_institutional_crowding(ts, symbol)

if crowding >= 90th_percentile:
    # Suppress momentum (institutionally crowded)
    features = exclude_momentum_features(features)
else:
    # Full momentum
    features = all_features
```

**Why this is quantitative, NOT qualitative:**

- **Qualitative** = News, narrative, sentiment (soft data, NLP required)
- **Quantitative** = Holdings, weights, flows (hard data, exact numbers)

13F data is **hard quantitative data** — positions, weights, timestamps. No NLP, no sentiment analysis, no interpretation. Pure math.

**Advantages over comomentum:**

| Dimension | Comomentum | 13F Flows |
|-----------|-----------|-----------|
| Data source | Price/volume (derived) | Holdings (source) |
| Frequency | Daily/real-time | Quarterly |
| Lag | Real-time | 45-day delay |
| Precision | Correlation metric | Exact positions |
| Causality | Symptom detection | Direct observation |
| Coverage | 58 ETFs | Entire market (stocks + ETFs) |

**Disadvantages:**
- **45-day lag**: Q1 2025 filed May 15, 2025 — not real-time
- **Quarterly granularity**: Can't see intramonth flow changes
- **Coverage gaps**: Small funds (<$100M AUM) don't file
- **SPC/AUM complexity**: Need to account for separate account vs fund holdings

**Hybrid approach:**

Use 13F for **regime calibration** (quarterly baseline) + deconstructed index for **real-time detection** (daily/intraday):

```python
# Quarterly: Calibrate thresholds
baseline_crowding = load_13f_crowding(quarter='2025-Q1')
crowding_threshold_80th = baseline_crowding.quantile(0.80)

# Daily: Detect when we exceed baseline
if daily_crowding_index >= crowding_threshold_80th:
    regime = "crowded"
else:
    regime = "normal"
```

**Implementation roadmap:**

1. **Phase 0**: Feasibility study (1 week)
   - Download sample 13F-HR filings (SEC EDGAR)
   - Parse XML → validate data quality
   - Compute crowding metrics manually
   - Check: Does 13F crowding predict momentum crashes?

2. **Phase 1**: Ingestion pipeline (2-3 weeks)
   - Build `filings_ingester` daemon
   - Database schema (institutional_positions, institutional_flows)
   - Backfill historical filings (SEC has full archive)

3. **Phase 2**: Integration (1-2 weeks)
   - Link to feature_vectors (left-join crowding score)
   - Update ensemble_trainer to read institutional_crowding
   - Backtest: Does 13F-based filter improve IC?

4. **Phase 3**: Real-time calibration (1 week)
   - Use 13F baselines to calibrate daily crowding index
   - Dashboard: Show both 13F (quarterly) + daily index

**Dependencies:**
- SEC EDGAR API access (free, public)
- XML parsing library
- Database storage (backfill = 10+ years of filings)
- Validation against known fund holdings (cross-check)

### Recommendation

**Don't integrate into feature_factory. Use as diagnostic.**

**Phase 0 decision gate:**
1. Run diagnostic script on 1d timeframe
2. Measure effect size: Does IC actually collapse when crowded?
3. Check statistical significance: Is signal real or noise given our sample?

**If validation shows strong signal:**
- Add to `market_regimes.comomentum` (market-state table, not feature vectors)
- Use for regime-aware validation (IC by comomentum bucket)
- Consider ensemble regime filter ONLY if backtest proves value

**If validation shows weak signal:**
- Dashboard widget only (operator awareness)
- No automated integration
- Document as "inconclusive for ETF universe"

**Renaissance principle**: Empirical over theoretical. Run the diagnostic, measure the effect, then decide. Don't build it because it sounds clever — build it because the data shows it works.

## Implementation Roadmap

### Approach A: Deconstructed Crowding Index (RECOMMENDED)

**Rationale**: First/second-order primitives from OHLCV, transparent, testable components, faster signal.

#### Phase 0: Primitive Validation (1-2 days)
- [ ] Add 4 primitives to feature_factory:
  - `volume_flow_correlation`
  - `return_comovement`
  - `trade_burst_correlation`
  - `price_volume_divergence`
- [ ] Compute historical series (1d timeframe, 20y data)
- [ ] Validate each component independently:
  - Plot IC decay by regime (top 20% vs bottom 20%)
  - Check: IC should be lower when metric is high
  - Bootstrap confidence intervals

**Success criterion**: ≥2 components show statistically significant IC decay

#### Phase 1: Composite Build (1-2 days)
- [ ] Build composite `crowding_index` (weighted sum of 4 components)
- [ ] Add to `market_regimes` table (`crowding_index`, `crowding_regime`)
- [ ] Extend `regime_writer` to compute crowding per TF

#### Phase 2: Validation (2-3 days)
- [ ] Backtest ensemble with/without crowding filter
- [ ] Measure IC improvement when suppressing momentum in crowded regime
- [ ] Compare: Deconstructed index vs paper's comomentum (which works better?)

**Success criterion**: ≥5% IC improvement + statistical significance

#### Phase 3: Production (1 day)
- [ ] Update ensemble_trainer to read `crowding_regime`
- [ ] Add crowding monitoring to Grafana
- [ ] Dashboard: Show each component + composite index

### Approach B: Paper's Comomentum (Alternative)

**Rationale**: Direct replication of published research, validated on 50 years of equity data.

#### Phase 0: Feasibility (1 day)
- [ ] Create diagnostic script (`comomentum_diagnostic.py`)
- [ ] Run on 1d timeframe (20y data) → validate vs paper results
- [ ] Visualize comomentum distribution + forward momentum IC

### Phase 1: Integration (2-3 days)
- [ ] Extend `regime_writer` to compute comomentum per TF
- [ ] Migration: add `comomentum` + `comomentum_regime` to market_regimes
- [ ] Update corpus pipeline to write comomentum

### Phase 2: Validation (3-5 days)
- [ ] Backtest ensemble with/without comomentum filter
- [ ] Measure IC decay by comomentum quartile
- [ ] Publish validation report (`docs/analysis/comomentum-validation.md`)
- [ ] Compare vs Approach A (deconstructed index)

### Phase 3: Production (1-2 days)
- [ ] Update ensemble_trainer to read comomentum_regime
- [ ] Add comomentum monitoring to Grafana
- [ ] Document parameter regime (`alpha.comomentum.*` APR keys)

### Approach C: 13F Institutional Flows (Future Enhancement)

**Rationale**: Direct observation of institutional positioning (SOURCE of crowding, not symptom).

**Timeline**: Phase 150+ (requires separate ingestion pipeline, not in current scope)

**Prerequisites**:
- SEC EDGAR API access validation
- XML parsing pipeline design
- Database schema for institutional_positions + institutional_flows
- Backfill strategy (10+ years of quarterly filings)

**Hybrid approach** (long-term vision):
- Use 13F quarterly baselines to calibrate daily crowding index thresholds
- Real-time detection (deconstructed index) + quarterly validation (13F flows)
- Dashboard shows both: "We're at 85th percentile crowding vs 13F baseline"

**Status**: Deferred until v3.0 AlphaEngine validated and stable.

## Dependencies

**Blocked by**: None (standalone metric)  
**Blocks**: ensemble_trainer regime-filter enhancement  
**Related**: market_regimes design, IC engine stratification

## References

- **Paper**: Lou, Dong, and Christopher Polk (2022). "Comomentum: The Cross-Section of Crowding in Momentum Strategies"
- **Our system**: `docs/plans/2026-06-20-alphaengine-v1-methodology.md` (IC methodology)
- **Related work**: VIX × breadth regime model (already in market_regimes)

## Next Steps

### Phase 0: Decision Gate (Run First)

**Goal**: Empirical validation before committing to integration

#### Option 1: Deconstructed Index Validation (RECOMMENDED)

1. **Add 4 primitives to feature_factory** (1-2 days)
2. **Compute historical series** on 1d timeframe (20y data)
3. **Validate each component**:
   - Plot IC decay by regime (top 20% vs bottom 20%)
   - Bootstrap confidence intervals
   - Check: ≥2 components show significant IC decay

4. **Make go/no-go decision**:
   - **GO** (≥2 components work): Build composite → Phase 1
   - **NO-GO** (weak signal): Dashboard widget only
   - **HYBRID** (mixed results): Use working components, discard others

#### Option 2: Paper's Comomentum Validation (ALTERNATIVE)

1. **Run diagnostic script** on 1d timeframe (20y data)
   - Compute historical comomentum series
   - Measure effect size: IC decay by comomentum quartile
   - Check statistical significance

2. **Compare vs Option 1**:
   - Which approach shows stronger IC decay?
   - Which is more stable across timeframes?
   - Which is easier to interpret/debug?

3. **Make go/no-go decision**:
   - **GO** (strong signal): Proceed to Phase 1 integration
   - **NO-GO** (weak signal): Dashboard widget only
   - **INCONCLUSIVE** (high variance): Defer until more data

#### Option 3: 13F Feasibility Study (FUTURE)

1. **Download sample 13F-HR filings** from SEC EDGAR (1 day)
2. **Parse XML** → validate data quality
3. **Compute crowding metrics** manually → check predictive power
4. **Decision**: If strong, add to roadmap as Phase 150+

### Success Criteria

**Minimum bar for Phase 1 integration (either approach):**
- IC decay ≥ 5% when metric ≥ 80th percentile (statistically significant)
- Effect direction matches theory (crowded → lower forward returns)
- Signal is stable across multiple timeframes (not just 1d)

**If any criterion fails:** Dashboard widget only, defer to future phase

---

**Outcome if successful**: AlphaEngine becomes self-aware of crowding risk, automatically suppressing momentum features when ETF flows synchronize — preventing the class of crashes that destroyed discretionary momentum funds in 2000/2008/2020.

**Outcome if unsuccessful**: We learn that ETF crowding doesn't manifest like single-stock crowding — valuable negative result, prevents wasted effort on weak signal.

## Appendix: Data Classification

### Is 13F Qualitative or Quantitative?

**13F filings are QUANTITATIVE hard data**, not qualitative.

| Data Type | Examples | Processing | Characteristics |
|-----------|----------|------------|-----------------|
| **Quantitative** | Prices, volumes, holdings, weights | Math, statistics | Exact numbers, precise, objective |
| **Qualitative** | News, sentiment, narrative | NLP, interpretation | Fuzzy, subjective, language-based |

**13F data structure:**
```
<Filing>
  <fundName>Citadel Advisors</fundName>
  <periodOfReport>2025-03-31</periodOfReport>
  <holding>
    <ticker>SPY</ticker>
    <shares>5,000,000</shares>
    <marketValue>2,500,000,000</marketValue>
    <portfolioWeight>0.08</portfolioWeight>
  </holding>
</Filing>
```

This is **exact numerical data** — no NLP required, no sentiment analysis, no interpretation. Pure math.

**Where 13F fits in v3.0 architecture:**

``                    ┌─────────────────────────────────────┐
                    │      v3.0 Intelligence Vectors       │
                    └─────────────────────────────────────┘
                                      │
                    ┌─────────────────┴─────────────────┐
                    │                                   │
         ┌──────────▼──────────┐          ┌──────────▼──────────┐
         │  Feature Factory    │          │  Alternative Data    │
         │  (OHLCV primitives)  │          │  (External sources)  │
         └─────────────────────┘          └─────────────────────┘
                    │                                   │
         ┌──────────┴──────────┐          ┌──────────┴──────────┐
         │ feature_vectors     │          │ institutional_flows  │
         │ (54 per-symbol)      │          │ (quarterly, per-ETF) │
         └─────────────────────┘          └─────────────────────┘
                    │                                   │
                    └─────────────────┬─────────────────┘
                                      │
                              ┌───────▼────────┐
                              │ ensemble_trainer│
                              │                │
                              │ Reads both:    │
                              │ - feature_vec  │
                              │ - inst_flows    │
                              └────────────────┘
```

**Other quantitative external data sources:**
- **SEC filings**: 13F (holdings), 10-K/10-Q (fundamentals), 8-K (events)
- **Government data**: FRED (economic series), CFTC COT (futures positioning)
- **Corporate data**: Earnings releases, shareholder reports
- **Alternative data**: Satellite imagery, credit card transactions, web scraping

**Qualitative intelligence (v3.0 I8 AI layer):**
- News sentiment analysis (NLP)
- Narrative synthesis (LLM-based)
- Event interpretation (subjective)

**Key distinction**: Quantitative data = INPUT to models; qualitative intelligence = INTERPRETATION of context. 13F is input, not interpretation.

**In v3.0 terms**, 13F would be part of the "alternative data" layer feeding into regime awareness, not the "qualitative intelligence" layer (AI agents).
