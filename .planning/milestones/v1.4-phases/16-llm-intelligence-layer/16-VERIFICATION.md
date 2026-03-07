---
phase: 16-llm-intelligence-layer
verified: 2026-03-06T06:00:00Z
status: passed
score: 11/11 must-haves verified
re_verification:
  previous_status: gaps_found
  previous_score: 9/11
  gaps_closed:
    - "Migration 019 creates llm_calls as a TimescaleDB hypertable partitioned by called_at"
    - "At startup and every 5 minutes, ai_narrative_service reads Redis llm_scores:{call_type}:{regime} and promotes any is_significant=True winner to providers[0]"
  gaps_remaining: []
  regressions: []
---

# Phase 16: LLM Intelligence Layer Verification Report

**Phase Goal:** Every LLM call is captured, outcome-linked, and used to adaptively route model selection — no model decision is made without data

**Verified:** 2026-03-06T06:00:00Z
**Status:** passed
**Re-verification:** Yes — after gap closure plans 16-06 (hypertable fix) and 16-07 (per-regime routing)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Migration 019 creates llm_calls as a TimescaleDB hypertable partitioned by called_at | VERIFIED | `timescaledb_information.hypertables` returns `llm_calls | 1` in production. Migration 020 applied composite PK (call_id, called_at) and called create_hypertable with migrate_data. `information_schema.key_column_usage` confirms both columns in the PK. |
| 2 | Migration 019 creates llm_model_scores with PK (model, regime, setup_type, call_type) | VERIFIED | Table exists. PK confirmed in migration SQL line 103. |
| 3 | stream_keys.py exports llm_calls_stream(), llm_outcomes_stream(), llm_scores_cache() | VERIFIED | All three confirmed at lines 68, 73, 78 of src/core/stream_keys.py. |
| 4 | llm_writer_service.py exists, batch-INSERTs to llm_calls, UPDATEs outcomes by signal_id | VERIFIED | 819 lines. `execute_batch(_INSERT_LLM_CALL_SQL)` at line 455, `execute_batch(_UPDATE_OUTCOME_SQL)` at line 563. |
| 5 | LLMWriterService recomputes llm_model_scores every 15 min from outcome rows | VERIFIED | `_score_recompute_loop` uses `SCORE_RECOMPUTE_INTERVAL_SECS=900.0`. `execute_batch(_UPSERT_SCORE_SQL)` at line 622. |
| 6 | Redis score cache updated after every score recompute | VERIFIED | `hset(cache_key, model, score_blob)` at line 642, key via `llm_scores_cache(self._env_prefix, call_type, regime)`. |
| 7 | All 3 call paths in ai_narrative_service emit to llm_calls:stream via asyncio.create_task | VERIFIED | `create_task(xadd(llm_calls_stream(...)))` at lines 525 (counterfactual), 556 (per_signal), 805 (group_synthesis). |
| 8 | signal_lifecycle_service emits to llm_outcomes:stream on both exit paths | VERIFIED | `create_task(xadd(sk_llm_outcomes_stream(...)))` at lines 306-307 (shadow path) and 417-418 (normal active→exit path). |
| 9 | ai_narrative_service reads score cache at startup and every 5 min; promotes is_significant winner per call_type+regime | VERIFIED | `_apply_score_routing` at line 716 now populates `_preferred_models[call_type][regime]` independently for each (call_type, regime) pair. Regime-aware promotion injected at `per_signal_chain.generate()` call site (lines 539-545) using `signal_data["regime_context"]`. Group synthesis uses `__all__` entry (line 800). Startup call at line 894, 5-min loop at line 709. |
| 10 | indicagent-llm-writer systemd service is enabled and running | VERIFIED | `systemctl is-active indicagent-llm-writer` returns "active". Both unit files exist with correct ExecStart. |
| 11 | Prometheus metrics endpoint :9117 returns llm_writer_* metric names | VERIFIED | Returns `llm_writer_calls_consumed_total`, `llm_writer_outcomes_processed_total`, `llm_writer_batch_writes_total`, `llm_writer_service_uptime_seconds`. |

**Score:** 11/11 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `production/migrations/019_llm_intelligence_layer.sql` | llm_calls hypertable + llm_model_scores + 3 indexes | VERIFIED | 131 lines. Composite PK (call_id, called_at). `SELECT create_hypertable('llm_calls', 'called_at')` — no silent if_not_exists. 3 indexes present. |
| `production/migrations/020_llm_calls_hypertable_fix.sql` | Gap closure: idempotent DO-block, composite PK, create_hypertable with migrate_data | VERIFIED | 51 lines. DO-block guards on timescaledb_information.hypertables. DROP CONSTRAINT + ADD PRIMARY KEY (call_id, called_at) + PERFORM create_hypertable with migrate_data => TRUE. |
| `tests/unit/test_migration_020.py` | 7 structural tests for migration SQL | VERIFIED | All 7 tests pass: test_drop_constraint_present, test_composite_pk_present, test_create_hypertable_no_if_not_exists, test_migrate_data_flag, test_idempotency_guard, test_019_pk_corrected, test_019_no_silent_if_not_exists |
| `src/core/stream_keys.py` | 3 new helper functions | VERIFIED | llm_calls_stream (L68), llm_outcomes_stream (L73), llm_scores_cache (L78) |
| `tests/unit/service_tests/test_llm_writer_service.py` | 12 tests all PASS | VERIFIED | 12 tests GREEN |
| `services/llm_writer_service.py` | 250+ lines, exports 3 pure functions + LLMWriterService | VERIFIED | 819 lines. All key functions present. |
| `services/ai_narrative_service.py` | Per-regime routing in _apply_score_routing; _preferred_models attribute | VERIFIED | `_preferred_models: dict[str, dict[str, str]] = {}` at line 309. `_apply_score_routing` at line 716 builds per-(call_type, regime) dict. Regime-aware promotion at lines 539-545. Group synthesis uses `__all__` at line 800. |
| `services/signal_lifecycle_service.py` | Both exit paths emit to llm_outcomes:stream | VERIFIED | _build_outcome_payload at L71, two create_task xadd calls at L306 and L417. |
| `production/systemd/indicagent-llm-writer.service` | Systemd unit pointing to llm_writer_service.py | VERIFIED | ExecStart correct, SyslogIdentifier=indicagent-llm-writer. |
| `services/indicagent-llm-writer.service` | Convenience copy alongside other service files | VERIFIED | Identical content to production/systemd copy. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `production/migrations/020_llm_calls_hypertable_fix.sql` | llm_calls (TimescaleDB) | composite PK (call_id, called_at) then create_hypertable on called_at | VERIFIED | Production DB: `timescaledb_information.hypertables` returns `llm_calls | 1`. PK columns confirmed: call_id + called_at. |
| `src/core/stream_keys.py` | `services/llm_writer_service.py` | import llm_calls_stream, llm_outcomes_stream, llm_scores_cache | VERIFIED | L35 in llm_writer_service.py imports all three. |
| `services/llm_writer_service.py` | llm_calls (TimescaleDB) | execute_batch(_INSERT_LLM_CALL_SQL) | VERIFIED | L455: `await self.db_manager.execute_batch(_INSERT_LLM_CALL_SQL, params)` |
| `services/llm_writer_service.py` | llm_calls (outcome back-fill) | execute_batch(_UPDATE_OUTCOME_SQL) WHERE signal_id | VERIFIED | L563: `await self.db_manager.execute_batch(_UPDATE_OUTCOME_SQL, [params])` |
| `services/llm_writer_service.py` | Redis llm_scores:{call_type}:{regime} | redis_client.hset(llm_scores_cache(...)) | VERIFIED | L641-642: cache_key via llm_scores_cache(), then `await self.redis_client.hset(cache_key, model, score_blob)` |
| `services/ai_narrative_service.py` | {env_prefix}llm_calls:stream | asyncio.create_task(redis_client.xadd(llm_calls_stream(...))) | VERIFIED | 3 fire-and-forget xadd calls at lines 525, 556, 805 |
| `services/ai_narrative_service.py` | `_preferred_models[call_type][regime]` | hgetall Redis score cache, select max avg_pnl_r where is_significant per (call_type, regime) | VERIFIED | `_apply_score_routing` at L716 iterates all (call_type, regime) pairs independently, stores winner per-regime. `_preferred_models` populated at line 759. |
| `services/ai_narrative_service.py _process_single_message` | `per_signal_chain` | `_promote_model_in_chain` using regime from signal_data | VERIFIED | Lines 539-545: regime_key from `signal_data["regime_context"]`, looks up `_preferred_models["per_signal"][regime_key]`, falls back to `__all__`, calls `_promote_model_in_chain` before `chain.generate()`. |
| `services/signal_lifecycle_service.py` | {env_prefix}llm_outcomes:stream | asyncio.create_task(redis_client.xadd(llm_outcomes_stream(...))) | VERIFIED | Two create_task xadd calls at L306 and L417. |
| `production/systemd/indicagent-llm-writer.service` | `services/llm_writer_service.py` | ExecStart path | VERIFIED | ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/llm_writer_service.py |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| LLM-01 | 16-01, 16-05, 16-06 | llm_calls hypertable + llm_model_scores created by migration 019; gap closure in 020 | SATISFIED | llm_calls confirmed hypertable in production (timescaledb_information.hypertables returns one row). Composite PK (call_id, called_at). Migration 019 source corrected. |
| LLM-02 | 16-03 | ai_narrative_service emits full payload to llm_calls:stream after every LLM call | SATISFIED | 3 fire-and-forget xadd calls wired; payload builder produces flat dict[str,str] with all required fields. |
| LLM-03 | 16-04 | signal_lifecycle_service emits to llm_outcomes:stream when any signal exits | SATISFIED | Both exit paths (shadow + normal) emit via asyncio.create_task. |
| LLM-04 | 16-02, 16-05 | llm_writer_service batch INSERTs, back-fills outcomes, recomputes scores, writes Redis cache | SATISFIED | execute_batch for INSERT and UPDATE confirmed; _score_recompute_loop at 900s cadence; Redis hset confirmed; systemd service active. |
| LLM-05 | 16-03, 16-07 | ai_narrative_service reads Redis score cache at startup and every 5 min; promotes is_significant winner per call_type+regime | SATISFIED | `_apply_score_routing` now builds `_preferred_models[call_type][regime]` per-regime independently. Regime-aware promotion injected at per_signal chain call site. 4 new unit tests GREEN (29 total in test_ai_narrative_service.py). |

No orphaned requirements — all 5 LLM requirement IDs accounted for across plans.

### Anti-Patterns Found

None. No stub implementations, placeholder returns, TODO comments, or silent error suppression in any of the key service files. Migration 020 explicitly surfaces errors by omitting if_not_exists from create_hypertable.

### Human Verification Required

None — all items verifiable programmatically.

### Re-verification Summary

**Gap 1 — CLOSED: llm_calls is now a TimescaleDB hypertable**

Migration 020 (`production/migrations/020_llm_calls_hypertable_fix.sql`) was applied to production. The DO-block dropped the single-column UUID PK constraint, added composite PK (call_id, called_at), and called create_hypertable with migrate_data => TRUE. Production DB confirms: `timescaledb_information.hypertables` returns one row for llm_calls with num_dimensions=1. PK columns confirmed as call_id + called_at. Migration 019 source was also corrected so future deployments (CI, staging, new environments) get the correct schema from the start without silent no-op. 7 structural unit tests verify migration SQL properties without requiring a DB connection.

**Gap 2 — CLOSED: Per-regime adaptive routing now selects winner per (call_type, regime) pair**

`_apply_score_routing` in `services/ai_narrative_service.py` was rewritten (plan 16-07). It now builds `_preferred_models: dict[str, dict[str, str]]` — keyed `[call_type][regime]` — by iterating all four regimes (trending, ranging, volatile, __all__) independently for each call_type. A trending-regime winner cannot override routing for ranging calls. The per-signal call site (lines 539-545) reads `signal_data["regime_context"]` and promotes the regime-specific model before `chain.generate()`; falls back to `__all__` entry if no regime-specific winner. Group synthesis (line 800) uses the `__all__` entry since cross-symbol synthesis has no single regime. All 29 ai_narrative_service unit tests pass, including 4 new per-regime tests.

**Regressions:** None. Full unit suite: 1172 tests passing. Ruff: 0 errors.

---

_Verified: 2026-03-06T06:00:00Z_
_Verifier: Claude (gsd-verifier)_
