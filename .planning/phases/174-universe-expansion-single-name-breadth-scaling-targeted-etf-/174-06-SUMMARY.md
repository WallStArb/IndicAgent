---
phase: 174-universe-expansion-single-name-breadth-scaling-targeted-etf
plan: 06
subsystem: database
tags: [postgresql, config, instrument-governance, structlog, threading]

# Dependency graph
requires:
  - phase: 174-02
    provides: "instruments.compute_eligible / instruments.live_tradeable columns (migration 337)"
provides:
  - "get_active_contracts(settings=None, dimension='compute') -- dimension in {backfill, compute, live}"
  - "per-dimension cache: _active_contracts_cache/_active_contracts_last_refresh are now dict[str, ...], keyed by dimension"
  - "dimension-scoped error-path fallback -- never substitutes another dimension's cached list"
affects: [174-10, 174-12]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dimension validated against a literal module-owned dict before use; SQL clause never built from caller-supplied text"
    - "Per-dimension cache dict (value + refresh-timestamp) replacing a single shared cache, to make cross-caller poisoning structurally impossible rather than relying on discipline"

key-files:
  created:
    - tests/unit/config/test_settings_active_contracts_dimension.py
  modified:
    - src/config/settings.py
    - tests/unit/services/test_service_contract_resolution.py

key-decisions:
  - "dimension='compute' is the default, not 'backfill' -- matches the plan's explicit instruction and keeps the unparameterized call's default behavior aligned with the more conservative (compute-ready) universe, while remaining behaviorally identical to the pre-change query today because migration 337 set compute_eligible=true for every is_active=true row"
  - "Invalid dimension raises ValueError before touching Settings or the DB -- checked as the very first statement in the function body, ahead of the s = settings or _default_settings() line, so a typo'd dimension costs zero DB round trips"
  - "test_service_contract_resolution.py's _reset_cache() and two direct _active_contracts_last_refresh assignments updated for the new dict-typed globals (Rule 3 blocking fix, not separately scoped in the plan's files_modified but required for that file's own tests to keep passing after the cache-type change)"

patterns-established:
  - "get_active_contracts(dimension=) is now the addressable per-dimension read API for the active universe -- future call sites that need the backfill or live dimension pass it explicitly; the 37 existing call sites are unaffected by relying on the compute default"

requirements-completed: [D-07a, D-07b]

# Metrics
duration: ~7min
completed: 2026-09-15
---

# Phase 174 Plan 06: get_active_contracts() Dimension Parameter Summary

**`get_active_contracts()` gained a `dimension` parameter (backfill/compute/live) reading Plan 02's `compute_eligible`/`live_tradeable` columns, with the module cache converted from a single list to a per-dimension dict so one dimension's result can never leak to a caller asking for another.**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-09-15T15:10:00Z (worktree base commit merge-base correction + venv symlink)
- **Completed:** 2026-09-15T15:17:05Z
- **Tasks:** 2/2 completed
- **Files modified:** 1 created (test file), 2 modified (settings.py, one pre-existing test file)

## Accomplishments

- `get_active_contracts(settings=None, dimension="compute")` now maps `dimension` to a literal,
  module-owned WHERE-clause dict (`backfill` → `is_active = true`; `compute` → adds
  `compute_eligible = true`; `live` → adds `live_tradeable = true`), with an unrecognized value
  raising `ValueError` before any Settings instantiation or DB round trip.
- `_active_contracts_cache`/`_active_contracts_last_refresh` converted from a single
  list/float pair to `dict[str, ...]` keyed by dimension, both read and written under
  `_settings_lock` with the DB query still running outside the lock (existing double-checked
  locking discipline preserved). `invalidate_active_contracts_cache()` keeps its zero-argument
  signature and now clears every dimension.
- The error-path fallback is dimension-scoped: on a DB error it returns the warm cache for
  *only* the requested dimension, logging `dimension` on both the `db_query_failed` warning and
  the `cold_start_db_unavailable` critical events; it never substitutes another dimension's list.
- Added `tests/unit/config/test_settings_active_contracts_dimension.py` (9 tests): default
  equivalence (asserts symbol-set equality between the unparameterized call and
  `dimension="backfill"`, plus asserts the default call's SQL contains `compute_eligible = true`),
  compute-narrows-correctly, live-is-empty-by-design (with all three predicates present in the
  executed SQL), invalid-dimension-raises-zero-queries, cache isolation (live-then-compute
  triggers a second DB query rather than serving live's cached empty list), cache-hit-within-TTL,
  invalidation-clears-all-dimensions, dimension-scoped error-path (via `capture_logs`, asserting
  the critical event carries `dimension="live"`), and an 8-thread concurrent cross-dimension
  contention test proving no cross-contamination and exactly three cache keys at the end.
- Live spot check against the real DB: `len(g())=231`, `len(g(dimension='backfill'))=231`,
  `len(g(dimension='live'))=0` — matches the plan's `<verification>` expectation exactly (two
  equal non-zero counts, one trailing zero).
- Full `tests/unit/` suite green (0 failures) after the change.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add the dimension parameter and key the cache by dimension** - `ab4caf3ff` (feat)
2. **Task 2: Prove default-equivalence and cache isolation** - `04f0bca61` (test)

**Plan metadata:** this SUMMARY's own commit (docs: complete plan)

## Files Created/Modified

- `src/config/settings.py` - `get_active_contracts()` gained `dimension` parameter and a
  module-owned `_ACTIVE_CONTRACTS_DIMENSION_CLAUSES` dict; cache globals converted to
  per-dimension dicts; `invalidate_active_contracts_cache()` clears all dimensions
- `tests/unit/config/test_settings_active_contracts_dimension.py` - 9 new tests covering
  default-equivalence, per-dimension narrowing, live-empty, invalid dimension, cache
  isolation/hit/invalidation, dimension-scoped error path, and 8-thread concurrency
- `tests/unit/services/test_service_contract_resolution.py` - `_reset_cache()` and two
  TTL-expiry test bodies updated to set dict entries (`{"compute": ...}` /
  `["compute"] = ...`) instead of assigning a bare `None`/`float` to the now-dict-typed
  module globals

## Decisions Made

- **Default dimension is `"compute"`, not `"backfill"`** — the plan's interfaces section
  specifies this explicitly; it is behaviorally identical to the pre-change unparameterized
  query today (migration 337 backfilled `compute_eligible=true` for every `is_active=true`
  row), and Task 2 case 1 proves the equivalence as a regression test rather than a comment.
- **Dimension validation happens before `Settings` is touched** — `ValueError` is raised as the
  first statement in the function body, ahead of `s = settings or _default_settings()`, so an
  invalid dimension never instantiates a `Settings()` singleton or opens a DB connection.
  Verified by Task 2 case 4 (`mock_connect.call_count == 0`).
- **Fixed `test_service_contract_resolution.py`'s cache-reset/expiry helpers (Rule 3 — blocking
  fix)** — that file is not in this plan's `files_modified` frontmatter, but its `_reset_cache()`
  helper and two TTL-expiry test bodies directly assigned `None`/a bare `float` to
  `_active_contracts_cache`/`_active_contracts_last_refresh`, which are now `dict`-typed. Left
  unfixed, three existing tests in that file would break on this plan's own cache-type change.
  Fixed by setting `{}` / `{"compute": ...}` instead; verified the full file plus `tests/unit/`
  stays green.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated `test_service_contract_resolution.py`'s cache helpers for the new dict-typed globals**
- **Found during:** Task 1 (cache type conversion)
- **Issue:** `_reset_cache()` set `_active_contracts_cache = None` / `_active_contracts_last_refresh = 0.0`, and two tests (`test_db_error_returns_cache_when_warm`, `test_cache_expires_after_60s`) directly overwrote `_active_contracts_last_refresh` with a bare `float`. After converting both globals to `dict[str, ...]`, these assignments would silently break the double-checked-locking cache-read logic (`.get(dimension, ...)` on a `float` raises `AttributeError`) for every test in the file.
- **Fix:** Changed `_reset_cache()` to assign `{}` to both dicts; changed the two direct assignments to key into the `"compute"` dimension (`_active_contracts_last_refresh["compute"] = ...`), matching the dimension those tests actually exercise (the default).
- **Files modified:** `tests/unit/services/test_service_contract_resolution.py`
- **Verification:** `.venv/bin/pytest tests/unit/config/ tests/unit/services/test_service_contract_resolution.py -q` — 74/74 pass (per the plan's own Task 1 verify command).
- **Committed in:** `ab4caf3ff` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary to keep a pre-existing, plan-adjacent test file's own suite green after the cache-type conversion this plan's Task 1 required. No scope creep — no behavior outside the plan's stated cache-conversion work was touched.

## Issues Encountered

None beyond the `.venv` symlink gotcha already documented in 174-02's SUMMARY (worktree spawns
without its own `.venv`; fixed by `ln -s /home/bg/dev/indicagent/.venv .venv`, read-only,
non-destructive).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `get_active_contracts(dimension=)` is live, committed, and behaviorally verified against the
  real 231-symbol corpus. Plans 10 and 12 (both listed in this plan's `affects`) can call
  `dimension="compute"` (implicitly, via the default) for onboarding new symbols, and any future
  live-streaming consumer must now explicitly request `dimension="live"` and will get an empty
  list until a subscription whitelist is deliberately chosen — closing the T-174-01 elevation-of-
  privilege threat this plan's threat model registered.
- No blockers. All four STRIDE threats registered in this plan's threat model (T-174-01,
  T-174-16, T-174-07, T-174-17) are mitigated and covered by an automated test case.

---
*Phase: 174-universe-expansion-single-name-breadth-scaling-targeted-etf*
*Completed: 2026-09-15*

## Self-Check: PASSED

- FOUND: src/config/settings.py
- FOUND: tests/unit/config/test_settings_active_contracts_dimension.py
- FOUND: tests/unit/services/test_service_contract_resolution.py
- FOUND: commit ab4caf3ff
- FOUND: commit 04f0bca61
