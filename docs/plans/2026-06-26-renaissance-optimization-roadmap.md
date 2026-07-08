# Renaissance-Grade Optimization Roadmap

**Date:** 2026-06-26  
**Status:** SUPERSEDED 2026-06-27  
**Scope:** IC Engine, Feature Factory, AlphaEngine Architecture  
**Philosophy:** Jim Simons would demand ruthlessly eliminating hidden bias, complexity, and edge-case failures while maximizing alpha per unit of compute

## Disposition (2026-06-27)

| Item | Status | Resolution |
|------|--------|------------|
| IC-001: Overnight gap look-ahead bias | DONE | Phase 140-P0 — `complete_{scale}` flags filter contaminated returns |
| IC-002: Context feature autocorrelation bias | DONE | Phase 140.5-P5 — `context_features` table + `DISTINCT ON` daily observation |
| IC-003: Regime transition contamination | OPEN | Todo 025 — `alpha.ic.regime_purge_bars` purge window |
| PERF-001: IC engine vectorization | OPEN | Todo candidate — post-Phase 141 optimization |
| PERF-002: Incremental FeatureFactory | DEFERRED | Irrelevant until streaming path re-enabled |
| PERF-003: DB round-trip consolidation | DEFERRED | Low impact (~7s); revisit if corpus runtime becomes a blocker |
| ALPHA-001: Feature redundancy audit | PARTIAL | Foundation done (clustering + Feature Registry); audit runs after Phase 141 |
| ALPHA-002: Regime-adaptive lookahead | OPEN | In ROADMAP Phase 143 |
| ALPHA-003: Cross-sectional rank features | OPEN | Todo 026 — columns exist, need batch compute script |
| ALPHA-004: Ensemble weighting beyond IC Sharpe | OPEN | In ROADMAP Phase 144 |
| ARCH-001: APR compile-time binding | OPEN | Todo 028 — load config once at startup, not per-call in hot paths |
| ARCH-002: FeatureFactory.compute/compute_batch unification | OPEN | Todo 029 — eliminate divergence that already caused Phase 140.5-P1 silent-constant bugs |
| ARCH-003: Numba JIT HMM forward-filter (20-50x speedup) | OPEN | Todo 027 — after corpus pipeline stabilizes |
| OBS-001: Rolling IC drift detection | PLANNED | ROADMAP Phase 149B — ICLifecycleMonitor (v3.0a IntegrityMonitor) |
| OBS-002: Feature distribution drift | PLANNED | ROADMAP Phase 149A — DistributionDriftMonitor (v3.0a IntegrityMonitor) |

---

## Executive Summary

This document channels Renaissance Technologies' first principles: **data integrity is paramount, silent wrong answers are worse than loud crashes, and every line of code must justify its existence in alpha or correctness.**

The IC engine optimization (Phase 138) addressed critical correctness bugs (Fisher z-transform CI, HAC Sharpe, walk-forward embargo). However, a Renaissance audit would surface deeper structural issues across the entire v3.0 stack:

1. **Hidden bias risks** that could invalidate IC estimates
2. **Latency inefficiencies** in the compute pipeline  
3. **Alpha leakage** from suboptimal feature/ensemble design
4. **Architectural complexity** that doesn't pull its weight

This roadmap prioritizes by **severity of data-integrity risk**, then by **alpha-per-compute ROI**, then by **maintenance burden**. Each item includes Renaissance-grade rationale and implementation guidance.

---

## Priority 0: Data-Integrity Violations (Fix Immediately)

### IC-001: Forward Return Look-Ahead Bias in Overnight Gaps

**Risk:** `CRITICAL` - Invalidates all IC measurements if present

**Issue:** The forward return formula `ln(open[T+N+1]/open[T+1])` is correct for continuous markets, but ETFs trade nearly 24/7 with microscopic overnight gaps. The formula measures **open-to-open** return, but for 5m/15m/1h timeframes, this includes microscopic overnight gaps that:

1. **Vary by broker** (IBKR snapshot timing vs market open)
2. **Are not tradeable** (you can't consistently capture the 00:01-00:05 UTC move)
3. **Introduce microstructure noise** that inflates measurement error variance

**Renaissance analysis:** "You're measuring noise as signal. The overnight gap for liquid ETFs is 1-2 basis points with 50 bips of variance depending on snapshot timing. This destroys signal-to-noise for short lookaheads."

**Fix:** For intraday TFs (5m/15m/1h), use **close-to-close** returns measured from the **last bar before market close** to the **last bar N periods later**:

```sql
-- For 5m TF with lookahead=5, measure from 16:00 close to 16:00 close 5 bars later
-- This excludes the non-tradeable overnight period
SELECT 
    bar_ts,
    ln(close[LEAD(N)] / close) AS return_close_N  -- close-to-close
FROM market_data_ohlcv
WHERE EXTRACT(HOUR FROM bar_ts) = 16  -- Anchor to daily close
```

For daily TF, keep current `open[T+N+1]/open[T+1]` formula (overnight gaps are meaningful at daily scale).

**Migration:** Phase 140 - Forward Return Formula Fix

**Validation:** Re-run IC engine; expect `ic_sharpe` to increase by 15-30% for intraday TFs due to noise reduction.

---

### IC-002: Context Feature Autocorrelation Bias

**Risk:** `HIGH` - Inflates IC for daily features by 2-5x

**Issue:** Daily-cadence features (`vix_z`, `flight_quality`, `yield_slope_z`) are stored in `context_features` with one value per calendar day. The IC engine uses `DISTINCT ON (DATE(bar_ts))` to pick the earliest intraday bar as the observation.

**Problem:** For 5m ETF data, one calendar day = ~78 bars. The same daily feature value is duplicated 78 times in the feature matrix. When computing IC on 5m bars:

```python
# Current approach: 78 identical rows, each paired with different 5m forward returns
X = [vix_z_day1] * 78  # Same value 78 times
y = [5m_forward_return_1, 5m_forward_return_2, ...]  # Different returns
```

This **artificially inflates sample size**. The true N is the number of **trading days**, not the number of 5m bars. The current approach treats 78 correlated observations as independent, violating the i.i.d. assumption and producing artificially narrow confidence intervals.

**Renaissance analysis:** "You're measuring the same relationship 78 times and calling it 78 independent observations. This is textbook autocorrelation bias. Your t-statistics are inflated by sqrt(78) ≈ 8.8x."

**Fix:** IC engine should compute context feature IC on **daily bars only**, not intraday:

```python
# In ic_engine.py, context feature section:
# Change from: measure IC against intraday returns
# To: aggregate returns to daily, then measure IC

# Compute daily forward returns from intraday
daily_returns = {}
for bar_ts, return_val in intraday_returns:
    date_key = bar_ts.date()
    if date_key not in daily_returns:
        daily_returns[date_key] = []  # Collect all intraday returns for this day
    daily_returns[date_key].append(return_val)

# Aggregate: use the last complete return of the day (16:00 close)
final_daily_returns = {
    date: returns[-1]  # Last return of the day (most liquid)
    for date, returns in daily_returns.items()
}

# Now measure IC: daily feature value vs daily aggregated return
X_daily = [vix_z[day1], vix_z[day2], ...]  # One value per day
y_daily = [final_daily_returns[day1], final_daily_returns[day2], ...]  # One return per day
```

**Migration:** Phase 140.1 - Context Feature Daily Aggregation

**Validation:** After fix, expect context feature IC to **decrease by 40-60%** (true effect size), but `ic_sharpe` to **increase slightly** (more accurate N, less noise). Confidence intervals should widen by 2-3x.

---

### IC-003: Regime Transition Contamination

**Risk:** `MEDIUM` - IC measurements include mislabeled regime transitions

**Issue:** HMM regime labels switch states at discrete boundaries. At the moment of regime change (e.g., ranging → trending), the label is **forward-filtered** but the underlying price dynamics are still transitioning.

**Problem:** Bars immediately following a regime switch are assigned the new regime label but still contain residual dynamics from the old regime. This introduces **label noise** into regime-stratified IC measurements:

- Regime A (trending): IC measured on bars 1-100, but bars 95-100 are still transitioning from A→B
- Regime B (ranging): IC measured on bars 101-200, but bars 101-105 still have trending momentum

**Renaissance analysis:** "Your regime labels are switching faster than the underlying dynamics. You're measuring a transition period as if it were pure regime. This biases IC toward zero (regime misclassification dilutes signal)."

**Fix:** Add a **regime purge window** to IC engine:

```python
# In ic_engine.py, _compute_symbol_tf():
# After regime_label is determined, exclude bars within ±K bars of regime change

regime_transition_bars = 20  # APR: alpha.ic.regime_purge_bars (default 20)

# Find regime change indices
regime_changes = np.where(np.diff(regime_aligned) != 0)[0]

# Build mask excluding transition zones
valid_mask = np.ones(len(regime_aligned), dtype=bool)
for change_idx in regime_changes:
    # Exclude 20 bars before and after each change
    start = max(0, change_idx - regime_transition_bars)
    end = min(len(regime_aligned), change_idx + regime_transition_bars)
    valid_mask[start:end] = False

# Only compute IC on valid_mask == True
X_purged = X_aligned[valid_mask]
returns_purged = returns_aligned[valid_mask]
```

**Trade-off:** Reduces sample size by 5-10%, but increases IC purity. Expect `ic_sharpe` to increase for regime-dependent features (momentum_z, hmma_slope_z) by 10-20%.

**Migration:** Phase 140.2 - Regime Transition Purge

---

## Priority 1: Latency & Compute Efficiency

### PERF-001: IC Engine CPU Vectorization Gaps

**Risk:** `MEDIUM` - Wastes 40-60% of CPU cycles

**Issue:** The IC engine has excellent parallelism (ProcessPoolExecutor, 12 workers), but **per-worker compute** has vectorization gaps:

1. **Rank computation:** `rankdata(X, axis=0)` is called 3x per scale (full IC, walk-forward, rolling windows). scipy `rankdata` is not vectorized across columns.

2. **Rolling window IC:** `_compute_ic_rolling_metrics()` loops over windows manually instead of using stride tricks.

3. **Correlation clustering:** `np.corrcoef(X.T)` computes a full 54×54 matrix but we only need pairwise distances for linkage.

**Renaissance analysis:** "You're doing O(n_features) passes over the data for ranking when one pass would suffice. You're computing a full correlation matrix when you only need distances. This is 1970s code running on 2020s hardware."

**Fix:** Implement vectorized rank and rolling IC:

```python
# 1. Vectorized ranking (O(n) single pass):
def vectorized_rank_axis_0(X: np.ndarray) -> np.ndarray:
    """Rank each column independently. Returns ranks in [1, n]."""
    n = X.shape[0]
    # Lexsort columns: first by value, then by column index
    # This gives a stable sort across columns
    sort_idx = np.lexsort((np.arange(X.shape[1])[None, :].repeat(n, 0), X))
    ranks = np.empty_like(X, dtype=float)
    ranks[sort_idx] = np.arange(1, n + 1).reshape(-1, 1).repeat(X.shape[1], 1)
    return ranks

# 2. Stride-trick rolling IC (O(n_windows) with precomputed ranks):
def rolling_ic_vectorized(
    ranks_X: np.ndarray,  # [n_obs, n_features], pre-ranked
    ranks_y: np.ndarray,  # [n_obs], pre-ranked
    window_size: int
) -> np.ndarray:  # [n_windows, n_features]
    """Compute rolling-window IC via stride tricks."""
    n = len(ranks_y)
    n_windows = n // window_size
    
    # Build strided view: [n_windows, window_size, n_features]
    X_strided = np.lib.stride_tricks.sliding_window_view(
        ranks_X[:n_windows * window_size], 
        window_shape=(window_size,), 
        axis=0
    ).reshape(n_windows, window_size, -1)
    
    y_strided = np.lib.stride_tricks.sliding_window_view(
        ranks_y[:n_windows * window_size],
        window_shape=(window_size,)
    )
    
    # Vectorized Pearson on ranks across all windows
    # X_strided: [n_windows, window_size, n_features]
    # y_strided: [n_windows, window_size]
    mean_X = X_strided.mean(axis=1, keepdims=True)
    mean_y = y_strided.mean(axis=1, keepdims=True)
    
    X_centered = X_strided - mean_X
    y_centered = y_strided - mean_y
    
    cov = (X_centered * y_centered[:, :, None]).sum(axis=1)  # [n_windows, n_features]
    std_X = np.sqrt((X_centered ** 2).sum(axis=1))
    std_y = np.sqrt((y_centered ** 2).sum(axis=1, keepdims=True))
    
    return cov / (std_X * std_y)  # [n_windows, n_features]
```

**Expected speedup:** 3-5x faster IC Sharpe computation per worker. Total IC engine runtime: 45 min → 12 min for full corpus.

**Migration:** Phase 141 - IC Engine Vectorization

---

### PERF-002: Feature Factory Redundant Computations

**Risk:** `LOW-MEDIUM` - 20-30% CPU waste in streaming path

**Issue:** `FeatureFactory.compute()` is called every bar in the streaming path (`IntelligencePipeline`). For each bar, it:

1. Converts `bars` list to numpy arrays (5x array(...) calls)
2. Recomputes series functions from scratch (ATR, momentum z-score, etc.)
3. Re-computes calendar features for every bar

**Problem:** For a sliding window of 500 bars, we rebuild the entire array each time instead of updating incrementally.

**Renaissance analysis:** "You're doing O(n) work to compute one new value when O(1) update would suffice. This is why high-frequency firms use incremental updates rather than full recompute."

**Fix:** Implement incremental FeatureFactory for streaming path:

```python
class IncrementalFeatureFactory:
    """Maintains rolling state, updates incrementally per bar."""
    
    def __init__(self, config: FeatureFactoryConfig):
        self.config = config
        self.closes: deque[float] = deque(maxlen=config.hurst_window)
        self.volumes: deque[float] = deque(maxlen=config.hurst_window)
        # ... other deques
        
        # Precomputed series state
        self.cumsum_close = 0.0
        self.cumsum_close_sq = 0.0
        self.n = 0
        
    def update(self, bar: dict) -> FeatureVector:
        """Update state and compute features in O(1)."""
        close = float(bar["close"])
        volume = float(bar["volume"])
        
        # Update deques
        self.closes.append(close)
        self.volumes.append(volume)
        
        # Incremental cumulative sums
        if self.n >= self.closes.maxlen:
            # Remove oldest value from cumsum
            oldest_close = self.closes[0]
            self.cumsum_close -= oldest_close
            self.cumsum_close_sq -= oldest_close ** 2
            self.n -= 1
        
        self.cumsum_close += close
        self.cumsum_close_sq += close ** 2
        self.n += 1
        
        # Compute z-score incrementally
        mean = self.cumsum_close / self.n
        var = max(self.cumsum_close_sq / self.n - mean ** 2, 0.0)
        std = math.sqrt(var)
        momentum_z = (close - mean) / std if std > 1e-10 else 0.0
        
        # ... rest of features
        return FeatureVector(...)
```

**Trade-off:** Batch path (backfill) should still use `compute_batch()` (full vectorization). Streaming path switches to incremental updates.

**Migration:** Phase 141.1 - Incremental FeatureFactory

**Expected speedup:** 5-10x faster feature computation in streaming path (enables sub-10ms per bar latency budget).

---

### PERF-003: Database Round-Trip Elimination

**Risk:** `LOW` - Marginal latency impact, but unnecessary complexity

**Issue:** IC engine workers perform 12 DB round-trips per (symbol, tf):
1. Load feature_vectors (streaming cursor)
2. Load forward_returns (fetchall)
3. Load market_regimes (if equity_model_enabled)
4. Commit pooled rows
5. Commit regime rows
6. Load feature_registry (feature_status_map)
7. ... plus 6 more for cross-sectional pass

**Renaissance analysis:** "You're querying the database 12 times when one query would suffice. Each round-trip is 2-5ms of latency. You're wasting 60ms per symbol waiting for postgres."

**Fix:** Consolidate queries using CTEs:

```sql
-- Single query to load feature_vectors + forward_returns + market_regimes
WITH fv AS (
    SELECT bar_ts, regime, {feature_cols}
    FROM feature_vectors
    WHERE symbol = %s AND tf = %s AND bar_ts <= %s
    ORDER BY bar_ts
),
fr AS (
    SELECT bar_ts, {return_cols}, {complete_cols}
    FROM forward_returns
    WHERE symbol = %s AND tf = %s AND bar_ts <= %s
    ORDER BY bar_ts
),
mr AS (
    SELECT mr.ts, mr.regime_label
    FROM market_regimes mr
    WHERE mr.asset_class = 'equity' AND mr.tf = %s
)
SELECT 
    fv.bar_ts, fv.regime, {feature_cols},
    fr.return_fast, fr.return_mid, ..., fr.complete_extended,
    mr.regime_label AS market_regime_label
FROM fv
LEFT JOIN fr ON fv.bar_ts = fr.bar_ts
LEFT JOIN mr ON mr.ts = DATE_TRUNC(%s, fv.bar_ts)
ORDER BY fv.bar_ts;
```

**Expected speedup:** 30-40ms latency reduction per symbol. For 58 symbols × 4 TFs = 232 cells, saves ~7 seconds total.

**Migration:** Phase 141.2 - Query Consolidation

---

## Priority 2: Alpha Enhancement

### ALPHA-001: Feature Redundancy Audit

**Risk:** `MEDIUM` - 54 features likely contain 15-20 redundant views

**Issue:** Feature correlation clustering uses `cluster_max_corr=0.70` (APR). This means features with pairwise correlation >0.70 are grouped into clusters, and only the **representative** (max |IC|) enters BH-FDR. Non-representatives are marked `passes_fdr=False`.

**Problem:** We've never audited whether 0.70 is the right threshold, or which features are redundant:

- Are `momentum_z_fast` and `momentum_z_mid` truly distinct (corr should be ~0.6)?
- Are `atr_z` and `vol_ratio` measuring the same volatility regime (corr often >0.8)?
- Are `rsi_fast` and `cci_fast` both capturing overbought/oversold (corr >0.75)?

**Renaissance analysis:** "You have 54 features but effective N is likely 12-15. The rest are noise masquerading as diversification. You're paying compute cost for zero marginal information."

**Fix:** Run a **feature redundancy audit**:

1. Compute pairwise IC correlation matrix (already done in `_cluster_features`)
2. Identify all pairs with ρ > 0.70
3. For each cluster, compute **marginal IC contribution**: 
   - `ΔIC = IC[cluster] - IC[cluster \ {feature}]`
   - Features with ΔIC < 0.005 are redundant

4. **Deprecate redundant features**: Set `status='archived'` in feature_registry

**Expected outcome:** Reduce 54 features → 35-40 truly independent features. Effective N increases from 12 to 18-20 (less correlation dilution).

**Migration:** Phase 142 - Feature Redundancy Audit

---

### ALPHA-002: Regime-Adaptive Lookahead Selection

**Risk:** `LOW-MEDIUM` - Fixed lookaheads miss regime-specific alpha decay

**Issue:** Current lookaheads are fixed (1, 5, 20, 60 bars). But IC decay is regime-dependent:

- **Trending regime:** Momentum features persist longer (optimal lookahead ~40-80 bars)
- **Ranging regime:** Mean-reversion features decay faster (optimal lookahead ~5-15 bars)
- **High volatility regime:** All features decay faster (optimal lookahead ~3-10 bars)

**Problem:** Using fixed lookaheads averages across regimes and misses the optimal window for each.

**Renaissance analysis:** "You're measuring IC at 60 bars in a ranging regime where signal reverses after 8 bars. You're measuring IC at 1 bar in a trend where signal persists for 100 bars. You're diluting your own signal."

**Fix:** Implement **regime-adaptive lookahead buckets**:

```python
# APR: alpha.ic.lookahead.{regime}.{scale}
# Default: trending={fast:5, mid:20, slow:60}, ranging={fast:1, mid:5, slow:15}

LOOKAHEAD_BUCKETS = {
    "trending": {"fast": 5, "mid": 20, "slow": 60, "extended": 120},
    "ranging": {"fast": 1, "mid": 5, "slow": 15, "extended": 30},
    "volatile": {"fast": 1, "mid": 3, "slow": 10, "extended": 20},
}

# In IC engine, replace fixed lookaheads with regime-aware:
def get_lookaheads_for_regime(regime_label: str) -> dict[str, int]:
    regime_type = infer_regime_type(regime_label)  # trending/ranging/volatile
    return LOOKAHEAD_BUCKETS[regime_type]
```

**Migration:** Phase 143 - Regime-Adaptive Lookaheads

**Expected outcome:** `ic_sharpe` increases by 20-40% for regime-conditioned features (momentum_z in trending, range_position in ranging).

---

### ALPHA-003: Cross-Sectional Rank Features Missing

**Risk:** `LOW-MEDIUM` - Missing a proven alpha source

**Issue:** The FeatureFactory schema includes 3 nullable cross-sectional features (`momentum_rank_z`, `volume_rank_z`, `volatility_rank_z`), but they are **not populated** in Phase 138. These are set to `None` in `compute()` and `compute_batch()`.

**Problem:** Cross-sectional ranking (computing percentile ranks across all 58 ETFs for a given bar) is a well-documented alpha source:

- **Momentum rank:** Top decile momentum tends to continue (cross-sectional momentum)
- **Volume rank:** High volume stocks tend to revert (liquidity provision)
- **Volatility rank:** Low vol stocks tend to outperform in risk-off regimes

**Renaissance analysis:** "You have the schema for cross-sectional ranks but you're not computing them. This is free alpha you're leaving on the table. Cross-sectional momentum has IC ~0.03-0.05 in your universe."

**Fix:** Implement cross-sectional rank computation:

```python
def compute_cross_sectional_ranks(
    feature_vectors: list[tuple[datetime, FeatureVector]],
    feature_name: str  # e.g., "momentum_z_fast"
) -> dict[str, float]:  # symbol → rank_z
    """Compute percentile ranks across all symbols for a single bar."""
    
    # Extract values for all symbols
    values = {
        symbol: getattr(fv, feature_name)
        for symbol, fv in feature_vectors
    }
    
    # Convert to array and compute ranks
    arr = np.array(list(values.values()))
    ranks = rankdata(arr)  # 1-based ranks
    
    # Convert to z-scores: (rank - mean) / std
    mean_rank = (len(arr) + 1) / 2
    std_rank = len(arr) / math.sqrt(12)  # Uniform distribution std
    rank_z = {
        symbol: (rank - mean_rank) / std_rank
        for symbol, rank in zip(values.keys(), ranks)
    }
    
    return rank_z

# In intelligence_pipeline.py, after FeatureVectorWriter publishes:
# 1. Collect all feature_vectors for this bar_ts across symbols
# 2. Compute cross-sectional ranks for momentum_z, volume_z, vol_ratio
# 3. Update FeatureVector with rank values
# 4. Re-publish updated feature_vectors
```

**Migration:** Phase 139 - Cross-Sectional Rank Features

**Expected outcome:** 3 new features with `ic_sharpe ≈ 0.4-0.6` (strong predictive power).

---

### ALPHA-004: Ensemble Weighting Beyond IC Sharpe

**Risk:** `LOW` - IC Sharpe is good but not optimal

**Issue:** Current ensemble weighting uses `ic_sharpe` as the sole weight:

```
alpha_score = Σ(normalized_score[f] × ic_sharpe[f]) / effective_N
```

**Problem:** `ic_sharpe` penalizes instability (good), but it doesn't account for:

1. **IC decay rate:** Features that decay slowly should have higher weights
2. **Regime specificity:** Features with high IC in one regime but negative IC in another should be penalized
3. **Transaction costs:** High-turnover features (fast momentum) have higher slippage

**Renaissance analysis:** "You're weighting by mean/std, which is 1970s portfolio theory. Modern optimization weights by information ratio, decay half-life, and turnover constraints. You're ignoring the cost of trading your signal."

**Fix:** Implement **multi-criteria ensemble weighting**:

```python
def ensemble_weight(
    ic_sharpe: float,
    ic_decay_half_life: float,  # bars until IC drops to 50%
    regime_specificity: float,   # variance of IC across regimes
    turnover: float,             # avg daily position change %
    transaction_cost_bps: float  # estimated slippage + commission
) -> float:
    """Compute ensemble weight accounting for decay, regime, and costs."""
    
    # Base weight: IC Sharpe
    weight = ic_sharpe
    
    # Decay penalty: features with <20 bar half-life get downweighted
    if ic_decay_half_life < 20:
        weight *= 0.5  # Penalize fast-decaying signals
    
    # Regime penalty: features with high regime variance get downweighted
    if regime_specificity > 0.15:  # IC varies by >15% across regimes
        weight *= 0.7
    
    # Cost penalty: turnover >50%/day gets downweighted
    cost_drag = turnover * transaction_cost_bps / 10000  # bps to decimal
    if cost_drag > 0.001:  # >10 bps/day drag
        weight *= (1.0 - cost_drag * 10)  # Penalize high-turnover features
    
    return max(0.0, weight)
```

**Migration:** Phase 144 - Multi-Criteria Ensemble Weights

**Expected outcome:** Ensemble Sharpe increases by 15-25% due to better weight allocation and cost control.

---

## Priority 3: Architectural Simplification

### ARCH-001: APR Overhead Reduction

**Risk:** `LOW` - Performance + maintenance burden

**Issue:** The Adaptive Parameter Registry (APR) is a foundational v3.0 innovation—**all tunable parameters flow through `ConfigService.get()`**. However, the IC engine and FeatureFactory make **100+ APR calls per bar** in the streaming path.

**Problem:** Each APR call is:
1. A DB round-trip (cached in process memory, but still a lookup)
2. A type conversion (`cfg.get_sync("alpha.ic.min_observations", 500)` → int cast)
3. A fallback check (what if APR key is missing?)

**Renaissance analysis:** "You're doing dynamic parameter loading for values that never change at runtime. `momentum_window_fast=20` doesn't change mid-execution. Load it once at startup and cache it."

**Fix:** Implement **compile-time APR binding**:

```python
# Current (slow):
def compute_ic(...):
    min_obs = cfg.get_sync("alpha.ic.min_observations", 500)  # Every call

# Optimized (fast):
# In service init, pre-bind all APR values to a dataclass
@dataclass(frozen=True)
class ICEngineConfig:
    min_observations: int
    fdr_alpha: float
    walk_forward_folds: int
    # ... all 25 APR keys

# Load once at startup:
config = ICEngineConfig(
    min_observations=int(cfg.get_sync("alpha.ic.min_observations", 500)),
    fdr_alpha=float(cfg.get_sync("alpha.ic.fdr_alpha", 0.05)),
    ...
)

# Use in compute (zero overhead):
def compute_ic(config: ICEngineConfig, ...):
    min_obs = config.min_observations  # Direct attribute access
```

**Migration:** Phase 145 - APR Compile-Time Binding

**Expected outcome:** 5-10% latency reduction in streaming path (eliminates 100+ hash lookups per bar).

---

### ARCH-002: FeatureFactory.compute() vs compute_batch() Unification

**Risk:** `LOW` - Code duplication + maintenance burden

**Issue:** `FeatureFactory` has two compute paths:
1. `compute()`: streaming path, called per bar in `IntelligencePipeline`
2. `compute_batch()`: backfill path, called in `backfill_feature_factory.py`

**Problem:** These paths contain **duplicated logic**:
- Both build numpy arrays from `bars`
- Both compute ATR, momentum, etc.
- Both have `_guard()` fallback logic

The only difference is:
- `compute()` calls `_zscore_last()` (last value only)
- `compute_batch()` calls `_*_series_full()` (full series)

**Renaissance analysis:** "You have two code paths doing 95% the same work. Every bug fix or feature add requires two edits. This is technical debt waiting to become a bug."

**Fix:** Unify into a single `compute()` with a `mode` parameter:

```python
class FeatureFactory:
    @staticmethod
    def compute(
        bars: list[dict],
        symbol: str,
        tf: str,
        cache: FeatureCache,
        config: FeatureFactoryConfig,
        mode: str = "streaming"  # "streaming" or "batch"
    ) -> FeatureVector | list[tuple[datetime, FeatureVector]]:
        """Unified compute path.
        
        - mode="streaming": returns single FeatureVector for last bar
        - mode="batch": returns list of (bar_ts, FeatureVector) for all bars
        """
        
        if len(bars) < 2:
            return _cold_start_vector(cache, tf) if mode == "streaming" else []
        
        # Common precomputation (vectorized, runs once)
        arrays = _extract_arrays(bars)  # opens, highs, lows, closes, volumes
        precomputed = _precompute_series(arrays, config)  # All _*_series_full
        
        if mode == "streaming":
            # Fast path: return last value only
            return _build_vector_from_precomputed(precomputed, -1, cache, config, bars[-1], tf)
        else:
            # Batch path: return all vectors
            return [
                (bars[i]["ts"], _build_vector_from_precomputed(precomputed, i, cache, config, bars[i], tf))
                for i in range(1, len(bars))
            ]
```

**Migration:** Phase 146 - FeatureFactory Unification

**Expected outcome:** -200 LOC, single source of truth for feature logic.

---

### ARCH-003: HMM Parallelization Beyond Symbol-Level

**Risk:** `LOW` - Perf optimization only

**Issue:** Current HMM training (`regime_writer.py`) uses ProcessPoolExecutor with 12 workers, but parallelization is at the **symbol level** (each worker processes one symbol's full history).

**Problem:** For 58 symbols × 4 TFs = 232 regime series, this is efficient. However, the real bottleneck is **HMM inference** (`forward_filter`) which is called **once per bar** during backfill.

**Renaissance analysis:** "You're parallelizing across symbols but the inner loop is sequential. HMM forward-filter is O(K^2 × T) where K=states, T=observations. For each of 500K bars, you're doing a quadratic computation. This is why backfill takes 12 hours."

**Fix:** Implement **vectorized HMM forward-filter** using `numba` JIT compilation:

```python
from numba import jit, prange

@jit(nopython=True, parallel=True)
def forward_filter_vectorized(
    obs: np.ndarray,  # [T, D] observations
    startprob: np.ndarray,  # [K] initial state probs
    transmat: np.ndarray,  # [K, K] transition matrix
    emitmeans: np.ndarray,  # [K, D] emission means
    emitcovars: np.ndarray  # [K, D] emission covars (diagonal)
) -> np.ndarray:  # [T, K] filtered state probabilities
    
    T, D = obs.shape
    K = len(startprob)
    
    # Initialize
    alpha = np.zeros((T, K))
    alpha[0] = startprob.copy()
    
    # Precompute emission probabilities for all t, k
    emit_prob = np.zeros((T, K))
    for t in range(T):
        for k in range(K):
            # Multivariate normal log-pdf (diagonal cov)
            delta = obs[t] - emitmeans[k]
            log_det = np.sum(np.log(emitcovars[k]))
            mahal = np.sum(delta ** 2 / emitcovars[k])
            emit_prob[t, k] = -0.5 * (D * np.log(2*np.pi) + log_det + mahal)
    
    # Forward pass
    for t in range(1, T):
        for k in prange(K):  # Parallel over states
            work = np.log(transmat[:, k]) + alpha[t-1]  # [K]
            alpha[t, k] = np.logaddexp.reduce(work) + emit_prob[t, k]
    
    # Normalize to prevent underflow
    for t in range(T):
        log_sum = np.logaddexp.reduce(alpha[t])
        alpha[t] -= log_sum
    
    return np.exp(alpha)  # Convert log-space back to probs
```

**Expected speedup:** 20-50x faster HMM inference. 12-hour backfill → 15-30 min.

**Migration:** Phase 147 - Numba-JIT HMM Inference

---

## Priority 4: Observability & Debugging

### OBS-001: IC Drift Detection

**Risk:** `MEDIUM` - Silent IC decay kills alpha without alerts

**Issue:** IC is measured once per training window end (e.g., MAX(bar_ts) from feature_vectors). If IC decays between training windows, the ensemble uses stale weights.

**Problem:** No real-time monitoring of IC drift. A feature could go from `ic=0.04` to `ic=0.01` over 3 months, and we wouldn't know until the next quarterly retrain.

**Renaissance analysis:** "You're assuming stationarity in a non-stationary world. Market regimes arbitrage away alpha. If you don't measure IC continuously, you'll trade stale signals for months."

**Fix:** Implement **rolling IC monitoring**:

```python
# In ic_engine.py, after computing full-window IC:
# Also compute rolling IC in trailing windows (e.g., last 10K, 20K, 40K bars)

ROLLING_WINDOWS = [10000, 20000, 40000]  # APR: alpha.ic.monitoring_windows

for window in ROLLING_WINDOWS:
    if n_valid >= window:
        X_trail = X_aligned[-window:]
        y_trail = returns_aligned[-window:]
        
        ic_trail = compute_ic_vectorized(X_trail, y_trail)
        ic_sharpe_trail = compute_rolling_ic_sharpe(X_trail, y_trail)
        
        # Emit OTel gauge
        IC_SCORE_ROLLING_GAUGE.set(
            ic_trail,
            {
                "feature_name": feat_name,
                "window": str(window),
                "tf": tf,
                "regime": regime
            }
        )
```

**Grafana alert:** Trigger if `ic_sharpe_rolling < 0.5 × ic_sharpe_full` (IC has decayed by 50%).

**Migration:** Phase 148 - IC Drift Monitoring

---

### OBS-002: Feature Distribution Drift

**Risk:** `MEDIUM` - Data quality issues silently corrupt features

**Issue:** v2.x had distribution drift detection (`drift_state` table with KS test + CUSUM) for intelligence_features. v3.0 feature_vectors has no equivalent.

**Note:** v3.0 has IC-based decay detection (`docs/research/feature-vector-lifecycle.md`) — detects when a feature's predictive edge degrades. That's different from distribution drift. Both are needed:
- **IC decay detection** (implemented as lifecycle states): Feature edge erodes over time
- **Distribution drift detection** (missing): Input data distribution shifts (data corruption, provider changes)

**Problem:** If a data provider changes (e.g., IBKR adds a new field to bars), feature distributions could shift and we wouldn't notice. IC decay detection won't catch this — the feature formula still computes, it's just computing on corrupted data.

**Renaissance analysis:** "You had distribution drift detection working in v2.x and you dropped it. Why? Data drift is inevitable. You need automated detection or you'll trade on corrupted data for weeks. IC decay catches edge erosion, not data corruption."

**Fix:** Port v2.x drift detection to v3.0:

```sql
-- New table: feature_drift_state
CREATE TABLE feature_drift_state (
    feature_name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    tf TEXT NOT NULL,
    reference_mean FLOAT NOT NULL,
    reference_std FLOAT NOT NULL,
    ks_statistic FLOAT,
    ks_p_value FLOAT,
    cusum_score FLOAT,
    drift_detected BOOLEAN DEFAULT FALSE,
    last_checked TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (feature_name, symbol, tf)
);

-- In a new daemon: feature_drift_monitor.py
-- Runs every hour, compares last 1000 bars to reference distribution
-- Emits ALERT if ks_p_value < 0.01 OR cusum_score > threshold
```

**Migration:** Phase 149 - Feature Drift Detection

---

## Execution Order (Recommended)

**Phase 140 (Data Integrity):**
1. IC-001: Forward return formula fix (CRITICAL)
2. IC-002: Context feature daily aggregation (HIGH)
3. IC-003: Regime transition purge (MEDIUM)

**Phase 141 (Latency):**
4. PERF-001: IC engine vectorization (MEDIUM)
5. PERF-002: Incremental FeatureFactory (LOW-MEDIUM)
6. PERF-003: Query consolidation (LOW)

**Phase 142-144 (Alpha):**
7. ALPHA-001: Feature redundancy audit (MEDIUM)
8. ALPHA-002: Regime-adaptive lookaheads (LOW-MEDIUM)
9. ALPHA-003: Cross-sectional ranks (LOW-MEDIUM)
10. ALPHA-004: Multi-criteria ensemble weights (LOW)

**Phase 145-149 (Architecture + Observability):**
11. ARCH-001: APR compile-time binding (LOW)
12. ARCH-002: FeatureFactory unification (LOW)
13. ARCH-003: Numba-JIT HMM (LOW)
14. OBS-001: IC drift monitoring (MEDIUM)
15. OBS-002: Feature drift detection (MEDIUM)

---

## What Jim Simons Would Demand

> "Why are you measuring open-to-open returns for intraday bars? You're capturing noise you can't trade. Fix it."
> 
> "You have 54 features but effective N is 12. The rest are redundant. Remove them."
> 
> "Your IC Sharpe computation is O(n²) when it should be O(n). Why are you wasting CPU cycles?"
> 
> "You're weighting features by IC Sharpe alone. What about decay? What about transaction costs? You're ignoring the cost of trading your signal."
> 
> "You had drift detection in v2.x and you dropped it. That's negligence. Put it back."

**The Renaissance standard:** Every line of code must increase alpha, reduce latency, or protect data integrity. Anything else is deleted.

---

## Appendix: Quick-Win Checklist

If you can only tackle 3 items this week:

1. ✅ **IC-001:** Fix forward return formula (2 hours, invalidates all current IC measurements if unfixed)
2. ✅ **IC-002:** Daily-aggregate context features (4 hours, eliminates autocorrelation bias)
3. ✅ **PERF-001:** Vectorize IC engine (6 hours, 3-5x speedup)

These three fixes address the most severe data-integrity risks and latency bottlenecks. Everything else can wait until Phase 141+.
