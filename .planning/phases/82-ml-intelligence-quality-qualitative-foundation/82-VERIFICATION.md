---
phase: 82-ml-intelligence-quality-qualitative-foundation
verified: 2026-05-13T20:30:00Z
status: passed
score: 27/27 must-haves verified
re_verification: false
---

# Phase 82: ML Intelligence Quality & Qualitative Foundation — Verification Report

**Phase Goal:** Build the ML intelligence quality and qualitative data foundation — HMM multi-TF instances with entropy/velocity fields, offline HMM training pipeline, regime soft gate, feature validation service (IC/p-value), and CTX qualitative data schema infrastructure.
**Verified:** 2026-05-13T20:30:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|---------|
| 1  | DATA-02 gate decision made from data, not default | VERIFIED | 82-01-SUMMARY.md documents DerivOsc PROMOTED (r=+0.011, p=0.013), ACOsc DEMOTED (r=-0.011) from 382K+ and 1.9M+ rows |
| 2  | Four named HMM instances (1m/5m/15m/1h) in TIER_SMC with correct lookbacks | VERIFIED | `register_plugins.py` lines 144-150; TIER_SMC includes all four; lookbacks 200/200/150/100 confirmed |
| 3  | `hmm_regime_entropy` and `hmm_regime_velocity` emitted per bar by every HMM instance | VERIFIED | `hmm_regime.py` lines 338-366; both in `outputs` frozenset (line 138-139) |
| 4  | `SMCContext` extended with entropy and velocity fields | VERIFIED | `schemas.py` lines 654-655 |
| 5  | `VELOCITY_WINDOW_BY_TF` module constant maps TFs to ints | VERIFIED | `hmm_regime.py` lines 47-56 (`{1m:5, 5m:5, 15m:4, 1h:3}`) |
| 6  | `reload_parameters()` public method exists on HMMRegimePlugin | VERIFIED | `hmm_regime.py` line 153 |
| 7  | Per-TF parameter file path logic (`config/hmm_parameters_{tf}.json`) in plugin | VERIFIED | `hmm_regime.py` `_load_tf_parameters()` uses TF-suffixed path, falls back to base |
| 8  | `intelligence_pipeline_agent` hot-reloads HMM parameters on SIGUSR1 | VERIFIED | `intelligence_pipeline_agent.py` line 627 `add_signal_handler(_signal.SIGUSR1, ...)`; `_on_hmm_sigusr1` at line 716 |
| 9  | HMM training agent excludes `is_backfill=TRUE` rows from training data | VERIFIED | `hmm_training_compute_agent.py` line 183 `is_backfill IS NOT TRUE` |
| 10 | Four per-TF parameter files written atomically via `.tmp` + `os.rename` | VERIFIED | `hmm_training_compute_agent.py` lines 346-350 |
| 11 | JSON parameter keys match `_load_parameters()` contract | VERIFIED | Keys `transition_matrix`, `emission_means`, `emission_variances` at lines 302-304 |
| 12 | Training pipeline emits SIGUSR1 to `indicagent-intelligence-pipeline.service` | VERIFIED | `hmm_training_compute_agent.py` line 380 literal `SIGUSR1` + `_PIPELINE_UNIT` constant |
| 13 | Monthly systemd oneshot timer for HMM training | VERIFIED | `indicagent-hmm-training.timer` line 5 `OnCalendar=monthly`; `.service` line 6 `Type=oneshot` |
| 14 | Three-band soft regime gate: suppress / soft-attenuate / full | VERIFIED | `regime_gate.py` has `SOFT_BAND_FLOOR=0.5`, `_entropy_multiplier()`, three-band `apply_regime_gate()` |
| 15 | `REGIME_PROB_SOFT_MAX` configurable via Settings with default 0.55 | VERIFIED | `settings.py` line 180 `default=0.55` |
| 16 | Soft-band Prometheus counter `REGIME_SOFT_GATE_SIGNALS_TOTAL{band}` | VERIFIED | `metrics.py` line 316; wired into `regime_gate.py` line 13 import |
| 17 | `intelligence_pipeline_agent` passes `prob_soft_max` to gate | VERIFIED | `intelligence_pipeline_agent.py` lines 469 + 1398 |
| 18 | Migration 086 idempotent: `validation_results` hypertable + `shadow_registry.promotion_evidence` | VERIFIED | `086_validation_results.sql` has `IF NOT EXISTS` on table, hypertable call, index, and `ADD COLUMN IF NOT EXISTS` |
| 19 | `FeatureValidationComputeAgent` writes VALIDATED/TWEAK/KILL rows to `validation_results` | VERIFIED | `feature_validation_compute_agent.py` line 310 `INSERT INTO validation_results`; delegates to `validate_backtest_results()` |
| 20 | `shadow_registry.promotion_evidence` updated as JSONB dict (never `json.dumps`) | VERIFIED | `feature_validation_compute_agent.py` line 331 `promotion_evidence`; dict passed directly per CLAUDE.md rule |
| 21 | `GET /api/validation/results` endpoint registered in FastAPI app | VERIFIED | `main.py` line 140 `app.include_router(validation.router, prefix="/api/validation")`; parameterized SQL |
| 22 | `FEATURE_VALIDATION_DECISIONS_TOTAL{decision}` counter increments per write | VERIFIED | `metrics.py` line 326; wired in `feature_validation_compute_agent.py` |
| 23 | Daily systemd oneshot for feature validation at 07:00 UTC (02:00 ET) | VERIFIED | `indicagent-feature-validation.timer` line 9 `OnCalendar=*-*-* 07:00:00 UTC` |
| 24 | Migration 085 idempotent: `ctx_events`, `ctx_snapshots`, `intelligence_features.ctx` | VERIFIED | `085_ctx_schema.sql` all 6 DDL guards confirmed |
| 25 | `topic_ctx_snapshot()` in `stream_keys.py` with dots-only naming | VERIFIED | `stream_keys.py` line 398; returns `f"{env_prefix(env_name)}ctx.snapshot"` |
| 26 | `CtxWriterAgent` enforces allowlist, payload cap, required-key validation; persists to both tables | VERIFIED | `ctx_writer_agent.py` lines 32-33 constants; dual-buffer architecture; UPSERT + close-prior SQL |
| 27 | `feature_writer_agent` includes `ctx` column via as-of join against `ctx_snapshots` | VERIFIED | `feature_writer_agent.py` lines 72 + 85-90; correlated subquery with parameter binding |

**Score:** 27/27 truths verified

---

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `src/intelligence/features/smc_context/hmm_regime.py` | VERIFIED | Multi-TF parameterized, entropy/velocity outputs, reload hook |
| `src/intelligence/register_plugins.py` | VERIFIED | Four HMM instances in TIER_SMC with correct lookbacks |
| `src/intelligence/schemas.py` | VERIFIED | `SMCContext` has `hmm_regime_entropy` and `hmm_regime_velocity` |
| `tests/unit/test_hmm_regime_multitf.py` | VERIFIED | 10 tests collected and passing |
| `src/intelligence/services/hmm_training_compute_agent.py` | VERIFIED | `HMMTrainingComputeAgent` with `run()`, `emit_sigusr1()`, `start()` |
| `services/hmm_training_agent.py` | VERIFIED | Oneshot entrypoint, `asyncio.run(agent.start())` |
| `production/systemd/indicagent-hmm-training.service` | VERIFIED | `Type=oneshot` |
| `production/systemd/indicagent-hmm-training.timer` | VERIFIED | `OnCalendar=monthly` |
| `tests/unit/test_hmm_training_compute_agent.py` | VERIFIED | 6 tests passing |
| `requirements.txt` | VERIFIED | `hmmlearn>=0.3.0` at line 28 |
| `src/intelligence/pipeline/regime_gate.py` | VERIFIED | `SOFT_BAND_FLOOR`, `_entropy_multiplier`, three-band gate, counter wiring |
| `src/config/settings.py` | VERIFIED | `REGIME_PROB_SOFT_MAX: float = Field(default=0.55)` |
| `src/observability/metrics.py` | VERIFIED | `REGIME_SOFT_GATE_SIGNALS_TOTAL` + `FEATURE_VALIDATION_DECISIONS_TOTAL` |
| `tests/unit/test_regime_gate_soft.py` | VERIFIED | 9 tests passing |
| `production/migrations/086_validation_results.sql` | VERIFIED | Hypertable, index, `promotion_evidence` column, idempotent |
| `src/intelligence/services/feature_validation_compute_agent.py` | VERIFIED | IC/p-value agent, JSONB dict compliance |
| `services/feature_validation_agent.py` | VERIFIED | Oneshot entrypoint |
| `production/systemd/indicagent-feature-validation.service` | VERIFIED | `Type=oneshot` |
| `production/systemd/indicagent-feature-validation.timer` | VERIFIED | Daily 07:00 UTC |
| `src/api/routes/validation.py` | VERIFIED | Read-only FastAPI router, parameterized SQL |
| `tests/unit/test_feature_validation_compute_agent.py` | VERIFIED | 6 tests passing |
| `production/migrations/085_ctx_schema.sql` | VERIFIED | `ctx_events` hypertable + `ctx_snapshots` + `intelligence_features.ctx` |
| `src/core/stream_keys.py` | VERIFIED | `topic_ctx_snapshot()` with dots-only naming |
| `services/ctx_writer_agent.py` | VERIFIED | `CtxWriterAgent`, allowlist, payload cap, dual-buffer, asyncpg dict |
| `services/service_auditor_agent.py` | VERIFIED | `indicagent-ctx-writer` in all three structures at L6 |
| `production/systemd/indicagent-ctx-writer.service` | VERIFIED | `Type=simple`, `ExecStart` referencing `services.ctx_writer_agent` |
| `tests/unit/test_ctx_writer_agent.py` | VERIFIED | 12 tests passing |
| `tests/unit/test_stream_keys_ctx.py` | VERIFIED | 3 tests passing |

---

### Key Link Verification

| From | To | Via | Status | Evidence |
|------|----|-----|--------|---------|
| `register_plugins.py` | `hmm_regime.py` | `HMMRegimePlugin(timeframe=..., lookback=...)` | WIRED | Lines 144-147 use `HMMRegimePlugin(timeframe=...)` constructor |
| `intelligence_pipeline_agent.py` | `hmm_regime.py` | SIGUSR1 `reload_parameters()` | WIRED | Lines 627 + 716-735; iterates TIER_SMC, filters HMMRegimePlugin, calls reload |
| `hmm_training_compute_agent.py` | `config/hmm_parameters_{tf}.json` | `json.dump` + atomic rename | WIRED | Line 345-350; `transition_matrix/emission_means/emission_variances` keys |
| `hmm_training_compute_agent.py` | `indicagent-intelligence-pipeline.service` | `systemctl kill --signal=SIGUSR1` | WIRED | Line 380; `_PIPELINE_UNIT` constant |
| `regime_gate.py` | `settings.py` | `REGIME_PROB_SOFT_MAX` | WIRED | `intelligence_pipeline_agent.py` line 469 caches from settings, passes at line 1398 |
| `regime_gate.py` | `metrics.py` | `REGIME_SOFT_GATE_SIGNALS_TOTAL` counter | WIRED | Import at line 13; `.labels(band=...).inc()` in all three gate paths |
| `feature_validation_compute_agent.py` | `validation_results` table | asyncpg INSERT | WIRED | Line 310 `INSERT INTO validation_results` with `$1...$N` binding |
| `feature_validation_compute_agent.py` | `shadow_registry.promotion_evidence` | asyncpg UPDATE JSONB | WIRED | Line 331 `promotion_evidence = $2` with dict passed directly |
| `ctx_writer_agent.py` | `topic_ctx_snapshot` | consumer subscription | WIRED | Line 23 import; line 101 `topic_ctx_snapshot(self.settings.env_name)` |
| `feature_writer_agent.py` | `ctx_snapshots` | as-of LEFT JOIN correlated subquery | WIRED | Lines 72 + 85-90; no f-string interpolation |

---

### Requirements Coverage

| Requirement ID | Global REQUIREMENTS.md ID | Status | Notes |
|----------------|--------------------------|--------|-------|
| P82-DATA02 | DATA-02 | SATISFIED | Gate executed via direct asyncpg (script has `bar->>'close'` bug documented); decision data-driven and recorded. Bug in `validate_alpha.py` documented but not fixed (out of plan scope). DATA-02 checkbox remains open — the script bug prevents using `--promote` flag but the gate _decision_ was correctly made. |
| P82-HMM-MULTITF | Phase-internal | SATISFIED | Four HMM instances registered; entropy/velocity outputs; SIGUSR1 reload wired |
| P82-REGIME-TRANSITION | Phase-internal | SATISFIED | Three-band gate live; Settings + Prometheus surface complete |
| P82-FEATURE-VALIDATION | Phase-internal | SATISFIED | Migration 086 + compute agent + API + daily timer |
| P82-CTX-SCHEMA | Phase-internal | SATISFIED | Migration 085 + stream key + writer + feature_writer as-of join + DAG |

**Note on DATA-02 in global REQUIREMENTS.md:** The requirement reads "validate_alpha.py --promote re-run once N >= 30." The gate was executed but the `--promote` script invocation could not be completed because `validate_alpha.py` has a confirmed bug (`bar->>'close'` vs `bar->>'c'`). The gate *decision* was correctly made using direct SQL. The DATA-02 checkbox is left open; a separate fix to `validate_alpha.py` is needed before it can be marked complete.

---

### Anti-Patterns Found

None blocking. No TODO/FIXME/placeholder patterns found in any of the delivered files. All implementations are substantive.

---

### Test Results (46 unit tests)

All 46 unit tests across 6 test files pass in 1.09 seconds:

- `test_hmm_regime_multitf.py`: 10/10 (including 4 parametrized TF cases)
- `test_hmm_training_compute_agent.py`: 6/6
- `test_regime_gate_soft.py`: 9/9
- `test_feature_validation_compute_agent.py`: 6/6
- `test_ctx_writer_agent.py`: 12/12 (including parametrized key rejection)
- `test_stream_keys_ctx.py`: 3/3

---

### Human Verification Required

None — all automated checks pass. The following items are noted as requiring operational steps but are not blocking verification:

1. **Systemd timer installation**: The HMM training and feature validation timers exist as reference files but require `sudo systemctl enable` to activate. This is intentional (deployment step, not a code gap).
2. **Migration execution**: Migrations 085 and 086 are ready but have not been applied. Operational deployment runs them.
3. **First training run**: `config/hmm_parameters_{tf}.json` files will not exist until the first `indicagent-hmm-training.service` run completes. The `HMMRegimePlugin` uses built-in defaults until then (graceful fallback confirmed in code).

---

## Gaps Summary

No gaps. All 27 observable truths verified. All 28 artifacts exist, are substantive, and are wired correctly. All 46 unit tests pass.

The one known issue — `validate_alpha.py` `bar->>'close'` bug — was present before Phase 82, was correctly documented in 82-01-SUMMARY.md as out-of-plan-scope, and does not block any Phase 82 goal. The DATA-02 gate *decision* was still made from data.

---

_Verified: 2026-05-13T20:30:00Z_
_Verifier: Claude (gsd-verifier)_
