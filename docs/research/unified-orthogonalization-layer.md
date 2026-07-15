# Unified Orthogonalization Layer — Architecture Specification

**Version:** 1.0
**Status:** design — architecture proposal, not yet implemented
**Priority:** high (foundational validation discipline across 4 layers)
**Milestone:** Phase 143.1+ (blocks Phase 144 regime work and Phase 148 portfolio construction)
**Last Updated:** 2026-07-14
**Tags:** orthogonalization, marginal-contribution, regime-validation, portfolio-construction, architecture

---

## The Problem

Current system measures individual quality (IC, Sharpe, FDR) but never answers: **"Does this add anything beyond what we already have?"**

This gap exists at 4 layers:

| Layer | Current State | Gap |
|-------|--------------|-----|
| **Features** | Individual IC measured, ensemble combined | No test of marginal contribution — redundant features admitted |
| **Regimes** | 2 regimes live, 8 alternatives proposed | No substitution test — unvalidated dimensions compound |
| **Predictions** | AlphaEngine and AnalogEngine measured separately | No incremental R² test — don't know if combination adds value |
| **Portfolio** | No portfolio layer yet | No position correlation — can't measure effective N or allocate risk |

**Renaissance invariant:** every new vector must prove it adds orthogonal information before admission.

---

## Architecture Overview

### Single Service, Shared Contract

```python
class OrthogonalizationEngine:
    """Unified orthogonalization testing across features, regimes, predictions, and portfolio."""
    
    def test_marginal_contribution(
        self,
        candidate: np.ndarray,
        incumbent_set: dict[str, np.ndarray],
        targets: np.ndarray,
        level: OrthogonalizationLevel,
        metadata: dict[str, Any]
    ) -> MarginalContributionResult
    
    def test_pairwise_orthogonality(
        self,
        vectors: dict[str, np.ndarray],
        level: OrthogonalizationLevel,
        threshold: float
    ) -> OrthogonalityMatrix
    
    def substitution_test(
        self,
        candidate_baseline: np.ndarray,
        incumbent_baseline: np.ndarray,
        targets: np.ndarray,
        level: OrthogonalizationLevel
    ) -> SubstitutionResult
```

**Four levels, one mathematical foundation:**

- `OrthogonalizationLevel.FEATURE` — residual IC, incremental R²
- `OrthogonalizationLevel.REGIME` — IC separation delta, substitution test
- `OrthogonalizationLevel.PREDICTION` — prediction combination R² gain
- `OrthogonalizationLevel.PORTFOLIO` — position correlation, effective N

### Shared Math Library

```python
# src/intelligence/orthogonalization/
├── __init__.py
├── residual_math.py       # Residualization, partial IC, incremental R²
├── correlation_math.py    # Correlation matrices, effective N, condition number
├── substitution_math.py  # Substitution tests, IC separation deltas
├── portfolio_math.py      # Position covariance, risk allocation
└── metrics.py            # Unified result types and scoring
```

**Math reuse across levels:**
- Residualization: features (regress out ensemble), predictions (regress out baseline)
- Correlation matrices: features (redundancy detection), positions (risk allocation)
- Incremental R²: features (marginal contribution), predictions (combination value)
- Substitution test: regimes (IC separation), predictions (method comparison)

---

## Level 1: Feature Orthogonalization

### Method: Residual IC (Partial IC)

**Concept:** Test if a feature's residuals (after removing incumbent influence) still predict returns.

```python
def residual_ic_test(
    feature_residuals: np.ndarray,  # ranks of feature_i ~ ensemble_without_i
    forward_returns: np.ndarray,
    regime: str,
    lookahead: int
) -> ResidualICResult:
    """
    Returns: residual_ic, residual_ic_ci, is_significant, marginal_value
    """
```

**Implementation:**
1. For candidate feature `f_i`, get active set `A` from `feature_registry` (max size per APR)
2. Regress `f_i ~ A` (in ranks) → residuals `r_i`
3. Compute `IC(r_i, forward_return)` with same bootstrap CI as standard IC
4. Gate: `residual_ic_ci_lower > 0` at 95% CI

**Integration:**
- Runs in `ic_engine` after standard IC computation
- Writes `partial_ic`, `partial_ic_ci_lower` to `feature_ic_scores`
- `feature_registry` promotion gate reads `partial_ic` instead of `ic_value`

**APR Keys:**
```sql
-- Feature-level orthogonalization
alpha.orthogonal.feature_partial_max_set_size DEFAULT 20  -- Max conditioning set size
alpha.orthogonal.feature_residual_ic_threshold DEFAULT 0.02  -- Minimum residual IC
alpha.orthogonal.feature_effective_n_threshold DEFAULT 5  -- Min effective N after conditioning
```

### Audit: Current 54 Features

Run once to identify redundancy:

```python
# For each feature, measure:
standalone_ic = IC(feature_i, returns)
marginal_ic = residual_ic_test(feature_i ~ active_set, returns)
redundancy_score = standalone_ic - marginal_ic

# Flag features where:
redundancy_score > 0.02  -- Adds < 2% marginal value over ensemble
```

**Output:** Feature redundancy report → demote or deprecate highly redundant features.

---

## Level 2: Regime Stratification Orthogonalization

### Method: Substitution Test + IC Separation

**Concept:** Does a new regime dimension improve IC separation beyond the current dimension?

```python
def regime_substitution_test(
    current_regime_labels: np.ndarray,  # e.g., cross_sectional_regime_model
    candidate_regime_labels: np.ndarray,  # e.g., volatility_regime
    features: np.ndarray,
    forward_returns: np.ndarray,
    regime_scope: str  -- 'symbol_hmm' | 'cross_sectional'
) -> SubstitutionResult:
    """
    Measure IC separation under:
    1. Current stratification only
    2. Candidate stratification only  
    3. Both stratifications (interaction)
    
    Returns: ic_separation_delta, recommendation (ACCEPT | REJECT | COMPLEMENT)
    """
```

**Implementation:**
1. Run `ic_engine` stratified by current regime → `IC_current`
2. Run `ic_engine` stratified by candidate regime → `IC_candidate`
3. Run `ic_engine` stratified by both → `IC_combined`
4. Compute separation: `delta = mean(IC_combined) - mean(IC_current)`
5. Gate: `delta > threshold` AND candidate not highly correlated with current

**Integration with `StratificationDimension` contract:**

```python
class StratificationDimension:
    def validate_orthogonality(self, incumbent: StratificationDimension) -> OrthogonalityResult:
        """Substitution test against current dimension."""
        result = ortho_engine.substitution_test(
            candidate_baseline=self.labels,
            incumbent_baseline=incumbent.labels,
            targets=forward_returns,
            level=OrthogonalizationLevel.REGIME
        )
        return result
```

**APR Keys:**
```sql
-- Regime orthogonalization
alpha.orthogonal.regime_ic_separation_delta_threshold DEFAULT 0.005  -- Min IC gain
alpha.orthogonal.regime_max_correlation DEFAULT 0.7  -- Max label correlation with incumbent
alpha.orthogonal.regime_min_effective_n DEFAULT 3000  -- Min obs per regime cell
```

**Concept Registry Integration:**
- Every regime model is a `concept_registry` row (`domain='regime_model'`)
- Promotion gate: substitution test must pass
- Existing 8 alternatives from `docs/plans/2026-07-01-regime-stratification-alternatives.md` become candidates

---

## Level 3: Prediction Method Orthogonalization

### Method: Incremental R² on Prediction Combinations

**Concept:** Do AlphaEngine and AnalogEngine predictions add orthogonal information?

```python
def prediction_combination_test(
    alpha_engine_scores: np.ndarray,
    analog_engine_scores: np.ndarray,
    forward_returns: np.ndarray
) -> CombinationResult:
    """
    Measure:
    1. R²(alpha_engine, returns) 
    2. R²(analog_engine, returns)
    3. R²(combined, returns) where combined = w1*alpha + w2*analog
    
    Returns: incremental_r2, combination_weights, recommendation
    """
```

**Implementation:**
1. Compute OOS R² for each method independently (walk-forward)
2. Combine predictions: grid search over `w1, w2` where `w1 + w2 = 1`
3. Measure `R²_combined`
4. Compute incremental value: `ΔR² = R²_combined - max(R²_alpha, R²_analog)`
5. Gate: `ΔR² > threshold` at 95% CI

**Integration:**
- Runs as weekly batch after both prediction engines emit
- Results inform whether to maintain parallel systems or converge
- If `ΔR² ≈ 0`, retire weaker method; if `ΔR² > 0`, combine optimally

**APR Keys:**
```sql
-- Prediction orthogonalization  
alpha.orthogonal.prediction_incremental_r2_threshold DEFAULT 0.001  -- Min R² gain
alpha.orthogonal.prediction_min_combination_weight DEFAULT 0.1  -- Min weight to retain method
alpha.orthogonal.prediction_reval_cadence_days DEFAULT 7  -- How often to re-test
```

---

## Level 4: Portfolio Orthogonalization (v4.0)

### Method: Position Correlation Matrix + Effective N

**Concept:** Are portfolio positions correlated or orthogonal bets? What is the effective number of independent bets?

```python
def portfolio_orthogonality_analysis(
    positions: dict[str, float],  -- Symbol -> weight
    returns_history: pd.DataFrame,  -- Historical returns matrix
    lookback_days: int = 60
) -> PortfolioResult:
    """
    Compute:
    1. Position correlation matrix (Σ)
    2. Effective N: N_eff = trace(Σ) / sum(Σ)  -- Ledoit-Wolf eigenvalues
    3. Concentration ratio: λ_max / sum(λ)
    4. Risk allocation: decompose portfolio variance into independent factors
    
    Returns: n_effective, concentration_ratio, factor_risk_allocation
    """
```

**Implementation:**
1. Compute returns covariance matrix (60-day lookback, exponential decay)
2. Apply position weights → portfolio covariance `Σ_p = w' Σ w`
3. Eigenvalue decomposition → effective N calculation
4. Risk attribution: how much variance comes from each independent factor
5. Flag concentration: if `N_eff < 0.5 * N_positions`, portfolio is under-diversified

**Integration with v4.0 Portfolio Construction:**
- Phase 156 (Portfolio State Foundation) builds this layer
- Kelly sizing uses effective N, not nominal position count
- Risk allocation gates: "no more than 20% variance from any single factor"

**APR Keys:**
```sql
-- Portfolio orthogonalization
alpha.orthogonal.portfolio_min_effective_n_ratio DEFAULT 0.5  -- N_eff / N_positions
alpha.orthogonal.portfolio_max_concentration_ratio DEFAULT 0.3  -- λ_max / sum(λ)
alpha.orthogonal.portfolio_lookback_days DEFAULT 60
alpha.orthogonal.portfolio_risk_factor_limit DEFAULT 0.2  -- Max variance per independent factor
```

---

## Service Architecture

### OrthogonalizationEngine as Batch Service

```python
# services/orthogonalization_engine.py

class OrthogonalizationEngine(BaseBatch):
    """Unified orthogonalization testing across 4 levels."""
    
    # Feature-level: run with ic_engine
    def compute_partial_ic(
        self,
        feature_vectors: dict[str, np.ndarray],
        forward_returns: np.ndarray,
        active_features: list[str]
    ) -> dict[str, ResidualICResult]:
        """Compute partial IC for all features against active set."""
        
    # Regime-level: run on regime dimension proposal
    def regime_substitution_test(
        self,
        incumbent_regime: StratificationDimension,
        candidate_regime: StratificationDimension
    ) -> SubstitutionResult:
        
    # Prediction-level: run weekly
    def prediction_combination_test(
        self,
        alpha_scores: np.ndarray,
        analog_scores: np.ndarray,
        forward_returns: np.ndarray
    ) -> CombinationResult:
        
    # Portfolio-level: run in v4.0
    def portfolio_effective_n(
        self,
        positions: dict[str, float],
        returns_matrix: pd.DataFrame
    ) -> PortfolioResult:
```

**Cadence:**
- Feature-level: Runs with `ic_engine` (weekly corpus run)
- Regime-level: On-demand (when new regime dimension proposed)
- Prediction-level: Weekly batch ( Mondays, after prediction engines emit)
- Portfolio-level: Real-time in v4.0 ( every portfolio rebalance)

### Database Schema

```sql
-- Feature orthogonalization results (extend feature_ic_scores)
ALTER TABLE feature_ic_scores ADD COLUMN partial_ic DOUBLE PRECISION;
ALTER TABLE feature_ic_scores ADD COLUMN partial_ic_ci_lower DOUBLE PRECISION;
ALTER TABLE feature_ic_scores ADD COLUMN marginal_value DOUBLE PRECISION;  -- ic_value - partial_ic

-- Regime orthogonalization results
CREATE TABLE regime_orthogonalization_results (
    candidate_dimension TEXT NOT NULL,
    incumbent_dimension TEXT NOT NULL,
    ic_separation_delta DOUBLE PRECISION,
    label_correlation DOUBLE PRECISION,
    recommendation TEXT NOT NULL,  -- 'ACCEPT' | 'REJECT' | 'COMPLEMENT'
    evaluated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (candidate_dimension, incumbent_dimension, evaluated_at)
);

-- Prediction orthogonalization results
CREATE TABLE prediction_combination_results (
    run_id TIMESTAMPTZ NOT NULL,
    method_a TEXT NOT NULL,
    method_b TEXT NOT NULL,
    r2_a DOUBLE PRECISION,
    r2_b DOUBLE PRECISION,
    r2_combined DOUBLE PRECISION,
    incremental_r2 DOUBLE PRECISION,
    optimal_weights JSONB,
    recommendation TEXT NOT NULL,
    evaluated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, method_a, method_b)
);

-- Portfolio orthogonalization results (v4.0)
CREATE TABLE portfolio_orthogonality_snapshot (
    snapshot_at TIMESTAMPTZ NOT NULL,
    n_positions INTEGER NOT NULL,
    n_effective DOUBLE PRECISION NOT NULL,
    concentration_ratio DOUBLE PRECISION NOT NULL,
    factor_risk_allocation JSONB,
    PRIMARY KEY (snapshot_at)
);
```

---

## Integration Points

### Feature Registry Promotion Gate

```python
# src/intelligence/feature_registry_service.py

def validate_promotion(self, feature_name: str) -> PromotionResult:
    """Feature earns 'active' on marginal contribution, not standalone IC."""
    
    feature_ic_row = self.db.fetch_one(
        "SELECT ic_value, partial_ic, partial_ic_ci_lower FROM feature_ic_scores WHERE feature_name = $1",
        feature_name
    )
    
    # Gate 1: Partial IC must be significant
    if feature_ic_row.partial_ic_ci_lower <= 0:
        return PromotionResult.REJECTED, "Partial IC not significant"
    
    # Gate 2: Marginal value must exceed threshold
    marginal_value = feature_ic_row.ic_value - feature_ic_row.partial_ic
    if marginal_value < self.config.get("alpha.orthogonal.feature_residual_ic_threshold"):
        return PromotionResult.REJECTED, f"Marginal value {marginal_value:.4f} below threshold"
    
    return PromotionResult.ACCEPT, "Feature adds orthogonal information"
```

### Concept Registry (Regime Dimensions)

```python
# Every regime model must pass substitution test before activation

class RegimeModelConcept(Concept):
    def validate_activation(self) -> ActivationResult:
        incumbent = self.get_active_regime_model()
        result = ortho_engine.regime_substitution_test(
            incumbent_regime=incumbent,
            candidate_regime=self
        )
        
        if result.recommendation == "REJECT":
            return ActivationResult.REJECTED, f"Fails substitution test: {result.reason}"
        
        if result.recommendation == "ACCEPT":
            return ActivationResult.ACCEPT, "Superior IC separation"
            
        return ActivationResult.CONDITIONAL, "Complementary dimension (consider joint model)"
```

### Prediction Combination (AlphaEngine + AnalogEngine)

```python
# Weekly batch to test combination value

def evaluate_prediction_combination():
    alpha_scores = fetch_alpha_engine_scores()
    analog_scores = fetch_analog_engine_scores()
    returns = fetch_forward_returns()
    
    result = ortho_engine.prediction_combination_test(alpha_scores, analog_scores, returns)
    
    if result.incremental_r2 > threshold:
        # Update combination weights in APR
        config_service.set("alpha.ensemble.combination_weights", result.optimal_weights)
    else:
        # Flag for potential retirement of weaker method
        logger.warning(f"Combination adds {result.incremental_r2:.6f} R² — consider retirement")
```

---

## APR Keys (Complete Set)

```sql
-- Feature orthogonalization
INSERT INTO config_schema (config_key, config_value, description, domain, provenance) VALUES
('alpha.orthogonal.feature_partial_max_set_size', '20', 'Max conditioning set size for partial IC', 'alpha.orthogonal', '[initial_estimate]'),
('alpha.orthogonal.feature_residual_ic_threshold', '0.02', 'Minimum residual IC for marginal contribution', 'alpha.orthogonal', '[initial_estimate]'),
('alpha.orthogonal.feature_effective_n_threshold', '5', 'Min effective N after conditioning', 'alpha.orthogonal', '[initial_estimate]');

-- Regime orthogonalization  
INSERT INTO config_schema (config_key, config_value, description, domain, provenance) VALUES
('alpha.orthogonal.regime_ic_separation_delta_threshold', '0.005', 'Min IC gain for regime substitution test', 'alpha.orthogonal', '[initial_estimate]'),
('alpha.orthogonal.regime_max_correlation', '0.7', 'Max label correlation with incumbent regime', 'alpha.orthogonal', '[initial_estimate]'),
('alpha.orthogonal.regime_min_effective_n', '3000', 'Min obs per regime cell for substitution test', 'alpha.orthogonal', '[initial_estimate]');

-- Prediction orthogonalization
INSERT INTO config_schema (config_key, config_value, description, domain, provenance) VALUES
('alpha.orthogonal.prediction_incremental_r2_threshold', '0.001', 'Min incremental R² for prediction combination', 'alpha.orthogonal', '[initial_estimate]'),
('alpha.orthogonal.prediction_min_combination_weight', '0.1', 'Min weight to retain prediction method in combination', 'alpha.orthogonal', '[initial_estimate]'),
('alpha.orthogonal.prediction_reval_cadence_days', '7', 'Days between prediction combination re-evaluation', 'alpha.orthogonal', '[initial_estimate]');

-- Portfolio orthogonalization (v4.0)
INSERT INTO config_schema (config_key, config_value, description, domain, provenance) VALUES
('alpha.orthogonal.portfolio_min_effective_n_ratio', '0.5', 'Min N_eff / N_positions ratio for diversification', 'alpha.orthogonal', '[initial_estimate]'),
('alpha.orthogonal.portfolio_max_concentration_ratio', '0.3', 'Max λ_max / sum(λ) concentration ratio', 'alpha.orthogonal', '[initial_estimate]'),
('alpha.orthogonal.portfolio_lookback_days', '60', 'Lookback days for portfolio covariance estimation', 'alpha.orthogonal', '[initial_estimate]'),
('alpha.orthogonal.portfolio_risk_factor_limit', '0.2', 'Max variance contribution per independent risk factor', 'alpha.orthogonal', '[initial_estimate]');
```

---

## Phase Planning

### Phase 1: Foundation + Feature Level (Priority: HIGH)
**Goal:** Build shared architecture and prove value at feature level

**Wave 1 — Architecture + Math Library**
- `src/intelligence/orthogonalization/` module structure
- `residual_math.py`, `correlation_math.py`, `metrics.py`
- Unit tests for residual IC, correlation matrices, effective N
- APR migration for feature-level keys

**Wave 2 — Feature Orthogonalization Implementation**
- `OrthogonalizationEngine.compute_partial_ic()` method
- Integration with `ic_engine` (partial IC computation after standard IC)
- Schema migration: `partial_ic`, `partial_ic_ci_lower` columns
- Feature registry promotion gate update
- One-time audit script: redundancy analysis of current 54 features

**Wave 3 — Verification**
- Run on current corpus → identify redundant features
- Feature demotion/promotion based on marginal contribution
- Documentation update: feature lifecycle now includes orthogonalization

**Exit Gate:** Feature-level orthogonalization live and influencing promotion decisions. At least one redundant feature identified and handled.

---

### Phase 2: Regime Level (Priority: HIGH)
**Goal:** Validate regime stratification dimensions before admission

**Prerequisite:** Phase 1 complete + Phase 143.1 complete (clean measurement foundation)

**Wave 1 — Regime Substitution Test**
- `substitution_math.py` implementation
- `OrthogonalizationEngine.regime_substitution_test()` method  
- Schema migration: `regime_orthogonalization_results` table
- APR migration for regime-level keys

**Wave 2 — StratificationDimension Integration**
- `StratificationDimension.validate_orthogonality()` method
- Concept Registry integration (regime models as governed concepts)
- 8 regime alternatives from existing doc become candidates for testing

**Wave 3 — Validation**
- Run substitution tests for all 8 alternatives vs current cross-sectional regime
- Documentation: which dimensions add orthogonal information, which are redundant
- Update ROADMAP: Phase 144 scope refined based on test results

**Exit Gate:** Regime orthogonalization gate blocks unvalidated dimension promotion. Substitution tests run for all candidates.

---

### Phase 3: Prediction Level (Priority: MEDIUM)
**Goal:** Test if AlphaEngine and AnalogEngine add orthogonal value

**Prerequisite:** Phase 1 complete + both prediction engines emitting

**Wave 1 — Prediction Combination Test**
- Incremental R² math in `residual_math.py`
- `OrthogonalizationEngine.prediction_combination_test()` method
- Schema migration: `prediction_combination_results` table
- Weekly batch scheduling

**Wave 2 — Integration and Monitoring**
- Wire into weekly evaluation pipeline
- APR key for combination weights (if combination adds value)
- Monitoring: track incremental R² over time, degradation detection

**Wave 3 — Decision Making**
- Run 4-week backtest → measure combination vs independent methods
- Decision: retire weaker method, maintain both, or combine optimally
- Documentation: prediction architecture final state

**Exit Gate:** Prediction combination tested and decision made. Either optimal combination deployed or redundant method retired.

---

### Phase 4: Portfolio Level (Priority: MEDIUM)
**Goal:** Portfolio construction with orthogonal bet measurement

**Prerequisite:** Phase 1 complete + v4.0 execution layer foundation

**Wave 1 — Portfolio Orthogonalization**
- `portfolio_math.py` implementation
- `OrthogonalizationEngine.portfolio_effective_n()` method
- Schema migration: `portfolio_orthogonality_snapshot` table
- APR migration for portfolio-level keys

**Wave 2 — Portfolio Construction Integration**
- Integration with Kelly sizing (use effective N, not nominal count)
- Risk allocation: decompose variance into independent factors
- Concentration gates: prevent under-diversified portfolios

**Wave 3 — Validation**
- Backtest: portfolio construction with vs without orthogonalization
- Measure diversification benefit, risk-adjusted return improvement
- Documentation: portfolio construction methodology

**Exit Gate:** Portfolio orthogonalization live in v4.0. Effective N and concentration gates enforced.

---

## Success Metrics

### Feature Level
- **Redundancy identification:** % of features with marginal value < threshold
- **Promotion discipline:** % of promotions blocked by partial IC gate
- **Ensemble quality:** Ensemble IC Sharpe before vs after orthogonalization

### Regime Level  
- **Dimension validation:** % of regime candidates rejected by substitution test
- **IC separation:** Mean IC separation improvement from validated dimensions
- **Model simplicity:** Number of active regime dimensions (goal: < 3)

### Prediction Level
- **Combination value:** Incremental R² from combination vs best single method
- **Retirement decisions:** Prediction methods retired due to redundancy
- **Forecast quality:** Combined vs independent prediction OOS Sharpe

### Portfolio Level
- **Diversification:** Mean N_eff / N_positions ratio
- **Concentration:** Mean concentration ratio (lower = better)
- **Risk-adjusted returns:** Portfolio Sharpe with vs without orthogonalization gates

---

## Open Questions

1. **Feature conditioning set size:** Should `partial_ic` condition on ALL active features or a subset (top N by weight)? Large conditioning sets can make residuals noisy.
   
2. **Regime interaction models:** When two regime dimensions are both validated, should we build an interaction model or maintain separate models? This affects `ic_engine` multi-axis stratification.

3. **Prediction combination cadence:** Weekly re-evaluation may be too slow for fast-moving markets. Should we trigger re-evaluation on prediction drift detection instead?

4. **Portfolio effective N calibration:** Is `N_eff = trace(Σ) / sum(Σ)` the right metric, or should we use eigenvalue thresholding (`λ_i > threshold` count)? Needs empirical validation.

5. **Cross-level orthogonalization:** Should feature-level orthogonalization consider regime structure (test partial IC per regime), or should it be regime-agnostic?

---

## References

- Todo 029 "Feature Scoring Beyond IC" — original marginal contribution spec
- `docs/plans/2026-07-01-regime-stratification-alternatives.md` — 8 regime candidates + orthogonality gates
- `docs/research/intel-13-analog-engine.md` — AnalogEngine as complementary prediction method
- `docs/research/intel-11-dual-system-discrete-vs-portfolio.md` (archived) — portfolio construction gap
- `docs/research/measurement-ic-engine.md` — Measurement Gaps section (0a marginal contribution)
- ROADMAP.md Phases 143.1, 144, 148 — sequencing dependencies
