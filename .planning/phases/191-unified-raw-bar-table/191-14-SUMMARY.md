---
phase: 191-unified-raw-bar-table
plan: 14
subsystem: database
tags: [timescaledb, migration, vendor-kind, table-swap, views, systemd]

requires:
  - phase: 191-unified-raw-bar-table
    provides: "plan 12's proven market_data_ohlcv_v2 rebuild (461,198,119 rows, migration 496) and plan 13's basis corrections (migrations 494/495)"
provides:
  - "market_data_ohlcv swapped to the vendor/kind table in one transaction (migration 497); the label-column table kept as market_data_ohlcv_old"
  - "The four dependent views recreated over vendor and kind: tradeable (volume nulled by kind), scrub_input, market_data_5m, canonical_bar_lineage"
  - "Compression policy moved to the new table name (30 days, 12h schedule); the old table's job unscheduled"
  - "--swap / --post-check / --rollback wired in ops_canonical_vendor_kind_swap.py with the L4 fresh-prove-in-code gate and the API hold (todo 535 items 43-44)"
  - "Integration harness replay unblocked: migrations 485/488/497 replay-safe, instruments seed regenerated (fixes a breakage dating to 191-07)"
affects: [191-17, bar-derivation, nightly-backfill, api, ic-measure, research-s0]

tech-stack:
  added: []
  patterns:
    - "Swap-in-place: literal RENAME pair at the top of the migration so _migration_catalog resolves final names in file order"
    - "L4 prove gate in code: the swap refuses unless the prove record postdates the last build with clean result and equal per-timeframe counts"
    - "Replay-tolerant migration assertions: live-data checks accept the harness baseline's zero-footprint case with a comment naming both accepted counts"

key-files:
  created:
    - production/migrations/497_market_data_ohlcv_vendor_kind_views.sql
    - tests/unit/scripts/test_canonical_vendor_kind_swap.py
    - tests/integration/fixtures/seed_instruments_2026-10-16.sql
  modified:
    - scripts/ops/bars/ops_canonical_vendor_kind_swap.py
    - tests/unit/test_vendor_kind_swap_migration_contract.py
    - tests/unit/test_single_writer_registry.py
    - tests/unit/test_table_and_apr_key_readers.py
    - tests/unit/test_backfill_status_retirement_migration_contract.py
    - tests/integration/test_derived_grid_live.py
    - tests/integration/test_d2_single_writer_live.py
    - tests/integration/conftest.py
    - production/migrations/485_last_wins_by_serve_time_and_basis_review.sql
    - production/migrations/488_delete_ibkr_4h_raw.sql

key-decisions:
  - "Swap executed as one transaction: ACCESS EXCLUSIVE on both tables under lock_timeout 30s, write-counter stability checked before and inside the lock, migration 497 executed as a single unit, api stopped before and restarted after the post-check"
  - "The prove must be fresh in code since the last build (todo 535 item 43): prove_blockers() refuses the swap on a missing, unclean, stale or drifted prove record"
  - "Both failed-state units were resumed and re-failed on byte-identical pre-existing causes (dividend writer: PSKY/WBD/QRVO/CCO data conditions; fetcher: gateway lost mid-run); neither is a swap regression, both retried on their timers and wrote data before failing"
  - "The two live integration failures are pre-existing data drift, proven by re-running the pre-191-14 queries against market_data_ohlcv_old: logged to deferred-items.md rather than fixed"

patterns-established:
  - "Capture-then-recreate rollback: pre-swap view definitions, comments, grants and policy rows are captured in the swap report so --rollback can restore them without the migration file"

metrics:
  duration: "about 11 h across two sessions (429 rate-limit kill in between; prove re-verified clean after)"
  completed: 2026-10-17

---

# Phase 191 Plan 14: canonical table swap to vendor and kind summary

The proven market_data_ohlcv_v2 rebuild took the name market_data_ohlcv in one 12.2-second
transaction (swap committed 2026-10-17T00:25:12.765401Z), the four dependent views were
recreated over vendor and kind with volume nulling by kind, and every write and read lane was
verified against the swapped table before the ten held units resumed.

## What was done

1. Contract tests first (950ccebf2): literal rename order, four DROP+CREATE view pairs, kind
   based volume nulling, combined grant, policy move, no ohlcv_venue_head touch, catalog final
   names; plus seven pure tests of the L4 prove gate.
2. Migration 497 and the --swap/--post-check/--rollback modes (a956b1dd2); the alter_job
   job_id type fixed to integer after a BEGIN/ROLLBACK wrap validation caught the signature
   failure server-side (ec2677afd).
3. Fresh prove in code (L4 gate): 461,198,119 rows both sides, per-timeframe equal, gate
   clean, completed 2026-10-16T14:54:22Z, recorded in logs/vendor_kind_swap_state.json.
4. The swap: preflight ready, api stopped by the script, lock acquired on both tables,
   counters stable, migration executed inside the transaction, committed 00:25:12Z, locked
   section 12.2 s. Report: logs/vendor_kind_swap_191_14.json.
5. Post-check result "verified": tradeable per-timeframe counts equal to pre-swap and to the
   old table's views; zero venue/fallback volume rows; S0 SPY read identical from 2000-01-03;
   plan 07 selection gate clean on the swapped table (12 series, 0 real differences, 0 digest
   mismatches); plan 08 d2 equivalence exit 0 on six names; venue_head unchanged (327); api
   restarted and healthy. Report: logs/vendor_kind_swap_post_check_191_14.json.
6. Bare VACUUM market_data_ohlcv: exit 0, under 10 s (the rebuilt table's visibility maps
   were already clean).
7. All ten held units cleared with the post-check as evidence and resumed through the window
   script; fetcher plan gate passed (191-06/08/10 summaries on disk).
8. First fetcher tick: 88 items, 87 ok, 20,324 bars, gateway lost at BOW/1d after the work
   (same class as its pre-window failure at ARE/1d). First bar_derivation run: success, 87
   symbols, 1,988 new rows, 18 changed, 384,347 unchanged, 0 refused, 0 failed, writing
   through the recreated views and the bar_derivation_writer grant.
9. Full unit suite green (2 pre-existing intentional skips). Integration harness replay
   unblocked (see deviations); both live integration files then ran their bodies.
10. repro_frozen: bit-identical (see Verification).

## Verification

- Swap state on disk: market_data_ohlcv carries vendor, kind, base, price_sanity_status (no
  source); market_data_ohlcv_old exists with the pre-swap shape; compression job active on
  the new name, unscheduled on the old.
- API: restarted by post-check, /health healthy, /api/market-data/SPY/1d serves vendor and
  kind, values equal to pre-swap facts.
- repro_frozen: bit-identical on every recorded phase (run after the swap against the
  recreated tradeable view).
- tests/unit/: 0 failed. Targeted guard tests for every modified contract: green.
- Integration: fixture replay now reaches 497 cleanly; the two live-data failures that remain
  are documented in deferred-items.md and proven pre-existing.

## Deviations from plan

### Auto-fixed issues

**1. [Rule 1 - Bug] alter_job takes an integer job id**
- Found during: BEGIN/ROLLBACK wrap validation of migration 497
- Issue: `outgoing_job bigint` broke named-notation resolution (TimescaleDB 2.27.1 exposes
  alter_job(integer, ...)); the DO block failed server-side
- Fix: declared `outgoing_job integer`; re-validated the full wrap clean
- Commit: ec2677afd

**2. [Rule 3 - Blocking] migration 459 retirement contract vs market_data_ohlcv_old**
- Found during: guard test updates
- Issue: market_data_ohlcv_old is a name migration 459 dropped; two tests failed
- Fix: _REUSED_BY_191_14 exemption in test_backfill_status_retirement_migration_contract.py
  with a comment; single-writer registry entry moved from v2 to old
- Commit: a956b1dd2

**3. [Rule 3 - Blocking] stale pending-retirement entry for market_data_ohlcv_v2**
- Found during: full unit suite
- Issue: the allow-list expiry rule requires removing a pending entry whose name no longer
  exists in the catalog
- Fix: removed it; added the five infra.canonical_swap.* APR keys and market_data_ohlcv_old
  with retire: 191-17 so plan 17's obligation is preserved
- Commit: a956b1dd2

**4. [Rule 3 - Blocking] integration harness replay broken since 191-07**
- Found during: the plan's integration verification step
- Issue: migration 485's assertion (exactly 80 superseded offers) cannot hold in a replay
  from the 2026-10-02 baseline, which carries no ohlcv_revision rows; 488's 4h footprint
  check likewise; 494/495 hit instrument FKs for names the seed snapshot lacked; 497's
  policy move would fail on a baseline with no compression policies. Every integration run
  since 191-07 died at 485 before any test body.
- Fix: 485 and 488 assertions accept the zero-footprint replay case (both accepted counts
  documented in-file); 497 skips the policy move when the outgoing table has no policy job;
  instruments seed regenerated from production (954 to 1,551 rows, dated snapshot
  convention); conftest repointed
- Commits: e15fb5108

**5. [Rule 3 - Blocking] stale docstring in the swap script**
- Issue: the module docstring said plan 17 runs the post-swap VACUUM; plan 14 runs it
- Fix: one line corrected
- Commit: e15fb5108

### Out of scope (logged to deferred-items.md)

- 16 bars dated 2026-10-08 plus scattered singles where raw holds a volume-plus-or-minus-one
  re-serve newer than canonical (identical in market_data_ohlcv_old; the lineage test's
  equality join then finds no match). Expected to close when the nightly canonical refresh
  lane runs again.
- Derived 1h volume deficit vs ibkr 1d observations for CTVA, ETHA, MDGL (worst median 2.0);
  the pre-191-14 query against the old table flags the same three names.

## Authentication gates

None.

## Known stubs

None.

## TDD gate compliance

RED (950ccebf2, failing contract tests) then GREEN (a956b1dd2) then fixes ec2677afd and
e15fb5108; sequence present in git log.

## Self-check: PASSED

All created files exist on disk; all four commits (950ccebf2, a956b1dd2, ec2677afd,
e15fb5108) present in git log.

## Deviation 2: window record archived post-run (main session, 2026-10-17 ~02:35Z)

The executor resumed all ten units individually but the record file outlived the window
(`status` still printed `window opened`, holding the IBKR 1d deepening gate past the swap).
The script has no close verb (known gap, 191-12-REVIEW L45); the 191-12 precedent treats the
record as a log. Archived to `logs/raw_cutover_window.closed_191_14.json` after verifying
all units healthy (api active, fetcher timer active, catch-up run in flight); `status` now
exits 1 with no record, and the deepening gate's 02:41Z tick proceeds past the window check.
