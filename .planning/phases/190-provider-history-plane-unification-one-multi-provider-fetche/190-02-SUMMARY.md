---
phase: 190-provider-history-plane-unification-one-multi-provider-fetche
plan: 02
subsystem: infra
tags: [two-tier-ledger, migration, coverage-writer, provider-dimension, live-drain-safe]

# Dependency graph
requires:
  - phase: 189-ibkr-history-fetch-consolidation
    provides: ohlcv_coverage (migration 432) and its single writer, the running IBKR 5m drain this plan must not disturb
provides:
  - Applied migration 464: ohlcv_coverage.provider (NOT NULL DEFAULT 'ibkr', named CHECK) and ohlcv_provider_head.timeframe (nullable), backward-compatible with the running drain
  - Committed-but-unapplied migration 465: the two-tier PK swaps plus measured per-TF floor seeds, applying at the 190-06 cutover only
  - Provider-parameterized coverage writer (upsert_coverage, record_fetch_outcome, reset_failures, refresh_1d_bounds, rebuild_from_stored_state) with the OLD conflict target as the live path
  - CoverageDelta.provider threading from the fetching vendor into the coverage upsert
  - Per-provider rebuild filters (_REBUILD_FILTERS) replacing the hardcoded IBKR request filter
  - parity-before.tsv dry-run sanity reference
affects: [190-03 planner, 190-04 fetcher generalization, 190-06 cutover (owns the 465 apply and the conflict-target flip), todo 521 alpaca leaf]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Additive-then-breaking migration split: 464 applies live under a running drain, 465 sits contract-tested and un-applied for the cutover window"
    - "Source-level conflict-target fence: the boundary test pins every ON CONFLICT to the old shape until the cutover flips both test and code in one commit"
    - "Force-rolled-back DDL simulation: an integration test applies the breaking migration's DDL plus the flipped SQL inside one transaction and raises to roll back"

key-files:
  created:
    - production/migrations/464_ohlcv_coverage_provider_dimension.sql
    - production/migrations/465_provider_history_two_tier_keys.sql
    - tests/unit/test_provider_history_migration_contract.py
    - .planning/phases/190-provider-history-plane-unification-one-multi-provider-fetche/parity-before.tsv
  modified:
    - services/ohlcv_coverage_writer.py
    - scripts/infrastructure/backfill/_intraday_persist.py
    - tests/unit/test_ohlcv_coverage_writer_boundary.py
    - tests/unit/scripts/test_intraday_persist.py
    - tests/integration/test_ohlcv_coverage_atomic_write.py
    - tests/integration/conftest.py

key-decisions:
  - "Migration 465's header carries the cutover-window contract: applied by 190-06 with the fetcher timer AND service stopped, in the same shell breath as the writer's conflict-target flip (a live drain would fail every chunk persist with 42P10 once the old PK drops)"
  - "Stored-state labeling rule stated in both headers and COMMENTs: the ibkr label is the authoring fetch plane of a canonical-tier row, never a vendor provenance claim; Tradier-era 1d bounds and 449-lane bars ride under ibkr; vendor claims stay in ohlcv_load.source and the per-provider tier"
  - "Floor seeds (ibkr 5m 2006-07-01T22:00Z, 1d 2000-01-03, [measured], todo 526) use ON CONFLICT DO NOTHING so a verified head row always wins over the seed"
  - "The integration post-flip case simulates the WHOLE 190-06 flip (new PK plus the swapped ON CONFLICT) inside one force-rolled-back transaction, so no DB-backed test asserts the new PK against any live schema before the cutover"
  - "Integration conftest gains _COMMITTED_BUT_UNAPPLIED = {465}: the test DB must mirror the live schema, and 190-06 removes the entry in the same breath as the live apply"

patterns-established:
  - "Committed-but-unapplied migration exclusion set in tests/integration/conftest.py (reusable for any future cutover-window migration)"

requirements-completed: [P190-migration, P190-ledger, P190-writers]

# Metrics
duration: 39min
completed: 2026-10-10
---

# Phase 190 Plan 02: Two-tier ledger migrations and provider-parameterized coverage writer Summary

**Migration 464 applied live (provider columns, drain-safe), migration 465 written and contract-tested but deliberately un-applied for the 190-06 cutover, and the coverage writer now labels every row with the fetching vendor's provider while keeping the old (symbol, timeframe) conflict target the running drain holds in memory**

## Performance

- **Duration:** 39 min
- **Started:** 2026-10-10T04:44:04Z
- **Completed:** 2026-10-10T05:23:00Z
- **Tasks:** 3
- **Files modified:** 10 (4 created, 6 modified)

## Accomplishments

- Migration 464 applied live against the running drain: ohlcv_coverage gained provider (NOT NULL DEFAULT 'ibkr' with the named CHECK) and ohlcv_provider_head gained a nullable timeframe; the pre- and post-apply dry runs are identical, proving additive-only
- Migration 465 committed UN-APPLIED with the cutover-window header: provider_head re-keys to (symbol, provider, timeframe) with the NULL-to-'1d' backfill and measured floor seeds; ohlcv_coverage re-keys to (symbol, timeframe, provider). Live PK verified unchanged at the end of the plan (the plan's own machine check)
- Coverage writer provider-parameterized end to end: CoverageDelta carries the fetching vendor's label, all four writer statements insert it, the rebuild reads per-provider filters and raises on an unknown provider, and the conflict target stays the old shape with the flip documented at both SQL constants
- Enforcement green: 12 new contract/boundary/persist cases plus the force-rolled-back post-flip integration case; full unit suite green (7441+ passed, pre-existing skips only)
- The live drain kept fetching through every commit boundary (ohlcv_request answers within a minute of the last commit)

## Task Commits

Each task was committed atomically:

1. **Task 1: parity-before dry run + migration 464 applied live** - `1b49aa69a` (feat)
2. **Task 2: migration 465 written un-applied + contract tests for both migrations** - `7fc7fd743` (feat)
3. **Task 3: provider-parameterized writer, CoverageDelta threading, rollback-fixture integration case** - `806c6b51b` (feat; includes pre-commit black formatting)

## Files Created/Modified
- `production/migrations/464_ohlcv_coverage_provider_dimension.sql` - additive provider columns, stored-state labeling rule in header and COMMENTs, VACUUM-rule N/A stated, no new APR keys
- `production/migrations/465_provider_history_two_tier_keys.sql` - breaking PK swaps + floor seeds, cutover-window header (42P10 rationale, NULL-timeframe labeling rule)
- `tests/unit/test_provider_history_migration_contract.py` - source-level, comment-stripped, apply-timing-independent contract tests for both migrations
- `services/ohlcv_coverage_writer.py` - provider parameter on all five write functions, provider in all four INSERT column lists, _REBUILD_FILTERS dict, wave-5 flip comments on both upserts
- `scripts/infrastructure/backfill/_intraday_persist.py` - docstring states the provider threading (the delta carries the label; the helper hands it through untouched)
- `tests/unit/test_ohlcv_coverage_writer_boundary.py` - single-writer fence plus the wave-1 conflict-target fence (every ON CONFLICT must stay (symbol, timeframe) until the cutover)
- `tests/unit/scripts/test_intraday_persist.py` - default ibkr label, non-default provider reaches the upsert, SQL-level provider parameter under the old target
- `tests/integration/test_ohlcv_coverage_atomic_write.py` - post-flip distinct-row case inside a force-rolled-back transaction
- `tests/integration/conftest.py` - _COMMITTED_BUT_UNAPPLIED = {465} keeps the test DB mirroring the live schema
- `.planning/phases/190-.../parity-before.tsv` - committed sanity reference (not the parity bar; 190-06 diffs a back-to-back pair)

## Decisions Made
- **The integration post-flip test simulates the full flip, not just the DDL.** With the new PK alone the writer's old-shape ON CONFLICT has no unique index (42P10), which is exactly the cutover hazard. The test therefore swaps both the PK (DDL) and the conflict target (monkeypatched _UPSERT_SQL) inside one transaction, asserts a second provider upserts a DISTINCT row, then raises to force the rollback. This proves the 465 shape under the flipped writer SQL, which is precisely what 190-06 deploys.
- **_intraday_persist.py threads the provider by handing the whole delta through.** The plan's text located CoverageDelta construction in _intraday_persist; it is actually built in _history_fetch_item.py (a live-drain file the plan deliberately does not list, and shared-checkout rules forbid touching beyond the plan). Since CoverageDelta now carries provider with the ibkr stored-state default and upsert_coverage reads it from the delta, the threading is complete without editing the item: the helper's docstring states this, and when 190-04 generalizes the items it sets the label where the delta is built. Recorded as a plan-reality note below.
- **parity-before.tsv is a sanity reference only** (review adjudication item 4): the phase's parity gate is 190-06's back-to-back old-vs-new dry-run pair against a quiescent DB.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Integration conftest would auto-apply un-applied migration 465 to the test DB**
- **Found during:** Task 3
- **Issue:** _replay_post_baseline_migrations replays every migration numbered above the 433 baseline, so the committed 465 would apply to indicagent_test on the next integration run. The test DB would then hold the new PK while the writer targets the old shape, failing every live-shape case (and diverging from production, where 465 is deliberately un-applied).
- **Fix:** _COMMITTED_BUT_UNAPPLIED = {465} exclusion set in tests/integration/conftest.py, with a comment that 190-06 removes the entry in the same breath as the live apply.
- **Files modified:** tests/integration/conftest.py
- **Committed in:** 806c6b51b

**2. [Plan-reality sync] CoverageDelta construction site is _history_fetch_item.py, not _intraday_persist.py**
- **Found during:** Task 3
- **Issue:** The plan's threading instruction located the CoverageDelta build in _intraday_persist.py (:222-228); it is built in scripts/infrastructure/backfill/_history_fetch_item.py:321, a live-drain file outside the plan's files_modified list.
- **Fix:** No fetcher-file edit (shared-checkout hard rule: nothing beyond the plan's listed files). The delta carries the provider field and upsert_coverage reads it from the delta, so threading is complete by construction; the helper's docstring documents where the label is set. 190-04 sets the non-default labels at the item when the fetcher generalizes.
- **Files modified:** none (documented in scripts/infrastructure/backfill/_intraday_persist.py's docstring)
- **Committed in:** 806c6b51b

---

**Total deviations:** 2 (1 blocking fix, 1 plan-reality sync). No scope creep; no live-drain file edited; the drain kept fetching through every boundary.

## Issues Encountered
- The integration post-flip case first committed instead of rolled back (psycopg commits a clean transaction exit); fixed by raising a sentinel exception after the in-transaction assertions so the 465 shape never outlives the test.
- The 464 contract test initially banned ADD CONSTRAINT outright; 464's named CHECK legitimately uses it, so the assertion now pins the exact constraint name instead.

## User Setup Required
None - migration 464 was applied live via psql; no external service configuration required.

## Next Phase Readiness
- 190-03 (per-provider planner) can read the per-provider tier contract: 465's key shapes are fixed and contract-tested; the floor seeds land at the cutover
- 190-06 owns exactly two synchronized actions, both now precisely specified in code comments and test fences: apply 465 (fetcher stopped) and flip the writer conflict target to (symbol, timeframe, provider), then update the boundary fence's ON CONFLICT assertions and remove the conftest 465 exclusion in the same commit
- The Alpaca leaf (todo 521) needs no writer change: CoverageDelta(provider="alpaca") plus a _REBUILD_FILTERS entry land with its lane; the boundary test forbids hand-writing the alpaca filter before then
- No edits touched the running drain's files (ibkr_history_fetcher.py, _history_fetch_item.py, _fetch_queue.py untouched)

## Self-Check: PASSED

All ten created/modified files exist on disk; all three task commits verified in git log (1b49aa69a, 7fc7fd743, 806c6b51b). Live schema verified post-execution: ohlcv_coverage has provider with PK (symbol, timeframe); ohlcv_provider_head has nullable timeframe with PK (symbol, provider).

---
*Phase: 190-provider-history-plane-unification-one-multi-provider-fetche*
*Completed: 2026-10-10*
