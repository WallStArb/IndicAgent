---
phase: 16-llm-intelligence-layer
verified: 2026-03-06T00:00:00Z
status: gaps_found
score: 9/11 must-haves verified
gaps:
  - truth: "Migration 019 creates llm_calls as a TimescaleDB hypertable partitioned by called_at"
    status: failed
    reason: "llm_calls is a plain PostgreSQL table, NOT a TimescaleDB hypertable. The create_hypertable call in 019_llm_intelligence_layer.sql uses if_not_exists => TRUE which silently suppresses the actual error: 'cannot create a unique index without the column called_at (used in partitioning)' — the UUID primary key (call_id only) conflicts with TimescaleDB's requirement that the partition column be part of the PK. SELECT from timescaledb_information.hypertables returns 0 rows for llm_calls; intelligence_features, signal_ledger, market_data_ohlcv, technical_indicators are the only hypertables."
    artifacts:
      - path: "production/migrations/019_llm_intelligence_layer.sql"
        issue: "call_id UUID PRIMARY KEY conflicts with hypertable partition on called_at. Fix: change PK to PRIMARY KEY (call_id, called_at) or drop UUID PK and use a UNIQUE constraint on call_id instead."
    missing:
      - "Either alter llm_calls PK to include called_at (e.g. ALTER TABLE llm_calls DROP CONSTRAINT llm_calls_pkey; ALTER TABLE llm_calls ADD PRIMARY KEY (call_id, called_at);) then call create_hypertable, or redefine the migration schema so call_id is UNIQUE (not PRIMARY KEY) allowing called_at to serve as the hypertable partition column."
  - truth: "At startup and every 5 minutes, ai_narrative_service reads Redis llm_scores:{call_type}:{regime} and promotes any is_significant=True winner to providers[0]"
    status: partial
    reason: "_apply_score_routing selects the global best model by max avg_pnl_r across all regimes rather than per-regime promotion. The plan (LLM-05) states routing should be 'for that call_type + regime combination' but implementation promotes a single winner globally. This is a documented design decision in 16-03-SUMMARY.md ('per-regime adaptive routing deferred'). The startup call and 5-min loop are correctly wired. Functionally the routing fires but does not perform per-regime selection as the requirement specifies."
    artifacts:
      - path: "services/ai_narrative_service.py"
        issue: "_apply_score_routing at line 704 finds best_model by iterating all regimes and picking max avg_pnl_r globally, then promotes that single model for both per_signal and group_synthesis chains. LLM-05 states 'for that call_type + regime combination' implying per-regime promotion."
    missing:
      - "Per-regime routing: for each (call_type, regime) pair, find the best is_significant model in that regime specifically and promote it — not a global cross-regime winner. This is a partial implementation; the wiring is correct but the selection logic is coarser than the requirement specifies."
---

# Phase 16: LLM Intelligence Layer Verification Report

**Phase Goal:** Every LLM call is captured, outcome-linked, and used to adaptively route model selection — no model decision is made without data

**Verified:** 2026-03-06T00:00:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Migration 019 creates llm_calls as a TimescaleDB hypertable partitioned by called_at | FAILED | llm_calls is a plain Postgres table. `timescaledb_information.hypertables` returns 0 rows for llm_calls. `create_hypertable` failed silently due to UUID-only PK conflicting with hypertable partition requirement. |
| 2 | Migration 019 creates llm_model_scores with PK (model, regime, setup_type, call_type) | VERIFIED | Table exists in production: `SELECT table_name FROM information_schema.tables WHERE table_name IN ('llm_calls','llm_model_scores')` returns both rows. PK confirmed in migration SQL line 102. |
| 3 | stream_keys.py exports llm_calls_stream(), llm_outcomes_stream(), llm_scores_cache() | VERIFIED | All three confirmed at lines 68, 73, 78 of src/core/stream_keys.py. |
| 4 | llm_writer_service.py exists, batch-INSERTs to llm_calls, UPDATEs outcomes by signal_id | VERIFIED | 819 lines. `execute_batch(_INSERT_LLM_CALL_SQL)` at line 455, `execute_batch(_UPDATE_OUTCOME_SQL)` at line 563. CONSUMER_GROUP="llm_writer" at line 43. |
| 5 | LLMWriterService recomputes llm_model_scores every 15 min from outcome rows | VERIFIED | `_score_recompute_loop` uses `SCORE_RECOMPUTE_INTERVAL_SECS=900.0`. `execute_batch(_UPSERT_SCORE_SQL)` at line 622. |
| 6 | Redis score cache updated after every score recompute | VERIFIED | `hset(cache_key, model, score_blob)` at line 642, key constructed via `llm_scores_cache(self._env_prefix, call_type, regime)`. |
| 7 | All 3 call paths in ai_narrative_service emit to llm_calls:stream via asyncio.create_task | VERIFIED | `create_task(xadd(llm_calls_stream(...)))` at lines 525 (counterfactual), 556 (per_signal), 805 (group_synthesis). |
| 8 | signal_lifecycle_service emits to llm_outcomes:stream on both exit paths | VERIFIED | `create_task(xadd(sk_llm_outcomes_stream(...)))` at lines 306-307 (shadow/regime_suppressed path) and 417-418 (normal active→exit path). Emit fires BEFORE update_signal_status() and BEFORE memory cleanup. |
| 9 | ai_narrative_service reads score cache at startup and every 5 min; promotes significant winner | PARTIAL | `_score_refresh_loop` correctly wired in start() at line 880. `_apply_score_routing()` called at startup line 875 and every 5 min. However, promotion is global (best across all regimes) rather than per-regime as LLM-05 specifies. The hgetall pattern reads all regimes but picks single winner. |
| 10 | indicagent-llm-writer systemd service is enabled and running | VERIFIED | `systemctl is-active indicagent-llm-writer` returns "active". Both unit files exist with correct ExecStart pointing to services/llm_writer_service.py. |
| 11 | Prometheus metrics endpoint :9117 returns llm_writer_* metric names | VERIFIED | `curl http://localhost:9117/metrics` returns `llm_writer_calls_consumed_total`, `llm_writer_outcomes_processed_total`, `llm_writer_batch_writes_total`, `llm_writer_service_uptime_seconds`. |

**Score:** 9/11 truths verified (2 failed/partial)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `production/migrations/019_llm_intelligence_layer.sql` | llm_calls hypertable + llm_model_scores + 3 indexes | PARTIAL | File exists (129 lines), tables created in DB, 3 indexes exist, but llm_calls is NOT a hypertable — create_hypertable silently no-oped due to UUID PK conflict |
| `src/core/stream_keys.py` | 3 new helper functions | VERIFIED | llm_calls_stream (L68), llm_outcomes_stream (L73), llm_scores_cache (L78) all present and correct |
| `tests/unit/service_tests/test_llm_writer_service.py` | 12 tests all PASS | VERIFIED | All 12 tests passing: 5 stream key contracts + 7 service function tests GREEN |
| `services/llm_writer_service.py` | 250+ lines, exports 3 pure functions + LLMWriterService | VERIFIED | 819 lines. _parse_llm_call_fields (L116), _parse_outcome_fields (L184), _build_score_insert_params (L223), LLMWriterService class (L278) |
| `services/ai_narrative_service.py` | Instrumented with _emit_llm_call on all paths + _promote_model_in_chain | VERIFIED | _build_llm_call_payload and _promote_model_in_chain present; 3 xadd call sites confirmed at lines 525, 556, 805; _score_refresh_loop at L684 |
| `services/signal_lifecycle_service.py` | Both exit paths emit to llm_outcomes:stream | VERIFIED | _build_outcome_payload at L71, sk_llm_outcomes_stream imported at L31, two create_task xadd calls at L306 and L417 |
| `production/systemd/indicagent-llm-writer.service` | Systemd unit pointing to llm_writer_service.py | VERIFIED | 21 lines, ExecStart correct, SyslogIdentifier=indicagent-llm-writer |
| `services/indicagent-llm-writer.service` | Convenience copy alongside other service files | VERIFIED | 22 lines, identical content to production/systemd copy |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| src/core/stream_keys.py | services/llm_writer_service.py | import llm_calls_stream, llm_outcomes_stream | VERIFIED | L35 in llm_writer_service.py: `from src.core.stream_keys import llm_calls_stream, llm_outcomes_stream, llm_scores_cache` |
| production/migrations/019_llm_intelligence_layer.sql | llm_calls hypertable | create_hypertable called_at | FAILED | create_hypertable call present in migration at L55, but silently no-oped in production due to UUID PK conflict. llm_calls exists as a regular table. |
| services/llm_writer_service.py | llm_calls (TimescaleDB) | execute_batch(_INSERT_LLM_CALL_SQL) | VERIFIED | L455: `await self.db_manager.execute_batch(_INSERT_LLM_CALL_SQL, params)` |
| services/llm_writer_service.py | llm_calls (outcome back-fill) | execute_batch(_UPDATE_OUTCOME_SQL) WHERE signal_id | VERIFIED | L563: `await self.db_manager.execute_batch(_UPDATE_OUTCOME_SQL, [params])` |
| services/llm_writer_service.py | Redis llm_scores:{call_type}:{regime} | redis_client.hset(llm_scores_cache(...)) | VERIFIED | L641-642: cache_key via llm_scores_cache(), then `await self.redis_client.hset(cache_key, model, score_blob)` |
| services/ai_narrative_service.py | {env_prefix}llm_calls:stream | asyncio.create_task(redis_client.xadd(llm_calls_stream(...))) | VERIFIED | 3 fire-and-forget xadd calls at lines 525, 556, 805 |
| services/ai_narrative_service.py | Redis llm_scores:{call_type}:{regime} | _score_refresh_loop reads hgetall then promotes in chain | PARTIAL | hgetall at L718, promotes global winner not per-regime winner |
| services/signal_lifecycle_service.py | {env_prefix}llm_outcomes:stream | asyncio.create_task(redis_client.xadd(llm_outcomes_stream(...))) | VERIFIED | Two create_task xadd calls at L306 and L417, one per exit path |
| production/systemd/indicagent-llm-writer.service | services/llm_writer_service.py | ExecStart path | VERIFIED | ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/llm_writer_service.py |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| LLM-01 | 16-01, 16-05 | llm_calls hypertable + llm_model_scores created by migration 019 | PARTIAL | llm_model_scores: satisfied. llm_calls: table exists but NOT a hypertable. Schema design in migration is correct but create_hypertable silently failed due to UUID PK conflict. |
| LLM-02 | 16-03 | ai_narrative_service emits full payload to llm_calls:stream after every LLM call (success, failure, counterfactual) | SATISFIED | 3 fire-and-forget xadd calls wired; payload builder produces flat dict[str,str] with all required fields; 7 unit tests GREEN |
| LLM-03 | 16-04 | signal_lifecycle_service emits to llm_outcomes:stream when any signal exits | SATISFIED | Both exit paths (shadow + normal) emit via asyncio.create_task before update_signal_status(); 5 unit tests GREEN |
| LLM-04 | 16-02, 16-05 | llm_writer_service batch INSERTs, back-fills outcomes, recomputes scores, writes Redis cache | SATISFIED | execute_batch for INSERT and UPDATE confirmed; _score_recompute_loop at 900s cadence; Redis hset at llm_scores_cache key; Prometheus :9117 live; systemd service active |
| LLM-05 | 16-03 | ai_narrative_service reads Redis score cache at startup and every 5 min; promotes is_significant winner per call_type+regime | PARTIAL | Startup call and 5-min loop correctly wired. Promotion logic selects global best (across all regimes) rather than per-regime winner. The is_significant gate (p<0.05, n>=30) is correctly read from the cache blob. |

No orphaned requirements: all 5 LLM requirement IDs from REQUIREMENTS.md are accounted for across plans.

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| production/migrations/019_llm_intelligence_layer.sql | create_hypertable with if_not_exists=TRUE masks silent failure due to PK constraint conflict | Blocker | llm_calls is not time-partitioned; no automatic chunk management, no hypertable compression, query performance degrades as table grows — the TimescaleDB audit log advantage is lost |

No stub implementations, placeholder returns, or TODO comments found in any of the 4 key service files.

### Human Verification Required

None — all items were verifiable programmatically.

### Gaps Summary

**Gap 1 (Blocker): llm_calls is not a TimescaleDB hypertable**

The migration file is correctly written and the intent is correct, but `create_hypertable('llm_calls', 'called_at', if_not_exists => TRUE)` silently no-oped when applied to production. The root cause: `call_id UUID PRIMARY KEY` defines a unique index on `call_id` alone; TimescaleDB requires the partition column (`called_at`) to be included in any unique index on the table. The error message is: "cannot create a unique index without the column 'called_at' (used in partitioning)". The `if_not_exists => TRUE` flag suppressed this error.

The table is fully functional as a plain Postgres table (data can be inserted, queried, and indexed normally), so the audit logging pipeline works end-to-end. However, the hypertable time-partitioning benefit — automatic chunk management, compression, faster time-range queries — is absent. As the llm_calls table grows with every LLM call, this will become a performance concern.

**Fix required:** Either (a) `ALTER TABLE llm_calls DROP CONSTRAINT llm_calls_pkey; ALTER TABLE llm_calls ADD PRIMARY KEY (call_id, called_at);` then run `SELECT create_hypertable(...)`, or (b) change the schema so `call_id` is `UNIQUE` (not `PRIMARY KEY`) and add a separate primary key that includes `called_at`. The migration SQL must be corrected to prevent future re-deployment from repeating the silent failure. The `if_not_exists => TRUE` guard should be removed or the PK should be fixed before that call.

**Gap 2 (Warning): LLM-05 adaptive routing is per-call-type, not per-regime**

The `_apply_score_routing` implementation promotes a single global winner (maximum avg_pnl_r across all regimes where is_significant=True) for each call_type, not a per-regime winner. LLM-05 specifies promotion "for that call_type + regime combination." The 16-03-SUMMARY documents this as an intentional deferral: "per-regime adaptive routing deferred" pending sufficient regime-segmented data.

Functionally the routing fires correctly (startup + 5-min cadence, correct hgetall pattern, correct atomic chain.providers list replacement). The gap is in selection granularity: when enough data accumulates to have multiple is_significant models in different regimes, the routing will not differentiate by regime — it will always promote the same globally-best model. This is a correctness gap relative to LLM-05 rather than a wiring gap.

---

_Verified: 2026-03-06T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
