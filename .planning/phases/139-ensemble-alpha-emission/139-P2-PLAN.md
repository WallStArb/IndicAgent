---
phase: 139-ensemble-alpha-emission
plan: P2
type: execute
wave: 2
depends_on: [P1]
files_modified:
  - services/ensemble_builder.py
  - services/alpha_emitter.py
  - services/service_auditor.py
  - production/systemd/indicagent-ensemble-builder.service
  - production/systemd/indicagent-alpha-emitter.service
  - tests/unit/test_ensemble_builder.py
  - tests/unit/test_alpha_emitter.py
autonomous: true

must_haves:
  truths:
    - "EnsembleBuilder reads feature_ic_scores (is_pooled=false, passes_walkforward=true), derives IC-Sharpe weights, applies LW cluster deflation (cluster_deflate_weights), and writes ensemble_weights + ensemble_alpha"
    - "EnsembleBuilder scores ensemble_alpha via vectorized matmul (X @ signed_weights) with bulk executemany insert — no per-bar Python loop"
    - "EnsembleBuilder feature_vectors query includes WHERE regime_label = stratum_regime — no cross-regime score contamination"
    - "EnsembleBuilder skips strata where derive_weights() returns a zero-sum weight vector (all features have non-positive IC Sharpe)"
    - "AlphaEmitter reads ensemble_alpha above threshold, enforces effective_N >= gate, writes alpha_events, and publishes to Kafka topic alpha.events"
    - "AlphaEmitter emission gate is direction-aware: long signals require alpha_ci_lower > 0; short signals require alpha_ci_upper < 0"
    - "AlphaEmitter skips rows where effective_n == 0 (zero-weight stratum guard before CI math)"
    - "Both services extend BaseBatch and emit D-06 job_completed_total automatically"
    - "AlphaEmitter preloads all ensemble_weights at execute() start into weights_cache = {(symbol, tf, regime): [rows]} — zero per-emission queries for top_features"
    - "AlphaEmitter reads alpha.ensemble.top_features_count APR key and includes only the top-N features (by abs(weight)) in alpha_events.top_features"
    - "All numeric parameters (cap, gate, cluster thresholds, per-TF thresholds, weight_version, top_features_count) are loaded from APR, not hardcoded"
    - "Kafka publish uses await producer.publish(topic_alpha_events(settings.env_name), msg=...) — topic is the first positional argument, always awaited"
    - "EnsembleBuilder commits a new weight_version atomically (all weight rows for a version or none)"
    - "Both services are registered in service_auditor _DAG_ORDER and _ONESHOT_UNITS"
  artifacts:
    - path: "services/ensemble_builder.py"
      provides: "EnsembleBuilder(BaseBatch) oneshot"
      contains: "class EnsembleBuilder(BaseBatch)"
      min_lines: 120
    - path: "services/alpha_emitter.py"
      provides: "AlphaEmitter(BaseBatch) oneshot with Kafka emission"
      contains: "class AlphaEmitter(BaseBatch)"
      min_lines: 100
    - path: "production/systemd/indicagent-ensemble-builder.service"
      provides: "oneshot systemd unit"
      contains: "Type=oneshot"
    - path: "production/systemd/indicagent-alpha-emitter.service"
      provides: "oneshot systemd unit"
      contains: "Type=oneshot"
    - path: "tests/unit/test_alpha_emitter.py"
      provides: "Kafka publish await + effective_N gate + direction-aware gate coverage"
      min_lines: 50
  key_links:
    - from: "services/ensemble_builder.py"
      to: "src/intelligence/ensemble"
      via: "import pure math functions"
      pattern: "from src.intelligence.ensemble"
    - from: "services/alpha_emitter.py"
      to: "alpha.events Kafka topic"
      via: "topic_alpha_events + producer.publish(topic_alpha_events(...), msg=...)"
      pattern: "publish\\(topic_alpha_events"
    - from: "services/service_auditor.py"
      to: "ensemble-builder + alpha-emitter units"
      via: "_DAG_ORDER and _ONESHOT_UNITS registration"
      pattern: "indicagent-ensemble-builder"
---

<objective>
Build the two batch compute services: EnsembleBuilder (feature_ic_scores → ensemble_weights + ensemble_alpha) and AlphaEmitter (ensemble_alpha → alpha_events + Kafka). Both extend BaseBatch, load all parameters from APR, register in service_auditor, and ship with systemd units and unit tests.

Purpose: These services apply the P1 math against the corpus. SoC is strict — EnsembleBuilder writes DB only; AlphaEmitter reads DB and publishes to Kafka. This separation is a hard invariant from the architecture doc (compute ≠ transport).
Output: services/ensemble_builder.py, services/alpha_emitter.py, two systemd units, service_auditor registration, and two unit test files. This plan is code-only and does NOT require corpus data to be present — the actual corpus run is P3.
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
@.planning/phases/139-ensemble-alpha-emission/139-P1-PLAN.md
@src/core/agent/base_batch.py
@services/ic_engine.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: EnsembleBuilder service</name>
  <read_first>
    - src/core/agent/base_batch.py (full — the run()/execute(pool)/content_key() contract, job_name + compute_version class attrs, asyncpg pool passed to execute)
    - services/ic_engine.py lines 1-240 (startup crash-loud gates, _load_apr pattern via load_config_service_sync, OTel init, __main__ entrypoint, ON CONFLICT idempotency) — but use asyncpg throughout per RESEARCH.md Pitfall 6, not psycopg2
    - .planning/phases/139-ensemble-alpha-emission/139-RESEARCH.md (Pattern 4 feature selection SQL lines 200-218, Pattern 1 LedoitWolf + effective_N, Phase Structure P2 lines 569-578, Pitfall 6 asyncpg-not-psycopg2)
    - src/intelligence/ensemble/ (P1 pure functions: select_features_per_stratum, compute_shrinkage_covariance, derive_weights, effective_n, compute_alpha_score)
    - docs/plans/2026-06-20-alphaengine-architecture.md (Ensemble Builder atomic weight version commit, lines 808-827; Observability Contract Ensemble metrics lines 657-668)
  </read_first>
  <action>
    Create services/ensemble_builder.py with class EnsembleBuilder(BaseBatch): set job_name = "ensemble-builder" and compute_version = "1.0.0". Use asyncpg throughout (the pool from execute(pool)). JSONB columns return as dicts (no json.loads).

    Startup crash-loud gates in execute() (mirror ic_engine._assert_prerequisites): raise RuntimeError if feature_ic_scores has zero rows WHERE is_pooled = false AND passes_walkforward = true; raise RuntimeError if feature_vectors is empty (needed to score ensemble_alpha). These gates make a "successful" empty run impossible.

    APR loading (asyncpg only, per RESEARCH.md Pitfall 6 — no psycopg2, no _batch_utils): inside execute(pool), fetch the config rows directly via the asyncpg pool with `SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'alpha.%'`, then build a plain dict {config_key: config_value} from the returned rows. Wrap it in a small `cfg.get(key, default)` accessor (or use dict.get) and read every parameter through it: alpha.ensemble.max_feature_weight, alpha.ensemble.effective_n_gate, alpha.ensemble.weight_version, alpha.ensemble.lookahead_selection, alpha.ensemble.min_passing_features. config_value is text, so cast numeric values to float/int at read time. No inline numeric fallbacks beyond the documented APR defaults passed as the get() default.

    Core loop per (symbol, tf, regime):
    1. Query feature_ic_scores WHERE symbol=$1 AND tf=$2 AND regime=$3 AND is_pooled=false AND passes_walkforward=true AND reliable=true AND ic_sharpe IS NOT NULL.
    2. select_features_per_stratum() to pick best lookahead per feature_name. Skip stratum if count < min_passing_features.
    3. Bulk-load the feature value matrix X from feature_vectors for this stratum: SELECT <feature_cols> FROM feature_vectors WHERE symbol=$1 AND tf=$2 AND regime_label=$3 ORDER BY bar_ts. This gives [n_bars, n_features] for the scoring matmul AND feeds compute_shrinkage_covariance(). The WHERE regime_label=$3 filter ensures IC weights trained on one regime do not score bars from a different regime — omitting this filter is a hidden cross-regime bias (Finding 2 blocker).
    4. derive_weights(ic_sharpes, max_feature_weight) → raw_weights. Then compute_shrinkage_covariance(X) → (cov_matrix, shrinkage) to get the LW covariance; convert to correlation matrix (divide each element by sqrt of the product of corresponding diagonal variances). Apply cluster_deflate_weights(raw_weights, corr_matrix, max_cluster_corr, max_cluster_weight) → weights. effective_n(weights). Emit ENSEMBLE_SHRINKAGE_INTENSITY_GAUGE{symbol, tf, weight_version} with the shrinkage scalar. Zero-weight guard: if weights.sum() == 0 after deflation, log a warning with fields symbol, tf, regime, and reason="zero_weight_vector", then continue to the next stratum. Increment ENSEMBLE_FEATURES_ZERO_WEIGHT_GAUGE.
    5. Write ensemble_weights rows in a single transaction (atomic weight_version commit per architecture doc): one row per feature with weight_version from APR, raw_weight, weight (post-deflation), ic_sharpe, lookahead_bars, effective_n. Use ON CONFLICT (symbol, tf, regime, weight_version, feature_name) DO NOTHING for idempotency.
    6. Score ensemble_alpha via vectorized matmul (no per-bar Python loop — Finding 1 performance fix):
       - signed_weights = weights * ic_signs [n_features] — computed once per stratum.
       - alpha_scores = X @ signed_weights [n_bars] — single matmul replacing the per-bar loop.
       - ic_sigma = (ic_ci_upper - ic_ci_lower) / 3.92 per feature; margin = 1.96 * sqrt(dot(weights**2, ic_sigma**2)) — constant per stratum, computed once.
       - ci_lower_arr = alpha_scores - margin; ci_upper_arr = alpha_scores + margin.
       - Bulk-insert all n_bars rows into ensemble_alpha via conn.executemany(INSERT ... ON CONFLICT (symbol, tf, bar_ts, weight_version) DO NOTHING, rows). Set effective_n and n_features_active as constants for the stratum.

    Emit OTel gauges from P1: ENSEMBLE_FEATURE_WEIGHT_GAUGE per feature, ENSEMBLE_EFFECTIVE_N_GAUGE, ENSEMBLE_SHRINKAGE_INTENSITY_GAUGE, ENSEMBLE_FEATURES_ZERO_WEIGHT_GAUGE — labeled symbol, tf, weight_version. Call init_otel_providers("indicagent-ensemble-builder") at startup; BaseBatch.run() already calls flush_and_shutdown_metrics().

    Use observed_span equivalents for ensemble_builder.solve. Exception variable name is error. All timestamps datetime.now(UTC). __main__ block: build db_dsn from Settings (replace postgresql+asyncpg:// with postgresql://) and asyncio.run(EnsembleBuilder(db_dsn=db_dsn).run()).
  </action>
  <verify>
    .venv/bin/python -c "import ast,sys; ast.parse(open('services/ensemble_builder.py').read()); print('parse ok')" prints parse ok.
    grep -n "class EnsembleBuilder(BaseBatch)" services/ensemble_builder.py returns a match.
    grep -n "from src.intelligence.ensemble" services/ensemble_builder.py returns a match.
    grep -nE "0\.20|3\.0|= 1\.5|= 1\.2" services/ensemble_builder.py returns nothing outside APR-default fallbacks in cfg.get calls (no inline magic thresholds in compute logic).
    grep -n "zero_weight_vector" services/ensemble_builder.py returns a match (zero-weight guard present).
    .venv/bin/ruff check services/ensemble_builder.py exits 0.
  </verify>
  <acceptance_criteria>
    - services/ensemble_builder.py contains `class EnsembleBuilder(BaseBatch)` with `job_name = "ensemble-builder"`
    - Imports select_features_per_stratum, compute_shrinkage_covariance, derive_weights, cluster_deflate_weights, effective_n from src.intelligence.ensemble
    - feature_vectors SELECT includes `WHERE symbol=$1 AND tf=$2 AND regime_label=$3` — regime filter present (grep for regime_label in the query string)
    - Scoring uses matmul: `X @ signed_weights` replaces per-bar loop (grep for `@ signed_weights` or `matmul`)
    - Bulk insert uses `conn.executemany(` for ensemble_alpha rows (not a Python for-loop with individual INSERTs)
    - LW cluster deflation: `cluster_deflate_weights` is called after `derive_weights` and before writing ensemble_weights
    - Zero-weight guard: when weights.sum() == 0 after deflation, the stratum is skipped (log + continue) — no weights or alpha rows written
    - ensemble_weights INSERT is wrapped in `async with conn.transaction():` (atomic weight_version)
    - Both INSERTs use ON CONFLICT DO NOTHING (idempotent re-run)
    - Two startup RuntimeError gates exist (empty feature_ic_scores passing rows; empty feature_vectors)
    - max_feature_weight, effective_n_gate, weight_version, min_passing_features, max_cluster_corr, max_cluster_weight read from the asyncpg-loaded config dict via cfg.get with alpha.ensemble.* keys
    - `.venv/bin/ruff check services/ensemble_builder.py` exits 0
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 2: AlphaEmitter service</name>
  <read_first>
    - services/ensemble_builder.py (the asyncpg + BaseBatch + APR-load pattern just written in Task 1 — replicate the structure)
    - src/core/agent/base_batch.py lines 102-116 (content_key staticmethod for event_id)
    - .planning/phases/139-ensemble-alpha-emission/139-RESEARCH.md (Pattern 5 AlphaEmitter shadow-mode Kafka publishing lines 222-251, Pitfall 5 await publish, Phase Structure P3 emission gate logic lines 580-586, content-key formula line 250)
    - src/core/stream_keys.py (topic_alpha_events from P1)
    - src/core/kafka/producer.py (KafkaProducerClient — the publish(topic, msg, key) signature; topic is the first positional argument, not a kwarg)
    - docs/plans/2026-06-20-alphaengine-architecture.md (Alpha Emitter idempotency via PK lines 829-835, top_features NOT NULL data integrity invariant; Observability Contract Alpha Emitter metrics lines 679-689)
    - CLAUDE.md key rules: KafkaProducerClient.publish kwarg is msg=; await producer.publish; structlog event= collision; exception variable error; UTC timestamps
  </read_first>
  <action>
    Create services/alpha_emitter.py with class AlphaEmitter(BaseBatch): job_name = "alpha-emitter", compute_version = "1.0.0", ensemble_version = "v1.0.0" (class attr used in content_key and alpha_events.ensemble_version). asyncpg throughout.

    APR loading: alpha.ensemble.effective_n_gate, alpha.ensemble.weight_version, alpha.ensemble.top_features_count (default 10), alpha.quant.threshold.5m / .15m / .1h / .1d. Provide a helper _threshold_for_tf(tf) returning the matching APR threshold from the asyncpg-loaded config dict (no inline literals — fall through to the cfg.get default only).

    Startup crash-loud gate: raise RuntimeError if ensemble_alpha is empty (nothing to emit from). This prevents a silent "success" with zero events.

    Construct a KafkaProducerClient and the topic via topic_alpha_events(settings.env_name). Initialize the producer in execute() (await any start/connect per the existing producer contract; read src/core/kafka/producer.py for the exact lifecycle).

    Preload: before the emission loop, SELECT * FROM ensemble_weights WHERE weight_version = $weight_version and build weights_cache = {(symbol, tf, regime): [rows]} (one query, not one per emission). This eliminates the N+1 query pattern — 100K emitted events no longer each query the same weight rows (Finding 3). Weights are constant per stratum; the preload pays once.

    Emission loop: read ensemble_alpha rows for the current weight_version. For each row, first apply the zero-weight guard: if effective_n == 0, skip the row entirely before any CI math (log at debug level with reason="zero_weight_stratum"). Then apply the direction-aware emission gate:
    - Determine direction: 'long' if alpha_score > 0, 'short' if alpha_score < 0. Skip (don't emit) if alpha_score == 0.
    - Long gate: alpha_score > threshold[tf] AND alpha_ci_lower > 0 AND effective_n >= effective_n_gate.
    - Short gate: abs(alpha_score) > threshold[tf] AND alpha_ci_upper < 0 AND effective_n >= effective_n_gate.
    - Equivalently: ((alpha_score > 0 AND alpha_ci_lower > 0) OR (alpha_score < 0 AND alpha_ci_upper < 0)) AND abs(alpha_score) > threshold[tf] AND effective_n >= effective_n_gate.
    On reject, increment ALPHA_EMITTER_REJECTIONS_TOTAL with the appropriate rejection_reason: 'ci_not_directional' (for the CI direction check — ci_lower <= 0 on a long, or ci_upper >= 0 on a short), 'effective_n_low', 'threshold_miss', or 'zero_weight_stratum'. On pass:
    - event_id = BaseBatch.content_key(symbol, tf, str(int(bar_ts.timestamp()*1e9)), ensemble_version).
    - Build top_features dict from weights_cache[(symbol, tf, regime)] (no per-emission query — cache was preloaded): sort rows by abs(weight) descending, take top-N where N = top_features_count from APR, build {feature_name: weight} dict. This MUST be non-empty (top_features NOT NULL invariant from P1 architecture doc).
    - Write alpha_events row (ON CONFLICT (event_id, bar_ts) DO NOTHING) including ensemble_version, weight_version, regime, alpha_score, ci bounds, effective_n, n_features_active, emission_threshold, direction, top_features jsonb. Pass the dict directly to asyncpg (no json.dumps).
    - Publish JSON payload to Kafka: await self._producer.publish(topic_alpha_events(settings.env_name), msg=payload) — topic_alpha_events(settings.env_name) is the first positional argument, msg= is the keyword argument. payload matches the RESEARCH.md alpha_event schema (event_id, symbol, tf, bar_ts ISO via format_iso_ts, ensemble_version, weight_version, alpha_score, ci bounds, effective_n, regime, n_features_active, top_features, emitted_at).
    - Increment ALPHA_EMITTER_EMISSIONS_TOTAL{symbol,tf,direction,regime} and ALPHA_EMITTER_BARS_SCORED_TOTAL.

    Shadow mode: emission writes alpha_events + publishes to Kafka only — no execution, no trade. Document this in the module docstring.

    init_otel_providers("indicagent-alpha-emitter") at startup. Exception variable error. UTC timestamps via format_iso_ts. __main__ entrypoint mirrors EnsembleBuilder.
  </action>
  <verify>
    .venv/bin/python -c "import ast; ast.parse(open('services/alpha_emitter.py').read()); print('parse ok')" prints parse ok.
    grep -n "class AlphaEmitter(BaseBatch)" services/alpha_emitter.py returns a match.
    grep -nE "publish\(topic_alpha_events" services/alpha_emitter.py returns a match (correct call with topic as first arg).
    grep -n "publish(msg=" services/alpha_emitter.py returns nothing (old bare-kwarg form absent).
    grep -n "value=" services/alpha_emitter.py returns nothing (wrong kwarg absent).
    grep -n "await self._producer.publish" services/alpha_emitter.py returns a match (awaited).
    grep -n "alpha_ci_upper" services/alpha_emitter.py returns a match (short-direction CI check present).
    grep -n "zero_weight_stratum" services/alpha_emitter.py returns a match (zero effective_n guard present).
    .venv/bin/ruff check services/alpha_emitter.py exits 0.
  </verify>
  <acceptance_criteria>
    - services/alpha_emitter.py contains `class AlphaEmitter(BaseBatch)` with `job_name = "alpha-emitter"`
    - weights_cache is preloaded before the emission loop via a single SELECT ... FROM ensemble_weights WHERE weight_version = $version (grep for `weights_cache` dict initialization before the per-row loop)
    - No ensemble_weights query inside the per-row emission loop (grep for `FROM ensemble_weights` inside the loop body returns nothing)
    - top_features built from weights_cache[(symbol, tf, regime)] sliced to top top_features_count rows by abs(weight)
    - top_features_count read from alpha.ensemble.top_features_count APR key (grep for `top_features_count` in APR load block)
    - Emission gate is direction-aware: long path checks alpha_ci_lower > 0; short path checks alpha_ci_upper < 0
    - Zero-weight guard: rows where effective_n == 0 are skipped before CI math (log + continue, rejection_reason='zero_weight_stratum')
    - Kafka publish uses `await self._producer.publish(topic_alpha_events(settings.env_name), msg=...)` — topic_alpha_events(settings.env_name) is the first positional argument
    - grep for bare `publish(msg=` (without topic arg) returns nothing
    - grep for `value=` returns nothing (wrong kwarg absent)
    - top_features is populated (non-empty dict) before alpha_events insert — never NULL
    - alpha_events insert uses ON CONFLICT (event_id, bar_ts) DO NOTHING (matching the composite PK from P1)
    - event_id from BaseBatch.content_key is still used as the unique identifier in the payload
    - Per-TF thresholds read from alpha.quant.threshold.{tf} APR keys, not literals
    - `.venv/bin/ruff check services/alpha_emitter.py` exits 0
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 3: systemd units, service_auditor registration, unit tests</name>
  <read_first>
    - production/systemd/indicagent-feature-validation.service and production/systemd/indicagent-hmm-training.service (oneshot unit template: Type=oneshot, ExecStart=.venv/bin/python services/..., User, WorkingDirectory, Environment, no Restart for oneshots)
    - services/service_auditor.py lines 104-199 (_DAG_ORDER Phase 138 oneshot block at 106-109, _ONESHOT_UNITS frozenset at 174-199 — add the two new units adjacent to the IC pipeline oneshots)
    - .planning/phases/139-ensemble-alpha-emission/139-P1-PLAN.md and the two service files from Tasks 1-2 (for the job_name → unit name mapping: ensemble-builder, alpha-emitter)
  </read_first>
  <action>
    Create production/systemd/indicagent-ensemble-builder.service and production/systemd/indicagent-alpha-emitter.service following the feature-validation.service oneshot template: Type=oneshot, WorkingDirectory=/home/bg/dev/indicagent, ExecStart=/home/bg/dev/indicagent/.venv/bin/python /home/bg/dev/indicagent/services/ensemble_builder.py (resp. alpha_emitter.py), appropriate User and Environment (match the env-prefix and INDICAGENT_ENV pattern used by the IC pipeline units). No Restart= directive (oneshot). Add a [Install] WantedBy=multi-user.target.

    Register both in services/service_auditor.py:
    - _DAG_ORDER: add "indicagent-ensemble-builder": 8 and "indicagent-alpha-emitter": 8 next to the Phase 138 IC pipeline oneshots block (lines 106-109), with the same inline comment style ("oneshot; ... -> table").
    - _ONESHOT_UNITS frozenset: add "indicagent-ensemble-builder" and "indicagent-alpha-emitter" with the Phase-138-style comment "Type=oneshot; inactive between IC pipeline runs is correct".

    Create tests/unit/test_ensemble_builder.py: unit-test the pure data-shaping logic that lives in the service module if any (e.g., stratum grouping, threshold lookup), and assert the service class exposes job_name == "ensemble-builder" and is a BaseBatch subclass. Mock asyncpg pool; do not require a live DB.

    Create tests/unit/test_alpha_emitter.py: assert AlphaEmitter.job_name == "alpha-emitter"; test _threshold_for_tf returns the correct APR-loaded value per TF; test the emission gate predicate covering all rejection paths and both directions:
    - A row with effective_n below gate is rejected with reason 'effective_n_low'.
    - A row with effective_n == 0 is rejected with reason 'zero_weight_stratum' (before CI math).
    - A long row (alpha_score > 0) with alpha_ci_lower <= 0 is rejected with reason 'ci_not_directional'.
    - A short row (alpha_score < 0) with alpha_ci_upper >= 0 is rejected with reason 'ci_not_directional'.
    - abs(alpha_score) below threshold is rejected with reason 'threshold_miss'.
    - A passing long row: alpha_score=2.0, alpha_ci_lower=0.5, alpha_ci_upper=3.5, threshold=1.0, effective_n=4.0 → produces direction='long' and emits.
    - A passing short row: alpha_score=-2.0, alpha_ci_upper=-0.5, alpha_ci_lower=-3.5, threshold=1.0, effective_n=4.0 → produces direction='short' and emits.
    - weights_cache preload test: after execute() is called, the mock conn.fetch for ensemble_weights is called exactly once regardless of how many ensemble_alpha rows are processed (assert call_count == 1 for the ensemble_weights fetch).
    - top_features_count test: when top_features_count=3 and weights_cache has 10 features, top_features dict in the emitted payload contains exactly 3 keys (the top-3 by abs(weight)).
    Mock the KafkaProducerClient and assert publish is awaited with the topic as first positional arg and msg= kwarg, using AsyncMock and mock_producer.publish.assert_awaited_once_with(topic_alpha_events(...), msg=...) — catches both the unawaited-coroutine and wrong-kwarg and missing-topic-arg traps from RESEARCH.md Pitfall 5.
  </action>
  <verify>
    grep -n "indicagent-ensemble-builder" services/service_auditor.py returns matches in both _DAG_ORDER and _ONESHOT_UNITS.
    grep -n "indicagent-alpha-emitter" services/service_auditor.py returns matches in both.
    test -f production/systemd/indicagent-ensemble-builder.service && test -f production/systemd/indicagent-alpha-emitter.service && echo units-exist prints units-exist.
    .venv/bin/pytest tests/unit/test_ensemble_builder.py tests/unit/test_alpha_emitter.py -q exits 0.
    .venv/bin/pytest tests/unit/service_tests/test_service_auditor.py -q exits 0 (DAG registration did not break existing auditor tests).
  </verify>
  <acceptance_criteria>
    - Both systemd unit files exist and contain `Type=oneshot`
    - `grep -c "indicagent-ensemble-builder" services/service_auditor.py` >= 2 (DAG_ORDER + ONESHOT_UNITS)
    - `grep -c "indicagent-alpha-emitter" services/service_auditor.py` >= 2
    - test_alpha_emitter.py covers all rejection reasons: ci_not_directional, effective_n_low, threshold_miss, zero_weight_stratum
    - test_alpha_emitter.py covers passing long (alpha_score=2.0, ci_lower=0.5 → direction='long') and passing short (alpha_score=-2.0, ci_upper=-0.5 → direction='short')
    - test_alpha_emitter.py asserts `mock_producer.publish` was called with topic_alpha_events(...) as first arg and msg= kwarg (AsyncMock assert_awaited_once_with)
    - test_alpha_emitter.py asserts ensemble_weights fetch is called exactly once per execute() run (weights_cache preload — no N+1)
    - test_alpha_emitter.py asserts top_features has exactly top_features_count keys when weights_cache has more than top_features_count features
    - `.venv/bin/pytest tests/unit/test_ensemble_builder.py tests/unit/test_alpha_emitter.py -q` exits 0
    - Existing service_auditor unit tests still pass
  </acceptance_criteria>
</task>

</tasks>

<verification>
- EnsembleBuilder and AlphaEmitter both subclass BaseBatch and parse/lint clean
- EnsembleBuilder feature_vectors query includes WHERE regime_label = stratum_regime (no cross-regime scoring)
- EnsembleBuilder scores via vectorized matmul (X @ signed_weights) + conn.executemany bulk insert — no per-bar Python loop
- EnsembleBuilder applies LW cluster deflation (cluster_deflate_weights) after derive_weights
- EnsembleBuilder skips zero-weight strata (zero-sum weights after deflation) with log and continue
- AlphaEmitter preloads weights_cache with one query before emission loop (weights_cache preload test passes)
- AlphaEmitter top_features sliced to top_features_count by abs(weight)
- All numeric parameters loaded via the asyncpg-loaded APR config dict (cfg.get) — no inline magic thresholds
- Kafka publish awaited with topic as first positional arg and msg= kwarg (verified by test)
- Emission gate is direction-aware: short signals check alpha_ci_upper < 0 (not alpha_ci_lower > 0)
- Both units registered in service_auditor _DAG_ORDER and _ONESHOT_UNITS
- `.venv/bin/pytest tests/unit/test_ensemble_builder.py tests/unit/test_alpha_emitter.py tests/unit/service_tests/test_service_auditor.py -q` green
- `.venv/bin/ruff check services/ensemble_builder.py services/alpha_emitter.py` exits 0
</verification>

<success_criteria>
- EnsembleBuilder writes ensemble_weights (IC-Sharpe + 0.20 cap + LW cluster deflation) + ensemble_alpha (vectorized composite scores, CI bounds) — success criteria 1, 2
- EnsembleBuilder skips strata with zero-sum weight vectors (log + continue, no silent empty writes)
- AlphaEmitter enforces direction-aware CI gate (ci_lower > 0 for longs; ci_upper < 0 for shorts) and effective_N >= gate before emission, then publishes to alpha.events Kafka topic in shadow mode — success criteria 4, 5
- Emission threshold read from alpha.quant.threshold.{tf} APR — success criterion 3
- All alpha.ensemble.* APR keys loaded via asyncpg-loaded config dict — success criterion 6
</success_criteria>

<output>
After completion, create `.planning/phases/139-ensemble-alpha-emission/139-P2-SUMMARY.md`
</output>
