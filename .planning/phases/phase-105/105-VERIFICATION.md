---
phase: 105-architecture-hotfix-sprint
verified: 2026-05-24T14:00:00Z
status: gaps_found
score: 17/18 must-haves verified
gaps:
  - truth: "Full unit suite is green after all phase-105 fixes"
    status: failed
    reason: "1 phase-105 test fails: test_bar_writer_agent::test_flush_batch_leaves_buffer_on_error — test sets agent._db_pool = mock_pool expecting an exception but the fixed bar_writer path no longer raises through that mock (the test fixture is stale relative to the new code path). 58 additional pre-existing failures exist across test_signal_ledger, test_api, test_orchestrator_integration, and test_service_contract_resolution — none are phase-105 files."
    artifacts:
      - path: "tests/unit/services/test_bar_writer_agent.py"
        issue: "test_flush_batch_leaves_buffer_on_error sets _db_pool but the fixed code path no longer raises through that mock — test is stale"
    missing:
      - "Fix test_flush_batch_leaves_buffer_on_error to match the current bar_writer error-handling path (or confirm it is testing a pre-phase-105 code path that was deliberately removed)"
human_verification:
  - test: "Run indicagent-shadow-auditor and trigger a full audit cycle; inspect logs for swarm_agent skip events and shadow metric .set() calls"
    expected: "shadow_audit_skip_swarm_agent log lines appear; Grafana shadow_win_rate shows point-in-time value (not accumulating)"
    why_human: "Requires live DB with shadow_registry rows populated and Grafana dashboard inspection"
---

# Phase 105: Architecture Hotfix Sprint Verification Report

**Phase Goal:** Fix hotfix bugs in writer services and shadow governance (HF-1 through HF-11, SG-1 through SG-7)
**Verified:** 2026-05-24T14:00:00Z
**Status:** gaps_found
**Re-verification:** No - initial verification

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | CtxWriterAgent flushes without AttributeError; .add() used | VERIFIED | `_events_written.add(len(event_batch))` at line 343, `_snapshots_written.add(len(snapshot_batch))` at line 351; zero `.inc(` calls |
| 2  | CtxWriterAgent teardown calls super()._teardown() first | VERIFIED | `await super()._teardown()` at line 377, before custom buffer flush |
| 3  | LLMWriterService _parse_update uses db_manager; no self._pool | VERIFIED | `await self.db_manager.execute_command(_UPDATE_PARSE_SQL, ...)` at line 691; zero `self._pool` references |
| 4  | LLMWriterService stall watchdog reads _last_message_ts | VERIFIED | Zero `_last_msg_ts` references; `_record_message_consumed()` called at line 961 inside _process_loop |
| 5  | intelligence.i8 and llm.outcomes dead subscriptions removed with TODO | VERIFIED | No matching lines outside TODO; `TODO(HF-10): intelligence.i8 and llm.outcomes` at line 556 |
| 6  | llm_writer_service consumes from earliest offset | VERIFIED | `auto_offset_reset="earliest"` at line 563 |
| 7  | llm_writer_service uses enable_auto_commit=False | VERIFIED | `enable_auto_commit=False` at line 564 |
| 8  | FeatureWriterAgent crashes hard on DB connect failure | VERIFIED | `self.logger.error("feature_writer.db_connect_failed", ...)` + `raise` at line 414; zero `db_manager = None` or "persistence disabled" references |
| 9  | BarWriterAgent _record_message_consumed called per bar | VERIFIED | `self._record_message_consumed()  # Track liveness for stall detection` at line 256, after contract-update routing block |
| 10 | SwarmLedgerWriterAgent does not auto-commit before DB write | VERIFIED | `enable_auto_commit=False` at line 99; `await self._consumer.commit()` at line 120 only after terminal outcome |
| 11 | Shadow governance metrics are point-in-time gauges | VERIFIED | All 6 SHADOW_* definitions use `point_gauge(...)` in metrics.py lines 224-229; zero `create_up_down_counter` for shadow |
| 12 | Pipeline latency instruments are histograms with .record() | VERIFIED | 3 `create_histogram` calls; `.record()` wired at lines 500, 524, 548 with real latency variables |
| 13 | bars_processed and pipeline_errors are monotonic counters | VERIFIED | `_bars_processed = counter(` at line 176, `_pipeline_errors = counter(` at line 190 |
| 14 | executor stamps is_shadow on every signal dict | VERIFIED | `sig["is_shadow"] = self._is_shadow(task.plugin_name, cache_snapshot.shadow_cache)` at line 714 |
| 15 | Shadow plugins filtered from select_winner via eligible_ranked | VERIFIED | `eligible_ranked = []` at line 425; `select_winner(eligible_ranked, ...)` at line 435; full `ranked` still persisted |
| 16 | Shadow auditor PROMOTION gate uses is_shadow=TRUE; DEMOTION uses is_shadow=FALSE | VERIFIED | `AND is_shadow = TRUE` at line 126 (_check_promotion); `AND is_shadow = FALSE` at line 267 (_check_demotion) |
| 17 | Swarm agents skipped by shadow auditor | VERIFIED | `if ctype == "swarm_agent": continue` at lines 100-101 in `_run_audit()` |
| 18 | Full unit suite green after all phase-105 fixes | FAILED | 1 phase-105 regression test fails (test_bar_writer_agent::test_flush_batch_leaves_buffer_on_error); 58 additional pre-existing failures unrelated to this phase |

**Score:** 17/18 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `services/ctx_writer_agent.py` | OTel .add() calls and super()._teardown() | VERIFIED | Lines 343, 351, 377 |
| `services/llm_writer_service.py` | db_manager.execute_command, _last_message_ts, earliest, enable_auto_commit=False | VERIFIED | Lines 563-564, 691, 961 |
| `services/feature_writer_agent.py` | Raise on DB connect failure | VERIFIED | Line 414 |
| `services/bar_writer_agent.py` | _record_message_consumed in _run() | VERIFIED | Line 256 |
| `services/swarm_ledger_writer_agent.py` | enable_auto_commit=False + consumer.commit() | VERIFIED | Lines 99, 120, 158, 184 |
| `src/observability/metrics.py` | 6 SHADOW_* via point_gauge | VERIFIED | Lines 224-229 |
| `services/intelligence_pipeline_agent.py` | i1/i7/pipeline as histograms with .record(); bars/errors as counters | VERIFIED | Lines 176, 190, 500, 524, 548 |
| `src/intelligence/pipeline/executor.py` | sig["is_shadow"] stamp in post-processing loop | VERIFIED | Line 714 |
| `src/intelligence/pipeline/signal_processor.py` | eligible_ranked filter; shadow status stamp | VERIFIED | Lines 425, 431, 435 |
| `services/shadow_auditor_agent.py` | is_shadow=TRUE promotion, is_shadow=FALSE demotion, swarm skip, .set() calls | VERIFIED | Lines 100-101, 126, 267; 7 .set() calls |
| `tests/unit/pipeline/test_signal_processor.py` | shadow winner-suppression regression test | VERIFIED | is_shadow assertions present |
| `tests/unit/services/test_shadow_auditor_agent.py` | promotion is_shadow=TRUE + demotion is_shadow=FALSE tests | VERIFIED | Lines 157-174 |
| `tests/unit/services/test_swarm_ledger_writer_agent.py` | enable_auto_commit=False + commit-after-success test | VERIFIED | Lines 130-148 |
| `tests/unit/services/test_llm_writer_service.py` | LLM writer regression coverage | VERIFIED | Lines 450-465 |
| `tests/unit/services/test_feature_writer_agent.py` | fail-fast DB-connect-raises test | VERIFIED | Lines 639-673 |
| `tests/unit/services/test_bar_writer_agent.py` | _record_message_consumed regression test (PASSING) | VERIFIED | test_record_message_consumed_called passes; test_flush_batch_leaves_buffer_on_error FAILS |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| ctx_writer_agent._teardown | BaseWriterAgent._teardown final flush | await super()._teardown() as first statement | WIRED | Line 377 |
| llm_writer_service._stall_watchdog | _last_message_ts | _record_message_consumed() in _process_loop | WIRED | Line 961 |
| llm_writer_service KafkaConsumerClient | offset commit after batch write | enable_auto_commit=False | WIRED | Line 564 |
| bar_writer_agent._run loop | BaseAgent stall watchdog | _record_message_consumed() sets _last_message_ts | WIRED | Line 256 |
| swarm_ledger KafkaConsumerClient | offset commit after DB write | enable_auto_commit=False + consumer.commit() on success/terminal | WIRED | Lines 99, 120 |
| executor.py post-processing loop | signal_writer persistence of is_shadow | sig["is_shadow"] = self._is_shadow(...) | WIRED | Line 714 |
| signal_processor.py select_winner path | eligible_ranked (shadow-excluded candidates) | cache_snapshot.shadow_cache.get(setup_plugin) | WIRED | Lines 425-435 |
| shadow_auditor_agent promotion query | signal_ledger shadow-mode observations | AND is_shadow = TRUE | WIRED | Line 126 |
| shadow_auditor_agent demotion query | signal_ledger live-only rows | AND is_shadow = FALSE | WIRED | Line 267 |
| metrics.py SHADOW_* definitions | shadow_auditor_agent .set() call sites | create_gauge enables .set() | WIRED | 7 .set() calls in shadow_auditor_agent.py |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| tests/unit/services/test_bar_writer_agent.py | 215-231 | Stale test fixture sets `_db_pool` mock expecting raise; current code path does not raise through that mock | Blocker | Prevents plan 05 truth 8 ("full suite green") from passing |

### Human Verification Required

#### 1. Shadow audit cycle validation

**Test:** Start indicagent-shadow-auditor and let it run one full audit cycle against a DB with shadow_registry rows including at least one swarm_agent type.
**Expected:** Log line `shadow_audit_skip_swarm_agent` appears for swarm_agent rows; SHADOW_WIN_RATE in Grafana shows a stable point value that does not grow across repeated audit cycles.
**Why human:** Requires live DB with populated shadow_registry and Grafana dashboard access; cannot verify idempotent metric accumulation behavior via grep.

### Gaps Summary

One gap blocks full goal achievement: the plan 05 success criterion "full pytest tests/unit/ green" is not met.

The failure is in `tests/unit/services/test_bar_writer_agent.py::test_flush_batch_leaves_buffer_on_error` (line 215). This pre-existing test patches `agent._db_pool` and expects the flush to raise through an `asyncpg`-style pool mock. The phase-105 changes to `bar_writer_agent.py` altered the error-handling path, leaving the test fixture stale - it no longer reaches the mocked pool in the same way.

The 58 other unit-suite failures (`test_signal_ledger.*`, `test_api.*`, `test_orchestrator_integration.*`, `test_service_contract_resolution.*`, `test_signal_writer_agent::test_cis_fields_wired_from_payload`) are pre-existing failures from schema mismatches introduced by a prior phase (LedgerEntry missing `confidence` keyword argument). They are not caused by phase-105 changes and no phase-105 PLAN file claims to fix them.

The two collection errors (`test_trade_framer.py`, `test_winner_selector.py`) also collected cleanly when run in isolation (20 passed) - the error is a pytest collection ordering issue, not a real failure.

---

_Verified: 2026-05-24T14:00:00Z_
_Verifier: Claude (gsd-verifier)_
