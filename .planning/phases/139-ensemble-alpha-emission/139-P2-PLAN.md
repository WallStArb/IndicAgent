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
    - "EnsembleBuilder reads feature_ic_scores (is_pooled=false, passes_walkforward=true), derives Ledoit-Wolf weights, and writes ensemble_weights + ensemble_alpha"
    - "AlphaEmitter reads ensemble_alpha above threshold, enforces effective_N >= gate, writes alpha_events, and publishes to Kafka topic alpha.events"
    - "Both services extend BaseBatch and emit D-06 job_completed_total automatically"
    - "All numeric parameters (cap, gate, per-TF thresholds, weight_version) are loaded from APR via ConfigService, not hardcoded"
    - "Kafka publish uses await producer.publish(msg=...) — never value=, always awaited"
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
      provides: "Kafka publish await + effective_N gate coverage"
      min_lines: 40
  key_links:
    - from: "services/ensemble_builder.py"
      to: "src/intelligence/ensemble"
      via: "import pure math functions"
      pattern: "from src.intelligence.ensemble"
    - from: "services/alpha_emitter.py"
      to: "alpha.events Kafka topic"
      via: "topic_alpha_events + producer.publish(msg=...)"
      pattern: "publish\\(msg="
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
    3. Load the feature value matrix X from feature_vectors for that (symbol, tf, regime) over the selected feature columns; pass to compute_shrinkage_covariance() (records shrinkage for the OTel gauge). Note: shrinkage informs diagnostics; weights are derived from IC Sharpe per Pattern 2.
    4. derive_weights(ic_sharpes, max_feature_weight) → weights; effective_n(weights).
    5. Write ensemble_weights rows in a single transaction (atomic weight_version commit per architecture doc): one row per feature with weight_version from APR, raw_weight, weight, ic_sharpe, lookahead_bars, effective_n. Use ON CONFLICT (symbol, tf, regime, weight_version, feature_name) DO NOTHING for idempotency.
    6. Score ensemble_alpha for every feature_vectors bar in that stratum: for each bar, compute_alpha_score(feature_values, weights, ic_signs, ic_ci_lower, ic_ci_upper) → (alpha_score, ci_lower, ci_upper); write ensemble_alpha rows with effective_n and n_features_active. ON CONFLICT (symbol, tf, bar_ts, weight_version) DO NOTHING.

    Emit OTel gauges from P1: ENSEMBLE_FEATURE_WEIGHT_GAUGE per feature, ENSEMBLE_EFFECTIVE_N_GAUGE, ENSEMBLE_SHRINKAGE_INTENSITY_GAUGE, ENSEMBLE_FEATURES_ZERO_WEIGHT_GAUGE — labeled symbol, tf, weight_version. Call init_otel_providers("indicagent-ensemble-builder") at startup; BaseBatch.run() already calls flush_and_shutdown_metrics().

    Use observed_span equivalents for ensemble_builder.solve. Exception variable name is error. All timestamps datetime.now(UTC). __main__ block: build db_dsn from Settings (replace postgresql+asyncpg:// with postgresql://) and asyncio.run(EnsembleBuilder(db_dsn=db_dsn).run()).
  </action>
  <verify>
    .venv/bin/python -c "import ast,sys; ast.parse(open('services/ensemble_builder.py').read()); print('parse ok')" prints parse ok.
    grep -n "class EnsembleBuilder(BaseBatch)" services/ensemble_builder.py returns a match.
    grep -n "from src.intelligence.ensemble" services/ensemble_builder.py returns a match.
    grep -nE "0\.20|3\.0|= 1\.5|= 1\.2" services/ensemble_builder.py returns nothing outside APR-default fallbacks in cfg.get calls (no inline magic thresholds in compute logic).
    .venv/bin/ruff check services/ensemble_builder.py exits 0.
  </verify>
  <acceptance_criteria>
    - services/ensemble_builder.py contains `class EnsembleBuilder(BaseBatch)` with `job_name = "ensemble-builder"`
    - Imports select_features_per_stratum, compute_shrinkage_covariance, derive_weights, effective_n, compute_alpha_score from src.intelligence.ensemble
    - ensemble_weights INSERT is wrapped in `async with conn.transaction():` (atomic weight_version)
    - Both INSERTs use ON CONFLICT DO NOTHING (idempotent re-run)
    - Two startup RuntimeError gates exist (empty feature_ic_scores passing rows; empty feature_vectors)
    - max_feature_weight, effective_n_gate, weight_version, min_passing_features read from the asyncpg-loaded config dict (SELECT ... FROM config_state WHERE config_key LIKE 'alpha.%') via cfg.get with the alpha.ensemble.* keys
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
    - docs/plans/2026-06-20-alphaengine-architecture.md (Alpha Emitter idempotency via PK lines 829-835, top_features NOT NULL data integrity invariant; Observability Contract Alpha Emitter metrics lines 679-689)
    - CLAUDE.md key rules: KafkaProducerClient.publish kwarg is msg=; await producer.publish; structlog event= collision; exception variable error; UTC timestamps
  </read_first>
  <action>
    Create services/alpha_emitter.py with class AlphaEmitter(BaseBatch): job_name = "alpha-emitter", compute_version = "1.0.0", ensemble_version = "v1.0.0" (class attr used in content_key and alpha_events.ensemble_version). asyncpg throughout.

    APR loading: alpha.ensemble.effective_n_gate, alpha.ensemble.weight_version, alpha.quant.threshold.5m / .15m / .1h / .1d. Provide a helper _threshold_for_tf(tf) returning the matching APR threshold from the asyncpg-loaded config dict (no inline literals — fall through to the cfg.get default only).

    Startup crash-loud gate: raise RuntimeError if ensemble_alpha is empty (nothing to emit from). This prevents a silent "success" with zero events.

    Construct a KafkaProducerClient and the topic via topic_alpha_events(settings.env_name). Initialize the producer in execute() (await any start/connect per the existing producer contract; read src/core/kafka/producer.py for the exact lifecycle).

    Emission loop: read ensemble_alpha rows for the current weight_version. For each row apply the emission gate: abs(alpha_score) > threshold[tf] AND alpha_ci_lower > 0 AND effective_n >= effective_n_gate. On reject, increment ALPHA_EMITTER_REJECTIONS_TOTAL with rejection_reason in {ci_lower_negative, effective_n_low, threshold_miss}. On pass:
    - direction = 'long' if alpha_score > 0 else 'short'.
    - event_id = BaseBatch.content_key(symbol, tf, str(int(bar_ts.timestamp()*1e9)), ensemble_version).
    - Build top_features dict (top contributing features and their weight*value — query ensemble_weights for that stratum/weight_version; this MUST be non-empty per the NOT NULL invariant).
    - Write alpha_events row (event_id PK, ON CONFLICT DO NOTHING) including ensemble_version, weight_version, regime, alpha_score, ci bounds, effective_n, n_features_active, emission_threshold, direction, top_features jsonb. Pass the dict directly to asyncpg (no json.dumps).
    - Publish JSON payload to Kafka: await self._producer.publish(msg=payload) — payload matches the RESEARCH.md alpha_event schema (event_id, symbol, tf, bar_ts ISO via format_iso_ts, ensemble_version, weight_version, alpha_score, ci bounds, effective_n, regime, n_features_active, top_features, emitted_at).
    - Increment ALPHA_EMITTER_EMISSIONS_TOTAL{symbol,tf,direction,regime} and ALPHA_EMITTER_BARS_SCORED_TOTAL.

    Shadow mode: emission writes alpha_events + publishes to Kafka only — no execution, no trade. Document this in the module docstring.

    init_otel_providers("indicagent-alpha-emitter") at startup. Exception variable error. UTC timestamps via format_iso_ts. __main__ entrypoint mirrors EnsembleBuilder.
  </action>
  <verify>
    .venv/bin/python -c "import ast; ast.parse(open('services/alpha_emitter.py').read()); print('parse ok')" prints parse ok.
    grep -n "class AlphaEmitter(BaseBatch)" services/alpha_emitter.py returns a match.
    grep -nE "publish\(msg=" services/alpha_emitter.py returns a match (correct kwarg).
    grep -n "value=" services/alpha_emitter.py returns nothing (wrong kwarg absent).
    grep -n "await self._producer.publish" services/alpha_emitter.py returns a match (awaited).
    .venv/bin/ruff check services/alpha_emitter.py exits 0.
  </verify>
  <acceptance_criteria>
    - services/alpha_emitter.py contains `class AlphaEmitter(BaseBatch)` with `job_name = "alpha-emitter"`
    - Emission gate enforces all three conditions: abs(alpha_score) > threshold, alpha_ci_lower > 0, effective_n >= effective_n_gate
    - Kafka publish uses `await self._producer.publish(msg=...)` and grep for `value=` returns nothing
    - top_features is populated (non-empty dict) before alpha_events insert — never NULL
    - alpha_events insert uses event_id from BaseBatch.content_key and ON CONFLICT DO NOTHING
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

    Create tests/unit/test_alpha_emitter.py: assert AlphaEmitter.job_name == "alpha-emitter"; test _threshold_for_tf returns the correct APR-loaded value per TF; test the emission gate predicate (a row with effective_n below gate is rejected with reason effective_n_low; a row with alpha_ci_lower <= 0 rejected ci_lower_negative; abs(alpha_score) below threshold rejected threshold_miss; a passing row produces direction long/short correctly). Mock the KafkaProducerClient and assert publish is awaited with msg= kwarg using mock_producer.publish.assert_awaited_once_with style (catches the unawaited-coroutine and wrong-kwarg traps from RESEARCH.md Pitfall 5). Use AsyncMock for the producer.
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
    - test_alpha_emitter.py asserts `mock_producer.publish.assert_awaited` with msg= kwarg
    - test_alpha_emitter.py covers all three rejection reasons (ci_lower_negative, effective_n_low, threshold_miss)
    - `.venv/bin/pytest tests/unit/test_ensemble_builder.py tests/unit/test_alpha_emitter.py -q` exits 0
    - Existing service_auditor unit tests still pass
  </acceptance_criteria>
</task>

</tasks>

<verification>
- EnsembleBuilder and AlphaEmitter both subclass BaseBatch and parse/lint clean
- All numeric parameters loaded via the asyncpg-loaded APR config dict (cfg.get) — no inline magic thresholds in compute logic
- Kafka publish awaited with msg= kwarg (verified by test)
- Both units registered in service_auditor _DAG_ORDER and _ONESHOT_UNITS
- `.venv/bin/pytest tests/unit/test_ensemble_builder.py tests/unit/test_alpha_emitter.py tests/unit/service_tests/test_service_auditor.py -q` green
- `.venv/bin/ruff check services/ensemble_builder.py services/alpha_emitter.py` exits 0
</verification>

<success_criteria>
- EnsembleBuilder writes ensemble_weights (Ledoit-Wolf, 0.20 cap) + ensemble_alpha (z-scored composite, CI bounds) — success criteria 1, 2
- AlphaEmitter enforces effective_N >= gate before emission and publishes to alpha.events Kafka topic in shadow mode — success criteria 4, 5
- Emission threshold read from alpha.quant.threshold.{tf} APR — success criterion 3
- All alpha.ensemble.* APR keys loaded via ConfigService.get — success criterion 6
</success_criteria>

<output>
After completion, create `.planning/phases/139-ensemble-alpha-emission/139-P2-SUMMARY.md`
</output>
