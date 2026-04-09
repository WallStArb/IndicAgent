---
phase: 58.1-contract-lifecycle-automation
plan: "03"
subsystem: infra
tags: [bar-auditor, gap-detection, trading-session, kafka, completeness-threshold]

requires:
  - phase: 58.1-01
    provides: "TradingSession.session_window_for_date() and max_achievable_pct() methods; topic_contract_updates() stream key"

provides:
  - "BarAuditorAgent gap detection uses session-aligned UTC windows via session_window_for_date()"
  - "Per-session completeness threshold derived from max_achievable_pct() * 0.97 (replaces hardcoded 0.95)"
  - "Contract update subscription via topic_contract_updates for cache invalidation"
  - "HTF completeness (5m/15m/1h/4h) observed as metrics and warnings — no HTF BarGapRequests"
  - "12 unit tests verifying session-aligned windows, derived thresholds, non-trading day skips"

affects:
  - "bar_auditor_agent"
  - "gap-fill pipeline"
  - "completeness monitoring"

tech-stack:
  added: []
  patterns:
    - "session_window_for_date() for UTC window computation in auditor (eliminates midnight-to-midnight UTC)"
    - "max_achievable_pct() * gate constant pattern for per-session threshold derivation"
    - "HTF-observe-only pattern: metrics emitted, no gap requests issued for HTF timeframes"
    - "Non-blocking contract update drain via async generator with safety cap of 100 messages"

key-files:
  created:
    - "tests/unit/test_bar_auditor_agent.py"
  modified:
    - "services/bar_auditor_agent.py"

key-decisions:
  - "asyncpg pool.acquire() mock requires MagicMock (not AsyncMock) for return_value — AsyncMock makes it a coroutine, breaking async with protocol"
  - "Plan 01 methods (session_window_for_date, max_achievable_pct) cherry-picked from worktree-agent-addbc714 — parallel execution means Plan 03 must include Plan 01 changes"
  - "HTF gap detection is observe-only (log + metric) — gap fill is 1m-only by design; issuing HTF BarGapRequests would be incorrect"
  - "_drain_contract_updates uses async generator with 100-message safety cap — prevents blocking on message flood while draining pending updates"
  - "_COMPLETENESS_GATE = 0.97 replaces _COMPLETENESS_THRESHOLD = 0.95 — higher gate + session-specific max_achievable_pct() gives correct per-session floor"

patterns-established:
  - "session-aligned windows: always call session.session_window_for_date(target_date) for any per-session query window"
  - "derived threshold: session.max_achievable_pct() * GATE_CONSTANT — never hardcode across session types"

requirements-completed:
  - CLA-03

duration: 5min
completed: "2026-04-02"
---

# Phase 58.1 Plan 03: Session-Aligned Gap Detection Summary

**BarAuditorAgent gap detection upgraded to session-aware UTC windows and derived completeness thresholds, eliminating false positives for CME overnight sessions and adding HTF completeness observability**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-02T19:01:14Z
- **Completed:** 2026-04-02T19:06:23Z
- **Tasks:** 2
- **Files modified:** 2 (+ 1 cherry-picked Plan 01 commit for dependency)

## Accomplishments

- Replaced midnight-to-midnight UTC windows with `session_window_for_date()` calls — gap fill requests now carry correct session-aligned start/end timestamps
- Derived per-session completeness threshold: `session.max_achievable_pct() * 0.97` — CME overnight sessions (1380/1440 achievable) no longer trigger infinite false-positive gap requests
- Added contract update subscription (`topic_contract_updates`) with non-blocking drain for cache invalidation
- HTF completeness (5m/15m/1h/4h) now observed as metrics and warning logs — no HTF BarGapRequests issued (gap fill is 1m-only by design)
- 12 unit tests covering all new behaviors, including exact UTC timestamp assertions

## Task Commits

Each task was committed atomically:

1. **Task 1: Session-aligned gap detection implementation** - `bf43846` (feat)
2. **Task 2: Unit tests for session-aligned gap detection** - `a1f5a17` (test)

**Plan 01 dependency (cherry-picked):** `e4adee2`, `c05e6e6` (feat from worktree-agent-addbc714)

## Files Created/Modified

- `/home/bg/dev/indicagent/services/bar_auditor_agent.py` — Added `_COMPLETENESS_GATE`, `_HTF_TIMEFRAME_MINUTES`, `_drain_contract_updates()`, updated `_detect_gaps()` with session windows and derived threshold
- `/home/bg/dev/indicagent/tests/unit/test_bar_auditor_agent.py` — 12 new tests; `__new__` pattern per CLAUDE.md; `MagicMock` for asyncpg pool.acquire() context manager

## Decisions Made

- **asyncpg pool mock pattern**: `pool.acquire.return_value` must be a `MagicMock` (not `AsyncMock`) for `async with pool.acquire() as conn` to work — `AsyncMock` makes `acquire()` return a coroutine, which doesn't support the async context manager protocol
- **Plan 01 cherry-pick**: `session_window_for_date()` and `max_achievable_pct()` were built in worktree-agent-addbc714 (Plan 01, parallel agent). Cherry-picked `56ebd69` (test), `f296703` (feat) commits; skipped `8ac86b9` (docs STATE.md conflict). `stream_keys.py` docstring conflict resolved by merging both descriptions.
- **HTF observe-only**: HTF gaps emit metrics and warning logs but never publish `BarGapRequest`. The gap fill pipeline only handles 1m bars — issuing HTF requests would be semantically incorrect.
- **Safety cap in drain**: `_drain_contract_updates()` caps at 100 messages to prevent blocking on flood; resets `_active_contracts_last_refresh = 0.0` for each batch received.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Cherry-picked Plan 01 dependency from parallel worktree**

- **Found during:** Task 1 setup — `session_window_for_date` and `max_achievable_pct` not in models.py on this branch
- **Issue:** Plan 03 depends on Plan 01 methods added by a parallel agent in worktree-agent-addbc714
- **Fix:** Cherry-picked commits `56ebd69` and `f296703` from Plan 01 worktree branch; resolved docstring conflict in `stream_keys.py` by merging both descriptions; skipped docs-only commit `8ac86b9` (STATE.md conflict, irrelevant to execution)
- **Files modified:** `src/core/models.py`, `src/core/stream_keys.py`, `src/core/schemas/market_events.py`, `tests/unit/test_models.py`
- **Verification:** `grep -n "session_window_for_date\|max_achievable_pct" src/core/models.py` confirms methods present
- **Committed in:** `e4adee2`, `c05e6e6` (cherry-pick of Plan 01 commits)

---

**Total deviations:** 1 auto-fixed (Rule 3 - blocking dependency from parallel plan execution)
**Impact on plan:** Cherry-pick was necessary and correct — this is a known parallel execution pattern where Plan 03 depends on Plan 01 output. No scope creep.

## Issues Encountered

- `stream_keys.py` had docstring merge conflict between Plan 02 (current branch HEAD) and Plan 01 (cherry-picked) — both had added the same `topic_contract_updates` and `topic_roll_dlq` functions with different docstrings. Resolved by combining both docstrings.

## Known Stubs

None — all completeness data flows from real DB queries; no placeholder values in metrics or log output.

## Next Phase Readiness

- Plan 03 complete: BarAuditorAgent now uses session-aligned windows and derived thresholds
- Ready for Plan 04: ContractRollAgent (uses the same session models) or Plan 05: end-to-end contract lifecycle integration
- No blockers

## Self-Check

Verifying claims before marking complete...
