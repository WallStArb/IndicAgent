---
phase: 139-ensemble-alpha-emission
plan: P1
type: execute
wave: 1
depends_on: []
files_modified:
  - production/migrations/168_ensemble_tables.sql
  - src/core/stream_keys.py
  - src/observability/metrics.py
  - src/intelligence/ensemble/__init__.py
  - src/intelligence/ensemble/feature_selector.py
  - src/intelligence/ensemble/covariance.py
  - src/intelligence/ensemble/weights.py
  - src/intelligence/ensemble/alpha_score.py
  - tests/unit/test_ensemble_math.py
autonomous: true

must_haves:
  truths:
    - "Three v3.0 tables exist: ensemble_weights, ensemble_alpha, alpha_events"
    - "All 9 alpha.ensemble.* and alpha.quant.threshold.* APR keys are seeded and loadable via ConfigService"
    - "Pure functions exist for feature selection, Ledoit-Wolf covariance, IC-Sharpe weight derivation, and composite alpha scoring"
    - "effective_N is computed as 1/sum(w^2) on the post-cap post-renorm weight vector"
    - "Per-feature weight cap of 0.20 is enforced with iterative proportional redistribution"
    - "topic_alpha_events() returns the env-prefixed alpha.events topic string"
    - "alpha_events PRIMARY KEY is (event_id, bar_ts) — composite PK required for TimescaleDB hypertable"
  artifacts:
    - path: "production/migrations/168_ensemble_tables.sql"
      provides: "ensemble_weights + ensemble_alpha + alpha_events DDL and APR seeds"
      contains: "CREATE TABLE IF NOT EXISTS ensemble_weights"
    - path: "src/intelligence/ensemble/weights.py"
      provides: "derive_weights() and effective_n() pure functions"
      min_lines: 30
    - path: "src/intelligence/ensemble/alpha_score.py"
      provides: "compute_alpha_score() with analytic CI propagation"
      min_lines: 20
    - path: "src/intelligence/ensemble/covariance.py"
      provides: "compute_shrinkage_covariance() LedoitWolf wrapper"
      min_lines: 15
    - path: "tests/unit/test_ensemble_math.py"
      provides: "Unit coverage for cap, effective_N, CI propagation, LedoitWolf"
      min_lines: 60
  key_links:
    - from: "src/intelligence/ensemble/covariance.py"
      to: "sklearn.covariance.LedoitWolf"
      via: "import and fit(X)"
      pattern: "from sklearn.covariance import LedoitWolf"
    - from: "src/core/stream_keys.py"
      to: "alpha.events topic"
      via: "topic_alpha_events function"
      pattern: "def topic_alpha_events"
---

<objective>
Build the Phase 139 foundation: DB schema (three v3.0 tables), APR seeds (9 keys), the pure-function ensemble math library, the Kafka topic key, and OTel metric definitions — all unit-tested and independent of corpus data.

Purpose: Phase 139 P2 (services) and P3 (corpus run) build on this. Separating schema + pure math + tests into one plan keeps the math testable without DB or data, matching the Phase 138 P2/P7 pattern where pure functions live in their own module with dedicated unit tests.
Output: Migration 168, `src/intelligence/ensemble/` module (4 pure-function files), `topic_alpha_events()` in stream_keys.py, ensemble/alpha OTel gauges in metrics.py, and `tests/unit/test_ensemble_math.py`.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/139-ensemble-alpha-emission/139-RESEARCH.md
@docs/plans/2026-06-20-alphaengine-architecture.md
@production/migrations/161_alpha_ic_apr_keys.sql
@production/migrations/160_ic_engine_tables.sql
@src/core/agent/base_batch.py
@src/core/stream_keys.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Migration 168 — ensemble tables + APR seeds</name>
  <read_first>
    - production/migrations/161_alpha_ic_apr_keys.sql (APR seed migration template: config_schema + config_state two-section pattern, ON CONFLICT (config_key) DO NOTHING, provenance tags in descriptions)
    - production/migrations/160_ic_engine_tables.sql (hypertable + content-key + partial-index DDL pattern from Phase 138)
    - .planning/phases/139-ensemble-alpha-emission/139-RESEARCH.md (DB Schema section lines 443-519 and APR Keys section lines 523-539 — exact column lists)
    - docs/plans/2026-06-20-alphaengine-architecture.md (alpha_events schema lines 371-397)
  </read_first>
  <action>
    Create production/migrations/168_ensemble_tables.sql with three sections.

    Section 1 — DDL for three tables (use exact columns from RESEARCH.md DB Schema):
    - ensemble_weights: columns symbol text, tf text, regime text, weight_version text, feature_name text, ic_sharpe double precision, raw_weight double precision, weight double precision NOT NULL, lookahead_bars integer NOT NULL, effective_n double precision, computed_at timestamptz NOT NULL DEFAULT now(); PRIMARY KEY (symbol, tf, regime, weight_version, feature_name); NOT a hypertable; CREATE INDEX IF NOT EXISTS ensemble_weights_lookup_idx ON ensemble_weights (symbol, tf, regime, weight_version).
    - ensemble_alpha: columns symbol text, tf text, bar_ts timestamptz, weight_version text, regime text, alpha_score double precision NOT NULL, alpha_ci_lower double precision, alpha_ci_upper double precision, effective_n double precision, n_features_active integer, computed_at timestamptz NOT NULL DEFAULT now(); PRIMARY KEY (symbol, tf, bar_ts, weight_version); SELECT create_hypertable('ensemble_alpha', 'bar_ts', chunk_time_interval => INTERVAL '3 months', if_not_exists => TRUE); CREATE INDEX IF NOT EXISTS ensemble_alpha_symbol_tf_idx ON ensemble_alpha (symbol, tf, bar_ts DESC).
    - alpha_events: columns event_id text, symbol text, tf text, bar_ts timestamptz, ensemble_version text NOT NULL, weight_version text NOT NULL, regime text, alpha_score double precision NOT NULL, alpha_ci_lower double precision, alpha_ci_upper double precision, effective_n double precision, n_features_active integer, emission_threshold double precision, direction text NOT NULL CHECK (direction IN ('long','short')), top_features jsonb NOT NULL, emitted_at timestamptz NOT NULL DEFAULT now(); PRIMARY KEY (event_id, bar_ts) — composite PK including bar_ts is required for TimescaleDB hypertable enforcement across chunks; SELECT create_hypertable('alpha_events', 'bar_ts', chunk_time_interval => INTERVAL '3 months', if_not_exists => TRUE); CREATE INDEX IF NOT EXISTS alpha_events_symbol_tf_idx ON alpha_events (symbol, tf, bar_ts DESC). Note: top_features is NOT NULL — the architecture doc traceability invariant requires top_features never be null on an emission. event_id is still generated by BaseBatch.content_key() — only the PK definition changes, not the content_key formula.
    All CREATE TABLE use IF NOT EXISTS.

    Section 2 — config_schema INSERTs (mirror migration 161 column set: config_key, value_type, default_value, min_value, max_value, description) for the 9 keys, with provenance tags in description:
    - alpha.ensemble.max_feature_weight float 0.20 min 0.05 max 1.0 [conventional]
    - alpha.ensemble.effective_n_gate float 3.0 min 1.0 max 20.0 [initial_estimate]
    - alpha.ensemble.weight_version str 'v1' (text type — set min/max NULL) [operator_controlled]
    - alpha.ensemble.lookahead_selection str 'max_ic_sharpe' [initial_estimate]
    - alpha.ensemble.min_passing_features int 5 min 1 max 61 [initial_estimate] — minimum of 5 features required per stratum; 5 × max_weight(0.20) = 1.0 ensures the weight cap constraint is mathematically feasible; values below 5 with max_weight=0.20 cannot produce a valid normalized weight vector. NOT an ML learning target.
    - alpha.quant.threshold.5m float 1.5 min 0.1 max 5.0 [initial_estimate]
    - alpha.quant.threshold.15m float 1.2 min 0.1 max 5.0 [initial_estimate]
    - alpha.quant.threshold.1h float 1.0 min 0.1 max 5.0 [initial_estimate]
    - alpha.quant.threshold.1d float 0.8 min 0.1 max 5.0 [initial_estimate]
    Each description must note it is NOT an ML learning target and explain the transaction-cost-threshold semantics for the threshold keys (per RESEARCH.md Pitfall 4 — thresholds are in composite z-score units, to be recalibrated post corpus run). Close with ON CONFLICT (config_key) DO NOTHING.

    Section 3 — config_state INSERTs (config_key, config_value, version=1) for the same 9 keys with values matching defaults (min_passing_features = '5'); ON CONFLICT (config_key) DO NOTHING.

    Apply the migration: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/168_ensemble_tables.sql
  </action>
  <verify>
    PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d ensemble_weights" shows the weight, effective_n, lookahead_bars columns.
    PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d alpha_events" shows top_features jsonb NOT NULL, direction CHECK constraint, and PRIMARY KEY (event_id, bar_ts).
    PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT count(*) FROM config_state WHERE config_key LIKE 'alpha.ensemble.%' OR config_key LIKE 'alpha.quant.threshold.%'" returns 9.
    PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT config_value FROM config_state WHERE config_key = 'alpha.ensemble.min_passing_features'" returns '5'.
    PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_name IN ('ensemble_alpha','alpha_events')" returns 2.
  </verify>
  <acceptance_criteria>
    - File production/migrations/168_ensemble_tables.sql exists
    - `\d ensemble_weights` lists PRIMARY KEY (symbol, tf, regime, weight_version, feature_name)
    - `\d alpha_events` shows PRIMARY KEY (event_id, bar_ts) — composite, not single-column
    - `\d alpha_events` shows top_features as NOT NULL and a CHECK on direction
    - SELECT count over config_state for the two namespaces returns exactly 9
    - SELECT config_value WHERE config_key = 'alpha.ensemble.min_passing_features' returns '5' (not '3')
    - ensemble_alpha and alpha_events are registered hypertables (count = 2)
    - Re-running the migration produces no errors and no duplicate rows (idempotent via IF NOT EXISTS + ON CONFLICT)
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 2: Pure-function ensemble math library</name>
  <read_first>
    - .planning/phases/139-ensemble-alpha-emission/139-RESEARCH.md (Architecture Patterns 1-4, lines 90-220 — exact function signatures for compute_shrinkage_covariance, derive_weights, compute_alpha_score, plus the effective_N formula and lookahead-selection rule)
    - src/intelligence/schemas.py lines 1204-1299 (FeatureVector — the 61 feature field names; feature_selector and alpha_score must align to these column names)
    - services/ic_engine.py lines 100-110 (how feature names are derived from FeatureVector dataclass fields — replicate so the ensemble reads the same canonical name list)
    - docs/plans/2026-06-20-alphaengine-architecture.md (ensemble section lines 204-229 — alpha_raw = Σ sign(ic[f]) × centered_score[f] × weight[f])
  </read_first>
  <action>
    Create src/intelligence/ensemble/ package (Ring 1, no DB imports, no Kafka imports — pure functions only). Add __init__.py exporting the public functions.

    feature_selector.py — function select_features_per_stratum(rows: list[dict]) -> list[dict]: input is rows from feature_ic_scores already filtered to WHERE is_pooled = false AND passes_walkforward = true AND reliable = true AND ic_sharpe IS NOT NULL for one (symbol, tf, regime). Group by feature_name; for each feature keep the single row with the highest ic_sharpe (lookahead disambiguation per RESEARCH.md Pitfall 1 — never average across lookaheads). Tie-break: when two lookaheads share identical ic_sharpe, prefer the shorter lookahead (ORDER BY ic_sharpe DESC, lookahead_bars ASC) — shorter lookahead converges faster and is less likely to be a noise artifact. Return one row per feature_name. Each returned row carries feature_name, ic_sharpe, ic_ci_lower, ic_ci_upper, ic_sign, lookahead_bars.

    covariance.py — function compute_shrinkage_covariance(X: np.ndarray) -> tuple[np.ndarray, float]: wrap sklearn.covariance.LedoitWolf (store_precision=False, assume_centered=False); X is shape [n_obs, n_features]; return (lw.covariance_, float(lw.shrinkage_)). Handle X with fewer than 2 rows or 0 features by returning (empty/identity covariance, 0.0) without raising.

    weights.py — two functions.
      derive_weights(ic_sharpes: np.ndarray, max_weight: float) -> np.ndarray: zero out non-finite and non-positive IC Sharpe; normalize to sum 1; apply per-feature cap with iterative proportional redistribution to uncapped features (max 100 iters, converge when excess < 1e-10); final renorm; return zeros if no positive feature. max_weight is passed in (caller loads alpha.ensemble.max_feature_weight from APR — no inline 0.20 in src/).
      effective_n(weights: np.ndarray) -> float: return 1.0 / float(np.sum(weights ** 2)) computed on the post-cap post-renorm vector; return 0.0 if sum of squares is 0.

    alpha_score.py — function compute_alpha_score(feature_values, weights, ic_signs, ic_ci_lower, ic_ci_upper) -> tuple[float, float, float]: alpha = sum(weights * ic_sign * safe_feature_values) where non-finite feature values are treated as 0; CI variance = dot(weights**2, ((ci_upper - ci_lower)/3.92)**2) with non-finite CI widths treated as 0; margin = 1.96 * sqrt(var); return (alpha, alpha - margin, alpha + margin). Per RESEARCH.md Pitfall 3, do NOT z-score the composite again — feature values are already z-scores.

    No hardcoded numeric thresholds in this module except the mathematical/statistical constants 1.96 and 3.92 (z-score for 95% CI and its 2x — APR-exempt mathematical constants) and convergence epsilon 1e-10.
  </action>
  <verify>
    .venv/bin/python -c "from src.intelligence.ensemble.weights import derive_weights, effective_n; import numpy as np; w = derive_weights(np.array([5.0,1.0,1.0,1.0,1.0,1.0]), 0.20); print(round(float(w.sum()),6), round(effective_n(w),3))" prints 1.0 and an effective_n value, and max(w) <= 0.20 + 1e-9.
    .venv/bin/python -c "from src.intelligence.ensemble.covariance import compute_shrinkage_covariance; import numpy as np; c,s = compute_shrinkage_covariance(np.random.randn(100,5)); print(c.shape, 0.0 <= s <= 1.0)" prints (5, 5) True.
    .venv/bin/ruff check src/intelligence/ensemble/ exits 0.
  </verify>
  <acceptance_criteria>
    - src/intelligence/ensemble/__init__.py, feature_selector.py, covariance.py, weights.py, alpha_score.py all exist
    - covariance.py contains `from sklearn.covariance import LedoitWolf`
    - derive_weights output sums to 1.0 (within 1e-6) and respects the cap: no element exceeds max_weight + 1e-9
    - effective_n is computed as 1.0/sum(w**2) on the passed weight vector
    - feature_selector.py tie-break: when ic_sharpe values are equal, the row with smaller lookahead_bars is selected (ORDER BY ic_sharpe DESC, lookahead_bars ASC)
    - No import of asyncpg, psycopg2, or kafka anywhere in src/intelligence/ensemble/ (grep returns nothing)
    - `.venv/bin/ruff check src/intelligence/ensemble/` exits 0
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 3: topic_alpha_events, OTel gauges, and unit tests</name>
  <read_first>
    - src/core/stream_keys.py lines 41-168 (env_prefix() and the topic_* function pattern; topic_feature_vectors at line 152 is the closest v3.0 analog)
    - src/observability/metrics.py lines 1-90 (the _meter, create_gauge, create_up_down_counter helper pattern) and lines 380-440 (Phase 138 IC gauges EFFECTIVE_N_GAUGE, IC_SCORE_GAUGE — replicate the create_gauge style)
    - .planning/phases/139-ensemble-alpha-emission/139-RESEARCH.md (Code Examples lines 419-439 for the exact gauge names) and architecture doc Observability Contract Ensemble/Alpha Emitter metric tables (lines 657-689)
  </read_first>
  <action>
    Add to src/core/stream_keys.py a function topic_alpha_events(env_name: str) -> str returning f"{env_prefix(env_name)}alpha.events" with a docstring noting it is the v3.0 AlphaEngine emission topic. Place it after topic_intelligence_i7_signals to keep v3.0 topics grouped.

    Add to src/observability/metrics.py (following the existing _meter.create_gauge / create_up_down_counter pattern, placed near the Phase 138 IC gauges):
    - ENSEMBLE_FEATURE_WEIGHT_GAUGE = create_gauge "ensemble_feature_weight" (labels feature, symbol, tf, weight_version per architecture doc)
    - ENSEMBLE_EFFECTIVE_N_GAUGE = create_gauge "ensemble_effective_n" (labels symbol, tf, weight_version)
    - ENSEMBLE_SHRINKAGE_INTENSITY_GAUGE = create_gauge "ensemble_shrinkage_intensity" (labels symbol, tf, weight_version)
    - ENSEMBLE_FEATURES_ZERO_WEIGHT_GAUGE = create_gauge "ensemble_features_zero_weight_total" (labels symbol, tf, weight_version)
    - ALPHA_EMITTER_EMISSIONS_TOTAL = create_up_down_counter "alpha_emitter_emissions_total" (labels symbol, tf, direction, regime)
    - ALPHA_EMITTER_BARS_SCORED_TOTAL = create_up_down_counter "alpha_emitter_bars_scored_total" (labels symbol, tf)
    - ALPHA_EMITTER_REJECTIONS_TOTAL = create_up_down_counter "alpha_emitter_rejections_total" (labels symbol, tf, rejection_reason)
    Use the existing module helpers (the wrappers around _meter.create_*) so descriptions are populated; do not call prometheus_client.

    Create tests/unit/test_ensemble_math.py covering: derive_weights returns zeros for all-negative IC Sharpe; derive_weights respects the cap when one feature dominates (assert max <= cap); derive_weights sums to 1.0; effective_n equals 1/sum(w^2) on a known vector (e.g. 5 equal weights of 0.2 -> effective_n 5.0); compute_alpha_score with NaN feature values treats them as 0; compute_alpha_score CI bounds bracket the point estimate; compute_alpha_score sign-flip — feature_values=[1.0], weights=[1.0], ic_signs=[-1], ci_lower=[0.0], ci_upper=[0.1] returns alpha_score < 0 (negative IC sign flips a positive feature into a negative contribution); compute_alpha_score sign-keep — same inputs with ic_signs=[+1] returns alpha_score > 0 (positive IC sign keeps the contribution positive); compute_shrinkage_covariance returns shape [n_features, n_features] and shrinkage in [0,1]; select_features_per_stratum keeps the max-ic_sharpe row per feature_name when duplicate lookaheads exist; select_features_per_stratum tie-break — when two rows for the same feature_name have equal ic_sharpe but different lookahead_bars, the row with smaller lookahead_bars is returned. Tests import from src.intelligence.ensemble only — no DB.
  </action>
  <verify>
    .venv/bin/python -c "from src.core.stream_keys import topic_alpha_events; print(topic_alpha_events('prod').endswith('alpha.events'))" prints True.
    .venv/bin/python -c "from src.observability.metrics import ENSEMBLE_EFFECTIVE_N_GAUGE, ALPHA_EMITTER_EMISSIONS_TOTAL; print('ok')" prints ok.
    .venv/bin/pytest tests/unit/test_ensemble_math.py -q exits 0.
  </verify>
  <acceptance_criteria>
    - `grep -n "def topic_alpha_events" src/core/stream_keys.py` returns a match
    - `from src.observability.metrics import ENSEMBLE_EFFECTIVE_N_GAUGE, ENSEMBLE_FEATURE_WEIGHT_GAUGE, ALPHA_EMITTER_EMISSIONS_TOTAL, ALPHA_EMITTER_REJECTIONS_TOTAL` imports without error
    - `grep -n "prometheus_client" src/observability/metrics.py` returns nothing (OTel only)
    - `.venv/bin/pytest tests/unit/test_ensemble_math.py -q` exits 0 with at least 11 test cases (10 original + tie-break test)
    - effective_n test asserts 5 equal 0.2 weights yield effective_n == 5.0 (within 1e-9)
    - compute_alpha_score test asserts ic_signs=[-1] on a positive feature yields alpha_score < 0, and ic_signs=[+1] yields alpha_score > 0
    - select_features_per_stratum tie-break test asserts that when two rows have equal ic_sharpe, the one with smaller lookahead_bars is selected
  </acceptance_criteria>
</task>

</tasks>

<verification>
- Migration 168 applied: three tables present, two hypertables, 9 APR keys in config_state
- alpha_events PRIMARY KEY is (event_id, bar_ts) — verified via \d alpha_events
- alpha.ensemble.min_passing_features = '5' in config_state
- src/intelligence/ensemble/ pure module imports with no DB/Kafka dependency
- topic_alpha_events() and 7 OTel instruments importable
- `.venv/bin/pytest tests/unit/test_ensemble_math.py -q` green
- `.venv/bin/ruff check src/intelligence/ensemble/ tests/unit/test_ensemble_math.py` exits 0
</verification>

<success_criteria>
- ensemble_weights, ensemble_alpha, alpha_events tables exist with the architecture-doc schema (success criteria 1, 2, 4 schema substrate)
- alpha_events PRIMARY KEY (event_id, bar_ts) compatible with TimescaleDB hypertable chunking
- 9 alpha.ensemble.* / alpha.quant.threshold.* APR keys seeded and loadable; min_passing_features = 5 (success criteria 3, 6)
- effective_N = 1/sum(w^2) and 0.20 weight cap implemented as pure tested functions (success criteria 1, 5)
- feature_selector tie-break deterministic: shorter lookahead wins on ic_sharpe tie
- topic_alpha_events() ready for P3 Kafka emission (success criterion 4)
</success_criteria>

<output>
After completion, create `.planning/phases/139-ensemble-alpha-emission/139-P1-SUMMARY.md`
</output>
