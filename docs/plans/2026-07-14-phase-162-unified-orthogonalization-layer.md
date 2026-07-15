# Phase 162: Unified Orthogonalization Layer

**Status:** PLANNED
**Priority:** HIGH (unblocks Phase 144 regime work and Phase 148 portfolio construction)
**Estimated Effort:** 3-4 sessions (architecture + feature level), 2-3 sessions each for regime/prediction/portfolio levels
**Dependencies:** Phase 143.1 COMPLETE (measurement foundation solid)
**Blocks:** Phase 144 (regime unification) until 162.1 complete
**Last Updated:** 2026-07-14

---

## Goal

Build a unified `OrthogonalizationEngine` service that tests whether new vectors add orthogonal information across 4 layers: features, regimes, predictions, and portfolio positions. Every new vector must prove it adds incremental value beyond what the system already has — Renaissance-style validation discipline.

**The Problem:** Current system measures individual quality (IC, Sharpe, FDR) but never asks "does this add anything beyond what we already have?" Redundant features, regime dimensions, and prediction methods accumulate without empirical validation of marginal contribution.

**The Solution:** Shared orthogonalization testing with 4 implementations:
- Feature level: Residual IC (partial IC after regressing out active set)
- Regime level: Substitution test (IC separation delta vs incumbent)
- Prediction level: Incremental R² (combination value vs best single method)
- Portfolio level: Position correlation + effective N (diversification measurement)

---

## Architecture Overview

### Single Service, Shared Contract

```python
class OrthogonalizationEngine(BaseBatch):
    """Unified orthogonalization testing across features, regimes, predictions, and portfolio."""
    
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

## Phase 162.0: Architecture + Feature Level

**Goal:** Build shared architecture and prove value at feature level with immediate impact on current 54 features.

**Dependencies:** Phase 143.1 complete
**Blocks:** Feature promotion decisions will use orthogonalization gate
**Exit Gate:** Feature-level orthogonalization live, at least one redundant feature identified and handled

### Wave 1 — Architecture + Math Library (1 session)

**162.0-W01-PLAN.md** — Core infrastructure

**Implementation:**
1. Create `src/intelligence/orthogonalization/` module structure
2. Build `residual_math.py`:
   - `residualize_vector(candidate_vec, incumbent_matrix)` — returns residuals
   - `compute_partial_ic(residuals, targets, regime, lookahead)` — Spearman IC with bootstrap CI
   - `marginal_value_analysis(standalone_ic, partial_ic)` — redundancy score
3. Build `correlation_math.py`:
   - `compute_correlation_matrix(vectors_dict)` — feature/position correlation
   - `effective_n_from_correlation(correlation_matrix)` — Ledoit-Wolf eigenvalue method
   - `concentration_ratio(eigenvalues)` — λ_max / sum(λ)
4. Build `metrics.py`:
   - `ResidualICResult`, `SubstitutionResult`, `CombinationResult`, `PortfolioResult` dataclasses
   - Unified scoring across all 4 levels
5. Unit tests for all math functions (test residualization with synthetic correlated data)

**APR Migration:**
```sql
-- Feature orthogonalization keys
INSERT INTO config_schema (config_key, config_value, description, domain, provenance) VALUES
('alpha.orthogonal.feature_partial_max_set_size', '20', 'Max conditioning set size for partial IC', 'alpha.orthogonal', '[initial_estimate]'),
('alpha.orthogonal.feature_residual_ic_threshold', '0.02', 'Minimum residual IC for marginal contribution', 'alpha.orthogonal', '[initial_estimate]'),
('alpha.orthogonal.feature_effective_n_threshold', '5', 'Min effective N after conditioning', 'alpha.orthogonal', '[initial_estimate]');
```

**Verification:**
- Unit tests pass for residualization (synthetic test: residual of correlated feature has IC ≈ 0)
- Correlation matrix tests: effective N calculation verified on known eigenvalues
- APR keys readable via `ConfigService`

---

### Wave 2 — Feature Orthogonalization Implementation (1 session)

**162.0-W02-PLAN.md** — Service integration

**Implementation:**
1. Create `services/orthogonalization_engine.py`:
   - Extend `BaseBatch` (same pattern as `ic_engine.py`)
   - `compute_partial_ic()` method:
     - Fetch active features from `feature_registry` (max size per APR)
     - For each candidate feature, regress out active set (in ranks)
     - Compute residual IC with same bootstrap CI as standard IC
     - Return `dict[str, ResidualICResult]`
   - Batch processing: parallelize per (symbol, tf, regime) via `ProcessPoolExecutor`
2. Integrate with `ic_engine`:
   - After standard IC computation, call `compute_partial_ic()`
   - Write results to `feature_ic_scores` (new columns)
3. Schema migration:
```sql
ALTER TABLE feature_ic_scores ADD COLUMN partial_ic DOUBLE PRECISION;
ALTER TABLE feature_ic_scores ADD COLUMN partial_ic_ci_lower DOUBLE PRECISION;
ALTER TABLE feature_ic_scores ADD COLUMN marginal_value DOUBLE PRECISION;  -- ic_value - partial_ic
CREATE INDEX idx_feature_ic_partial ON feature_ic_scores(feature_name, symbol, tf, regime) WHERE partial_ic IS NOT NULL;
```
4. Update feature registry promotion gate:
```python
# src/intelligence/feature_registry_service.py
def validate_promotion(self, feature_name: str) -> PromotionResult:
    """Feature earns 'active' on marginal contribution, not standalone IC."""
    feature_ic_row = self.db.fetch_one(
        "SELECT ic_value, partial_ic, partial_ic_ci_lower FROM feature_ic_scores WHERE feature_name = $1",
        feature_name
    )
    
    if feature_ic_row.partial_ic_ci_lower <= 0:
        return PromotionResult.REJECTED, "Partial IC not significant"
    
    marginal_value = feature_ic_row.ic_value - feature_ic_row.partial_ic
    threshold = self.config.get("alpha.orthogonal.feature_residual_ic_threshold")
    if marginal_value < threshold:
        return PromotionResult.REJECTED, f"Marginal value {marginal_value:.4f} below threshold"
    
    return PromotionResult.ACCEPT, "Feature adds orthogonal information"
```
5. Register service in `service_auditor.py` `_DAG_ORDER`

**Verification:**
- Integration test: run on small corpus (2 symbols, 1 TF) → verify partial IC written
- Promotion gate test: feature with high IC but low partial IC correctly rejected
- Service audit: `orthogonalization_engine` appears in DAG order

---

### Wave 3 — Verification + Impact Analysis (1 session)

**162.0-W03-PLAN.md** — Audit current features

**Implementation:**
1. One-time audit script: `scripts/ops/orthogonalization/ops_feature_redundancy_audit.py`
   - Load all 54 features' IC scores
   - Compute marginal value: `ic_value - partial_ic`
   - Flag redundant features: `marginal_value < 0.02`
   - Report: feature name, standalone IC, partial IC, marginal value, recommendation
2. Run audit on current corpus:
   - Fetch `feature_ic_scores` for all active features
   - Generate redundancy report
   - Identify features with marginal contribution < threshold
3. Handle redundant features:
   - Option A: Demote to `shadow_only` (keep in corpus, don't admit to ensemble)
   - Option B: Deprecate (remove from active set entirely)
   - Update `feature_registry` based on findings
4. Documentation:
   - Document redundancy findings in `docs/analysis/feature-redundancy-audit-YYYY-MM-DD.md`
   - Update feature registry governance documentation
   - Record how many features removed/demoted

**Verification:**
- Audit runs successfully on full corpus
- Redundancy report generated with clear recommendations
- At least 1 feature identified as redundant (if none found, investigate why threshold may be too lax)
- Feature registry updated (if redundant features found)
- Ensemble IC Sharpe before vs after redundant feature removal (should improve or stay same)

**Exit Gate Criteria:**
- ✅ Feature-level orthogonalization integrated with `ic_engine`
- ✅ `partial_ic` columns populated for all features
- ✅ Feature registry promotion gate using marginal contribution
- ✅ Redundancy audit completed on current 54 features
- ✅ At least one redundant feature identified and handled (or clear explanation why none found)

---

## Phase 162.1: Regime Level

**Goal:** Validate regime stratification dimensions before admission, preventing regime proliferation.

**Dependencies:** Phase 162.0 complete, Phase 143.1 complete
**Blocks:** Phase 144 (regime unification) — needs orthogonalization discipline first
**Exit Gate:** Regime dimensions must pass substitution test before Concept Registry promotion

### Wave 1 — Regime Substitution Test (1 session)

**162.1-W01-PLAN.md** — Regime orthogonalization math

**Implementation:**
1. Build `substitution_math.py`:
   - `substitution_test_ic_separation(candidate_labels, incumbent_labels, features, returns)`:
     - Run IC stratified by incumbent regime only → `IC_incumbent`
     - Run IC stratified by candidate regime only → `IC_candidate`  
     - Run IC stratified by both (interaction) → `IC_combined`
     - Compute separation: `delta = mean(IC_combined) - mean(IC_incumbent)`
     - Compute label correlation: `correlation(candidate_labels, incumbent_labels)`
   - `evaluate_regime_orthogonality(delta, correlation, thresholds)` → recommendation
2. Extend `OrthogonalizationEngine`:
   - `regime_substitution_test(incumbent_regime, candidate_regime)` method
   - Load regime labels from `market_regimes` (incumbent) and candidate source
   - Call `substitution_test_ic_separation`
   - Return `SubstitutionResult` with recommendation (ACCEPT/REJECT/COMPLEMENT)
3. Schema migration:
```sql
CREATE TABLE regime_orthogonalization_results (
    candidate_dimension TEXT NOT NULL,
    incumbent_dimension TEXT NOT NULL,
    ic_separation_delta DOUBLE PRECISION,
    label_correlation DOUBLE PRECISION,
    recommendation TEXT NOT NULL,  -- 'ACCEPT' | 'REJECT' | 'COMPLEMENT'
    evaluated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (candidate_dimension, incumbent_dimension, evaluated_at)
);
```

**APR Migration:**
```sql
INSERT INTO config_schema (config_key, config_value, description, domain, provenance) VALUES
('alpha.orthogonal.regime_ic_separation_delta_threshold', '0.005', 'Min IC gain for regime substitution test', 'alpha.orthogonal', '[initial_estimate]'),
('alpha.orthogonal.regime_max_correlation', '0.7', 'Max label correlation with incumbent regime', 'alpha.orthogonal', '[initial_estimate]'),
('alpha.orthogonal.regime_min_effective_n', '3000', 'Min obs per regime cell for substitution test', 'alpha.orthogonal', '[initial_estimate]');
```

**Verification:**
- Unit test: synthetic regime labels with known IC separation
- Test rejects highly correlated candidate regime (> 0.9 correlation)
- Test accepts orthogonal candidate regime with clear IC improvement
- APR keys loaded correctly

---

### Wave 2 — StratificationDimension Integration (1 session)

**162.1-W02-PLAN.md** — Wire into governance

**Implementation:**
1. Extend `StratificationDimension` contract:
```python
class StratificationDimension:
    def validate_orthogonality(self, incumbent: StratificationDimension) -> OrthogonalityResult:
        """Substitution test against current dimension."""
        result = ortho_engine.regime_substitution_test(
            incumbent_regime=incumbent,
            candidate_regime=self
        )
        return result
```
2. Concept Registry integration:
   - Add `domain='regime_model'` concept type
   - Every regime model becomes a `concept_registry` row
   - Promotion gate: `validate_activation()` calls `validate_orthogonality()`
   - Demotion gate: regime dimensions that fail substitution tests auto-demoted
3. Load existing 8 regime alternatives as candidates:
   - From `docs/plans/2026-07-01-regime-stratification-alternatives.md`
   - Create `concept_registry` rows for each candidate
   - Set status to `candidate` (not `active` until orthogonalization passes)
4. Update ROADMAP Phase 144:
   - Scope now limited to regime dimensions that pass orthogonalization
   - Phase 144 execution order updated based on substitution test results

**Verification:**
- Integration test: propose synthetic regime dimension → validation runs correctly
- Concept Registry test: regime dimension promotion requires orthogonalization pass
- All 8 alternatives loaded as candidates in `concept_registry`
- ROADMAP Phase 144 scope reflects orthogonalization constraints

---

### Wave 3 — Validation and Decision Making (1 session)

**162.1-W03-PLAN.md** — Test all regime alternatives

**Implementation:**
1. Run substitution tests for all 8 candidates:
   - Candidate set: volatility, dispersion, factor, HMM variants, microstructure, volume, session, skew/tail
   - Incumbent: current cross-sectional regime (`cross_sectional_regime_model.py`)
   - Run `regime_substitution_test` for each candidate
   - Results written to `regime_orthogonalization_results`
2. Analysis and decisions:
   - Which candidates ADD orthogonal information (ACCEPT)
   - Which are redundant with current regime (REJECT)
   - Which are complementary (COMPLEMENT — consider joint model)
   - Generate report: `docs/analysis/regime-orthogonalization-results-YYYY-MM-DD.md`
3. Update `concept_registry`:
   - ACCEPT candidates → promote to `active`
   - REJECT candidates → demote to `shadow_only` or deprecate
   - COMPLEMENT candidates → flag for potential joint modeling
4. ROADMAP update:
   - Phase 144 scope refined to only validated regime dimensions
   - Unblocks Phase 144 execution

**Verification:**
- All 8 candidates tested
- Clear decision documentation (which accepted/rejected/complement)
- Concept Registry updated with validated regime dimensions
- ROADMAP Phase 144 unblocked and refined scope
- Performance: substitution tests complete in reasonable time (< 1 hour per candidate)

**Exit Gate Criteria:**
- ✅ Regime substitution test implemented and validated
- ✅ All 8 regime alternatives tested against incumbent
- ✅ Concept Registry integration complete (promotion requires orthogonalization)
- ✅ ROADMAP Phase 144 unblocked with refined scope
- ✅ Clear documentation of which regime dimensions validated/rejected

---

## Phase 162.2: Prediction Level

**Goal:** Test if AlphaEngine and AnalogEngine add orthogonal information, determine optimal combination or retirement.

**Dependencies:** Phase 162.0 complete, both prediction engines emitting
**Blocks:** Decision on maintaining parallel prediction systems vs convergence
**Exit Gate:** Prediction combination tested and decision made (combine/retire/maintain)

### Wave 1 — Prediction Combination Test (1 session)

**162.2-W01-PLAN.md** — Prediction orthogonalization

**Implementation:**
1. Extend `residual_math.py`:
   - `incremental_r2_combination(scores_a, scores_b, targets, weight_grid)`:
     - Compute OOS R² for each method independently: `R²_a`, `R²_b`
     - Grid search over combination weights: `combined = w_a * scores_a + w_b * scores_b`
     - Compute `R²_combined` for each weight pair
     - Find optimal weights: `argmax(R²_combined)`
     - Compute incremental value: `ΔR² = R²_combined_optimal - max(R²_a, R²_b)`
   - Bootstrap CI for `ΔR²` (circular block bootstrap, same as IC)
2. Extend `OrthogonalizationEngine`:
   - `prediction_combination_test(alpha_scores, analog_scores, returns)` method
   - Load weekly prediction batches from both engines
   - Call `incremental_r2_combination`
   - Return `CombinationResult`: `R²_a`, `R²_b`, `R²_combined`, `optimal_weights`, `ΔR²`, `recommendation`
3. Schema migration:
```sql
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
```
4. Weekly batch scheduling:
   - Create `scripts/ops/prediction/ops_prediction_combination_test.py`
   - Schedule via systemd timer: weekly (Mondays 00:00 UTC)
   - Fetch latest week of predictions from both engines
   - Run combination test → write results

**APR Migration:**
```sql
INSERT INTO config_schema (config_key, config_value, description, domain, provenance) VALUES
('alpha.orthogonal.prediction_incremental_r2_threshold', '0.001', 'Min incremental R² for prediction combination', 'alpha.orthogonal', '[initial_estimate]'),
('alpha.orthogonal.prediction_min_combination_weight', '0.1', 'Min weight to retain prediction method in combination', 'alpha.orthogonal', '[initial_estimate]'),
('alpha.orthogonal.prediction_reval_cadence_days', '7', 'Days between prediction combination re-evaluation', 'alpha.orthogonal', '[initial_estimate]');
```

**Verification:**
- Unit test: synthetic predictions with known combination value
- Bootstrap CI test: verify confidence intervals are reasonable
- Weekly batch script runs end-to-end
- APR keys loaded correctly

---

### Wave 2 — Integration and Monitoring (1 session)

**162.2-W02-PLAN.md** — Wire into prediction pipeline

**Implementation:**
1. Integration with prediction engines:
   - Add combination results logging to both prediction services
   - If combination adds value, update APR combination weights:
   ```python
   if result.incremental_r2 > threshold:
       config_service.set("alpha.ensemble.prediction_combination_weights", result.optimal_weights)
   ```
2. Monitoring and degradation detection:
   - Track `ΔR²` over time (degradation curve)
   - Alert if `ΔR²` drops below threshold for 3 consecutive weeks
   - Monitoring dashboard: combination weights, incremental R² trend
3. Decision framework:
   - If `ΔR² > threshold` consistently → use optimal combination
   - If `ΔR² ≈ 0` consistently → consider retiring weaker method
   - If `ΔR²` highly variable → investigate structural changes
4. Documentation:
   - Prediction architecture decision log
   - Method retirement criteria (if applicable)
   - Combination weight update process

**Verification:**
- Integration test: end-to-end prediction combination flow
- Monitoring dashboard displays combination metrics
- Decision framework documented
- APR combination weight updates tested

---

### Wave 3 — Validation and Decision Making (1 session)

**162.2-W03-PLAN.md** — Backtest and finalize

**Implementation:**
1. 4-week backtest:
   - Run combination test on historical 4-week rolling windows
   - Measure: mean `ΔR²`, stability of optimal weights, consistency of recommendation
   - Compare combined vs independent predictions: OOS Sharpe, hit rate
2. Decision analysis:
   - **Scenario A** (`ΔR²` consistently positive): Use optimal combination
   - **Scenario B** (`ΔR² ≈ 0`): Retire weaker method (simpler system)
   - **Scenario C** (`ΔR²` variable): Investigate regime-dependence, consider conditional combination
3. Architecture decision:
   - Document final decision with evidence
   - Update ROADMAP if method retirement affects planned phases
   - If combination adopted: update prediction emission layer
   - If retirement: deprecation plan for retired method
4. Documentation:
   - `docs/analysis/prediction-combination-decision-YYYY-MM-DD.md`
   - Update prediction architecture docs
   - Record decision rationale and supporting evidence

**Verification:**
- 4-week backtest completed
- Clear decision made with supporting evidence
- Architecture updated based on decision
- Documentation complete with decision rationale

**Exit Gate Criteria:**
- ✅ Prediction combination test implemented and validated
- ✅ 4-week backtest completed with clear findings
- ✅ Decision made: adopt combination/retire method/maintain parallel
- ✅ Architecture and ROADMAP updated based on decision
- ✅ Decision fully documented with supporting evidence

---

## Phase 162.3: Portfolio Level (v4.0)

**Goal:** Portfolio construction with orthogonal bet measurement, diversification gates, and effective N-based Kelly sizing.

**Dependencies:** Phase 162.0 complete, v4.0 execution layer foundation (Phases 156-159)
**Blocks:** Phase 156 (Portfolio State Foundation)
**Exit Gate:** Portfolio orthogonalization live in v4.0, effective N and concentration gates enforced

**Note:** This phase is v4.0 work and should be sequenced as part of the execution layer milestone. The specification is provided here for completeness but execution depends on v4.0 planning.

### Wave 1 — Portfolio Orthogonalization (1 session)

**162.3-W01-PLAN.md** — Portfolio math implementation

**Implementation:**
1. Build `portfolio_math.py`:
   - `compute_position_correlation(positions, returns_history, lookback_days)`:
     - Fetch historical returns matrix (exponential decay, lookback from APR)
     - Compute covariance matrix: `Σ = returns.cov()`
     - Apply position weights: `Σ_p = w' Σ w`
   - `effective_n_from_covariance(covariance_matrix)`:
     - Eigenvalue decomposition: `λ_i`
     - Ledoit-Wolf effective N: `N_eff = trace(Σ) / sum(Σ)` 
     - Alternative: eigenvalue threshold count (λ_i > threshold)
   - `concentration_ratio(eigenvalues)`: `λ_max / sum(λ)`
   - `factor_risk_attribution(covariance, eigenvalues, eigenvectors)`: decompose portfolio variance into independent factors
2. Extend `OrthogonalizationEngine`:
   - `portfolio_effective_n(positions, returns_matrix)` method
   - Return `PortfolioResult`: `n_positions`, `n_effective`, `concentration_ratio`, `factor_risk_allocation`
3. Schema migration:
```sql
CREATE TABLE portfolio_orthogonality_snapshot (
    snapshot_at TIMESTAMPTZ NOT NULL,
    n_positions INTEGER NOT NULL,
    n_effective DOUBLE PRECISION NOT NULL,
    concentration_ratio DOUBLE PRECISION NOT NULL,
    factor_risk_allocation JSONB,
    PRIMARY KEY (snapshot_at)
);
```

**APR Migration:**
```sql
INSERT INTO config_schema (config_key, config_value, description, domain, provenance) VALUES
('alpha.orthogonal.portfolio_min_effective_n_ratio', '0.5', 'Min N_eff / N_positions ratio for diversification', 'alpha.orthogonal', '[initial_estimate]'),
('alpha.orthogonal.portfolio_max_concentration_ratio', '0.3', 'Max λ_max / sum(λ) concentration ratio', 'alpha.orthogonal', '[initial_estimate]'),
('alpha.orthogonal.portfolio_lookback_days', '60', 'Lookback days for portfolio covariance estimation', 'alpha.orthogonal', '[initial_estimate]'),
('alpha.orthogonal.portfolio_risk_factor_limit', '0.2', 'Max variance contribution per independent risk factor', 'alpha.orthogonal', '[initial_estimate]');
```

**Verification:**
- Unit tests: synthetic portfolios with known correlation structure
- Effective N calculation verified on diagonal covariance (N_eff = N_positions)
- Concentration ratio verified on single-factor portfolio (ratio → 1.0)
- APR keys loaded correctly

---

### Wave 2 — Portfolio Construction Integration (1 session)

**162.3-W02-PLAN.md** — Wire into v4.0 portfolio layer

**Implementation:**
1. Integration with Kelly sizing:
   - Replace `N_positions` with `N_effective` in Kelly formula
   - Kelly leverage: `f* = μ / (σ² * N_eff)` (not `N_positions`)
   - Prevents over-leveraging in correlated portfolios
2. Risk allocation gates:
   - Check `N_eff / N_positions >= threshold` (0.5 from APR)
   - Check `concentration_ratio <= threshold` (0.3 from APR)
   - Check factor risk allocation: no single factor > threshold (0.2 from APR)
   - If gates fail: reject portfolio or rebalance
3. Portfolio optimization:
   - Incorporate effective N into objective function
   - Diversification constraint: maximize N_eff subject to return target
   - Position size limits adjusted for correlation
4. Real-time monitoring:
   - Portfolio orthogonalization snapshot computed every rebalance
   - Tracking: N_eff over time, concentration ratio trend
   - Alerts: diversification degradation, concentration spikes

**Verification:**
- Integration test: portfolio construction with orthogonalization gates
- Kelly sizing test: leverage reduced for correlated portfolios
- Gate tests: under-diversified portfolios rejected
- Monitoring dashboard: portfolio orthogonalization metrics displayed

---

### Wave 3 — Validation and Backtesting (1 session)

**162.3-W03-PLAN.md** — Portfolio orthogonalization validation

**Implementation:**
1. Backtest comparison:
   - Portfolio construction with vs without orthogonalization gates
   - Measure: Sharpe ratio, max drawdown, effective N over time
   - Validate: orthogonalization improves risk-adjusted returns
2. Sensitivity analysis:
   - Test different APR threshold values
   - Measure impact on portfolio construction frequency and quality
   - Calibrate thresholds for optimal risk/return tradeoff
3. Documentation:
   - Portfolio construction methodology with orthogonalization
   - Kelly sizing adjustment for effective N
   - Risk allocation process and gates
   - Validation results and recommendations
4. Integration with v4.0:
   - Update Phase 156 specification with orthogonalization requirements
   - Wire portfolio orthogonalization into real-time construction
   - Monitoring and alerting setup

**Verification:**
- Backtest shows orthogonalization improves risk-adjusted returns
- Sensitivity analysis identifies optimal APR threshold values
- Portfolio construction methodology fully documented
- Real-time integration tested and validated

**Exit Gate Criteria:**
- ✅ Portfolio orthogonalization math implemented and tested
- ✅ Integration with Kelly sizing and portfolio construction complete
- ✅ Diversification gates enforced in real-time
- ✅ Backtest validates orthogonalization improves performance
- ✅ Documentation complete and v4.0 integration validated

---

## Cross-Cutting Concerns

### Performance and Scalability

**Feature-level:** Runs with `ic_engine` weekly batch — no latency concerns
**Regime-level:** On-demand (candidate regime proposed) — acceptable latency
**Prediction-level:** Weekly batch — no latency concerns  
**Portfolio-level:** Real-time (every rebalance) — performance critical

**Optimization:**
- Correlation matrix computation: O(N²) but N small (54 features, ~58 positions)
- Eigenvalue decomposition: fast for small matrices
- Residualization: parallelized per (symbol, tf, regime)
- Caching: regime substitution test results cached

### Testing Strategy

**Unit tests:** All math functions with synthetic data
**Integration tests:** End-to-end flows with small corpora
**Backtests:** Historical validation for all 4 levels
**A/B tests:** Feature/promotion/prediction/portfolio decisions with vs without orthogonalization

### Monitoring and Observability

**Metrics to track:**
- Feature-level: % features rejected by partial IC gate, ensemble IC Sharpe trajectory
- Regime-level: % regime candidates rejected, mean IC separation of accepted dimensions
- Prediction-level: ΔR² trend, combination weights stability
- Portfolio-level: N_eff / N_positions ratio, concentration ratio, factor risk allocation

**Alerts:**
- Feature promotion gate rejecting > 50% of candidates (may indicate threshold too strict)
- Regime orthogonalization test failures (substitution test error)
- Prediction ΔR² degradation (combination losing value)
- Portfolio diversification gate failures (concentration risk)

### Documentation Standards

Every orthogonalization decision must be queryable 10 years later:
- **What** vector was tested (candidate)
- **Against what** incumbent set
- **When** the test ran
- **Result** (accept/reject/complement, with metrics)
- **Why** the decision was made (thresholds, rationale)
- **Who/what** made the decision (automated gate, human override)

`concept_registry` + orthogonalization result tables provide this audit trail.

---

## Success Metrics

### Feature Level (Phase 162.0)
- **Redundancy identification:** % of features with marginal value < threshold (target: 5-15%)
- **Promotion discipline:** % of promotions blocked by partial IC gate (target: 20-40%)
- **Ensemble quality:** Ensemble IC Sharpe before vs after orthogonalization (target: improvement or stable)

### Regime Level (Phase 162.1)
- **Dimension validation:** % of regime candidates rejected by substitution test (target: 30-60%)
- **IC separation:** Mean IC separation improvement from validated dimensions (target: > 0.005)
- **Model simplicity:** Number of active regime dimensions (target: < 3)

### Prediction Level (Phase 162.2)
- **Combination value:** Incremental R² from combination vs best single method (target: > 0.001 if combination adopted)
- **Decision clarity:** Clear decision outcome (combine/retire/maintain) with supporting evidence
- **Forecast quality:** Combined vs independent prediction OOS Sharpe (target: combination improves or equal)

### Portfolio Level (Phase 162.3)
- **Diversification:** Mean N_eff / N_positions ratio (target: > 0.5)
- **Concentration:** Mean concentration ratio (target: < 0.3)
- **Risk-adjusted returns:** Portfolio Sharpe with vs without orthogonalization (target: improvement)

---

## Risk Mitigation

### Feature-Level Risks

**Risk:** Partial IC gate too strict → blocks useful features
**Mitigation:** Calibrate threshold on current corpus, monitor rejection rate, adjust APR

**Risk:** Large conditioning sets make residuals noisy  
**Mitigation:** APR `feature_partial_max_set_size` cap, use top-weighted features only

### Regime-Level Risks

**Risk:** Substitution test computationally expensive
**Mitigation:** Cache results, run on symbol subset first, parallelize

**Risk:** Interaction models (regime × regime) increase complexity
**Mitigation:** COMPLEMENT recommendation only flags potential, doesn't auto-build

### Prediction-Level Risks

**Risk:** Weekly cadence too slow for fast-moving markets
**Mitigation:** Monitor ΔR² degradation, trigger re-evaluation on drift detection

**Risk:** Combination weights unstable over time
**Mitigation:** Exponential smoothing of weight history, minimum weight threshold

### Portfolio-Level Risks

**Risk:** Effective N calculation sensitive to estimation error
**Mitigation:** Use Ledoit-Wolf shrinkage, minimum lookback, bootstrap CI for N_eff

**Risk:** Diversification gates prevent valid trades
**Mitigation:** Gates as warnings not hard blocks initially, calibrate thresholds

---

## Timeline and Sequencing

**Immediate (Phase 162.0):** 3-4 sessions
- Architecture + math library (1 session)
- Feature-level implementation (1 session) 
- Audit and verification (1-2 sessions)

**Next (Phase 162.1):** 2-3 sessions  
- Regime substitution test (1 session)
- StratificationDimension integration (1 session)
- Validation and decisions (1 session)

**Parallel (Phase 162.2):** 2-3 sessions
- Can run in parallel with 162.1 if prediction engines both emitting
- Prediction combination test (1 session)
- Integration and monitoring (1 session)
- Validation and backtest (1 session)

**Later (Phase 162.3):** 2-3 sessions
- Depends on v4.0 execution layer foundation
- Portfolio math implementation (1 session)
- Portfolio construction integration (1 session)
- Validation and backtesting (1 session)

**Total:** 9-13 sessions across all 4 levels, can be parallelized

---

## References and Dependencies

**Existing specs:**
- Todo 029 "Feature Scoring Beyond IC" — original marginal contribution spec
- `docs/plans/2026-07-01-regime-stratification-alternatives.md` — 8 regime candidates
- `docs/research/intel-13-analog-engine.md` — AnalogEngine specification
- `docs/research/intel-11-dual-system-discrete-vs-portfolio.md` (archived) — portfolio construction
- `docs/research/unified-orthogonalization-layer.md` — full architecture specification

**Code dependencies:**
- `src/intelligence/statistics/ic_math.py` — bootstrap CI, rankdata
- `services/ic_engine.py` — IC computation integration
- `src/intelligence/feature_registry_service.py` — promotion gate
- `src/config/settings.py` — APR integration

**Database dependencies:**
- `feature_ic_scores` — partial IC columns
- `feature_registry` — promotion gate integration
- `market_regimes` — incumbent regime labels
- `alpha_events` — prediction sources (AlphaEngine, eventually AnalogEngine)

**Phase dependencies:**
- Phase 143.1 COMPLETE — measurement foundation solid
- Phase 144 — blocked until 162.1 complete  
- Phase 148 — benefits from 162.0 feature orthogonalization
- v4.0 (Phases 156-159) — 162.3 sequenced with execution layer

---

## Next Steps

1. **Review this phase plan** for correctness and completeness
2. **File as ROADMAP entry** Phase 162 in appropriate milestone
3. **Prioritize against other pending work** — this unblocks Phase 144
4. **Begin Phase 162.0 execution** when ready (architecture + feature level)
5. **Update STATE.md** to reflect orthogonalization layer in progress

The orthogonalization layer is fully specified and ready to implement. It will add institutional-grade validation discipline across all 4 layers of the system, ensuring every new vector proves it adds orthogonal information before admission.