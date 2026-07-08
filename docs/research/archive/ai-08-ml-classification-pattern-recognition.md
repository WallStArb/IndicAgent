# ML Classification for Pattern Recognition in IndicAgent

**Version:** 1.0
**Status:** draft
**Priority:** medium
**Milestone:** future (post-v2.8)
**Last Updated:** 2026-05-02
**Tags:** ml, classification, random-forest, knn, svm, pattern-recognition, supervised-learning

---

## Overview

This research explores integrating supervised machine learning classification algorithms (Random Forest, K-Nearest Neighbors, Support Vector Machines) into IndicAgent's intelligence tiers to enhance pattern recognition and trading signal quality.

**Context:** A collaborator (`lik`) has experience with these algorithms for recognizing profitable trading patterns and is interested in contributing pattern detection capabilities to IndicAgent.

---

## ML Algorithms Overview

### Random Forest

**What it does:** Ensemble learning method that builds multiple decision trees and combines their predictions through voting/averaging.

**Key strengths for trading:**
- **Feature importance analysis:** Can identify which technical features (RSI, ATR, volume patterns, etc.) most strongly predict outcomes
- **Handles non-linear relationships:** Captures complex interactions between indicators without manual feature engineering
- **Robust to overfitting:** Ensemble nature reduces overfitting risk compared to single decision trees
- **Handles missing values:** More resilient than some algorithms to incomplete feature vectors
- **Fast inference:** Once trained, prediction is fast (O(log n) per tree)

**Parameters of interest:**
- `n_estimators`: Number of trees (50-200 typical trading sweet spot)
- `max_depth`: Controls tree complexity (prevents overfitting)
- `min_samples_split`: Minimum samples to split node (regularization)
- `feature_importances_`: Extractable after training to understand what drives predictions

**sklearn API:**
```python
from sklearn.ensemble import RandomForestClassifier

rf = RandomForestClassifier(
    n_estimators=100,
    max_depth=10,
    min_samples_split=20,
    random_state=42,
    n_jobs=-1  # parallel training
)
rf.fit(X_train, y_train)
predictions = rf.predict(X_test)
proba = rf.predict_proba(X_test)  # class probabilities
importances = rf.feature_importances_  # what features matter most
```

---

### K-Nearest Neighbors (KNN)

**What it does:** Instance-based learning that classifies a data point by majority vote among its 'k' nearest neighbors in feature space.

**Key strengths for trading:**
- **Pattern similarity matching:** Naturally matches current market conditions to historically similar regimes
- **Non-parametric:** No assumptions about underlying data distribution
- **Simple and interpretable:** Easy to understand why a prediction was made (look at neighbors)
- **Adapts to new data:** No explicit training phase—just add new labeled examples

**Key parameters:**
- `n_neighbors`: Number of neighbors to consider (k=5-15 typical)
- `weights`: `'uniform'` (equal weight) vs `'distance'` (closer neighbors weigh more)
- `metric`: Distance function—`'euclidean'`, `'manhattan'`, `'cosine'`, `'minkowski'`
- `algorithm`: Search method—`'auto'`, `'ball_tree'`, `'kd_tree'`, `'brute'`

**Challenges for trading:**
- **Computational cost:** Must store all training data and compute distances at inference (O(n))
- **Feature scaling required:** Distance metrics break if features have different scales
- **Sensitive to noise:** Outliers can heavily influence neighbor selection
- **Curse of dimensionality:** Performance degrades with too many features

**sklearn API:**
```python
from sklearn.neighbors import KNeighborsClassifier

knn = KNeighborsClassifier(
    n_neighbors=5,
    weights='distance',  # closer neighbors matter more
    metric='euclidean',
    algorithm='auto'
)
knn.fit(X_train, y_train)
prediction = knn.predict(X_new)
distances, indices = knn.kneighbors(X_new, n_neighbors=5)  # inspect neighbors
```

---

### Support Vector Machines (SVM)

**What it does:** Finds optimal hyperplane that separates classes by maximizing margin between them.

**Key strengths for trading:**
- **Effective in high dimensions:** Works well with many technical features
- **Kernel trick:** Can model non-linear decision boundaries via kernels
- **Margin maximization:** Focuses on hardest-to-classify samples (support vectors)
- **Regularization built-in:** C parameter controls trade-off between margin width and classification error

**Kernel options:**
- `'linear'`: Fast, interpretable, good for linearly separable patterns
- `'rbf'` (Radial Basis Function): Most common—handles non-linear patterns
- `'poly'`: Polynomial kernels for polynomial decision boundaries
- `'sigmoid'`: Sigmoidal decision surfaces (less common)

**Challenges for trading:**
- **Sensitive to feature scaling:** Requires normalized features
- **Slow on large datasets:** Training is O(n²) to O(n³)
- **Memory intensive:** Stores all support vectors in model
- **Parameter tuning:** C and gamma (for RBF) require careful tuning

**sklearn API:**
```python
from sklearn.svm import SVC

svm_rbf = SVC(
    C=1.0,  # regularization strength
    kernel='rbf',
    gamma='scale',  # or 'auto' or float value
    probability=True,  # enables predict_proba()
    random_state=42
)
svm_rbf.fit(X_train, y_train)
prediction = svm_rbf.predict(X_test)
probabilities = svm_rbf.predict_proba(X_test)  # class probabilities
```

---

## Where These Fit in IndicAgent Tiers

### Current ML Usage in IndicAgent

| Tier | Current ML | Purpose |
|-------|-------------|---------|
| **I4** | `GARCHVolatility` | One-step volatility forecast |
| **I6 SMC** | `HMMRegime` | Regime classification (ranging/trending) with probability |
| **I7 Agg** | `CISScorer` (LogisticRegression) | Adaptive weight learning from `signal_ledger` outcomes |

**Note:** IndicAgent already has `sklearn` as a dependency for `CISScorer.weight_updater`.

---

### Integration Options for New ML Classifiers

#### **Option A: I7 Setup Enrichment Layer (Recommended)**
**Location:** New module in `src/intelligence/trading/` or `src/intelligence/ml/`

**Purpose:** Add a "confidence boost" or "meta-classification" layer on top of existing I7 setups.

**How it works:**
1. I7 setups fire with baseline CIS scores (existing behavior)
2. ML classifier reads the full `IntelligenceEvent` (I1-I6 features) for that bar
3. Classifier predicts: *given these conditions, what was the historical outcome distribution?*
4. Output: `ml_enrichment: {prediction: "profitable", probability: 0.73, top_features: [...]}`

**Benefits:**
- Non-invasive: Doesn't break existing I7 plugin logic
- A/B testable: Can run shadow mode alongside production
- Feature importance feedback: Can tell which tiers/features actually predict success
- Adaptive: Retrain weekly from `signal_ledger` outcomes like `CISScorer.weight_updater`

**Algorithm choice:**
- **Random Forest** (best fit): Handles mixed feature types, provides feature importances, robust to noise
- **KNN** (secondary): Good for regime similarity matching—"when did we last see this pattern?"
- **SVM** (tertiary): If we discover linear decision boundaries work well, SVM is interpretable

**Data flow:**
```
signal_generator_service (I7) → signal_ledger (INSERT)
                                       ↓
                                    ml_classifier_service (reads)
                                    ↓
                        (feature vector: I1-I6 from IntelligenceEvent)
                                    ↓
                        ML prediction (outcome class + probability)
                                    ↓
                        UPDATE signal_ledger SET ml_prediction, ml_probability
```

**Shadow mode pattern:**
- Phase 1: Log predictions without acting on them
- Phase 2: Compare prediction accuracy against actual outcomes (p < 0.05 statistical test)
- Phase 3: Route through ML gate if `ml_probability > threshold` AND `ml_prediction == 'profitable'`

---

#### **Option B: I5 Pattern Detector Replacement**
**Location:** New `src/intelligence/patterns/ml_pattern_classifier.py`

**Purpose:** Replace or augment rule-based pattern detectors (RSI divergence, double top, etc.) with learned pattern recognition.

**How it works:**
1. User manually labels historical bars with pattern types (double-top, squeeze, etc.)
2. Classifier learns feature representations of each pattern
3. At runtime, classifier predicts which pattern type (if any) is forming

**Challenges:**
- **Manual labeling required:** Need curated dataset of labeled patterns
- **Feature engineering critical:** Which features define a "double top" vs "triple bottom"?
- **Overfitting risk:** May memorize specific historical patterns rather than generalizing
- **Competes with existing I5:** 14 existing pattern detectors already rule-based

**Algorithm choice:**
- **KNN** (best fit): Pattern similarity matching is natural use case—"find me similar patterns"
- **Random Forest** (secondary): If we need feature importance for pattern rules

**Not recommended for initial implementation:**
- High upfront cost (manual labeling)
- Unclear advantage over existing rule-based I5 patterns
- Better to enrich existing signals (Option A) than replace them

---

#### **Option C: I4 Regime Classification Enhancement**
**Location:** Enhance `src/intelligence/context/` with new plugin

**Purpose:** Replace or augment `HMMRegime` with multi-class regime classifier.

**How it works:**
1. Train on labeled historical data (bull-trending, bear-trending, ranging, high-vol, low-vol)
2. Predict regime per bar from I1-I3 features
3. Use regime prediction to gate I7 setups (existing `regime_type` class attribute)

**Current state:**
- `HMMRegime` already provides 3-class regime (0=ranging, 1=bull-trend, 2=bear-trend) with probability
- Random Forest could expand to 5+ regimes: bull-trend-strong, bull-trend-weak, ranging, bear-trend-weak, bear-trend-strong

**Algorithm choice:**
- **Random Forest** (best fit): Multi-class classification, handles non-linear regime transitions
- **SVM** (secondary): If regime boundaries appear linear, SVM provides clean separation

**Shadow mode pattern:**
- Compare ML regime vs HMM regime predictions
- If ML regime correlates better with signal outcomes, promote to production

---

#### **Option D: Feature Engineering Discovery Tool**
**Location:** New utility in `src/intelligence/ml/feature_engineering.py`

**Purpose:** Use Random Forest feature importance to discover which I1-I4 features most strongly predict trading outcomes.

**How it works:**
1. Train Random Forest on `intelligence_features` + `signal_ledger` JOIN
2. Extract `feature_importances_` ranking
3. Output: automated discovery of "which features actually matter"

**Value add:**
- **Data-driven plugin development:** Focus engineering effort on high-impact features
- **Prune dead code:** Identify low-value features (e.g., unused indicators)
- **Validate intuition:** Test if "RSI divergence" actually predicts outcomes or if it's noise
- **Tier optimization:** Could discover that I4 context features matter more than I5 patterns

**Algorithm choice:**
- **Random Forest** (only fit): Built-in `feature_importances_` is unique strength
- **Permutation importance:** Use `sklearn.inspection.permutation_importance` for more robust ranking

**Output:**
```python
{
  "top_features": [
    {"feature": "i4.hmm_regime_prob", "importance": 0.23},
    {"feature": "i1.rsi_14", "importance": 0.18},
    {"feature": "i1.atr_14_pct", "importance": 0.12},
    ...
  ],
  "tier_impact": {
    "i1": 0.45,
    "i3": 0.28,
    "i4": 0.19,
    "i5": 0.08
  }
}
```

---

## Specific Implementation Ideas

### Idea 1: ML Setup Confidence Booster (Shadow Mode)

**Tier:** I7 (enrichment)
**Algorithm:** Random Forest (primary), KNN (secondary for similarity)
**Complexity:** Medium

**Implementation:**
1. Create `src/intelligence/ml/setup_classifier.py` with `RandomForestClassifier`
2. New service `ml_classifier_service.py` (systemd: `indicagent-ml-classifier`)
3. Consumer: reads `signals:SYMBOL:TF:aggregated` stream
4. Feature extraction: Pull full `IntelligenceEvent` from `intelligence:SYMBOL:TF` for that bar
5. Prediction: Classify as `profitable/unprofitable` with probability
6. Shadow mode: Write prediction to `signal_ledger.ml_prediction` field, don't route
7. Weekly retraining: Job that pulls `signal_ledger` outcomes, retrains model

**DB schema:**
```sql
ALTER TABLE signal_ledger ADD COLUMN ml_prediction TEXT;
ALTER TABLE signal_ledger ADD COLUMN ml_probability NUMERIC;
ALTER TABLE signal_ledger ADD COLUMN ml_top_features JSONB;
```

**Metrics:**
- Prometheus counter: `ml_classification_predictions_total`
- Prometheus gauge: `ml_classification_profitability_rate`
- Confusion matrix logged to `llm_calls`-style audit stream

**Success criteria:**
- Shadow mode accuracy > 60% over 100 signals
- Statistical significance (p < 0.05) vs random baseline
- Latency < 100ms per prediction (non-blocking to pipeline)

---

### Idea 2: Regime Similarity Matcher

**Tier:** I4 / I6 (regime context)
**Algorithm:** KNN
**Complexity:** Low

**Implementation:**
1. Create `src/intelligence/context/regime_similarity.py`
2. Store last N bars of each regime type in feature space
3. When new bar arrives, find k-nearest similar historical regimes
4. Output: `regime_similarity: {most_similar_regime: "bull-trend", distance: 0.23, historical_outcome_rate: 0.65}`

**Use case:**
- "Last time we saw this RSI + ATR + volume profile configuration, what happened?"
- Fuzzy regime matching when `HMMRegime` probability is low (< 0.55)

**Integration:**
- Enrich `IntelligenceEvent.i4` with similarity metadata
- Consume by I7 setups for adaptive confidence scaling

**Success criteria:**
- Similarity matches correlate with signal outcomes (r > 0.3)
- KNN lookup latency < 50ms with < 10,000 stored regimes

---

### Idea 3: Feature Importance Dashboard

**Tier:** Cross-tier analytics
**Algorithm:** Random Forest (one-time analysis)
**Complexity:** Low

**Implementation:**
1. Create `src/intelligence/ml/feature_importance_analyzer.py`
2. Query `intelligence_features` JOIN `signal_ledger` for last 90 days
3. Train Random Forest on `(features → outcome)` classification
4. Extract `feature_importances_`
5. Expose via API: `GET /api/ml/feature-importance`
6. Dashboard panel: Bar chart showing top 20 features by tier

**Value:**
- **Plugin prioritization:** Focus dev effort on high-impact features
- **Dead code detection:** Identify unused features
- **Tier balance:** Verify if I5 patterns actually contribute vs just I1/I4

**Output format:**
```json
{
  "analysis_date": "2026-03-11",
  "window_days": 90,
  "total_features": 85,
  "top_features": [
    {"tier": "i4", "feature": "hmm_regime_prob", "importance": 0.234},
    {"tier": "i1", "feature": "rsi_14", "importance": 0.187},
    {"tier": "i3", "feature": "swing_structure", "importance": 0.143},
    ...
  ],
  "tier_importance": {
    "i1": 0.42,
    "i3": 0.18,
    "i4": 0.31,
    "i5": 0.09
  }
}
```

---

### Idea 4: Linear SVM Regime Gate

**Tier:** I4
**Algorithm:** Linear SVM
**Complexity:** Low

**Implementation:**
1. Replace `HMMRegime` or augment as dual regime detector
2. Train `SVC(kernel='linear')` on labeled regime data
3. Fast inference: Linear SVM prediction is O(d) where d = feature dimension
4. Output: Binary regime (trend vs range) with confidence

**Why linear SVM?**
- Interpretable: Coefficients show which features drive regime
- Fast: No kernel computation needed
- Complementary to HMM: SVM captures static feature relationships, HMM captures temporal dynamics

**Hybrid approach:**
- SVM prediction: regime_static
- HMM prediction: regime_temporal
- Final regime: weighted average based on prediction confidence

**Success criteria:**
- Regime stability: No more than 2 flips per 50-bar window
- Correlation with volatility: Trend regime correlates with ATR > X percentile

---

## Data Requirements

### Labeled Training Data

All supervised ML approaches require labeled examples:

**Option A: Use existing `signal_ledger` outcomes**
- **Label source:** `signal_ledger.outcome` field (8 classes: never_activated, target_1, stopped_in_trade, etc.)
- **Label engineering:** Collapse to binary: `profitable` (target_1/1_2/full) vs `unprofitable` (stopped outcomes)
- **Advantage:** No manual labeling needed—use existing signal lifecycle data
- **Challenge:** Only I7 setups are labeled, not arbitrary market conditions

**Option B: Manual labeling dataset**
- **Label source:** User manually tags historical bars with pattern types or regime states
- **Advantage:** Can train on arbitrary patterns, not just I7 setups
- **Challenge:** Labor-intensive, requires domain expertise

**Recommendation:** Start with Option A (automated labels from `signal_ledger`), explore Option B if results show value.

### Feature Vector Construction

From `IntelligenceEvent` schema:
```python
features = {
    # I1: 25 indicators
    "i1.rsi_14": 72.3,
    "i1.atr_14": 23.5,
    "i1.macd_signal": "bullish",

    # I2: 10 composite events
    "i2.rsi_cross": "oversold_exit",
    "i2.macd_crossover": True,

    # I3: 8 structure fields
    "i3.swing_high": 4450.0,
    "i3.pivot_level": 4380.0,

    # I4: 7 context/regime
    "i4.hmm_regime": 1,  # 0=ranging, 1=bull, 2=bear
    "i4.garch_vol_forecast": 28.5,

    # I5: 14 pattern detections
    "i5.rsi_divergence": "bullish",
    "i5.bollinger_squeeze": True,

    # I6 SMC: 13 institutional order flow fields
    "smc.fvg_active": True,
    "smc.liquidity_swept": True,

    # I6 Confluence: 10 alignment scores
    "i6.cross_tf_confluence": 7.8,  # 0-10 score
}
```

**Preprocessing requirements:**
- **Categorical encoding:** One-hot encode string fields (rsi_signal, hmm_regime_class)
- **Feature scaling:** StandardScaler for SVM/KNN, optional for Random Forest
- **Missing value handling:** Impute with median (I1 indicators should never have nulls)
- **Feature selection:** Random Forest can handle ~50-100 features; prune if >150

---

## Technical Considerations

### Retraining Strategy

**Online vs batch:**
- **Online learning:** `partial_fit()` (KNN, SGD, not RF/SVM)—update model incrementally
- **Batch retraining:** Weekly cron job retrains on full dataset (Random Forest, SVM)

**Recommendation:** Weekly batch retraining
- Simpler implementation
- Can track model versioning (RF_v1, RF_v2, etc.)
- Allows statistical comparison across models

**Data window:**
- **Rolling window:** Last 90-180 days (avoid concept drift)
- **Full history:** All data with outcomes (more samples, but slower retrain)

### Model Versioning

```sql
CREATE TABLE ml_models (
    id SERIAL PRIMARY KEY,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    algorithm TEXT NOT NULL,
    trained_at TIMESTAMPTZ NOT NULL,
    accuracy NUMERIC,
    feature_importance JSONB,
    parameters JSONB,
    is_active BOOLEAN DEFAULT FALSE
);
```

### Shadow Mode Implementation Pattern

```python
# ml_classifier_service.py
async def process_signal(signal_event):
    # Extract features
    features = extract_features_from_intelligence_event(signal_event.intelligence_event)

    # Predict
    prediction, probability = model.predict_proba([features])[0], model.predict([features])[0]

    # Log prediction (shadow mode—don't affect routing)
    await update_signal_with_ml_prediction(
        signal_id=signal_event.signal_id,
        prediction=prediction,
        probability=probability,
        top_features=get_top_features(model)
    )

    # Shadow mode: don't modify routing
    # Future: if enable_ml_routing AND prediction == 'profitable' AND probability > 0.7:
    #     route_signal_to_dashboard_with_boost(signal_event, ml_boost=probability)
```

### Performance Monitoring

**Prometheus metrics:**
- `ml_model_inference_duration_seconds` — histogram
- `ml_model_accuracy_rate` — gauge (rolling 7-day)
- `ml_model_predictions_total{model, outcome}` — counter
- `ml_feature_importance_top{tier, feature}` — gauge

**Statistical validation:**
- Weekly chi-square test: ML predictions vs random baseline
- Confidence interval: Win rate with 95% CI
- Regime-specific accuracy: Break down by HMM regime type

---

## Open Questions

1. **Collaborator's patterns:** What specific patterns does "lik" want to detect? Are they already covered by I5 patterns (RSI divergence, squeeze, etc.) or new?

2. **Labeling workflow:** Does "lik" have a labeled dataset, or should we bootstrap from existing `signal_ledger` outcomes?

3. **Regime scope:** Should ML classifier be global (all symbols) or per-symbol (symbol-specific patterns)?

4. **Real-time vs batch:** Is the goal real-time signal enrichment (Option A) or offline analysis tool (Idea 3 feature importance dashboard)?

5. **Evaluation criteria:** What constitutes "successful" ML integration? Win rate improvement? Reduced false signals? Latency requirements?

---

## Recommended Implementation Order

**Phase 1: Discovery (Week 1)**
1. Build **Idea 3: Feature Importance Dashboard** (Random Forest one-shot analysis)
2. Validate data pipeline: Can we successfully JOIN `intelligence_features` + `signal_ledger` and extract features?
3. Discover which tiers/features actually predict outcomes

**Phase 2: Shadow Mode (Weeks 2-4)**
1. Implement **Idea 1: ML Setup Confidence Booster** with Random Forest
2. Shadow mode: Log predictions, don't route
3. Validate accuracy against `signal_ledger` outcomes

**Phase 3: A/B Test (Weeks 5-6)**
1. If shadow mode passes statistical validation, enable ML gate
2. A/B test: Split symbols 50/50 between baseline and ML-boosted
3. Compare win rates, latency, false signal rate

**Phase 4: Advanced Features (Week 7+)**
1. Implement **Idea 2: Regime Similarity Matcher** (KNN)
2. Explore **Idea 4: Linear SVM Regime Gate** as HMM alternative
3. Evaluate ensemble: Combine RF + KNN + SVM predictions

---

## References

**Sklearn API:**
- RandomForestClassifier: https://scikit-learn.org/stable/modules/ensemble.html#random-forest-classifier
- KNeighborsClassifier: https://scikit-learn.org/stable/modules/neighbors.html#nearest-neighbors-classification
- SVC: https://scikit-learn.org/stable/modules/svm.html#classification
- Permutation importance: https://scikit-learn.org/stable/modules/permutation_importance.html

**IndicAgent Stack Documentation:**
- `docs/research/tech-stack.md` — Current stack decisions (Ollama, Redis, TimescaleDB, etc.)
- `docs/research/ml-learning-machine.md` — ML Agent stack (full learning machine design)
  - Phase 1 libraries: scipy, alphalens-reloaded, evidently, tsfresh (discovery)
  - Phase 2 libraries: lightgbm, shap, optuna, statsmodels (training)
  - Phase 3 libraries: river (online learning)
  - Already in stack: scikit-learn, pandas, numpy, polars

**Current ML Usage:**
- `src/intelligence/weight_updater.py` — Uses `sklearn.linear_model.LogisticRegression` for CIS adaptive weights
- Random Forest, KNN, SVM would be **additional sklearn classifiers** (not replacing Ollama LLM)

---

## Next Steps

1. **Collaborator input:** Get specific patterns of interest from "lik"
2. **Data validation:** Confirm `signal_ledger` has sufficient labeled samples (>500 profitable + >500 unprofitable)
3. **Prototype:** Build Feature Importance Dashboard (Idea 3) as proof-of-concept
4. **Design review:** Choose between Option A (enrichment) vs Option D (discovery tool) for initial scope
5. **Add to ROADMAP:** Create phase for ML classifier integration if approved
