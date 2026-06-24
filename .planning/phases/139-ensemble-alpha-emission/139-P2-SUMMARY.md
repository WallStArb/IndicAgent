---
phase: 139-ensemble-alpha-emission
plan: P2
subsystem: ml, ensemble, kafka, observability
tags: [asyncpg, basebatch, ledoit-wolf, matmul, kafka, otel, apr, systemd]

requires:
  - phase: 139-ensemble-alpha-emission
    plan: P1
    provides: ensemble_weights + ensemble_alpha + alpha_events tables; src/intelligence/ensemble/ pure functions; topic_alpha_events(); 7 OTel instruments; 13 APR keys

provides:
  - services/ensemble_builder.py: EnsembleBuilder(BaseBatch) oneshot
  - services/alpha_emitter.py: AlphaEmitter(BaseBatch) oneshot with Kafka emission
  - production/systemd/indicagent-ensemble-builder.service: Type=oneshot systemd unit
  - production/systemd/indicagent-alpha-emitter.service: Type=oneshot systemd unit
  - service_auditor _DAG_ORDER + _ONESHOT_UNITS registration for both units
  - 40 unit tests covering class contracts, gate logic, Kafka kwarg correctness

affects:
  - 139-P3 (corpus run: runs ensemble_builder.py + alpha_emitter.py end-to-end)

tech-stack:
  added: []
  patterns:
    - "asyncpg APR loading: SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'alpha.%' — no psycopg2, no _batch_utils (Pitfall 6)"
    - "Vectorized matmul scoring: alpha_scores = X @ signed_weights — no per-bar Python loop (Finding 1)"
    - "weights_cache preload: single SELECT ensemble_weights before emit loop eliminates N+1 queries (Finding 3)"
    - "Direction-aware CI gate: long requires alpha_ci_lower > 0; short requires alpha_ci_upper < 0 (Finding 2 blocker)"
    - "Zero-weight guard: if weights.sum() < 1e-10 after cluster deflation, log + continue (no silent writes)"

key-files:
  created:
    - services/ensemble_builder.py
    - services/alpha_emitter.py
    - production/systemd/indicagent-ensemble-builder.service
    - production/systemd/indicagent-alpha-emitter.service
    - tests/unit/test_ensemble_builder.py
    - tests/unit/test_alpha_emitter.py
  modified:
    - services/service_auditor.py

key-decisions:
  - "asyncpg APR loading (not _batch_utils): BaseBatch.execute() receives an asyncpg pool, so APR is fetched inline via async conn.fetch — no psycopg2 connection needed and no mismatch between pool type and query driver"
  - "self._producer instance attr on AlphaEmitter: KafkaProducerClient assigned to self._producer in execute() so tests can assert on mock_producer.publish calls through the emitter"
  - "Analytic CI margin computed once per stratum: margin = 1.96 * sqrt(dot(weights**2, ic_sigma**2)) is constant per stratum and applied to all n_bars — avoids recomputing per bar"
  - "regime column on ensemble_alpha: the ensemble_alpha table must have a regime column for AlphaEmitter to read regime from rows (used for weights_cache lookup and alpha_events.regime field)"

patterns-established:
  - "BaseBatch asyncpg pattern: async with pool.acquire() as conn: -> await conn.fetch(APR_QUERY) -> cfg dict -> compute"
  - "Gate rejection counters: ALPHA_EMITTER_REJECTIONS_TOTAL with rejection_reason label covers all 4 paths"

requirements-completed: []

duration: 12min
completed: 2026-06-24
---

# Phase 139 Plan 2: EnsembleBuilder + AlphaEmitter Services Summary

**EnsembleBuilder and AlphaEmitter batch services with LW cluster deflation, vectorized matmul alpha scoring, direction-aware CI gate, weights_cache preload, Kafka shadow emission, and 40 unit tests verifying all gate paths and publish kwarg correctness**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-24T05:45:00Z
- **Completed:** 2026-06-24T05:57:00Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments

- `EnsembleBuilder(BaseBatch)` oneshot that reads `feature_ic_scores` (is_pooled=false, passes_walkforward=true), loads APR via asyncpg, applies LW shrinkage covariance + cluster deflation, scores all feature_vectors bars via vectorized matmul (`X @ signed_weights`), and bulk-inserts into ensemble_weights (atomic transaction) + ensemble_alpha (executemany) — no per-bar Python loop anywhere in the scoring path
- `AlphaEmitter(BaseBatch)` oneshot that preloads weights_cache in one query before the emit loop, applies direction-aware CI gate (long: `alpha_ci_lower > 0`; short: `alpha_ci_upper < 0`), enforces `effective_n >= gate`, skips zero-weight strata before CI math, writes alpha_events with composite PK (event_id, bar_ts), and publishes to Kafka with `await self._producer.publish(topic, msg=payload)`
- Two oneshot systemd units (Type=oneshot, no Restart=) installed at the correct path pattern
- Both units registered in service_auditor `_DAG_ORDER` (priority 8) and `_ONESHOT_UNITS` with Phase 138-style comments
- 40 unit tests: class contracts, cfg helpers, all 4 rejection reasons (zero_weight_stratum, effective_n_low, ci_not_directional, threshold_miss), passing long + short, Kafka publish topic-as-first-arg + msg= kwarg, weights_cache fetched exactly once, top_features_count slicing

## Task Commits

1. **Task 1: EnsembleBuilder service** - `e2df8b42` (feat)
2. **Task 2: AlphaEmitter service** - `12f69810` (feat)
3. **Task 3: systemd units, service_auditor, unit tests** - `ac4c6e19` (feat)

## Files Created/Modified

- `/services/ensemble_builder.py` — 496 lines: EnsembleBuilder(BaseBatch), async APR loading, 2 startup gates, stratum loop with LW covariance, cluster deflation, zero-weight guard, vectorized matmul, bulk executemany inserts, 5 OTel gauges
- `/services/alpha_emitter.py` — 390 lines: AlphaEmitter(BaseBatch), async APR loading, startup gate, weights_cache preload, direction-aware gate, 4 rejection reasons, alpha_events insert, Kafka publish, 3 OTel counters
- `/production/systemd/indicagent-ensemble-builder.service` — Type=oneshot, TimeoutStartSec=7200
- `/production/systemd/indicagent-alpha-emitter.service` — Type=oneshot, TimeoutStartSec=3600
- `/tests/unit/test_ensemble_builder.py` — 17 tests: class contract, BaseBatch subclass, import coverage, cfg helpers
- `/tests/unit/test_alpha_emitter.py` — 23 tests: all gate paths, Kafka kwarg, weights_cache preload, top_features_count
- `/services/service_auditor.py` — added ensemble-builder + alpha-emitter to `_DAG_ORDER` and `_ONESHOT_UNITS`

## Decisions Made

- **asyncpg APR loading, not _batch_utils**: `_batch_utils.load_config_service_sync()` wraps psycopg2. BaseBatch gives an asyncpg pool — using psycopg2 would open a second connection. Fetched APR inline via `await conn.fetch("SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'alpha.%'")` and built a plain dict.
- **self._producer instance attr**: KafkaProducerClient assigned to `self._producer` inside `execute()` so mock tests can intercept via `patch("services.alpha_emitter.KafkaProducerClient", return_value=mock_producer)` and assert on `mock_producer.publish`.
- **Analytic CI margin once per stratum**: `margin = 1.96 * sqrt(dot(weights**2, (ci_upper-ci_lower/3.92)**2))` is constant for a stratum — computed once and broadcast across all n_bars as `ci_lower_arr = alpha_scores - margin`. Matches the architecture doc formula.
- **regime column requirement on ensemble_alpha**: The plan schema from P1 includes a `regime` column on ensemble_alpha (set to the stratum regime when scoring). AlphaEmitter reads it for the weights_cache lookup key `(symbol, tf, regime)`. If the column is absent, the service will fail at execute() — this is intentional crash-loud behavior.

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as written.

### Notes

- Pre-commit hook could not find ruff/black in the worktree because hooks resolve `$REPO_ROOT/.venv/bin/ruff` to the worktree path. Fixed identically to P1: `ln -s /home/bg/dev/indicagent/.venv .claude/worktrees/agent-a37c65cb0c1e48cb5/.venv`. This is a worktree execution artifact, not a code decision.
- `ensemble_alpha` table must have a `regime` column for AlphaEmitter's weights_cache lookup. If P1 migration 168 did not include this column, P3 corpus run will fail at the `SELECT ... regime FROM ensemble_alpha` query — this will surface as a clear error, not a silent wrong answer.

## Next Phase Readiness

- P3 (corpus run): `services/ensemble_builder.py` and `services/alpha_emitter.py` are ready to run. Prerequisite: full corpus feature_vectors data from Phase 138 P8 full run + regime_writer + forward_return_writer + ic_engine runs across all 58 ETFs.
- The two systemd units can be installed with `sudo cp production/systemd/indicagent-{ensemble-builder,alpha-emitter}.service /etc/systemd/system/ && sudo systemctl daemon-reload`

---
*Phase: 139-ensemble-alpha-emission*
*Completed: 2026-06-24*

## Self-Check

**Files exist:**
- [x] services/ensemble_builder.py
- [x] services/alpha_emitter.py
- [x] production/systemd/indicagent-ensemble-builder.service
- [x] production/systemd/indicagent-alpha-emitter.service
- [x] tests/unit/test_ensemble_builder.py
- [x] tests/unit/test_alpha_emitter.py

**Commits exist:**
- [x] e2df8b42 - Task 1 (EnsembleBuilder)
- [x] 12f69810 - Task 2 (AlphaEmitter)
- [x] ac4c6e19 - Task 3 (systemd units, service_auditor, tests)

**Verification:**
- [x] EnsembleBuilder(BaseBatch), AlphaEmitter(BaseBatch) — both subclass confirmed
- [x] regime_label in feature_vectors WHERE clause — no cross-regime scoring
- [x] X @ signed_weights matmul — no per-bar Python loop
- [x] cluster_deflate_weights called after derive_weights
- [x] zero-weight guard: weights.sum() < 1e-10 -> log + continue
- [x] weights_cache preloaded once before emit loop
- [x] direction-aware gate: alpha_ci_lower > 0 for long; alpha_ci_upper < 0 for short
- [x] await self._producer.publish(topic, msg=payload) — topic positional, msg= kwarg
- [x] ON CONFLICT DO NOTHING on both tables (idempotent)
- [x] Both units in _DAG_ORDER and _ONESHOT_UNITS (count >= 2 each)
- [x] 65/65 tests passing (40 new + 25 existing service_auditor)
- [x] ruff check: all passed

## Self-Check: PASSED
