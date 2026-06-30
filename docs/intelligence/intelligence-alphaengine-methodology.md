# AlphaEngine — IC Measurement Methodology

**Status:** current — living reference
**Milestone:** v3.0+
**See also:** `intelligence-alphaengine.md` (conceptual overview), `intelligence-alphaengine.md` (architecture)

---

## Invariants

Non-negotiable statistical constraints. Violating any produces IC measurements that are wrong, biased, or meaningless.

| Invariant | Description | Status |
|-----------|-------------|--------|
| **Executable returns** | `ln(open[T+N+1] / open[T+1])`, not `ln(close[T+N] / close[T])` | ✅ Implemented |
| **Walk-forward gate** | No feature enters the ensemble without held-out validation | ✅ Implemented |
| **IC Sharpe weights** | Stability over time, not raw IC magnitude | ✅ Implemented |
| **Regime-stratified** | Pooled IC is diagnostic only; ensemble uses per-regime IC | ✅ Implemented |
| **Automated decay** | Rolling IC monitor triggers re-solve; no human gates | ⚠️ Designed, not yet built — see `docs/plans/2026-06-30-alphaengine-unfinished.md` |
| **Causal regimes** | Forward-filtered Viterbi only; no smoothed labels in `feature_vectors` | ✅ Implemented |
| **Non-overlapping windows** | Sub-sampled at stride N for IC Sharpe; each observation is independent | ✅ Implemented |

---

## Feature Universe — V1 (54 features)

All features are explicit typed columns in `feature_vectors`. "Promotion" means earning non-zero weight in `ensemble_weights`, not a schema migration.

**Momentum (5)**
| Column | Character |
|--------|-----------|
| `momentum_z_fast` | Fast-scale log return z-scored |
| `momentum_z_mid` | Mid-scale log return z-scored |
| `range_position` | `(close - low) / (high - low)` |
| `bar_close_pos` | Buying pressure: close position within day range |
| `gap_z` | Overnight gap z-scored vs rolling gap distribution |

**Oscillators — APR-backed periods (6)**
| Column | Scale | Character |
|--------|-------|-----------|
| `rsi_fast` | fast | Mean-reversion, short horizon |
| `rsi_mid` | mid | Mid-cycle mean-reversion |
| `rsi_slow` | slow | Longer-cycle mean-reversion |
| `cci_fast` | fast | CCI: deviation from mean, MAD-normalized, short |
| `cci_mid` | mid | CCI: mid-cycle deviation |
| `cci_slow` | slow | CCI: longer-cycle deviation |

RSI and CCI test different mean-reversion hypotheses: RSI uses range normalization; CCI uses mean absolute deviation. Column names encode scale, not period — periods live in APR under `feature.period.{rsi,cci}.{fast,mid,slow}`.

**Trend freshness and strength (4)**
| Column | Character |
|--------|-----------|
| `aroon_fast` | Time since recent high, short window |
| `aroon_slow` | Time since recent high, long window |
| `hma_slope_z` | Hull MA slope z-scored |
| `adx` | Average Directional Index (trend strength) |

**Volume and order flow (7)**
| Column | Character |
|--------|-----------|
| `informed_flow` | Composite informed trader flow signal |
| `volume_z` | Bar volume z-score vs rolling mean |
| `ofi_z` | Order flow imbalance z-scored |
| `ofi_div` | OFI vs price divergence |
| `cvd_slope_z` | Cumulative volume delta slope, z-scored |
| `cmf` | Chaikin money flow |
| `rel_volume` | Volume ratio vs rolling average |

**Volatility and market character (5)**
| Column | Character |
|--------|-----------|
| `vwap_dev_sigma` | Session VWAP deviation in sigma units |
| `atr_z` | ATR z-scored vs rolling ATR |
| `vol_ratio` | Short/long realized vol ratio |
| `hurst` | Hurst exponent (trending vs mean-reverting) |
| `shannon` | Shannon entropy of price |

**HMM regime state (4)**
| Column | Character |
|--------|-----------|
| `hmm_regime_prob` | HMM confidence in current regime state |
| `hmm_entropy` | Regime distribution entropy (clarity) |
| `hmm_duration` | Bars in current regime (maturity signal) |
| `garch_ratio` | GARCH conditional vol vs realized vol ratio |

`hmm_duration` and `hmm_entropy` are orthogonal: entropy measures certainty of the current state; duration measures how long we have been in it.

**Market structure (4)**
| Column | Character |
|--------|-----------|
| `poc_dist_atr` | Distance from Point of Control in ATR units |
| `va_position` | Position within Value Area (0=VAL, 1=VAH) |
| `sr_support_dist` | Distance to nearest support in ATR units |
| `sr_resist_dist` | Distance to nearest resistance in ATR units |

**Macro context (3)**
| Column | Character |
|--------|-----------|
| `vix_z` | VIX level z-scored vs rolling mean |
| `flight_quality` | Flight-to-quality signal (equity/bond ratio) |
| `yield_slope_z` | Yield curve slope z-scored |

**Calendar / session (9)**
| Column | Character |
|--------|-----------|
| `in_ny_session` | NY session active |
| `in_london_kz` | London killzone active (distinct from overlap) |
| `in_overlap` | London/NY overlap active |
| `power_hour` | 3-4 PM ET active |
| `opening_range` | First 30 min of session active |
| `above_wk_vwap` | Price above weekly VWAP |
| `dow_sin` | Day-of-week cyclical encoding (sin) |
| `dow_cos` | Day-of-week cyclical encoding (cos) |
| `month_position` | Position within month [0,1] |

**Cross-timeframe (3)**
| Column | Character |
|--------|-----------|
| `ctf_momentum` | HTF/LTF momentum divergence |
| `ctf_vwap_align` | Cross-TF VWAP alignment |
| `ctf_regime_align` | Cross-TF HMM regime agreement |

**Statistical process / liquidity (4)**
| Column | Character |
|--------|-----------|
| `amihud_illiq_z` | `\|return\| / dollar_volume` z-scored — price impact proxy (Amihud 2002) |
| `high_52w_dist` | Distance from 52-week high — momentum anchor (George & Hwang 2004) |
| `ret_skew_z` | Rolling return skewness z-scored |
| `ret_acf1_z` | Spearman autocorrelation of return[t] vs return[t-1], z-scored |

`ret_acf1_z` is distinct from `momentum_z`: momentum is cumulative return; autocorrelation measures serial dependence of individual bar returns.

### Feature-to-Vector Domain

| Group | `vector_domain` |
|-------|----------------|
| Momentum, oscillators, trend, volume, volatility, HMM, market structure, statistical | `'quant'` |
| Macro context | `'macro'` |
| Calendar / session | `'calendar'` |
| Cross-timeframe | `'quant'` |

`vector_domain` is written to every `feature_ic_scores` and `ensemble_weights` row, enabling per-vector IC aggregation and decay monitoring.

### V1 Exclusions

| Excluded | Reason |
|----------|--------|
| FX pairs | ~21 rows — statistically negligible; different microstructure |
| Candlestick patterns | Low base rate; needs >= 500 true events for IC |
| Categoricals (`smc.amd_phase`, `swing_low_type`, `trend_direction`) | IC requires continuous or binary |
| `obv` (raw) | Unbounded; meaningless without price normalization |
| `macd_line` (raw) | In price units; not cross-sectionally comparable |
| Any feature with null rate > 1% | Missing data biases IC estimates |
| Cross-sectional relative strength | Requires inter-symbol dependency at compute time — breaks pure per-symbol FeatureFactory |

---

## Forward Returns

### The Executable Return

```
R(T, N) = ln( open[T+N+1] / open[T+1] )
```

- T is the `ts` of the observation bar
- T+1 is the first executable entry (open of next bar)
- T+N+1 is the exit bar

`ln(close[T+N] / close[T])` is wrong because close[T] is the observation price, not the executable entry. The difference is material at short horizons (5m/15m) and in markets with opening gaps.

### Lookahead Horizons

Four horizons per TF, stored as gradient column names:

| Column | Description |
|--------|-------------|
| `return_fast` | Shortest lookahead (APR: `alpha.ic.lookahead.fast`) |
| `return_mid` | Mid lookahead |
| `return_slow` | Slow lookahead |
| `return_extended` | Longest lookahead |

The IC engine measures all four. The ensemble uses the horizon with the highest IC Sharpe per (feature, TF, regime) — the researcher does not pre-select.

### Gap Flag

`forward_returns.has_gap_before_entry` is populated but not yet used in IC stratification. A gap means an overnight or holiday break exists between the observation bar and entry — a structurally different return distribution from intraday IC. See unfinished plan for gap-stratified IC.

---

## Feature Normalization

### Cross-Sectional Rank Transform

All features are normalized via within-symbol percentile rank before IC computation. `feature_vectors` stores raw values; rank normalization is applied by the IC Engine at measurement time.

```
pct_rank(v, window) = (rank_of_v_in_window - 0.5) / count_non_null_in_window
```

Result: (0, 1) exclusive. The `- 0.5` avoids boundary effects.

### Why Rank, Not Z-Score

Z-score assumes a distribution shape. RSI is bounded [0,100]. Volume z-score is right-skewed. ATR is in price units. Rank normalization makes none of these assumptions and produces comparable unit-free outputs correct for Spearman IC (which is already a rank correlation).

### Direction Centering

```
centered_score = pct_rank - 0.5     # range: (-0.5, +0.5)
```

Whether high = bullish or bearish is determined empirically by the sign of IC. The same feature (e.g., RSI) may have positive IC in trending regimes and negative IC in ranging ones.

---

## IC Estimation

### Estimator

For each (feature, symbol, TF, regime, lookahead):

```
IC = Spearman( centered_score_t, R(t, N) )
```

Computed over observations where the forward return window is complete (`complete_{horizon} = true`).

**Spearman over Pearson:** returns have fat tails; Spearman is more robust and consistent with the rank-normalized feature inputs.

### Non-Overlapping Sub-Sampling

Consecutive bars are not independent — the N-bar return at T and T+1 share N-1 bars. Using every bar produces IC standard errors that are far too small.

**Solution:** sample every Nth bar (stride = lookahead_bars):

```
observations = rows where (row_index % N) == 0
```

This ensures no forward return window overlaps. Each observation is genuinely independent.

**Effective N:** `floor(T / N)` where T is total bar count. For 25,000 bars at N=5: 5,000 independent observations.

### Bootstrap Confidence Interval

2,000 bootstrap resamples (percentile method, with replacement on sub-sampled pairs). `ic_ci_lower` (2.5th pct) and `ic_ci_upper` (97.5th pct) are stored. Gate: `ic_ci_lower > 0.0` for ensemble eligibility.

### Minimum N

| Condition | Treatment |
|-----------|-----------|
| n_independent < 100 | `reliable = false` — stored, never enters ensemble |
| 100 <= n_independent < 500 | `reliable = true`, IC Sharpe not computed |
| n_independent >= 500 | IC Sharpe eligible |

IC Sharpe computation requires 20,000 independent observations (10 windows × 2,000). Without this, IC Sharpe is undefined and the feature does not enter the ensemble. Get more data — there is no interim path.

---

## Multiple Testing

### BH-FDR Correction

Applied globally across all IC tests in the batch:

1. Sort all p-values ascending: p(1) ≤ p(2) ≤ ... ≤ p(M)
2. Find the largest k such that p(k) ≤ (k/M) × q
3. Reject H₀ for all p(i) where i ≤ k

`q = 0.05`. All tests within the pre-specified feature universe are included — no separate correction per feature or TF.

The feature universe is **fully specified before any IC is measured**. Adding features after observing IC results is p-hacking. The pre-specified count determines the multiple-testing correction threshold.

### Walk-Forward Validation

Primary statistical guard. BH-FDR controls false discovery rate within training; walk-forward confirms out-of-sample replication.

```
Initial training end: training_start + 70% of available data
Fold size:           10% of available data
Number of folds:     3 (APR: alpha.ic.walk_forward_folds)
```

Expanding window (not rolling) — each fold includes all prior data.

**Validation criteria per feature:**

| Criterion | Threshold |
|-----------|-----------|
| IC > 0 in validation fold | >= 2 of 3 folds |
| IC Sharpe across folds | >= 0.4 |
| IC sign consistent | Same sign in >= 2 of 3 folds |

Failure is permanent for the current measurement cycle. The only valid re-evaluation path is additional data, re-running the full protocol from scratch.

**Holdout integrity:** Validation windows are used exactly once. If results are disappointing, the path forward is more data — not relaxed thresholds or adjusted features.

---

## IC Sharpe Computation

IC Sharpe is the primary ensemble weighting signal. A feature with IC=0.04 and IC std=0.01 is far more valuable than IC=0.06 and IC std=0.10.

### Rolling IC Time Series

For each feature passing FDR + walk-forward:

```
IC_Sharpe = mean(IC_t) / std(IC_t)

IC_t computed on non-overlapping windows of W = 2,000 independent observations:
    Window 1: observations [0, 2000)
    Window 2: observations [2000, 4000)
    ...
```

Non-overlapping windows ensure IC_t estimates are independent — required for IC Sharpe to be well-defined.

---

## Ensemble Weight Derivation

### The Problem with Simple IC Weighting

If `rsi_fast` and `roc_14` both have IC=0.04 and their IC time series are highly correlated (both drop in choppy markets), giving each full IC weight double-counts the same source of predictability. The ensemble Sharpe is lower than if one had zero weight.

### Ledoit-Wolf Covariance Shrinkage

```python
IC = build_ic_time_series(passing_features)  # shape: (n_features × n_ic_windows)
lw = LedoitWolf()
cov_ic = lw.fit(IC.T).covariance_             # shape: (n_features × n_features)
mu_ic = IC.mean(axis=1)
weights = maximize_sharpe(mu_ic, cov_ic, long_only=True)
```

**Why long-only:** Features with negative IC are handled by negating the centered score at ensemble computation time via `ic_sign`. The weight optimizer sees all features as contributing positively.

### Signed Weight Application

```python
alpha_score = sum(
    sign(ic[f]) × centered_score[f] × weight[f]
    for f in active_features
)
```

`ic_sign` (+1 or -1) is stored in `ensemble_weights`. Positive alpha_score = composite features predict upward movement; negative = downward.

### Weight Bounds

- Minimum: 0 (features below IC Sharpe threshold contribute nothing)
- Maximum per feature: 0.20 (enforced post-optimization by normalization)

### Weight Versioning

Every re-run that changes any weight produces a new `weight_version` (monotonically increasing integer). Old versions are retained for audit. The ensemble uses the latest with `is_active = true`.

### Ensemble Builder is the Sole Writer

`ensemble_weights` is written only by `EnsembleBuilder`. The decay monitor triggers a re-solve — it does not write weights directly. Writing `weight = 0` to a single feature while leaving other weights unchanged is an architecture violation: the Ledoit-Wolf adjustment is invalid for the remaining features without a full re-solve.

---

## Emission Threshold

### Current Implementation (APR-backed)

Emission thresholds are stored in APR under `alpha.quant.threshold.{tf}` and loaded at publisher startup. Default seeds: 5m=1.5, 15m=1.2, 1h=1.0, 1d=0.8 (alpha_score standard deviations).

These are researcher estimates, not empirically derived. The intended design (empirical sweep over ensemble IC and transaction costs) is not yet implemented — see unfinished plan.

### Cost Gate

`alpha.quant.cost_hurdle.{tf}` gates CI bounds: long requires `alpha_ci_lower > hurdle`; short requires `alpha_ci_upper < -hurdle`. Seeds at 0.0 pending corpus-derived calibration (todo 030).

---

## Alpha Decay Protocol (Designed, Not Yet Built)

The decay system design is recorded here as binding intent. Implementation status: not started — see `docs/plans/2026-06-30-alphaengine-unfinished.md`.

### Architectural Invariants

1. **`ensemble_weights` is the only valid weight store.** Individual feature weight updates are invalid. Any change requires a full Ledoit-Wolf re-solve producing a new `weight_version`.

2. **Decay is regime-stratified.** A feature decaying in one HMM regime does not imply decay in others. The monitor evaluates each (feature, symbol, tf, regime) cell independently.

### Decay Trigger

```
rolling_ic_ci_lower <= alpha.decay.ci_lower_threshold (default: 0.0)
AND
weight[feature][tf][regime] × |rolling_ic_ci_lower| > alpha.decay.materiality_threshold
```

The materiality filter prevents a 0.5%-weight feature triggering a full re-solve on a marginal CI exceedance.

**Regime-shift detection:** If >= `alpha.decay.regime_shift_fraction` (default: 0.60) of features simultaneously show `ic_ci_lower <= 0`, classify as a market regime shift, not individual decay. Do not zero weights — wait for normalization.

### Automated Response

1. Set `feature_ic_scores.is_decaying = true` for affected cells
2. Trigger `EnsembleBuilder` re-solve (excluding decayed cells)
3. New `weight_version` written atomically

### Recovery Gate

Recovery requires genuinely new evidence — not the same data re-examined. Minimum: `W_recovery = 2,000` new independent observations that did not overlap the decay detection window.

```
recovery_eligible_at = decay_triggered_at + (W_recovery × N_subsample × bar_duration)
```

At 5m with N=5: ~128 trading days. At 1h: ~26 trading days.

**No partial restoration.** The Ledoit-Wolf re-solve assigns the correct weight from the recovery evidence. A hard-coded fraction ("restore to 50%") is researcher intervention in an empirical process.
