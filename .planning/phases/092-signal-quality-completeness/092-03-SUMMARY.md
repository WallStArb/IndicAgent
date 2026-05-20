---
phase: 092-signal-quality-completeness
plan: "03"
subsystem: shadow-governance
tags: [otel, asyncpg, tail-risk, shadow-promotion, signal-metrics, pytest, asyncmock]

requires:
  - phase: 092-02
    provides: signal_metrics rows with skewness and recovery_factor columns, per-entry_type grouping

provides:
  - SHADOW_TAIL_RISK_BLOCKED OTel counter (shadow_tail_risk_blocked_total) with {plugin, reason} labels
  - SHADOW_TAIL_GATE_DB_ERROR OTel counter (shadow_tail_gate_db_error_total) with {plugin} label
  - TAIL_GATE_MIN_SKEWNESS (-2.0) and TAIL_GATE_MIN_RECOVERY (0.5) module-level constants
  - _tail_risk_blocks_promotion() pure gate function with strict-< semantics, None-safe
  - Tail gate block in _check_promotion() before _should_promote(); reuses existing pool.acquire() context
  - Fail-open exception handler around fetchrow; logs warning + increments DB error counter
  - 13 new unit tests covering all None-mix paths, threshold edges, constants lock, and fail-open DB-error

affects: [shadow_auditor_agent, signal_metrics, shadow_registry, shadow_promotion_gate]

tech-stack:
  added: []
  patterns:
    - "Fail-open DB gate: wrap fetchrow in try/except, log + counter on error, fall through to primary gate"
    - "Pure gate function pattern: _tail_risk_blocks_promotion alongside _should_promote, _should_demote"
    - "Connection reuse: tail gate fetchrow runs inside same pool.acquire() context as stats UPDATE"

key-files:
  created: []
  modified:
    - src/observability/metrics.py
    - services/shadow_auditor_agent.py
    - tests/unit/test_shadow_auditor_agent.py

key-decisions:
  - "Tail gate integrated before _should_promote() at line 198; early return at line 217 on block"
  - "fetchrow reuses second pool.acquire() block (lines 135-169) alongside shadow_registry UPDATE - no new connection"
  - "Thresholds locked as module-level float constants: TAIL_GATE_MIN_SKEWNESS=-2.0, TAIL_GATE_MIN_RECOVERY=0.5"
  - "Fail-open semantics: fetchrow exception increments SHADOW_TAIL_GATE_DB_ERROR, logs warning, does NOT return - _should_promote() remains authoritative"
  - "NULL metrics (metrics_row is None) skip the gate entirely - plugin too new is not a block"

patterns-established:
  - "Gate function order in _check_promotion: (1) tail-risk gate, (2) existing _should_promote gate"
  - "SHADOW_TAIL_RISK_BLOCKED reason label: 'skewness' when skewness < threshold, else 'recovery_factor'"

duration: 15min
completed: 2026-05-20
---

# Phase 092 Plan 03: Shadow Governance Tail-Risk Gates Summary

**Tail-risk promotion gate in shadow_auditor_agent that blocks setups with skewness < -2.0 or recovery_factor < 0.5, fails open on transient DB errors, with OTel counters and 13 new unit tests closing the measurement-to-action loop**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-05-20T13:48:00Z
- **Completed:** 2026-05-20T13:54:00Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Two new OTel counters (`SHADOW_TAIL_RISK_BLOCKED`, `SHADOW_TAIL_GATE_DB_ERROR`) registered in metrics.py and importable
- `_tail_risk_blocks_promotion()` pure gate function with strict-`<` semantics, None-safe for both inputs
- Tail gate wired into `_check_promotion()` at line 198 (before `_should_promote` at line 219), reusing the existing second `pool.acquire()` context - zero additional DB connections per cycle
- Fail-open exception handler: DB error increments `SHADOW_TAIL_GATE_DB_ERROR`, logs structured warning, falls through to `_should_promote` (no promotions blocked by DB hiccups)
- 22 total unit tests (9 pre-existing + 13 new), all passing; 7 pre-existing unrelated failures confirmed unchanged

## Task Commits

1. **Task 1: OTel counters** - `26bdb0ea` (feat)
2. **Task 2: Tail gate wired** - `101ecc08` (feat)
3. **Task 3: Unit tests** - `ce116137` (test)

## Files Created/Modified

- `src/observability/metrics.py` - Added SHADOW_TAIL_RISK_BLOCKED and SHADOW_TAIL_GATE_DB_ERROR counters after SHADOW_PROMOTION_READY
- `services/shadow_auditor_agent.py` - Added TAIL_GATE constants, _tail_risk_blocks_promotion() pure function, tail gate block in _check_promotion()
- `tests/unit/test_shadow_auditor_agent.py` - 13 new tests for pure gate function and fail-open path

## Tail Gate Insertion Point

In `services/shadow_auditor_agent.py`:

- `_tail_risk_blocks_promotion()` defined at line 65 (alongside `_should_promote`, `_should_demote`, `_ev_r_below_threshold`)
- Tail gate block: lines 198-217 (`if metrics_row is not None and _tail_risk_blocks_promotion(...)`)
- `_should_promote` check: line 219 (immediately after tail gate early-return path)
- `pool.acquire()` count in `_check_promotion`: 3 (unchanged from pre-edit count - fetchrow runs inside existing second acquire at line 135)

## Connection Reuse Confirmation

The tail gate `fetchrow` runs inside the `async with pool.acquire() as conn:` block at line 135 that also executes the `UPDATE shadow_registry SET last_eval_n=...` statement. No new `pool.acquire()` was introduced. The result (`metrics_row`) is held as a local variable and consumed after the `async with` block exits, before the tail gate check at line 198.

## Production State

`signal_metrics` query for currently blocked plugins (skewness < -2.0 OR recovery_factor < 0.5 where track='market' AND symbol='*' AND entry_type='*') returned 0 rows - no setups currently fail the gate. This is the expected state; the gate will activate when signal_metrics rows are populated with sufficient signal history by Plan 02's compute cycle.

## OTel Counter Confirmation

- `SHADOW_TAIL_RISK_BLOCKED` (`shadow_tail_risk_blocked_total`): importable, `.add(1, {"plugin": "x", "reason": "skewness"})` succeeds
- `SHADOW_TAIL_GATE_DB_ERROR` (`shadow_tail_gate_db_error_total`): importable, `.add(1, {"plugin": "x"})` succeeds
- Both counters verified via Python import test during Task 1

## Decisions Made

- Tail gate checks `metrics_row is not None` before calling `_tail_risk_blocks_promotion` - a None row (plugin has no signal_metrics history) skips the gate entirely; consistent with plan requirement that NULL never blocks
- `reason` label determined by: `"skewness"` when skewness is not None AND below threshold, else `"recovery_factor"` - handles the mixed-block case (e.g., both below threshold) by attributing to skewness first
- `except Exception` (not `asyncpg.PostgresError` only) catches all DB-side errors including connection drops and query timeouts; Gemini Actionable Item 2 recommendation

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Working directory reset between bash calls required using absolute paths for git commands and PYTHONPATH. Resolved by using `git -C <worktree>` and `PYTHONPATH=<worktree>:<worktree>/services` throughout.
- Accidental commit to main repo (instead of worktree) for Task 1 was immediately reversed with `git reset --hard HEAD~1` before proceeding; no data loss.

## Next Phase Readiness

- Phase 092 is complete (Plans 01-03 shipped): distribution-shape metrics in signal_metrics, per-entry_type grouping in SignalMetricsComputeAgent, and tail-risk gate in shadow promotion
- QUAL-04 closed: measurement-to-action loop complete
- Monitoring: alert on `shadow_tail_risk_blocked_total > 0` for governance events; alert on `shadow_tail_gate_db_error_total > 0` for DB issues during audit cycle

---
*Phase: 092-signal-quality-completeness*
*Completed: 2026-05-20*
