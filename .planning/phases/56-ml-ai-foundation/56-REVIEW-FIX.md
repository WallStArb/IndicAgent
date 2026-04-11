---
phase: 56-ml-ai-foundation
fixed_at: 2026-04-11T06:59:00Z
review_path: .planning/phases/56-ml-ai-foundation/56-REVIEW.md
iteration: 1
findings_in_scope: 9
fixed: 9
skipped: 0
status: all_fixed
---

# Phase 56: Code Review Fix Report

**Fixed at:** 2026-04-11T06:59:00Z
**Source review:** .planning/phases/56-ml-ai-foundation/56-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 9 (3 critical + 6 warnings)
- Fixed: 9
- Skipped: 0

## Fixed Issues

### CR-01: SQL logic inverted — CIS null-rate always measures non-null rate instead

**Files modified:** `services/ml_data_quality_agent.py`
**Commit:** e7c28f6d
**Applied fix:** Replaced `1.0 - COUNT(*) FILTER (WHERE i7 IS NOT NULL OR i7->>'cis' IS NOT NULL)` with `COUNT(*) FILTER (WHERE i7 IS NULL OR i7->>'cis' IS NULL)` — now directly counts null rows as the numerator, eliminating the inversion. The `1.0 - ...` subtraction was removed; the result is already a null rate.

---

### CR-02: `ml_orchestrator_agent.py` queries a non-existent table — quality gate permanently bypassed

**Files modified:** `production/migrations/061_ml_data_quality_runs.sql`, `services/ml_data_quality_agent.py`, `services/ml_orchestrator_agent.py`
**Commit:** 395b80a8
**Applied fix:** Created migration `061_ml_data_quality_runs.sql` with `ml_data_quality_runs (run_id, ts, score, status)` table. Added `_write_score()` method to `MLDataQualityAuditorAgent` that INSERTs the composite score to the new table after each run. The orchestrator's existing `SELECT score FROM ml_data_quality_runs` query now resolves correctly. Note: WR-04 (async subprocess) was bundled into the same commit since both edits touch `ml_orchestrator_agent.py`.

---

### CR-03: Circuit breaker state mutation bypasses transition logic — circuit never opens for LLM providers

**Files modified:** `src/core/llm/providers.py`
**Commit:** e4e85eb5
**Applied fix:** Added a pre-call OPEN gate check: if `plugin_state.state == CircuitState.OPEN` and recovery timeout has not elapsed, the function returns `None` immediately without calling the provider. After recovery timeout, state transitions to `HALF_OPEN` for a probe call. On success in HALF_OPEN, circuit closes and `failure_count` resets. On failure accumulation (`failure_count >= failure_threshold`), `plugin_state.state` is explicitly set to `CircuitState.OPEN` and `_llm_open_since` is recorded. This requires human verification of the logic path for HALF_OPEN → OPEN re-trip edge case.
**Status:** fixed: requires human verification

---

### WR-01: `ml_discovery_agent.py` — `setup_service_logging` not called in `__init__`

**Files modified:** `services/ml_discovery_agent.py`
**Commit:** 061763ab
**Applied fix:** Added `setup_service_logging("logs/ml_discovery_agent.log")` as the first line of `MLDiscoveryComputeAgent.__init__`, matching the pattern in `MLDataQualityAuditorAgent`.

---

### WR-02: `swarm_orchestrator_agent.py` — private attribute access on `SafeSwarmWrapper` for path filtering

**Files modified:** `src/intelligence/swarm/safety.py`, `services/swarm_orchestrator_agent.py`
**Commit:** 1a398fe6
**Applied fix:** Added `path` public property to `SafeSwarmWrapper` that returns `self._path`. Updated the filter in `_handle_signal` from `getattr(w._contributor, "path", "") == "deterministic"` to `w.path == "deterministic"`.

---

### WR-03: `swarm_writer_agent.py` — data lost on DB failure without payload content in DLQ

**Files modified:** `services/swarm_writer_agent.py`
**Commit:** fa3937c9
**Applied fix:** Added `"payloads": batch[:10]` to the DLQ publish dict in `_write_batch`, allowing failed rows to be replayed from the DLQ. Truncated to first 10 rows to avoid oversized messages.

---

### WR-04: `ml_orchestrator_agent.py` — blocking `subprocess.run()` called from async context

**Files modified:** `services/ml_orchestrator_agent.py`
**Commit:** 395b80a8 (bundled with CR-02)
**Applied fix:** Wrapped both `subprocess.run(...)` calls (data quality node and discovery node) with `await asyncio.to_thread(subprocess.run, ...)`, preventing event loop blocking during the 10-minute and 30-minute systemctl timeouts.

---

### WR-05: `src/core/llm/chain.py` — `_guardrails` singleton instantiated but `validate()` never called

**Files modified:** `src/core/llm/chain.py`
**Commit:** 050414ab
**Applied fix:** Added guardrails validation step after receiving a non-None response: if `call_type` has a registered schema in `_guardrails._schemas`, `validate()` is called; a `None` return rejects the response and returns `None` to the caller with a warning log. Also removed pre-existing unused import `ZAIProvider` (caught by pre-commit hook).

---

### WR-06: `src/core/ml/training_data.py` — SQL regime filter appended after `ORDER BY` clause

**Files modified:** `src/core/ml/training_data.py`
**Commit:** e1da6dde
**Applied fix:** Replaced the `sql += ...` append after `_BASE_SQL` with a `_BASE_SQL.replace("ORDER BY f.ts", "  AND ... = $5\nORDER BY f.ts")` that inserts the regime filter into the WHERE clause before `ORDER BY`. The `else: sql = _BASE_SQL` branch handles the non-regime case cleanly.

---

_Fixed: 2026-04-11T06:59:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
