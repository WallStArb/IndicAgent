# ML Scoring Model Research

**Project:** IndicAgent v2.0 — Regime-Specific ML Scoring Layer
**Researched:** 2026-03-19
**Mode:** Architecture + Feasibility
**Overall confidence:** HIGH (architecture; library versions verified via PyPI/docs)

---

## Recommended Stack

### New Dependencies (add to requirements.txt)

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| `lightgbm` | `>=4.6.0` | Primary signal scorer | Fastest training on 50k-200k rows, leaf-wise growth beats XGBoost for financial tabular data at this size, native DART mode handles feature correlation without manual feature selection |
| `xgboost` | `>=3.2.0` | Challenger scorer (A/B baseline) | Level-wise growth is more stable for small N per regime; validated on Python 3.13; run as shadow challenger |
| `shap` | `>=0.51.0` | Feature attribution | TreeExplainer gives exact Shapley values for GBDT models, O(TlogT) not O(T^2^); write top-5 SHAP features per signal to `signal_ledger.ml_top_features` for auditability |
| `optuna` | `>=4.3.0` | Hyperparameter search | TPE sampler + `LightGBMTuner` integration; run at model init and after major regime shift, not every retrain cycle |
| `statsmodels` | `>=0.14.4` | ADF stationarity tests + Pearson validation | Already in spirit (validate_alpha.py uses scipy); statsmodels adds `adfuller()` + `ols()` needed for promotion gate p-values |

**Existing stack already provides:** `scikit-learn>=1.5.0` (isotonic regression, logistic regression already in use), `scipy>=1.15.0`, `numpy>=2.4.0`, `pandas>=3.0.0`.

**Do NOT add:** `river` (online learning — overkill until N > 500k), `tensorflow`/`pytorch` (neural models require 12+ months labeled data), `tsfresh` (auto feature engineering conflicts with existing curated features).

### Algorithm Decision: LightGBM as Primary

**Confidence: HIGH** (verified via [PyPI](https://pypi.org/project/lightgbm/), [LightGBM 4.6 docs](https://lightgbm.readthedocs.io/en/latest/))

LightGBM wins for this use case on three grounds:

1. **Dataset size 50k-200k rows:** LightGBM's histogram-based split finding is materially faster (2-5x) than XGBoost's pre-sorted algorithm at these row counts. Memory headroom matters for on-server retraining without disrupting live services.

2. **Feature correlation tolerance:** Financial I1-I7 features are highly correlated (RSI, MACD, Stochastic, Williams %R all measure momentum). LightGBM's DART mode (dropout regularization for trees) handles correlated features better than XGBoost's default without requiring explicit feature pruning.

3. **Regime imbalance:** Class imbalance across regimes (ranging is typically underrepresented in trending markets) is handled via `class_weight='balanced'` or direct `pos_weight` in LightGBM without external resampling.

**XGBoost as challenger:** Run `xgb.XGBClassifier` in shadow/A-B mode. XGBoost 3.2.0 (released 2026-02-10) is more stable on small per-regime N (< 500 samples), which is relevant early when regime-0 (ranging) has fewer labeled examples. Promote whichever achieves higher out-of-sample log-loss after 90 days.

**sklearn ensemble (RandomForest, GradientBoostingClassifier): do NOT use** — 3-5x slower training than LightGBM, no native SHAP TreeExplainer acceleration, and no early stopping. Reserve for one-time feature importance discovery only.

---

## Training Architecture

### Data Source: Three-Table JOIN

```sql
SELECT
    -- Label
    CASE WHEN sl.outcome IN ('target_1','target_1_2','target_full') THEN 1 ELSE 0 END AS win,
    -- Signal metadata (for filtering, NOT features)
    sl.setup_plugin,
    sl.timeframe,
    sl.regime_type_at_fire,
    sl.symbol,
    sl.calibrated_confidence,   -- existing calibration score (for comparison)
    -- HMM regime (from intelligence_features JSONB)
    (if_.smc->>'hmm_regime')::int AS hmm_regime,
    (if_.smc->>'hmm_regime_prob')::float AS hmm_regime_prob,
    (if_.smc->>'hmm_regime_duration')::int AS hmm_regime_duration,
    -- Features from intelligence_features (full i1-i6 vector)
    if_.i1, if_.i2, if_.i3, if_.i4, if_.i5, if_.smc,
    -- Signal-fire features from signal_features (bucket contributions)
    sf.feature_name, sf.feature_value, sf.bucket_contribution
FROM signal_ledger sl
JOIN intelligence_features if_
    ON sl.symbol = if_.symbol
   AND sl.feature_ts = if_.feature_ts
   AND sl.feature_tf = if_.feature_tf
LEFT JOIN signal_features sf ON sl.signal_id = sf.signal_id
WHERE sl.is_shadow = FALSE
  AND sl.outcome IS NOT NULL
  AND sl.computed_at >= NOW() - INTERVAL '90 days'
ORDER BY sl.computed_at ASC   -- time order is load-bearing: no shuffle before split
```

**Key constraint:** Always order by time before train/test split. Never shuffle the full dataset. Shuffling introduces lookahead.

### Feature Matrix Construction

Extract from the JSONB tiers into flat columns at training time (not at inference time — pre-flatten to Parquet for speed):

```
I1 tier (25 indicators): rsi_14, macd_hist, atr_14_pct, adx, bb_pct_b, stoch_k,
         williams_r, obv_slope, cmf, hma_slope, hma_accel, roc_20, cci_14,
         mfi_14, aroon_osc, donchian_pct, historical_vol_20, supertrend_dir,
         parabolic_sar_dir, ac_osc, ao_osc, ema9_slope, ema21_slope

I2 tier: rsi_cross_signal, macd_crossover, stoch_signal, adx_trend_strength,
         vol_surge, exhaustion_score, acceleration_regime, obv_momentum, derivative_osc

I3 tier: swing_high_dist_pct, swing_low_dist_pct, sr_level_proximity,
         trend_structure_direction, session_poc_dist_pct, fib_zone_flag

I4 tier: hmm_regime (one-hot: 0/1/2), hmm_regime_prob, hmm_regime_duration,
         garch_vol_forecast, kalman_slope, hurst_exponent, shannon_entropy,
         session_kill_zone, mtf_vol_ratio, avwap_deviation_pct

I5 tier: rsi_divergence_dir, macd_divergence_dir, bollinger_squeeze_active,
         vol_divergence_score, cmf_divergence_dir, pattern_completion_score,
         candlestick_pattern_class (one-hot or ordinal)

SMC tier: fvg_active, fvg_size_pct, bos_detected, choch_detected,
          ob_proximity_pct, supply_zone_active, demand_zone_active,
          sweep_detected, premium_discount_zone

I6 tier: cross_tf_confluence_score

Signal metadata (NOT from intelligence_features):
  days_to_expiry, tod_hour_et, day_of_week, bars_to_activation_hist (from training)
```

**Total feature count:** ~80-95 raw features. After ADF filtering and encoding: 70-85 model inputs.

### Model Configuration (LightGBM primary)

```python
import lightgbm as lgb

LGBM_PARAMS = {
    "objective": "binary",
    "metric": "binary_logloss",
    "boosting": "dart",          # DART for correlated financial features
    "n_estimators": 500,
    "learning_rate": 0.05,
    "num_leaves": 31,            # conservative: prevents memorizing regimes
    "min_child_samples": 30,     # minimum 30 samples per leaf — Renaissance gate
    "subsample": 0.8,
    "colsample_bytree": 0.7,
    "reg_alpha": 0.1,            # L1 for sparse feature selection
    "reg_lambda": 1.0,           # L2 for stability
    "class_weight": "balanced",  # handle regime imbalance
    "random_state": 42,
    "n_jobs": 2,                 # leave cores for live services
    "early_stopping_rounds": 50, # stop before overfitting
    "verbose": -1,
}
```

### Model File Location

```
src/intelligence/ml/
  signal_scorer.py          # LGBMSignalScorer class (training + inference)
  feature_builder.py        # JSONB → flat feature matrix construction
  stationarity.py           # ADF gate (run once at training time)
  model_store.py            # joblib save/load with versioning

models/
  lgbm_global_v{N}.joblib   # global model (all regimes)
  lgbm_regime0_v{N}.joblib  # ranging regime model
  lgbm_regime1_v{N}.joblib  # trending model
  lgbm_regime2_v{N}.joblib  # volatile model (hmm_regime=2 maps to trending in existing code; keep separate)
  xgb_global_v{N}.joblib    # XGBoost challenger
  metadata_v{N}.json        # training date, N, AUC, log-loss, feature list
```

**Versioning:** `v{N}` is monotonically incrementing int stored in `ml_models` table. Inference always loads `is_active=TRUE` version. New version is shadow-active until promotion gate passes.

---

## Feature Engineering

### ADF Stationarity Gate

Run once at training time. Cache results in `metadata_v{N}.json`. Do not re-run at every retrain unless features change.

**Confirmed stationary (no transform needed):**
- `rsi_14` — bounded [0,100], mean-reverting by construction
- `stoch_k`, `williams_r` — bounded oscillators
- `macd_hist` — difference series, stationary in practice
- `bb_pct_b` — bounded [0,1] by definition
- `hmm_regime_prob` — bounded [0,1]
- `hurst_exponent` — bounded [0,1]
- `shannon_entropy` — bounded [0, log(N)]
- `adx` — bounded [0,100], slow drift but typically passes ADF at p<0.10
- `atr_14_pct` — ATR expressed as % of price removes price-level trend
- `cross_tf_confluence_score` — normalized composite score

**Likely non-stationary — apply log-return or percent-change transform:**
- `obv` raw — use `obv_slope` (already computed) or `obv_pct_change(5)`
- `avwap_deviation_pct` — already percent, should pass ADF; verify
- `kalman_slope` — verify; if level-based, take first difference
- `garch_vol_forecast` — level; take `vol_ratio = garch_vol / rolling_vol_20` instead

**ADF protocol:**
```python
from statsmodels.tsa.stattools import adfuller

def adf_gate(series: pd.Series, alpha: float = 0.05) -> bool:
    """Return True if stationary at given significance level."""
    if series.dropna().nunique() < 20:
        return True   # near-constant features are stationary enough
    result = adfuller(series.dropna(), maxlag=10, autolag="AIC")
    return result[1] < alpha   # p-value < alpha → reject unit root → stationary

# Apply at training time:
stationary_features = [col for col in feature_cols if adf_gate(X_train[col])]
# For non-stationary: apply pct_change(1) then re-test
```

### Lag and Rolling Features (selective — do NOT add all)

Add only features that avoid lookahead by using only past bars:

```python
# Win rate of same setup over trailing 30 signals — available from signal_ledger at fire time
"setup_win_rate_30d"    # pre-computed in setup_performance table — already exists!

# Regime persistence score: how long has current regime been active
"hmm_regime_duration"   # already in i4 — no transform needed

# Cross-TF regime agreement (already in cross_tf_confluence_score in I6)
# Do NOT add raw higher-TF indicator values unless they're from a completed bar

# Days to expiry (already in intelligence_features.days_to_expiry)
# TOD bucket: map to sin/cos encoding to capture intraday periodicity
"tod_sin" = sin(2 * pi * hour_et / 24)
"tod_cos" = cos(2 * pi * hour_et / 24)
```

**Explicit prohibitions — these cause lookahead:**
- Future bar prices or indicators (obvious)
- `outcome` from the same signal (label leakage)
- Bar features computed using future volume (e.g., session VWAP recalculated at close)
- Any feature derived from `signal_ledger.mae` or `signal_ledger.mfe` at training time unless computing training labels from resolved signals with strict time cutoff

### Cross-Sectional Normalization

Do NOT apply cross-sectional Z-score normalization across symbols at training time — this requires knowing all symbols' values simultaneously, introducing look-forward bias if applied to a rolling window. Instead:

- Apply per-symbol rolling Z-score with a 252-bar backward window for level-based features: `z = (x - rolling_mean(252)) / rolling_std(252)` using only past data
- For tree models (LightGBM, XGBoost), normalization has zero effect on splits — skip it entirely. Trees are scale-invariant.
- Apply normalization ONLY if adding logistic regression as a downstream probability calibrator

---

## Regime-Specific Model Strategy

### Decision: Three Separate Models + One Global Model

**Confidence: HIGH** (informed by QuantInsti research doc in codebase + practice literature)

**Architecture:** Train four models:

1. `lgbm_global` — trained on all regimes, regime as feature (one-hot hmm_regime + hmm_regime_prob). Used as fallback when per-regime N < 500.
2. `lgbm_regime0` — ranging only (hmm_regime=0). Gate: N_0 >= 500.
3. `lgbm_regime1` — trending up (hmm_regime=1). Gate: N_1 >= 500.
4. `lgbm_regime2` — volatile / trending down (hmm_regime=2). Gate: N_2 >= 500.

**Inference routing:**
```python
def score_signal(features: dict, hmm_regime: int, hmm_regime_prob: float) -> float:
    if hmm_regime_prob < 0.55:
        # Uncertain regime: use global model, apply 0.85 confidence dampener
        return global_model.predict_proba([features])[0][1] * 0.85

    regime_model = regime_models.get(hmm_regime)
    if regime_model is None or not regime_model.is_ready:
        return global_model.predict_proba([features])[0][1]

    return regime_model.predict_proba([features])[0][1]
```

**Why NOT mixture-of-experts (soft gating):**
- MoE requires a separate router network to blend expert outputs — significant added complexity
- With 3 HMM regimes already probabilistically assigned, hard routing based on `argmax(hmm_state_probs)` is equivalent to a degenerate MoE with a pre-trained router
- Soft MoE blending (weighted average of regime-0 and regime-1 scores based on HMM state probabilities) is a valid V2 extension — implement after hard routing proves stable

**Why NOT single model with regime as feature:**
- A single model must learn regime-conditional patterns simultaneously, which requires 3x the data to converge vs regime-specific models
- Feature interactions between `hmm_regime=0` and trend-specific indicators are complex; trees can capture this but require more depth/leaves, increasing overfit risk
- The existing HMM regime signal is already high quality (5D observations, calibrated probabilities) — trusting it to separate training data is sound

**Regime model N=500 gate justification:**
- With ~90 days of live data across 23 symbols × 4 TFs = 92 instruments × ~390 bars/day (for 1m) ≈ well over 500 signals in trending conditions
- Ranging (regime-0) accumulates slower — expect N=500 for regime-0 by day 60-90 if 35% of bars are ranging
- Never train a regime-specific model with N < 500 — at N=200 the AUC CI is too wide for a meaningful promotion gate

---

## Walk-Forward Retraining Design

### Cadence

| Trigger | Action | When |
|---------|--------|------|
| Sunday 02:00 ET (weekly) | Full retrain all models on trailing 90-day window | Systemd timer, Persistent=true |
| N_new_outcomes >= 200 | Trigger ad-hoc retrain for that (regime, TF) group | Checked in weight_updater.py at 30-min cadence |
| KS drift p < 0.01 | Force retrain + Prometheus alert | drift_monitor_service already emits this flag |

**Weekly is the primary cadence.** Ad-hoc retrain is a safety net for fast regime shifts (e.g. VIX spike). Daily retraining is premature optimization — with N=50k total signals, weekly gives ~700 new labeled samples per cycle which is statistically meaningful.

### Walk-Forward Split Protocol

```
Total history window: 90 days

Split point: 75 days train / 15 days test (83% / 17%)

Walk-forward evaluation (for validation only — not for production model):
  Fold 1: train[0:60d], test[60:75d]
  Fold 2: train[0:75d], test[75:90d]

Production model: train on ALL 90 days, deploy immediately after validation passes.

CRITICAL: Split must be time-based. No sklearn train_test_split with shuffle.
```

```python
from sklearn.model_selection import TimeSeriesSplit

tscv = TimeSeriesSplit(n_splits=5, test_size=2000)  # 2000 rows ≈ 15 days of 1m signals
for fold_idx, (train_idx, test_idx) in enumerate(tscv.split(X)):
    X_tr, X_te = X.iloc[train_idx], X.iloc[test_idx]
    y_tr, y_te = y.iloc[train_idx], y.iloc[test_idx]
    # ... train and evaluate
```

### Minimum N Gate Per Model

| Model | Minimum N (train) | Minimum N per regime (per-regime model) |
|-------|------------------|-----------------------------------------|
| Global | 500 | N/A |
| Per-regime | 500 global + 500 per-regime | 500 in that regime |
| Promotion to live | 1000 labeled outcomes | AUC > 0.55, log-loss < 0.69 (random baseline) |
| Statistical significance | p < 0.05 (Pearson r on predicted vs actual win rate) | N >= 200 per OOS test fold |

**N=500 global gate aligns with Renaissance "earn the right" principle.** Below this, the isotonic calibration (already in use for CIS) provides better probability estimates than an undertrained GBDT.

### What Retraining Produces

1. `models/lgbm_global_v{N+1}.joblib` — new model file
2. `metadata_v{N+1}.json` — AUC, log-loss, N, feature list, training date, regime breakdown
3. INSERT to `ml_models` table with `is_active=FALSE` (shadow candidate)
4. Log validation metrics to Prometheus gauges
5. If validation passes promotion gate: set `is_active=TRUE`, deactivate previous version
6. If validation fails: keep previous version active, log `ml_retrain_failed` alert

### ml_models Table Schema

```sql
CREATE TABLE ml_models (
    id              SERIAL PRIMARY KEY,
    model_name      TEXT         NOT NULL,  -- 'lgbm_global', 'lgbm_regime0', 'xgb_global'
    version         INT          NOT NULL,
    trained_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    training_rows   INT          NOT NULL,
    oos_auc         DOUBLE PRECISION NOT NULL,
    oos_log_loss    DOUBLE PRECISION NOT NULL,
    oos_brier       DOUBLE PRECISION NOT NULL,
    pearson_r       DOUBLE PRECISION,
    pearson_p       DOUBLE PRECISION,
    feature_list    JSONB        NOT NULL,
    shap_top10      JSONB,       -- top 10 SHAP feature importances
    is_active       BOOLEAN      NOT NULL DEFAULT FALSE,
    is_shadow       BOOLEAN      NOT NULL DEFAULT TRUE,
    model_path      TEXT         NOT NULL,
    metadata        JSONB,
    UNIQUE (model_name, version)
);
```

---

## Integration with CIS Pipeline

### Integration Pattern: Parallel Track with Multiplicative Blending

**Confidence: HIGH** (most coherent with existing architecture and shadow-first principle)

**Do NOT:**
- Replace CIS with ML score — CIS is well-understood, debuggable, and production-proven
- Use ML as a hard gate (ML < threshold → suppress signal) — gates without sufficient statistical validation reduce signal volume without proven benefit

**Do:**
- Run ML scorer as a parallel output that produces `ml_score ∈ [0,1]`
- Store `ml_score` in `signal_ledger` during shadow phase
- After promotion: apply as a multiplicative modifier to `calibrated_confidence`

### Shadow Phase (Weeks 1-8)

```python
# In signal_generator_service.py, after signal fire and CIS scoring:
if ml_scorer.is_ready():
    ml_score = ml_scorer.score(features, hmm_regime, hmm_regime_prob)
    # Shadow: log to signal_ledger, do NOT modify confidence or ranking
    signal["ml_score"] = ml_score
    signal["ml_model_version"] = ml_scorer.active_version
```

Signal ledger columns to add (migration 040):
```sql
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS ml_score DOUBLE PRECISION;
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS ml_model_version INT;
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS ml_top_features JSONB;
```

### Live Phase (after promotion gate)

```python
# Blending: CIS calibrated_confidence is primary, ML is a multiplicative modifier
# Blend weight α is tunable (start at 0.2, increase after 90d validation)
ML_BLEND_ALPHA = 0.20  # Setting, not hardcoded

blended = calibrated_confidence * (1 - ML_BLEND_ALPHA) + ml_score * ML_BLEND_ALPHA

# Alternatively: geometric mean for more conservative blending
blended = calibrated_confidence ** (1 - ML_BLEND_ALPHA) * ml_score ** ML_BLEND_ALPHA
```

**Why multiplicative (not additive replacement):**
- CIS is trained on the same data with isotonic calibration — adding ML additively double-counts the information
- Multiplicative blending as a modifier respects that CIS already captures most of the signal
- α=0.20 means CIS drives 80% of the rank; ML provides a 20% overlay

### Aggregator Integration

The aggregator currently sorts by `calibrated_confidence` (after Kalman filter + isotonic calibration + TOD multiplier). ML blending integrates at this final step:

```
CIS → Kalman filter → isotonic calibration → TOD multiplier → ML blend → aggregator sort
```

The `adjusted_rank` in `all_ranked` becomes the sort key. ML blend modifies `calibrated_confidence` before ranking — it does not add a new sort dimension.

### Inference Latency Budget

ML inference must not block the hot path. The signal pipeline has a ~seconds latency budget.

- LightGBM DART inference: ~0.5-2ms per prediction (batch of 1 feature row)
- SHAP computation: ~5-20ms for top-5 features with TreeExplainer
- Total ML overhead: < 25ms — acceptable for 1m bars (60-second cadence)

Run ML scorer in the signal generator's async task, not blocking the indicator pipeline. SHAP computation is optional at inference time — compute only when `is_shadow=FALSE` AND signal passes dual fire gate.

---

## Validation and Promotion Gate

### Metrics Required for Promotion

All conditions must be met simultaneously:

| Metric | Threshold | Rationale |
|--------|-----------|-----------|
| OOS AUC | >= 0.56 | Above random (0.50); meaningful edge without overfit |
| OOS log-loss | < 0.685 | Random binary classifier log-loss ≈ ln(2) = 0.693 |
| OOS Brier score | < 0.25 | Perfect = 0.0, random = 0.25; must beat baseline |
| Pearson r (predicted vs actual win rate, bucketed) | > 0.20, p < 0.05 | Calibration correlation consistent with Renaissance p < 0.05 gate |
| Win rate lift (ML_score > 0.6 vs all signals) | > +3% | Signals the model adds tradeable edge |
| Regime-specific AUC (each active regime model) | >= 0.54 | Weaker threshold because N is smaller |

### Out-of-Sample Validation Procedure

```python
# 1. Temporal holdout: last 15 days of training window, never touched during training
X_oos, y_oos = last_15d_data()

# 2. Walk-forward AUC (5 folds)
auc_scores = []
tscv = TimeSeriesSplit(n_splits=5, test_size=2000)
for train_idx, test_idx in tscv.split(X_75d):
    model = train_lgbm(X_75d.iloc[train_idx], y_75d.iloc[train_idx])
    auc_scores.append(roc_auc_score(y_75d.iloc[test_idx], model.predict_proba(...)[:,1]))
mean_cv_auc = np.mean(auc_scores)

# 3. Final holdout evaluation
final_model = train_lgbm(X_90d, y_90d)  # full 90-day model
oos_auc = roc_auc_score(y_oos, final_model.predict_proba(X_oos)[:,1])

# 4. Lift analysis
high_conf_mask = scores_oos > 0.60
lift = y_oos[high_conf_mask].mean() - y_oos.mean()

# 5. Pearson correlation (calibration check — Renaissance gate)
from scipy.stats import pearsonr
win_rate_by_bucket = bucket_predictions_by_decile(scores_oos, y_oos)
r, p = pearsonr(win_rate_by_bucket["predicted"], win_rate_by_bucket["actual"])
```

### Promotion Gate Execution

The promotion gate runs inside `weight_updater.py` alongside the existing CIS weight update and isotonic calibration. It checks the `ml_models` table for the newest shadow version and evaluates it. This keeps the retraining loop co-located.

```
weight_updater.py (30-min systemd timer):
  1. run_weight_update()           — CIS weights (existing)
  2. run_calibration_update()      — isotonic calibration (existing)
  3. run_ml_promotion_check()      — NEW: evaluate shadow ML models, promote if gate passes
```

### Ongoing Monitoring (Post-Promotion)

- Prometheus gauge: `ml_model_oos_auc{model_name}` — updated on each retrain
- Prometheus gauge: `ml_signal_win_rate_7d{score_bucket}` — rolling 7-day win rate per ML score bucket
- Alert: if `ml_model_oos_auc` drops below 0.52 for 2 consecutive retrains → revert to global model, emit `ml_degradation_alert`
- CUSUM monitor: extend existing `CUSUMMonitor` to track ML-scored signal win rate vs baseline

---

## Pitfalls and Prevention

### Critical Pitfalls

**Pitfall 1: Lookahead Bias in Feature Construction**
- **What goes wrong:** Using bar features that are computed using data not available at signal fire time. Common examples: VWAP computed at bar close (uses full bar volume), session POC recomputed retroactively, or future bar indicators in lag features.
- **Why it happens:** JSONB features in `intelligence_features` are written by `feature_writer_service` per bar. The bar data is fully available when written, but the feature must reflect what was known at signal fire time (mid-bar), not at bar close.
- **Prevention:** In `signal_features` hypertable (already schema'd), store the feature snapshot at signal fire time (mid-bar). Use `signal_features.feature_value` NOT `intelligence_features.i1...` for bar-of-signal features. For prior-bar features (lag-1), use `intelligence_features` for the bar before signal fire (feature_ts - 1 bar interval).
- **Detection:** If model AUC in walk-forward CV is > 0.70 on 90 days of data, suspect lookahead — real-world financial ML rarely exceeds 0.62-0.65 AUC.

**Pitfall 2: Target Leakage from Signal Metadata**
- **What goes wrong:** Including in features any field from `signal_ledger` that is computed AFTER signal fire: `mae`, `mfe`, `bars_in_trade`, `activation_price`, `zone_entry_pct`. These exist only after lifecycle resolution — using them to predict outcome = direct label leakage.
- **Prevention:** Enforce a strict feature whitelist in `feature_builder.py`. All features must come from `intelligence_features` (bar features at or before signal fire time) OR from `signal_features` (fire-time snapshot). Never read `signal_ledger` columns beyond the filtering keys (`signal_id`, `symbol`, `timeframe`, `computed_at`).

**Pitfall 3: Regime Shift — Model Trained in One Regime Predicting Another**
- **What goes wrong:** A model trained on 90 days of trending market data (2023 bull run type behavior) is deployed into a ranging/choppy regime. Win rate degrades 15-20%, but the model scores signals high because trending-regime feature patterns look "familiar."
- **Prevention:**
  1. Per-regime models — ranging-regime model trained only on ranging bars cannot apply trend-era patterns
  2. Drift monitor (already deployed) — KS test on feature distributions. When p < 0.01, trigger ad-hoc retrain
  3. Rolling training window (90 days, not full history) — old regime data ages out after 3 months
  4. CUSUM on ML model win rate — if win rate drops by > 5pp vs rolling baseline, auto-revert to global model

**Pitfall 4: Overfitting to Setup-Plugin Distribution**
- **What goes wrong:** If 60% of training signals are from TrendFollowing and VWAPDeviation, the model learns to rank these setups higher regardless of feature quality — it's learning a setup identity, not signal quality.
- **Prevention:** Stratified sampling by `setup_plugin` when building the training set. Limit any single plugin to 15% of training rows. This forces the model to learn feature patterns, not plugin identities.
- **Detection:** Check SHAP values — if `setup_plugin` (one-hot encoded) appears in the top-5 features, the model has memorized plugin identity. Remove `setup_plugin` from the feature matrix entirely.

**Pitfall 5: Class Imbalance Producing Trivial Predictions**
- **What goes wrong:** Overall signal win rate is ~40-50% but regime-0 (ranging) signals may have 30% win rate and regime-1 (trending) may have 55%. A model trained without class weighting learns to predict "win" for trending and "loss" for ranging, then appears to "work" but adds no value beyond regime labeling.
- **Prevention:** Use `class_weight="balanced"` in LightGBM. Evaluate with Brier score and log-loss (proper scoring rules), not accuracy. A 90% accuracy classifier that predicts the majority class constantly is worthless.

### Moderate Pitfalls

**Pitfall 6: SHAP Computation Blocking Hot Path**
- SHAP TreeExplainer can take 5-50ms per prediction depending on tree depth and N estimators
- Prevention: Compute SHAP only in background task, not inline in signal pipeline. Write to `signal_ledger.ml_top_features` asynchronously. Use a sampling rate (e.g., every 5th signal) during shadow phase.

**Pitfall 7: Stale Model Serving After Retraining Failure**
- If the weekly retrain fails (e.g., DB query timeout, insufficient N), the previous model version continues to serve — this is correct behavior. But if N drops below 500 (e.g., after pipeline reset), the model should be suspended, not kept active.
- Prevention: Check `N_training_rows` in `ml_models` at every inference cycle. If the active model was trained on < 500 rows, fall back to CIS-only scoring (ML blend weight = 0.0).

**Pitfall 8: Hyperparameter Overfitting (Optuna)**
- Running Optuna on the same data used for model validation produces hyperparameters that are optimized for the validation set — this is a second form of lookahead.
- Prevention: Run Optuna ONCE at initial model creation on the first 60 days of data. Freeze hyperparameters. Only re-run Optuna if mean CV AUC drops > 0.03 over 4 consecutive weekly retrains, indicating a structural regime shift requiring a new feature space.

### Minor Pitfalls

**Pitfall 9: Forgetting to Exclude Shadow Signals**
- Training on `is_shadow=TRUE` signals includes counterfactual signals that never activated — their outcomes are valid for research but should not be mixed with live signal training data without a clear flag.
- Prevention: Always filter `WHERE is_shadow = FALSE` in the training query. Build a separate shadow-signal analysis dataset as a validation artifact.

**Pitfall 10: ADF Test on Regime-Stratified Samples**
- Running ADF on the full dataset may reject unit root for features that are only stationary within regimes. In a ranging regime, RSI oscillates tightly (stationary). In a trending regime, RSI may drift 70-90 for days (non-stationary).
- Prevention: Run ADF separately on each regime stratum. A feature that fails ADF in any single regime should be differenced or dropped from that regime's model.

### Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Feature extraction from JSONB | Missing keys → NaN → imputed as 0 → model learns "NaN pattern" | Explicit default dict with sentinel values; log missing feature frequency |
| Initial training with N < 1000 | Model overfits to the few signal patterns present | Use global model only; defer per-regime until N_regime >= 500 |
| Enabling ML blend in aggregator | Correlated with CIS → double-counting momentum-type signals | Start with alpha=0.10, increase incrementally after 30-day validation |
| SHAP for dashboard display | Top-5 features per signal require ~20ms — real-time budget exceeded | Async batch SHAP computation after signal lifecycle resolution |
| Drift alert + retrain loop | Drift triggers retrain; retrain model trained on drifted data → oscillation | Retrain uses full 90-day window including stable history, not just recent drifted window |

---

## Implementation Order

This sequence minimizes risk by building infrastructure before enabling live influence.

### Wave 1: Data Infrastructure (Prerequisites)

1. **Migration 040:** Add `ml_score`, `ml_model_version`, `ml_top_features` to `signal_ledger`. Add `ml_models` table. No code changes to pipeline.

2. **`src/intelligence/ml/feature_builder.py`:** Flat feature matrix from JSONB tiers. Include ADF gate (cached result). Unit-tested against known feature shapes.

3. **`src/intelligence/ml/stationarity.py`:** `adf_gate()` function + `build_stationary_feature_list()`. Run once offline to produce the approved feature list that gets stored in `metadata_v{N}.json`.

4. **`src/intelligence/ml/model_store.py`:** joblib save/load + `ml_models` DB table reader/writer. Atomic file write pattern (write to `.tmp`, then `os.rename`).

### Wave 2: Model Training Pipeline

5. **`src/intelligence/ml/signal_scorer.py`:** `LGBMSignalScorer` class with `train()`, `predict_proba()`, `explain()` (SHAP top-5). Handles global + per-regime model routing.

6. **`production/scripts/train_ml_scorer.py`:** Standalone training script. Reads from TimescaleDB, builds feature matrix, trains all models, evaluates promotion gate, writes to `ml_models` table. Runnable offline: `python production/scripts/train_ml_scorer.py --dry-run`.

7. **Systemd timer `indicagent-ml-scorer-train.timer`:** Weekly Sunday 02:00, `Persistent=true`. Unit: `indicagent-ml-scorer-train.service` (oneshot). Identical pattern to existing weight-updater timer.

### Wave 3: Shadow Integration

8. **Integrate into `weight_updater.py`:** After `run_calibration_update()`, call `run_ml_promotion_check()`. This checks if a new shadow model exists, evaluates it, promotes if gate passes.

9. **Integrate into `signal_generator_service.py`:** After CIS scoring, if `ml_scorer.is_ready()`, call `score()` and attach `ml_score` to signal dict. Write to `signal_ledger` in shadow mode (`ml_score` stored, no influence on `calibrated_confidence` or ranking).

10. **Dashboard drill panel:** Display `ml_score` alongside `raw_cis_score`/`filtered_cis_score`/`calibrated_confidence` trio. Already has the three-field pattern — extend to four fields.

### Wave 4: Live Promotion (after 8 weeks shadow, gate passed)

11. **Enable ML blend in aggregator:** Introduce `ML_BLEND_ALPHA = 0.20` Setting. Aggregator computes `blended_confidence = calibrated_confidence * (1 - alpha) + ml_score * alpha`. Sort by `blended_confidence`. This is a one-line change to the aggregator once the ML scorer is trusted.

12. **Prometheus metrics service (`src/observability/ml_metrics.py`):**
    - `ml_model_oos_auc{model_name}`
    - `ml_signal_win_rate_7d{score_bucket}`
    - `ml_model_training_rows{model_name}`
    - `ml_inference_duration_seconds` (histogram)

13. **Extend KS drift monitor:** Add ML feature distribution to the existing drift baseline. When KS drift triggers on ML input features, emit `ml_drift_alert` and schedule ad-hoc retrain.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Library stack (LightGBM 4.6, XGBoost 3.2, SHAP 0.51) | HIGH | Verified via PyPI and official release pages, March 2026 |
| Regime-specific model architecture | HIGH | Consistent with QuantInsti research doc in codebase; literature confirmed |
| Walk-forward design | HIGH | Standard financial ML practice; verified via QuantInsti + arxiv 2025 paper |
| ADF feature stationarity classification | MEDIUM | Bounded oscillators (RSI, Stochastic) confirmed stationary; ATR/MACD require empirical verification on this dataset |
| ML blend alpha (0.20) | MEDIUM | Starting value based on practice; will require empirical tuning after shadow phase |
| N=500 per-regime gate | MEDIUM | Derived from statistical power analysis; validate with actual signal accumulation rate at 90 days |
| Inference latency (< 25ms) | MEDIUM | LightGBM DART benchmarks suggest this; verify on actual server hardware against live service load |

---

## Sources

- [LightGBM 4.6.0 documentation](https://lightgbm.readthedocs.io/en/latest/) — confirmed current version and DART mode
- [XGBoost 3.2.0 PyPI](https://pypi.org/project/xgboost/) — confirmed Python 3.13 support, Feb 2026 release
- [SHAP 0.51.0 PyPI](https://pypi.org/project/shap/) — confirmed current version, Mar 2026
- [QuantInsti — Regime-Adaptive Trading with HMM and Random Forest](https://blog.quantinsti.com/regime-adaptive-trading-python) — cited in `docs/ideas/regime-adaptive-trading.md`; walk-forward + stationarity protocol
- [arxiv 2512.12924 — Interpretable Hypothesis-Driven Trading: Walk-Forward Validation](https://arxiv.org/abs/2512.12924) — rigorous walk-forward framework, 2025
- [Analytics Vidhya — Gradient Boosting comparison](https://www.analyticsvidhya.com/blog/2026/02/gradient-boosting-vs-adaboost-vs-xgboost-vs-catboost-vs-lightgbm/) — LightGBM vs XGBoost comparison, Feb 2026
- [MDPI — GT-Score for overfitting reduction](https://www.mdpi.com/1911-8074/19/1/60) — financial ML overfitting pitfalls
- Internal: `docs/ideas/regime-adaptive-trading.md`, `docs/ideas/jim-simons-renaissance-principles.md`, `docs/ideas/ml-classification-pattern-recognition.md`
