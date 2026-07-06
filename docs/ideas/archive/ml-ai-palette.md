# ML/AI Technology Palette — Research, Rationale, and Decisions

**Version:** 1.0
**Status:** under-review
**Priority:** medium
**Milestone:** future
**Last Updated:** 2026-04-08
**Tags:** ml, ai, technology, lightgbm, pydantic-ai, sklearn, research, decision-framework

---

## Philosophy: The Right Tool for the Job

Renaissance demands: **Use the simplest tool that works.** Every technology choice must answer: "What problem does this solve better than the alternatives?" and "When will we know it's the wrong choice?"

This document captures the **reasoning behind our choices** so future decisions are grounded in research, not trends. When someone asks "why not PyTorch?" or "should we add Ray?", the answer is already here.

**How to use this:**
- **Evaluate new tools** — Before adding something new, check if an existing tool already solves the problem
- **Revisit decisions** — The "When to Reconsider" section tells you when a choice has outlived its purpose
- **Onboarding** — New team members understand not just WHAT we use, but WHY

---

## Categories

- [Models & Algorithms](#models--algorithms)
- [Statistics & Validation](#statistics--validation)
- [Feature Engineering](#feature-engineering)
- [Data Processing](#data-processing)
- [Infrastructure & Orchestration](#infrastructure--orchestration)
- [What We Don't Use (And Why)](#what-we-dont-use-and-why)

---

## Models & Algorithms

### LightGBM

**What it is:** Gradient boosting framework for tabular data. Tree-based ensemble that learns decision rules sequentially.

**Strengths:**
- **Dominates tabular benchmarks** — Consistently beats deep learning on structured/tabular data
- **Fast training** — 10-100× faster than XGBoost on large datasets
- **Handles categoricals natively** — No one-hot encoding needed (regime, setup_type, timeframe stay as-is)
- **Memory efficient** — Histogram-based algorithm, lower memory footprint
- **GPU optional** — CPU training is already fast; GPU only helps for massive datasets (>1M rows)
- **Explainable** — SHAP values computed efficiently via TreeSHAP

**Weaknesses:**
- **Not deep learning** — Can't learn hierarchical patterns in unstructured data (images, text, audio)
- **Manual hyperparameter tuning** — `num_leaves`, `learning_rate`, `feature_fraction` matter
- **Overfitting risk on noisy data** — Financial time series are noisy; requires careful validation
- **Feature engineering still matters** — Doesn't automatically discover interactions like neural networks
- **Small data limitation** — Needs >1K samples to shine; below that, simpler models win

**Why we chose it:**
1. **Our data is tabular** — Time-series features (RSI, ATR, regime) → tabular, not images/text
2. **Benchmark dominance** — Kaggle tabular competitions won by gradient boosting, not neural nets
3. **Speed** — Weekly retraining on 100K+ signals must complete in <30 minutes
4. **Categorical support** — Regime (0/1/2), setup_type (36 classes), timeframe (4 classes) handled natively
5. **Explainability** — Renaissance demands attribution; SHAP values tell us WHY a signal was scored high

**Intended use:**
- **Phase 54 (ML Scoring Model)** — Per-regime × per-setup × per-TF ensemble models
- **Feature importance discovery** — `feature_importances_` and SHAP values drive data-driven plugin development
- **Walk-forward validation** — Rolling retrain preserves causality (no lookahead)

**When to reconsider:**
- **Adding unstructured data** — If we ingest news sentiment (text), options chain surface images, or audio (earnings calls)
- **Deep learning beats benchmarks** — If neural networks consistently show ρ > 0.5 vs LightGBM's ρ = 0.3 on same features
- **Need hierarchical feature learning** — If hand-engineered features plateau and we need automatic feature discovery
- **Signal type changes** — If we move from price-based signals to something graph-based (correlation networks, limit order book graphs)

**Alternatives we considered:**
| Alternative | Why we didn't choose it |
|-------------|------------------------|
| XGBoost | LightGBM trains faster, handles categoricals natively; both are good, LightGBM wins on our scale |
| CatBoost | Excellent for categoricals, but slower training and heavier dependency |
| Random Forest | No gradient boosting → lower predictive power; we use RF for discovery only (feature importance) |
| PyTorch/TensorFlow | Overkill for tabular; overfitting risk higher; training slower; unnecessary complexity |

---

### Random Forest (scikit-learn)

**What it is:** Ensemble of decision trees trained via bagging. Each tree votes; majority wins.

**Strengths:**
- **Feature importance** — Built-in `feature_importances_` attribute reveals what drives predictions
- **Robust to overfitting** — Bagging reduces variance compared to single decision trees
- **Handles non-linear relationships** — No assumption of linearity
- **Fast inference** — Once trained, prediction is O(log n) per tree
- **Minimal preprocessing** — No feature scaling required

**Weaknesses:**
- **Not the strongest predictor** — Gradient boosting (LightGBM) usually beats RF on accuracy
- **Memory intensive** — Stores all trees in memory (100-200 trees × depth)
- **No online learning** — Can't update incrementally; must retrain from scratch
- **Correlated features** — Doesn't handle highly correlated features well (our I1 indicators have correlation)

**Why we chose it:**
1. **Feature importance discovery** — Tells us which of 85+ features actually matter (I4 regime vs I5 patterns)
2. **Baseline for LightGBM** — RF establishes floor; if RF can't find signal, neither will LightGBM
3. **Interpretability** — Can inspect individual trees to understand decision rules
4. **Low risk** — Mature, stable, unlikely to have bugs

**Intended use:**
- **Phase 1 (Discovery)** — One-off analysis: `train_random_forest()`, extract `feature_importances_`
- **Dead code detection** — Features with importance < 0.01 are candidates for removal
- **Plugin prioritization** — Focus dev effort on high-impact tiers/features
- **Not for production** — LightGBM replaces RF for real-time scoring

**When to reconsider:**
- **LightGBM feature importance available** — Once LightGBM is trained, RF importance is redundant
- **Permutation importance preferred** — `sklearn.inspection.permutation_importance` is more robust than RF's default importance

**Alternatives we considered:**
| Alternative | Why we didn't choose it |
|-------------|------------------------|
| Gradient Boosting (LightGBM) | Better for production; RF kept for discovery only |
| Permutation Importance (sklearn) | More robust but slower; we use it for validation, not discovery |

---

## Statistics & Validation

### scipy.stats

**What it is:** Core scientific computing library for statistical tests, distributions, and correlation analysis.

**Strengths:**
- **Pearson correlation** — `pearsonr()` returns correlation coefficient + p-value
- **Significance testing** — T-tests, chi-square, KS test, ANOVA
- **Distributions** — 100+ probability distributions (normal, t, chi-square, etc.)
- **Mature, stable** — Decades of development, battle-tested
- **Lightweight** — No heavy dependencies

**Weaknesses:**
- **Not time-series aware** — Doesn't handle autocorrelation, stationarity tests (use statsmodels)
- **Basic only** — No advanced ML metrics (AUC-ROC, log loss) — use sklearn for those
- **Slow for large data** — Pearson r on 1M rows is slower than optimized implementations

**Why we chose it:**
1. **Phase 2 (The Validator)** — `scipy.stats.pearsonr()` is the foundation of correlation gates
2. **P-values** — `pearsonr()` returns significance test automatically
3. **No dependencies** — Already installed with numpy; no new bloat
4. **Standard** — Scientific Python standard; well-documented

**Intended use:**
- **Shadow correlation analysis** — Daily job: `pearsonr(shadow_predictions, realized_pnl_r)`
- **Significance testing** — Verify that correlation isn't due to chance (p < 0.05)
- **Basic stats** — Mean, std, percentile for data quality checks

**When to reconsider:**
- **Time-series tests needed** — Use `statsmodels.tsa` for stationarity, autocorrelation
- **ML metrics needed** — Use `sklearn.metrics` for AUC-ROC, log loss, confusion matrix
- **Large-scale correlation** — Polars or numpy operations faster for >1M rows

**Alternatives we considered:**
| Alternative | Why we didn't choose it |
|-------------|------------------------|
| numpy.corrcoef | Doesn't return p-value; scipy does both in one call |
| statsmodels | Overkill for simple correlation; use statsmodels for time-series tests |
| pingouin | Additional dependency; scipy covers 95% of our needs |

---

### statsmodels

**What it is:** Statistical modeling library for time series analysis, regression, and hypothesis testing.

**Strengths:**
- **Stationarity tests** — Augmented Dickey-Fuller (ADF) test for unit roots
- **CUSUM changepoint** — Detect structural breaks in time series
- **Time-series models** — ARIMA, VAR, state space models
- **Regression diagnostics** — Heteroskedasticity, autocorrelation, multicollinearity tests
- **Comprehensive output** — P-values, confidence intervals, model summaries

**Weaknesses:**
- **Slow** — Pure Python in some paths, not optimized like scipy
- **Complex API** — Steeper learning curve than scipy
- **Overkill for simple tests** — Don't need it for basic correlation

**Why we chose it:**
1. **Stationarity validation** — ADF test ensures features aren't spurious (random walks look predictive but aren't)
2. **CUSUM changepoint** — Detect regime shifts, distribution drift in features
3. **Time-series awareness** — Handles autocorrelation, lags, seasonality correctly
4. **Academic standard** — Used in quantitative finance research

**Intended use:**
- **Feature validation** — ADF test on each feature before ML training
- **Drift detection** — CUSUM catches when feature distribution shifts (triggers retrain)
- **Time-series analysis** — If we add ARIMA/VAR models later

**When to reconsider:**
- **Performance bottleneck** — If ADF tests become slow, use faster approximations
- **Simple correlation only** — Use scipy for basic Pearson r, no need for statsmodels

**Alternatives we considered:**
| Alternative | Why we didn't choose it |
|-------------|------------------------|
| arch (library) | Specialized for volatility modeling; we don't need GARCH beyond what we have |
| pmdarima | Auto-ARIMA; we're not doing classical time-series forecasting |
| custom ADF | Reinventing the wheel; statsmodels is battle-tested |

---

### alphalens-reloaded

**What it is:** Quant-standard library for factor analysis. Computes Information Coefficient (IC), ICIR, decay, turnover — the metrics that matter for signal quality.

**Strengths:**
- **Quant-standard metrics** — IC (prediction correlation), ICIR (information ratio), decay (how long signal persists)
- **Forward returns** — Correctly computes forward returns for N bars (avoids lookahead)
- **Grouping** — Analyze IC by regime, sector, timeframe
- **Mature** — Based on Quantopian's alphalens; used by professional quants
- **Prevents lookahead** — Strict about temporal ordering

**Weaknesses:**
- **Pandas-centric** — Designed for pandas DataFrames; slower than polars
- **Finance-specific** — Not general-purpose; built for price prediction
- **Learning curve** — Requires understanding of quant metrics (IC, ICIR, turnover)
- **Documentation** — Not as user-friendly as sklearn

**Why we chose it:**
1. **Renaissance standard** — IC/ICIR are the metrics quants use, not accuracy/AUC
2. **Prevents lookahead bugs** — Handles forward returns correctly (easy to mess up manually)
3. **Feature ranking** — `factor_returns` tells us which features have predictive power
4. **Regime analysis** — Compute IC per HMM regime (0/1/2) to detect regime-specific alphas

**Intended use:**
- **Beta Pipeline (Discovery)** — Weekly job: compute IC for all 85 features by regime
- **Feature selection** — Drop features with IC < 0.05 (no predictive power)
- **Regime-specific validation** — Feature A may work in trending regime (IC=0.15) but fail in ranging (IC=-0.05)
- **Decay analysis** — How long does signal persist? (1 bar? 5 bars?)

**When to reconsider:**
- **Performance bottleneck** — If alphalens becomes slow, rewrite core logic in polars
- **Non-finance use** — Only for time-series prediction; wrong tool for classification/regression

**Alternatives we considered:**
| Alternative | Why we didn't choose it |
|-------------|------------------------|
| sklearn.metrics | Doesn't have IC/ICIR; built for classification, not quant finance |
| Custom IC calculation | Reinventing the wheel; alphalens handles edge cases (lookahead, grouping) |
| SHAP values | Complementary to alphalens; SHAP explains per-signal, alphalens explains overall feature |

---

## Feature Engineering

### tsfresh

**What it is:** Automatic time series feature extraction. Generates 700+ statistical features from any time series (mean, variance, entropy, autocorrelation, etc.).

**Strengths:**
- **Massive feature library** — 700+ features computed automatically
- **Handles irregular sampling** — Works with unevenly spaced time series
- **Relevant features only** — `select_features()` filters to statistically significant ones
- **Domain-agnostic** — Doesn't need finance knowledge; finds patterns in any time series
- **Parallelizable** — Multi-core processing for large datasets

**Weaknesses:**
- **Compute-intensive** — Full extraction on 100K bars × 85 features = hours
- **Many spurious features** — 700 features → most are noise; requires careful filtering
- **Black-box** — Hard to interpret what "histogram_number_peaks" means in finance terms
- **Lookahead risk** — Must ensure features are computed causally (no future data)

**Why we chose it:**
1. **Data-driven discovery** — "Let the data speak" vs hand-engineering features
2. **Novel patterns** — May find features we haven't considered (e.g., "time_series_synopsis_rhythm")
3. **Renaissance-aligned** — Validates hypotheses with data, not intuition
4. **Feature saturation** — If tsfresh finds nothing, we know we've exhausted the feature space

**Intended use:**
- **Beta Pipeline (Discovery)** — Weekly job: extract tsfresh features on recent bars
- **Hypothesis generation** — "Does `attr_autocorrelation__lag_10` predict outcomes?"
- **Feature augmentation** — Add top tsfresh features to our 85 hand-engineered features
- **Regime-specific discovery** — Run tsfresh separately per regime

**When to reconsider:**
- **Performance bottleneck** — If extraction takes >2 hours, curtail feature set
- **All features fail IC test** — If none beat IC=0.05, tsfresh isn't finding signal in this data
- **Interpretability required** — If we need explainable features for regulatory reasons

**Alternatives we considered:**
| Alternative | Why we didn't choose it |
|-------------|------------------------|
| Manual feature engineering | Limited by human imagination; tsfresh explores systematically |
| Feature tools (Facebook) | Similar but less comprehensive; tsfresh is domain-agnostic |
| Deep feature synthesis | Automated feature composition; heavier dependency, similar result |

---

### SHAP (SHapley Additive exPlanations)

**What it is:** Game theory-based approach to explain model predictions. Computes per-feature contribution to each prediction.

**Strengths:**
- **Per-signal attribution** — "Why was THIS signal scored 0.82?" → "RSI divergence (+0.15), regime bullish (+0.12), FVG proximity (-0.05)"
- **Theoretically sound** — Based on Shapley values (fair division of credit)
- **TreeSHAP is fast** — Optimized for tree models (LightGBM, RF); exact computation, not approximation
- **Global + local** — Aggregate explanations (overall feature importance) + individual explanations
- **Renaissance-aligned** — "Show me the data" → per-signal transparency

**Weaknesses:**
- **Computationally expensive** — For non-tree models, uses approximation (KernelSHAP)
- **Interpretation burden** — 85 features × 100 signals/day = 8,500 explanations to review
- **Doesn't fix bad models** — Explains predictions, doesn't improve them
- **Additive assumption** — Assumes feature contributions are independent (violated if features correlated)

**Why we chose it:**
1. **Per-signal debugging** — When a questionable signal fires, SHAP explains why
2. **Regulatory requirement** — "Why was this position sized at 1.8×?" → SHAP provides audit trail
3. **Feature validation** — If "VIX regime" has SHAP = 0.01, it's not contributing
4. **Trust building** — Traders more likely to trust ML when they can see the reasoning

**Intended use:**
- **Phase 54 (ML Scoring)** — Store `shap_values` JSONB in `ml_signal_scores` table
- **Dashboard display** — Show top 5 SHAP contributors per signal card
- **Feature importance** — Aggregate SHAP values across all signals to rank features
- **Model comparison** — Compare SHAP patterns between LightGBM and baseline

**When to reconsider:**
- **SHAP never used** — If traders never look at SHAP values, drop it
- **Performance bottleneck** — If TreeSHAP adds >5ms to inference latency
- **Simpler model sufficient** — If top 3 features always drive 90% of prediction, just show those

**Alternatives we considered:**
| Alternative | Why we didn't choose it |
|-------------|------------------------|
| LIME | Local approximation; less theoretically sound than SHAP |
| Permutation importance | Global only; no per-signal explanation |
| Feature importance (LightGBM) | Global only; doesn't explain individual predictions |

---

## Data Processing

### polars

**What it is:** Rust-based DataFrame library. 10-100× faster than pandas for batch operations.

**Strengths:**
- **Performance** — Rust implementation, multithreaded, zero-copy where possible
- **Memory efficient** — Lower memory footprint than pandas
- **Lazy evaluation** — Query optimization (like SQL query planner)
- **Apache Arrow native** — Zero-copy interoperability with PyArrow, Parquet
- ** pandas-like API** — Familiar syntax, low learning curve

**Weaknesses:**
- **Smaller ecosystem** — Fewer third-party libraries than pandas
- **Not real-time** — Batch operations only; wrong tool for per-bar inference
- **Learning curve** — Some operations differ from pandas (group_by, aggregations)
- **Debugging harder** — Rust backtraces less readable than Python

**Why we chose it:**
1. **Feature matrix building** — Join `intelligence_features` + `signal_ledger` for 100K bars: polars does this in seconds, pandas in minutes
2. **Weekly retraining** — Feature extraction for ML must complete in <30 minutes
3. **Scalability** — Handles 1M+ rows without memory issues
4. **Future-proof** — Rust-based projects are the future of Python data tools

**Intended use:**
- **Feature matrix jobs** — Build training data from TimescaleDB
- **Backfill scripts** — Process historical data in batches
- **Discovery pipeline** — tsfresh → polars → LightGBM

**When to reconsider:**
- **Real-time inference** — Use NumPy for per-signal predictions (<5ms)
- **Simple operations** — For <1K rows, pandas is fine
- **Library compatibility** — If a library only supports pandas, convert upstream

**Alternatives we considered:**
| Alternative | Why we didn't choose it |
|-------------|------------------------|
| pandas | Too slow for batch jobs; 10-100× slower than polars |
| dask | Distributed computing overkill; we're single-machine |
| vaex | Similar to polars but smaller ecosystem; polars has more momentum |

---

### NumPy

**What it is:** Foundational package for numerical computing in Python. N-dimensional arrays, fast linear algebra.

**Strengths:**
- **Ubiquitous** — Every ML library (scipy, sklearn, LightGBM) builds on NumPy
- **Fast vectorized operations** — C-level loops, 10-100× faster than Python lists
- **Memory efficient** — Contiguous arrays, cache-friendly
- **Mature** — Decades of development, battle-tested
- **Real-time capable** — Single-signal inference: <1ms for typical operations

**Weaknesses:**
- **Not for batch analytics** — Use polars for large datasets
- **No high-level APIs** — Manual implementation required for group_by, joins, etc.
- **2D array limitation** — Multi-dimensional arrays exist but ergonomics suffer

**Why we chose it:**
1. **Real-time inference** — Per-signal prediction: `model.predict(features_numpy)` is <5ms
2. **Already everywhere** — No new dependency; LightGBM/shap/scipy all use NumPy
3. **Simplicity** — For single-bar operations, NumPy is simplest
4. **Performance** — Vectorized operations fast enough for our <5ms SLA

**Intended use:**
- **Real-time inference** — Convert `IntelligenceEvent` to NumPy array, predict, return multiplier
- **Feature preprocessing** — Normalization, scaling on single samples
- **Tensor operations** — Element-wise math (add, multiply, sqrt) in hot path

**When to reconsider:**
- **Batch operations** — Use polars for >1K rows
- **Complex aggregation** — Polars group_by/join easier than NumPy manual implementation

**Alternatives we considered:**
| Alternative | Why we didn't choose it |
|-------------|------------------------|
| pandas | Slower, heavier; overkill for single-bar operations |
| PyTorch tensors | Overkill; no GPU benefit for tabular inference |
| Python lists | 100× slower; NumPy is the standard |

---

## Infrastructure & Orchestration

### MLflow (self-hosted)

**What it is:** Open-source ML platform for experiment tracking, model registry, and artifact management.

**Strengths:**
- **Experiment tracking** — Compare 20 training runs: hyperparameters, metrics, artifacts
- **Model registry** — Version models, track staging → production lifecycle
- **Self-hosted** — Docker deployment, no vendor lock-in, full data ownership
- **Python SDK** — Simple API: `mlflow.log_params()`, `mlflow.log_model()`
- **UI included** — Web interface for browsing experiments, comparing runs

**Weaknesses:**
- **Heavy dependency** — Adds ~200MB to Docker image
- **Overkill for small projects** — If training 1 model, use filesystem + CSV
- **UI latency** — Web interface can be slow for large numbers of runs
- **Complexity** — Learning curve for teams unfamiliar with MLops

**Why we chose it:**
1. **Reproducibility** — Every model version tracked with exact parameters/data/hash
2. **A/B testing** — Compare LightGBM vs Random Forest, or hyperparameter variants
3. **Audit trail** — Renaissance demands: "When was this model trained? On what data?"
4. **Self-hosted** — No cloud, no SaaS fees, full control
5. **Standard** — Industry standard for open-source MLops

**Intended use:**
- **Phase 54 (ML Scoring)** — Every training run logged to MLflow
- **Model registry** — `ml_models` table stores `mlflow_run_id` for lookup
- **Hyperparameter tuning** — Optuna + MLflow: log each trial, compare results
- **Rollback** — If production model degrades, revert to previous MLflow version

**When to reconsider:**
- **Training frequency** — If we train >100x/day, MLflow UI becomes cluttered
- **Simple use case** — If only 1 model trained monthly, filesystem is sufficient
- **Performance bottleneck** — If MLflow logging adds >10% to training time

**Alternatives we considered:**
| Alternative | Why we didn't choose it |
|-------------|------------------------|
| Weights & Biases | Cloud-based, paid; MLflow is open-source |
| filesystem + CSV | No UI, manual comparison; MLflow automates this |
| Sacred | Simpler but less comprehensive; MLflow is standard |

---

### optuna

**What it is:** Bayesian hyperparameter optimization framework. Automatically searches hyperparameter space to find best model configuration.

**Strengths:**
- **Smart search** — Bayesian optimization uses past trials to guide next trial (better than grid/random search)
- **Pruning** — Stop unpromising trials early (saves time)
- **Multi-objective** — Optimize for both accuracy AND inference latency
- **Framework-agnostic** — Works with LightGBM, sklearn, PyTorch, etc.
- **Visualization** — Built-in plots for parameter importance, optimization history

**Weaknesses:**
- **Additional complexity** — Need to wrap training in `objective()` function
- **Search space design** — Must define parameter ranges (low, high) correctly
- **Overfitting risk** — Can over-optimize on validation set; need hold-out test set
- **Compute cost** — 100 trials × 30 min/trial = 50 hours of training

**Why we chose it:**
1. **Automated tuning** — No manual grid search; Optuna finds best `num_leaves`, `learning_rate`, etc.
2. **Efficiency** — Bayesian optimization finds optimum in fewer trials than grid search
3. **Renaissance-aligned** — Let the data speak, not human intuition about hyperparameters
4. **Pruning** — Stops bad trials early, saves compute

**Intended use:**
- **Phase 54 (ML Scoring)** — Hyperparameter tuning for each regime × setup × TF model
- **Multi-objective** — Optimize for (win_rate, -inference_latency)
- **Automated retraining** — Weekly cron runs Optuna, retrains models

**When to reconsider:**
- **Default parameters sufficient** — If LightGBM defaults work well, skip Optuna
- **Overfitting** — If Optuna-tuned model performs worse on test set, revert to defaults

**Alternatives we considered:**
| Alternative | Why we didn't choose it |
|-------------|------------------------|
| Grid search (sklearn) | Inefficient; Optuna finds optimum in fewer trials |
| Random search | Better than grid but worse than Bayesian |
| Manual tuning | Subject to human bias; Optuna is data-driven |

---

### evidently

**What it is:** ML monitoring library for drift detection, data quality checks, and model performance tracking.

**Strengths:**
- **Drift detection** — KS test, PSI, Wasserstein distance per feature
- **Data quality** — Missing values, duplicates, out-of-range checks
- **ML-specific metrics** — Regression performance, classification quality, ranking metrics
- **Self-hosted** — No cloud, generate HTML reports locally
- **Integration** — Works with NumPy, pandas, polars

**Weaknesses:**
- **Batch-oriented** — Runs on snapshots of data, not streaming
- **Report-heavy** — Generates HTML reports; must parse programmatically for alerts
- **Learning curve** — Concepts like PSI, Wasserstein require statistics background
- **Threshold tuning** — What KS value = "drift detected"? Requires calibration

**Why we chose it:**
1. **Automated drift detection** — Catches feature distribution shifts before they corrupt models
2. **Monitoring Agent** — MLAgent's Monitoring Agent uses evidently for checks
3. **Self-hosted** — No SaaS, run locally; fits Renaissance no-vendor-lock-in principle
4. **Quant-standard metrics** — KS/PSI are used in institutional quant finance

**Intended use:**
- **MLAgent Monitoring Agent** — Daily drift checks on feature distributions
- **Data Quality Agent** — Validate training data before model retrains
- **Alerts** — Trigger retrain when drift exceeds threshold

**When to reconsider:**
- **False alarms** — If drift detected but model performance unchanged, adjust thresholds
- **Simple use case** — If only monitoring 1 feature, manual KS test is simpler

**Alternatives we considered:**
| Alternative | Why we didn't choose it |
|-------------|------------------------|
| Custom drift detection | Reinventing the wheel; evidently is battle-tested |
| AWS SageMaker Model Monitor | Cloud-based, paid; vendor lock-in |
| Arize | SaaS; evidently is self-hosted |

---

## What We Don't Use (And Why)

### PyTorch / TensorFlow

**What they are:** Deep learning frameworks for neural networks. Industry standard for unstructured data (images, text, audio).

**Why we don't use them:**
1. **Our data is tabular** — Time-series features (RSI, ATR, regime) are structured, not images/text
2. **Gradient boosting wins** — On tabular data, LightGBM beats deep learning 95% of the time
3. **Overfitting risk** — Neural networks overfit easily on noisy financial data
4. **Training time** — Deep learning requires 10-100× more compute than LightGBM
5. **Explainability** — Neural networks are black boxes; SHAP for deep nets is slow/imprecise

**When we'd reconsider:**
- **Adding unstructured data** — News articles (text), options chain surfaces (images), earnings calls (audio)
- **Deep learning beats benchmarks** — If Transformer/CNN consistently achieves ρ > 0.5 vs LightGBM's ρ = 0.3
- **Feature learning bottleneck** — If hand-engineered features plateau and we need automatic hierarchical feature learning

**Use cases we'd use them for:**
- **Sentiment analysis** — NLP on news headlines, Twitter, earnings transcripts
- **Options chain images** — CNN for vol surface pattern recognition
- **Sequence modeling** — Transformer for multi-timeframe context (1m → 5m → 15m → 1h)

---

### Ray / Dask

**What they are:** Distributed computing frameworks. Parallelize Python code across clusters.

**Why we don't use them:**
1. **Overkill for our scale** — Polars handles 1M rows on single machine; we don't have 100M rows yet
2. **Complexity** — Distributed computing adds operational overhead (cluster management, fault tolerance)
3. **Debugging harder** — Distributed stack traces are nightmares compared to single-machine
4. **Not bottleneck** — Our bottleneck is data quality, not compute; faster processing doesn't help if data is noisy

**When we'd reconsider:**
- **Data volume** — If we exceed 10M rows per retraining job
- **Training time** — If weekly retrain takes >4 hours on single machine
- **Multi-product scale** — When we have 6+ products × 10 years of data

**Use cases we'd use them for:**
- **Hyperparameter optimization** — Parallel Optuna trials across cluster
- **Feature extraction** — tsfresh on 100K symbols (not our current scale)

---

### Feast

**What it is:** Feature store for ML. Manages feature computation, storage, and serving.

**Why we don't use it:**
1. **TimescaleDB IS our feature store** — `intelligence_features` hypertable stores all features
2. **Redundant abstraction** — Adds layer between ML code and database
3. **Additional infra** — Requires Feast service + backend store (we'd use Redis/S3)
4. **Real-time serving** — We don't need sub-10ms feature retrieval; our features are computed in hot path

**When we'd reconsider:**
- **Multi-service sharing** — If QualAgent, DerivAgent, TradeAgent all need same features
- **Real-time feature serving** — If we need <10ms feature retrieval for high-frequency strategies
- **Feature versioning** — If we need to track feature schema evolution across multiple teams

**Use cases we'd use it for:**
- **Cross-product features** — Shared feature library for all trading products
- **Point-in-time correctness** — Prevents lookahead in backtesting (feast's strength)

---

### Temporal

**What it is:** Workflow orchestration platform. Manages long-running, multi-step workflows with durability and retries.

**Why we don't use it:**
1. **LangGraph sufficient** — Our agent workflows are simple; LangGraph handles state machines
2. **Single machine** — We don't have distributed workflows yet
3. **Operational overhead** — Temporal server + DB + workers = 3 more services to run
4. **Institutional scale** — Temporal shines at 1000+ concurrent workflows; we have <10

**When we'd reconsider:**
- **Multi-day workflows** — If we have workflows that run for days and must survive restarts
- **High concurrency** — If 100+ strategy workflows run simultaneously
- **Complex retry logic** — If workflows need exponential backoff, dead letter queues
- **Regulatory requirement** — If audit trail of every workflow decision is mandatory

**Use cases we'd use it for:**
- **Strategy bot lifecycle** — Entry → monitoring → exit across multiple days with state persistence
- **Multi-stage approval** — Human-in-the-loop workflows that span days/weeks

---

## Decision Log

| Date | Tool | Decision | Rationale |
|------|------|----------|-----------|
| 2026-03-24 | LightGBM | Chosen | Dominates tabular benchmarks; fast; categorical support |
| 2026-03-24 | PyTorch/TF | Rejected | Overkill for tabular; gradient boosting wins |
| 2026-03-24 | polars | Chosen | 10-100× faster than pandas; batch jobs |
| 2026-03-24 | Ray/Dask | Rejected | Overkill for current scale; add when triggered |
| 2026-03-24 | Feast | Rejected | TimescaleDB is our feature store |
| 2026-03-24 | Temporal | Rejected | LangGraph sufficient; institutional-scale only |
| 2026-03-15 | MLflow | Chosen | Self-hosted; experiment tracking; model registry |
| 2026-03-15 | Weights & Biases | Rejected | Cloud-based; MLflow is open-source |
| 2026-03-15 | optuna | Chosen | Bayesian optimization; automated tuning |
| 2026-03-15 | alphalens-reloaded | Chosen | Quant-standard IC/ICIR; prevents lookahead |
| 2026-03-15 | tsfresh | Chosen | Auto feature extraction; data-driven discovery |

---

## How to Update This Document

When adding or removing tools:

1. **Add new tool** — Create section with: What it is, Strengths, Weaknesses, Why Chosen, Intended Use, When to Reconsider, Alternatives
2. **Update Decision Log** — Add row with date, tool, decision, rationale
3. **Cross-reference** — Update `tech-stack.md` to point to this doc for detailed rationale
4. **Commit message** — Use format: `docs: add/remove/update [tool] in ML/AI palette`

**Before adding new tools:**
- Check if existing tool already solves the problem
- Verify it aligns with Renaissance principles (simple, proven, minimal)
- Document "Why not [existing tool]?" in alternatives section

---

## Related Documentation

- `tech-stack.md` — High-level stack decisions and infrastructure
- `ai-02-ml-agent-architecture.md` — Multi-agent ML system design
- `renaissance-alpha-pipeline.md` — Validation framework and governance
- `ai-08-ml-classification-pattern-recognition.md` — Random Forest/KNN/SVM research
