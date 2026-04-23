---
phase: 68-pipeline-hardening-institutional-foundation
fixed_at: 2026-04-23T00:00:00Z
review_path: .planning/milestones/v2.4-phases/68-pipeline-hardening-institutional-foundation/68-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
---

# Phase 68: Code Review Fix Report

**Fixed at:** 2026-04-23
**Source review:** `.planning/milestones/v2.4-phases/68-pipeline-hardening-institutional-foundation/68-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (WR-01 through WR-06; CR-* = 0; IN-* excluded by fix_scope)
- Fixed: 6
- Skipped: 0

**Test verification:** Pre-existing failure `test_total_instrument_count_60` (59 instruments, expects 60) confirmed present before any Phase 68 changes — not introduced by these fixes. All other 67 unit tests pass. Two pre-existing ruff B905/B007 violations in `llm_writer_service.py` and `test_bar_aggregator_agent.py` confirmed present before changes.

---

## Fixed Issues

### WR-01: Spurious zero-latency observation in `_flush_batch` corrupts percentiles

**Files modified:** `services/feature_writer_agent.py`
**Commit:** `7998f45b`
**Applied fix:** Removed the `PERSISTENCE_BATCH_LATENCY.labels(agent_id="feature_writer").observe(0)` call on the line immediately following the `self._batch_latency.time()` context manager. The context manager already records the correct observation; the `observe(0)` was a false zero that polluted histogram percentiles on every flush.

---

### WR-02: Duplicate column alias in `_SELECT_OUTCOME_ROWS_SQL` silently shadows n_calls

**Files modified:** `services/llm_writer_service.py`
**Commit:** `4d758899`
**Applied fix:** Removed the duplicate `COUNT(outcome) AS n_outcomes` line (line 118 of the original). The SQL now has exactly one `COUNT(*) AS n_calls` and one `COUNT(outcome) AS n_outcomes`, matching what `_recompute_scores()` reads by name via `row["n_calls"]` and `row["n_outcomes"]`.

---

### WR-03: `SignalMetricsWriterAgent._run()` consumes without stop-event check on entry

**Files modified:** `services/signal_metrics_writer_agent.py`
**Commit:** `7833d327`
**Applied fix:** Added `if self._stop_event.is_set(): return` guard at the top of `_run()` before the `async for` loop. This matches the pattern used by all other agents in the codebase and ensures the agent exits promptly if the stop event fires between `_setup()` and the first message arriving.

---

### WR-04: Fallback bar timestamp `datetime.now(UTC)` on missing `ts` silently creates wrong data

**Files modified:** `services/bar_aggregator_agent.py`, `services/bar_writer_agent.py`
**Commit:** `78ef2f28`
**Applied fix:** Replaced the `if ts_raw: ... else: ts = datetime.now(UTC)` pattern in both agents with an early-return guard: `if not ts_raw: ... return None`. Bars with no `ts` or `timestamp` field are now rejected (returning `None` routes them to DLQ) rather than silently stamped with wall-clock time. In `bar_aggregator_agent.py` the skip reason is also set to `"missing_timestamp"` for observability. This upholds the Renaissance data-quality principle: fabricated timestamps corrupt the OHLCV ground truth.

---

### WR-05: `LifecycleWriterAgent` does not wire `_consumer` for offset commits

**Files modified:** `services/lifecycle_writer_agent.py`
**Commit:** `aa8566d4`
**Applied fix:** Replaced `self._consumer_lag.set(len(self._buffer))` with `self._buffer_depth_gauge.set(len(self._buffer))`. `_consumer_lag` was never assigned as an instance attribute (not in `__init__`, not in `_setup()`, not in `BaseWriterAgent`) — calling `.set()` on it would raise `AttributeError` at runtime. `_buffer_depth_gauge` is provided by `BaseWriterAgent.__init__()` and is the correct gauge for tracking current buffer depth.

---

### WR-06: `test_bar_aggregator_agent._make_agent()` references non-existent attribute `_consumer_restart_requested`

**Files modified:** `tests/unit/service_tests/test_bar_aggregator_agent.py`
**Commit:** `58735e3f`
**Applied fix:** Removed the stale `agent._consumer_restart_requested = asyncio.Event()` assignment from `_make_agent()`. The actual `BarAggregatorComputeAgent.__init__` uses `self._consumer_restart_needed = False` (a bool flag, not an Event), which was already correctly set at line 79 of the same helper. The stale line set a wrong-typed attribute that is never read by the production code.

---

_Fixed: 2026-04-23_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
