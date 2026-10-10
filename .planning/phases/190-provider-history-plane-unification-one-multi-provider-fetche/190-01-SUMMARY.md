---
phase: 190-provider-history-plane-unification-one-multi-provider-fetche
plan: 01
subsystem: infra
tags: [provider-leaf, history-provider, protocol, conformance-test, boundary-test, ibkr]

# Dependency graph
requires:
  - phase: 189-ibkr-history-fetch-consolidation
    provides: the IBKR leaf's historical-data primitives (fetch_historical_bars walk, EmptyHistory verdict, RequestRecord capture) that fetch_ohlcv delegates to
provides:
  - HistoryProvider runtime_checkable protocol plus HistoryRequest / FetchBudget / NoDataVerdict / HistoryPage frozen types in src/providers/base.py (streaming DataProvider byte-identical)
  - IBKRProvider.fetch_ohlcv: one caller-driven windowed fetch returning bars, a resume point, and a NoDataVerdict on definitive no-data
  - Parameterized protocol-conformance suite (FakeHistoryLeaf behavioral cases + IBKR structure cases) at tests/unit/providers/test_history_conformance.py
  - CI import-boundary fence tests/unit/test_provider_leaf_boundary.py: services/, scripts/ and src/ cannot import a concrete leaf except through a reasoned allow-list
affects: [190-04 fetch-path seam, 190-02 ledger migrations, 190-03 planner, todo 521 Alpaca leaf]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Sibling runtime_checkable protocol alongside DataProvider (third protocol in base.py, established shape)"
    - "Caller-driven window-scoped pagination: next_window_start is a plain datetime resume point, never a cursor token"
    - "Per-vendor no-data evidence fields that do not collapse (n_confirming_chunks vs authoritative_empty)"

key-files:
  created:
    - tests/unit/providers/test_history_conformance.py
    - tests/unit/test_provider_leaf_boundary.py
  modified:
    - src/providers/base.py
    - src/providers/ibkr.py
    - src/providers/__init__.py

key-decisions:
  - "adjustment='split' raises loudly on the IBKR leaf: ADJUSTED_LAST is now-anchored (no endDateTime on ContFuture), so a windowed split-adjusted fetch cannot exist there; silent unadjusted answers are forbidden"
  - "Budget enforced at native-request issuance (deadline and max_requests checked before the window fetch; a block returns an empty page with the resume point intact); one window is by construction one SMART request plus the bounded 1d venue walk"
  - "rth_only threads an optional use_rth kwarg into the private _fetch_historical_bars_impl (default None keeps the STK-derived behavior); the public fetch_historical_bars signature is untouched"
  - "Boundary fence covers both concrete-leaf import forms: direct module path and package-level symbol re-export"

patterns-established:
  - "Conformance suite shape: contract assertion functions written once, fake leaf carries behavioral cases, real leaf carries structure-level cases, fetch-path proof stays in the existing item-test suite"
  - "Boundary allow-list entries carry status prefixes (SHRINKS IN 190-04 / PERMANENT) plus the reason"

requirements-completed: [P190-conformance, P190-boundary]

# Metrics
duration: 36min
completed: 2026-10-10
---

# Phase 190 Plan 01: HistoryProvider batch surface Summary

**HistoryProvider protocol with request/budget/verdict/page types in src/providers/base.py, a conforming IBKR leaf (fetch_ohlcv with caller-driven window pagination and per-vendor no-data evidence), a fake-vs-IBKR conformance suite, and a CI fence that bans concrete-leaf imports outside src/providers/**

## Performance

- **Duration:** 36 min
- **Started:** 2026-10-10T04:02:45Z
- **Completed:** 2026-10-10T04:38:31Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- The batch history surface exists as an additive sibling protocol: DataProvider, DataProviderAdapter, EmptyHistory and RequestRecord are byte-identical (base.py diff is additions only)
- IBKRProvider satisfies HistoryProvider with a real windowed fetch: newest single-chunk window of (start, end], resume point back to the caller, NoDataVerdict built from the walk's EmptyHistory with IBKR's chunk evidence
- Both phase-190 enforcement artifacts are green: the conformance suite (page boundaries, budget interface, verdict emission, observation shape over FakeHistoryLeaf; type/structure conformance over IBKR) and the import-boundary fence with an honest, reality-matched allow-list
- Full unit suite green: 7441 passed, 5 skipped (pre-existing skips)

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): conformance suite for the batch surface** - `6cdd1d1b0` (test)
2. **Task 1 (GREEN): HistoryProvider protocol + types; IBKRProvider conforms** - `252d87383` (feat)
3. **Task 2: behavioral conformance cases against FakeHistoryLeaf** - `9d82e91e4` (test)
4. **Task 3: provider leaf import-boundary fence** - `b9291dec2` (test)

_Note: Task 1 is tdd=true and follows the RED/GREEN gate sequence._

## Files Created/Modified
- `src/providers/base.py` - HistoryRequest, FetchBudget, NoDataVerdict, HistoryPage frozen dataclasses + HistoryProvider runtime_checkable protocol; module docstring states the surface's design provenance
- `src/providers/ibkr.py` - IBKRProvider.fetch_ohlcv (windowed page fetch, budget gate, verdict mapping, loud adjustment rejection); optional use_rth on the private impl
- `src/providers/__init__.py` - exports the five new surface names
- `tests/unit/providers/test_history_conformance.py` - the conformance suite: frozen/type shapes, IBKR isinstance + unchanged DataProvider surface (inspect.signature), FakeHistoryLeaf behavioral cases via shared assertion functions
- `tests/unit/test_provider_leaf_boundary.py` - grep-style fence over services/, scripts/, src/ (excluding src/providers/) with a reasoned allow-list

## Decisions Made
- **adjustment="split" raises on the IBKR leaf.** The named-contract windowed path is the unadjusted SMART TRADES tape; the split-adjusted ADJUSTED_LAST series cannot serve an arbitrary window (IBKR prohibits endDateTime on ContFuture). Raising beats silently answering unadjusted.
- **Budget semantics: gate at native-request issuance.** The leaf checks budget.deadline and max_requests before issuing its window fetch; one window is one SMART request by construction plus the bounded 1d venue walk, and the leaf's own sliding-window limiter keeps pacing the native request. Mid-call abortion is not possible on the existing primitive and belongs to 190-04's seam work; a blocked call returns an empty page with the resume point so the caller can retry under fresh budget.
- **rth_only is a declared convention, not a default.** Threads an optional use_rth into _fetch_historical_bars_impl (None preserves today's useRTH = STK behavior for existing callers); the conformance test pins fetch_historical_bars' public signature as unchanged.
- **The fake leaf counts requests across calls** (FetchBudget is frozen per-call state), modeling the planner's shared budget honestly.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical enforcement] Boundary regex extended to cover package-level leaf imports**
- **Found during:** Task 3
- **Issue:** The plan's single regex `(from|import)\s+src\.providers\.(ibkr|alpaca)\b` only catches direct module-path imports. Seven of the eleven real concrete-leaf importers (including the entire fetcher family and backfill_feature_factory) use `from src.providers import IBKRProvider[, ibkr]`, which the fence would not have seen, defeating the artifact's purpose.
- **Fix:** Second compiled pattern for package-level leaf-symbol imports; hits from both merged. `from src.providers.base import ...` and `ibkr_adapter` deliberately do not match.
- **Files modified:** tests/unit/test_provider_leaf_boundary.py
- **Verification:** test passes against today's tree; the sibling stale-entry test pins the list
- **Committed in:** b9291dec2

**2. [Plan instruction: allow-list must match reality] Allow-list seeded from the live grep, which differs from the plan's expected list**
- **Found during:** Task 3
- **Issue:** The plan's anticipated importer list was partially stale: src/api/routes/sse.py has no provider reference at all, src/providers/ibkr_adapter.py sits inside the excluded ring, and the real grep surfaced three onboarding/classification sourcing files (classification_ibkr_sourcing.py, universe_expansion_onboard_manifest.py, universe_expansion_stratified_sourcing.py) the plan only anticipated generically.
- **Fix:** Allow-list contains exactly the eleven verified importers, each with a real reason; fetcher-family entries carry SHRINKS IN 190-04 status prefixes.
- **Files modified:** tests/unit/test_provider_leaf_boundary.py
- **Committed in:** b9291dec2

---

**Total deviations:** 2 auto-fixed (1 missing-critical enforcement, 1 plan-reality sync)
**Impact on plan:** Both necessary for the fence to actually enforce "a vendor is a leaf". No scope creep; no fetcher or drain files touched.

## Issues Encountered
- The repo's duplicate-test-name pre-commit check flagged `test_allow_list_has_no_stale_entries` as colliding with the sibling boundary test; renamed to `test_leaf_boundary_allow_list_has_no_stale_entries` (b9291dec2).
- 90-day test span arithmetic: (2020-01-01, 2020-04-01] is 91 days and produces 4 windows, not 3; spans adjusted to exact multiples of the 30-day window.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 190-04 can dispatch through HistoryProvider; its seam work replaces the fetcher's provider_factory default and shrinks the three SHRINKS-IN-190-04 allow-list entries to zero
- The Alpaca leaf (todo 521's lane) conforms by passing tests/unit/providers/test_history_conformance.py: add the leaf to the CONFORMANCE_LEAVES parameter list and carry the behavioral cases (adjustment="split", authoritative_empty)
- 190-02/190-03 can type against NoDataVerdict and HistoryPage without further base.py changes
- No edits touched the live drain's files (ibkr_history_fetcher.py, _history_fetch*.py are read-only here, only referenced by the boundary test)

## Self-Check: PASSED

All five created/modified files exist on disk; all four task commits verified in git log (6cdd1d1b0, 252d87383, 9d82e91e4, b9291dec2).

---
*Phase: 190-provider-history-plane-unification-one-multi-provider-fetche*
*Completed: 2026-10-10*
