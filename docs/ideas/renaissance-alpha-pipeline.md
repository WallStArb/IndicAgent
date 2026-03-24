# Renaissance Alpha Pipeline — Deterministic Feature DAG

**Status:** draft
**Priority:** high
**Milestone:** v2.3+
**Last Updated:** 2026-03-24
**Tags:** renaissance, alpha, validation, dag, deterministic, automation, shadow-first

---

## 1. Executive Summary

The Renaissance Alpha Pipeline is a validation framework for all alpha contributors that enforces statistical rigor over architectural complexity. It replaces the "agent swarm" concept with a **Deterministic Feature DAG** where every signal source — whether I1-I7 plugins, ML features, or LLM-derived heuristics — must earn the right to affect position sizing through empirical validation.

**Core Principles:**
- **Show Me the Data** — No intuition, only statistically significant results (p < 0.05, sufficient N)
- **Alpha/Beta Separation** — Research happens offline; production is latency-validated
- **Shadow-First Validation** — No contributor touches production until 14-day correlation passes
- **Automated Governance** — CI/CD pipeline promotes/demotes based on Pearson correlation, not human judgment
- **Information Bottleneck** — Signal-to-noise ratio and predictive causality over complexity

**The Shift:**
- From: "Agent Swarm" with LLM-based real-time decisions
- To: "Deterministic Feature DAG" with high-performance code modules
- LLMs are **research-only** — they discover patterns offline, which get compiled to deterministic Python/C++/Rust

---

## 2. The Renaissance Framework

### 2.1 Alpha/Beta Pipeline Separation

Renaissance separates research from execution through a rigid two-stage pipeline:

**Beta (Research / Offline):**
- Deep, backtested discovery
- Non-causal analysis (uses future data in backtests)
- Pattern recognition via LLMs, statistical analysis, exploratory ML
- Output: Hypotheses about predictive features

**Alpha (Production / Online):**
- Causal, latency-validated implementations
- Only features that passed Beta validation gates
- Real-time execution with strict SLAs
- Output: Multipliers in `[0.0, 2.0]` that scale position sizes

**Key Rule:** Beta and Alpha never mix. A contributor is either in research (no production impact) or production (statistically validated), never both.

### 2.2 IAlphaContributor Interface

Every alpha contributor implements the same contract:

```python
class IAlphaContributor:
    """
    Base contract for all alpha contributors.
    Enforces [0.0, 2.0] multiplier range and shadow logging.
    """

    def compute_multiplier(signal_context: SignalContext) -> float:
        """
        Returns: multiplier in [0.0, 2.0]
        - 0.0 = Kill signal
        - 1.0 = Neutral (no adjustment)
        - 2.0 = Maximum confidence boost
        """
        pass

    def log_shadow_prediction(signal_id: UUID, multiplier: float):
        """
        Writes to shadow table for correlation analysis.
        Required for all contributors, even in production.
        """
        pass
```

**Invariants:**
- Multipliers are clamped to `[0.0, 2.0]` — no exceptions
- Every prediction is logged, even if not used (for ML training data)
- No blocking operations — contributors run asynchronously
- No LLM calls in production hot path

### 2.3 Validation Lifecycle

**Stage 1: Shadow Mode (14 days minimum)**
- Contributor writes predictions to shadow table
- No impact on position sizing
- Accumulates sample size N

**Stage 2: Correlation Gate**
- Daily job computes `Pearson(Contributor_Confidence, Realized_PnL_R)`
- Promotion criteria:
  - `N ≥ 100` (minimum sample size)
  - `ρ > 0.4` (positive correlation)
  - `p < 0.05` (statistical significance)

**Stage 3: Production**
- Multipliers feed into SignalLifecycleService
- Affects position sizing in real-time
- Continues shadow logging for ongoing monitoring

**Stage 4: Automated Degradation**
- Daily correlation checks continue
- If `ρ < 0.2` for 7 consecutive days: auto-disable
- If `p > 0.10` for 14 days: auto-disable
- Manual override requires root-level approval

### 2.4 Data Contract

**AlphaMultiplier Schema:**
```
{
  "signal_id": "uuid",
  "ts": "UTC_ISO",
  "contributors": {
    "regime_sentinel": {"multiplier": 0.3, "confidence": 0.82, "metadata": {...}},
    "liquidity_arbiter": {"multiplier": 1.0, "confidence": 0.65, "metadata": {...}},
    "smc_validator": {"multiplier": 1.2, "confidence": 0.91, "metadata": {...}}
  },
  "final_alpha_multiplier": 0.36,
  "is_safe": true,
  "validation_error": null
}
```

**Shadow Table Structure:**
- `contributor_id` — Which feature produced this
- `signal_id` — Link to signal_ledger
- `predicted_multiplier` — What the contributor said
- `timestamp` — When prediction was made
- `outcome_pnl_r` — Realized PnL multiple (back-filled post-exit)
- `regime_at_fire` — Regime label for segmentation
- `is_production` — Whether this was used for sizing

### 2.5 Safety Infrastructure

**SafeSwarm Pattern (Concept):**
- **Hard Shell** — Schema validation enforces types and ranges. Invalid JSON → immediate neutral (1.0).
- **Soft Shell** — Heuristic checks clamp values to safe bounds. Out-of-range → error logged, neutral returned.
- **Fallback Behavior** — On any error, return `multiplier=1.0` with `is_safe=false` and `validation_error` field populated
- **Defense-in-Depth** — Multiple validation layers: Pydantic schema, range checks, statistical gates

---

## 3. System Architecture

### 3.1 Predictive DAG Overview

``                    ┌─────────────────────────────────────┐
                    │   SignalLifecycleService (Entry)    │
                    └──────────────────┬──────────────────┘
                                       │
                    ┌──────────────────┴──────────────────┐
                    │     Alpha Contributors (Async)      │
                    └──────────────────┬──────────────────┘
                                       │
            ┌──────────────────────────┼──────────────────────────┐
            │                          │                          │
    ┌───────▼───────┐        ┌───────▼───────┐        ┌───────▼───────┐
    │   Regime/     │        │     SMC/      │        │   Cross-Asset │
    │   Entropy     │        │   Liquidity   │        │     & Macro   │
    │  Contributors │        │  Contributors │        │  Contributors │
    └───────────────┘        └───────────────┘        └───────────────┘
            │                          │                          │
    ┌───────▼───────┐        ┌───────▼───────┐        ┌───────▼───────┐
    │  Model Quality│        │   Structural  │        │  Contagion &  │
    │  Contributors │        │   Validation  │        │    Events     │
    └───────────────┘        └───────────────┘        └───────────────┘
                                       │
                    ┌──────────────────┴──────────────────┐
                    │     Multiplier Aggregation          │
                    │   (Weighted avg / Geometric mean)   │
                    └──────────────────┬──────────────────┘
                                       │
                    ┌──────────────────▼──────────────────┐
                    │   Final Alpha Multiplier [0.0,2.0]  │
                    └──────────────────┬──────────────────┘
                                       │
                    ┌──────────────────▼──────────────────┐
                    │     Position Sizing Adjustment      │
                    └─────────────────────────────────────┘
```

### 3.2 Contributor Types

**I. Regime & Entropy Contributors**
- Project market state onto latent manifold (entropy, dispersion, momentum)
- Detect regime transitions (HMM state changes)
- Compare implied vol vs realized vol (volatility compression/expansion)
- Output: `regime_multiplier`, `transition_probability`

**II. SMC & Structural Liquidity Contributors**
- Map signals against Order Blocks, FVG, support/resistance
- Quantify "proximity to structural trap" — signals inside OBs have lower alpha
- Detect liquidity sweeps vs true breakouts
- Monitor LOB dynamics for fill probability
- Output: `structural_multiplier`, `trap_probability`, `lob_friction_score`

**III. Cross-Asset & Macro Contributors**
- Monitor correlation drift (ES vs NQ, equity index vs VIX)
- Detect contagion patterns — if NQ shows liquidity decay, ES follows
- Track macro events (FOMC, CPI) with pre-event risk adjustment
- Output: `cross_asset_multiplier`, `event_risk_adjustment`

**IV. Model Quality Contributors**
- Monitor model drift in real-time
- If recent outcomes drop 3σ below 30-day mean → trigger `SystemicPause`
- Run counterfactual analysis: "Given this state, what's fail probability?"
- Output: `model_health_multiplier`, `systemic_pause_flag`

### 3.3 Data Flow & Performance

**Hot Path (Real-time, <10ms):**
1. Signal fires → `SignalContext` published to stream
2. Contributors consume asynchronously (never block signal execution)
3. Each contributor computes `multiplier` from numeric tensors only
4. No LLM calls, no database queries, no blocking I/O
5. Multipliers aggregated → `final_alpha_multiplier`
6. Feed into `SignalLifecycleService` for position sizing

**Warm Path (Shadow logging, async):**
1. All predictions written to shadow table (even unused ones)
2. Background job computes correlation nightly
3. Promotion/demotion flags updated automatically

**Cold Path (Offline research, no latency concern):**
1. LLMs analyze historical patterns
2. Statistical ML models discover features
3. Heuristics compiled to deterministic code
4. New contributors deployed to shadow mode

**Performance Design:**
- Contributors process `numpy` arrays or tensors — no per-bar object allocation
- State cached in memory (e.g., swing points, regime history)
- C++/Rust acceleration for: matrix operations, statistical computations, distance metrics
- Strict SLAs: contributor execution < 5ms p99

### 3.4 Separation of Concerns

**Contributors (Analytical Layer):**
- Pure functions over feature vectors
- No knowledge of other contributors
- No LLM calls, no network I/O
- Return `float` multiplier only

**Orchestrator (Integration Layer):**
- Manages contributor lifecycle
- Aggregates multipliers
- Handles failures (fallback to neutral)
- Publishes to streams

**Validator (Governance Layer):**
- Runs correlation checks
- Manages promotion/demotion
- Monitors drift
- Enforces statistical gates

---

## 4. Implementation Strategy

### Phase 0: Design Audit
**Goal:** Map SignalLifecycleService dependencies, identify injection points.

**Deliverables:**
1. Dependency graph of current signal pipeline
2. Injection point specification — where multipliers enter position sizing
3. Performance baseline — current latency measurements
4. Contributor taxonomy — what exists vs what's missing

**Success Criteria:**
- Clear understanding of where `final_alpha_multiplier` plugs in
- No architectural surprises

### Phase 1: The Kernel
**Goal:** Define IAlphaContributor base class, implement shadow logging.

**Deliverables:**
1. `IAlphaContributor` interface with `[0.0, 2.0]` enforcement
2. Shadow table schema + migration
3. Base contributor class with `log_shadow_prediction()` implemented
4. Safety wrapper pattern (range clamping, validation error handling)
5. Unit tests for boundary conditions (0.0, 1.0, 2.0, out-of-range)

**Success Criteria:**
- Any new contributor automatically logs to shadow table
- Multipliers never exceed `[0.0, 2.0]` even if code has bugs
- Validation errors return neutral (1.0) with `is_safe=false`

### Phase 2: The Validator
**Goal:** Automate shadow-to-prod promotion with correlation checks.

**Deliverables:**
1. CLI tool: `alpha-validator --check-correlation --contributor=<id>`
2. Daily cron job: computes Pearson r for all shadow contributors
3. Promotion logic: auto-enable when `ρ > 0.4, N ≥ 100, p < 0.05`
4. Degradation logic: auto-disable when `ρ < 0.2` for 7 days
5. Dashboard panel: show contributor health, correlation trends
6. Manual override workflow (requires approval)

**Success Criteria:**
- Zero manual steps for promotion/demotion
- Contributor performance tracked continuously
- Failed promoters alert before trading session

### Phase 3+: Contributor Development
**Goal:** Build out contributor catalog using Renaissance framework.

**Deliverables:**
1. Refactor existing I1-I7 plugins to implement `IAlphaContributor` (if applicable)
2. Build new contributors: Regime Sentinel, Liquidity Arbiter, SMC Validator, etc.
3. Each contributor ships with shadow mode enabled
4. Weekly review of correlation results
5. Promote validated contributors to production

**Success Criteria:**
- All contributors follow same interface
- Shadow table accumulating training data
- At least 3 contributors promoted after 14-day validation

---

## 5. Technology Stack — Renaissance-Aligned Choices

**Why this matters:** Tech stack IS architecture. Library choices determine performance boundaries, scalability limits, and what's even possible. Renaissance demands: proven tools, minimal dependencies, nothing over-engineered for the problem at hand.

### 5.1 Core ML Infrastructure (Already Decided in tech-stack.md)

| Package | Purpose | Renaissance Alignment |
|---------|---------|----------------------|
| `lightgbm` | The model — tabular data champion | Fast training, handles categoricals natively, dominates benchmarks |
| `scikit-learn` | Feature selection, preprocessing, cross-validation | Already in stack for CISScorer |
| `scipy` | Pearson correlation, p-values, significance tests | Phase 2 validator foundation |
| `statsmodels` | Stationarity tests (ADF), CUSUM changepoint, time series stats | Ensures features aren't spurious |
| `polars` | Rust dataframes, 10-100× faster than pandas | Feature matrix generation without bottleneck |
| `numpy` | Already in use — tensor operations | Foundational |

### 5.2 Feature Discovery & Validation (Beta Pipeline)

| Package | Purpose | Renaissance Alignment |
|---------|---------|----------------------|
| `alphalens-reloaded` | Quant-standard IC/ICIR analysis | Measures predictive power per feature — "show me the data" |
| `tsfresh` | Auto time series feature extraction (700+ features) | Let data speak, don't hand-engineer |
| `evidently` | Drift detection (KS/PSI/Wasserstein) | Automated degradation detection |
| `shap` | TreeSHAP explainability | Why did model score this signal? Attribution matters |

### 5.3 Model Training & Tuning

| Package | Purpose | Renaissance Alignment |
|---------|---------|----------------------|
| `optuna` | Bayesian hyperparameter optimization | Auto-tune without manual knob-turning |
| `MLflow` (self-hosted) | Experiment tracking, model registry | Version every model, compare 20 runs |

### 5.4 What We're NOT Adding (And Why)

| Technology | Why NOT | Renaissance Principle |
|------------|---------|----------------------|
| **PyTorch/TensorFlow** | Overkill for tabular scoring; tree ensembles dominate | Use the simplest tool that works |
| **Ray/Dask** | Overkill for data volume; polars is sufficient | Don't add complexity before proven need |
| **Feast** | TimescaleDB IS our feature store | Consolidate before expanding |
| **Weights & Biases** | Cloud, paid; MLflow is open-source | No vendor lock-in |
| **Temporal** | Institutional-scale; LangGraph sufficient for now | Add when trigger is real, not before |

### 5.5 Architecture Implications

**Model Choice → Feature Engineering:**
- LightGBM handles categoricals natively → No one-hot encoding needed for regime/setup/TF
- Tree-based → No feature scaling required (unlike SVM/NN)
- SHAP values → Per-signal attribution is cheap, not expensive post-hoc analysis

**Performance → Data Flow:**
- Polars for batch jobs (feature matrix building, retraining)
- NumPy for real-time (single-signal inference, <5ms SLA)
- No "convert to pandas then back" — choose one and stay there

**Observability → Debugging:**
- MLflow run IDs logged to `ml_models` table → Full reproducibility
- SHAP values stored per-signal in JSONB → "Why was this signal boosted?" is answerable
- Evidently reports persisted → Drift history is queryable

**Scalability Boundaries:**
- LightGBM trains on 100K rows in <30 seconds (single machine)
- Polars processes 1M features × 10K signals in <2 minutes
- River (online learning) for Phase 3 — continuous adaptation without full retrain

### 5.6 Integration Points

**Phase 2 (The Validator) uses:**
- `scipy.stats.pearsonr` — correlation coefficient
- `scipy.stats.linregress` — p-value, confidence interval
- `asyncpg` — query shadow table, compute stats in SQL where possible

**Phase 54 (ML Scoring Model) uses:**
- `polars.DataFrame` — build feature matrix from `intelligence_features`
- `lightgbm.train()` — fit per-regime × per-setup × per-TF models
- `shap.TreeExplainer` — compute feature attributions
- MLflow model registry — version and track all trained models

**Beta Pipeline (Discovery) uses:**
- `tsfresh.extract_features()` — auto-generate candidate features
- `alphalens-reloaded` — compute IC/ICIR per feature
- `evidently.DriftDetector` — catch distribution shifts before they corrupt models

---

## 6. Practical Handbook

### 5.1 Contributor Template

**What Every Contributor Needs:**

1. **Metadata** — `contributor_id`, `version`, `regime_type` (trend/mean_reversion/any)
2. **Input Specification** — What features from `IntelligenceEvent` are consumed
3. **Compute Function** — `compute_multiplier(context: SignalContext) -> float`
4. **Shadow Logging** — Automatic via base class
5. **Validation Tests** — Unit tests for edge cases, integration test with sample data

**Example Skeleton:**

```python
class RegimeSentinelContributor(IAlphaContributor):
    contributor_id = "regime_sentinel"
    version = "1.0.0"
    regime_type = "any"

    def compute_multiplier(self, context: SignalContext) -> float:
        # 1. Extract features from context
        hmm_regime = context.features.get("hmm_regime")
        entropy = context.features.get("shannon_entropy")

        # 2. Compute heuristic (deterministic, no LLM)
        if hmm_regime == 0 and entropy > 0.7:
            return 0.3  # Ranging regime with high entropy -> suppress trend signals
        elif hmm_regime in [1, 2] and entropy < 0.4:
            return 1.4  # Trending regime with low entropy -> boost
        else:
            return 1.0  # Neutral
```

### 5.2 Validation Checklist

**Before Submitting to Shadow Mode:**
- [ ] Multiplier always in `[0.0, 2.0]` (test with 0.0, 1.0, 2.0, -0.1, 2.5 inputs)
- [ ] No blocking operations (no LLM calls, no DB queries, no sleep())
- [ ] Pure function (same inputs → same outputs)
- [ ] Unit tests cover edge cases (null features, regime transitions, extreme values)
- [ ] Metadata complete (contributor_id, version, regime_type)
- [ ] Shadow logging confirmed (check shadow table after test run)

**Before Promotion to Production:**
- [ ] Shadow mode running ≥14 days
- [ ] Sample size `N ≥ 100`
- [ ] Pearson correlation `ρ > 0.4`
- [ ] P-value `p < 0.05`
- [ ] No regime overfitting (works in at least 2 regimes)
- [ ] Latency `< 5ms` p99
- [ ] Code review passed
- [ ] Manual risk assessment documented

### 5.3 Common Pitfalls

**Overfitting to Regime:**
- Symptom: `ρ = 0.8` in trending regime, `ρ = -0.2` in ranging
- Fix: Add regime gates or build separate contributors per regime

**Data Leakage:**
- Symptom: Backtest shows `ρ = 0.9`, live performance `ρ = 0.1`
- Fix: Ensure no future data used in `compute_multiplier()` — only features available at signal time

**Latency Spikes:**
- Symptom: P99 latency > 50ms, occasional > 500ms outliers
- Fix: Pre-compute expensive operations, cache in memory, move to C++/Rust

**Regime Bias:**
- Symptom: Contributor only fires in one regime type
- Fix: Declare `regime_type` correctly, let aggregator suppress in wrong regime

**Sparse Signals:**
- Symptom: `N < 30` after 30 days
- Fix: Lower activation threshold or broaden conditions (don't over-constrain)

---

## 7. CI/CD & Automation

### 6.1 Pipeline Gates

**Pre-Commit (Local):**
- Unit tests pass
- Ruff linting clean
- Type checking (mypy) passes
- No TODO/FIXME in new code

**Pre-Merge (CI):**
- All tests pass (unit + integration)
- Shadow table schema migration validates
- Contributor metadata validation
- Code review approval required

**Pre-Production (Staging):**
- Shadow mode deployment for ≥14 days
- Correlation checks pass (ρ > 0.4, p < 0.05)
- Latency benchmark passes (< 5ms p99)
- Manual sign-off from quant lead

**Production:**
- Gradual rollout (10% → 50% → 100% of signals)
- Monitor correlation drift in real-time
- Auto-rollback if ρ drops < 0.2 for 3 consecutive days

### 6.2 Promotion Criteria

**Automatic Promotion (No human干预):**
- `N ≥ 100` (minimum sample size)
- `ρ > 0.4` (positive correlation with PnL_R)
- `p < 0.05` (statistically significant)
- `Latency < 5ms` p99
- `No regime overfitting` (works in ≥2 regimes)

**Automatic Demotion:**
- `ρ < 0.2` for 7 consecutive days
- `p > 0.10` for 14 consecutive days
- `Latency > 50ms` p99 for 3 consecutive days
- `Validation error rate > 5%`

**Manual Override:**
- Root-level approval required
- Must document justification
- Triggers audit trail

### 6.3 Monitoring & Dashboards

**Contributor Health Panel:**
- Current correlation (ρ) with 7-day/14-day/30-day windows
- P-value trend
- Sample size (N)
- Latency distribution (p50, p99, max)
- Validation error rate
- Regime breakdown (performance by hmm_regime)

**Aggregate Metrics:**
- Total contributors in shadow vs production
- Promotion rate (contributors promoted / total)
- Degradation rate (contributors demoted / total)
- System-wide alpha (average final_multiplier across all signals)

**Alerts:**
- Contributor correlation drops < 0.3 (warning)
- Contributor correlation drops < 0.2 (critical)
- Validation error rate > 5% (critical)
- Latency > 20ms p99 (warning)
- Contributor auto-disabled (info)

### 6.4 Rollback Procedures

**Automatic Rollback:**
- Triggered by: correlation drop, latency spike, error rate surge
- Action: Set `is_production=false`, stop feeding multipliers
- Notification: Alert quant team, log to incident dashboard

**Manual Rollback:**
- CLI: `alpha-validator --disable --contributor=<id> --reason="<why>"`
- Requires: Root-level approval
- Audit: Logged to `contributor_audit_log` table

**Recovery:**
- Contributor must pass promotion gates again
- Minimum 7-day shadow period after rollback
- Root cause analysis required before re-promotion

---

## 8. Renaissance Principles Deep Dive

### 7.1 Information Bottleneck

**The Core Idea:** Not all data is signal. Most is noise. The Renaissance framework focuses on the **information bottleneck** — extracting only the predictive features that improve signal-to-noise ratio.

**Practical Application:**
- Every contributor must answer: "What predictive information does this add that's not already captured?"
- Correlation analysis filters out features that sound smart but don't predict PnL
- Regime segmentation prevents global rules that fail in specific contexts

**Anti-Pattern to Avoid:**
- Adding contributors because "they seem useful" without empirical validation
- Complex models that overfit historical data
- Features that are proxies for the same signal (e.g., 5 different momentum indicators)

### 7.2 "Show Me the Data"

**The Renaissance Culture:**
- No intuition, no "this should work," no expert opinion
- Only statistically significant evidence (p < 0.05, sufficient N)
- Shadow mode is non-negotiable — every contributor proves itself

**Practical Application:**
- Contributor debates are settled by correlation numbers, not persuasion
- Failed contributors are celebrated (we learned what doesn't work)
- Documentation includes correlation charts, p-values, regime breakdowns

**Anti-Pattern to Avoid:**
- Bypassing shadow mode for "high-confidence" contributors
- Promoting based on backtest only (no live validation)
- Ignoring statistical significance thresholds

### 7.3 Automated Over Manual

**The Renaissance Approach:**
- Build feedback loops that self-correct
- No manual tuning, no knob-turning, no discretionary intervention
- Systems degrade gracefully, adapt automatically

**Practical Application:**
- Promotion/demotion is automated, not committee-decided
- Correlation checks run daily without human trigger
- Failed contributors auto-disable before they cause damage

**Anti-Pattern to Avoid:**
- Manual overrides for "special cases"
- Disabling automation when it disagrees with intuition
- Parameter tuning based on recent performance (overfitting)

### 7.4 Segment Relentlessly

**The Renaissance Insight:**
- A rule that works globally is weaker than one that works in a specific regime
- Trend-following signals fail in ranging markets
- Mean-reversion signals fail in trending markets
- The same contributor can have `ρ = 0.6` in one regime, `ρ = -0.3` in another

**Practical Application:**
- Every contributor declares `regime_type`: "trend", "mean_reversion", or "any"
- Performance is analyzed per regime, not globally
- Regime-specific contributors suppress automatically in wrong regime

**Anti-Pattern to Avoid:**
- "This works most of the time" (which regime?)
- Ignoring regime breakdown in correlation analysis
- One-size-fits-all contributors

---

## 9. Next Steps

### Immediate Actions:
1. **Review and refine this document** — Challenge assumptions, add missing requirements
2. **Map current SignalLifecycleService** — Phase 0 design audit
3. **Define shadow table schema** — Get consensus on data model
4. **Build IAlphaContributor interface** — Phase 1 kernel

### Success Metrics (3-month horizon):
- [ ] Shadow table accumulating ≥1,000 predictions/day
- [ ] At least 3 contributors in shadow mode
- [ ] At least 1 contributor promoted to production
- [ ] Zero manual intervention in promotion/demotion
- [ ] Correlation dashboard operational

### Long-term Vision (6-12 months):
- Catalog of 20+ validated contributors across regime/SMC/cross-asset/model quality
- Automated contributor discovery pipeline (LLM research → code generation → validation)
- Continuous retraining loop (contributors updated weekly from fresh data)
- A/B testing framework for contributor comparisons

---

## Appendix: From "Swarm" to "DAG" — Concept Mapping

### Reusable Concepts:
- **Shadow validation infrastructure** — PostgreSQL logging, 14-day rolling correlation, promotion/demotion gates
- **AlphaMultiplier contract** — Aggregate output with per-contributor breakdown, final multiplier in `[0.0, 2.0]`, safety flags
- **Safety wrapper pattern** — Range enforcement, schema validation, neutral fallback on error
- **Contributor categories** — Regime/entropy, SMC/liquidity, cross-asset/macro, model integrity (implemented deterministically)
- **Promotion criteria** — ρ > 0.4 threshold, minimum sample size, automated degradation

### What Changes:
- **LLM-based agents** → Deterministic feature extractors (Python/C++/Rust modules)
- **Real-time LLM calls** → Offline research only, compile heuristics to code
- **"Agent" terminology** → "Alpha Contributor" or "Feature Extractor"
- **Chat orchestration** → Strict DAG data flow

### What Stays:
- **No blocking** — Contributors run out-of-band, never block signal execution
- **Differentiable outputs** — Everything is a quantifiable vector (multiplier, probability, score)
- **Shadow-first validation** — No production impact until proven statistically
- **Rigid schemas** — Type-safe contracts enforced at boundaries
