---
phase: 185-daily-data-foundation
plan: 24
subsystem: bars / reference data
tags: [D6, D-25, D-03, listing-venue, D7, docs, todo-close-out]
requires: [185-19, 185-23, 185-25, 185-26]
provides: [listing_venue table, services/listing_venue_writer.py, D7 listing_venue_coverage check, phase 185 glossary and registry entries]
affects: [bar_reconciliation_audit, glossary, canonical-truth-registry, instrument-onboarding-sop, operations-database, todos 052/155/347/433/446/495]
tech-stack:
  added: []
  patterns: [point-in-time spans with EXCLUDE no-overlap, reconstructed-history append-only trigger, pure inference plus append-only reconcile plan]
key-files:
  created:
    - production/migrations/408_listing_venue.sql
    - services/listing_venue_writer.py
    - tests/unit/services/test_listing_venue_writer.py
    - tests/unit/test_listing_venue_migration_contract.py
  modified:
    - services/bar_reconciliation_audit.py
    - tests/unit/services/test_bar_reconciliation_audit.py
    - docs/foundation/glossary.md
    - docs/foundation/canonical-truth-registry.md
    - docs/foundation/instrument-onboarding-sop.md
    - docs/operations/operations-database.md
    - .planning/todos/PRIORITIES.md
    - .planning/todos/pending/433-ibkr-daily-history-truncated-at-primary-listing-venue-change.md
    - tools/glossary_baseline.json
decisions:
  - "Former listing venue chosen by nearest-to-official-close wins first, volume second (not volume alone): measured on the moved names, max venue volume hands most post-2008 ranges to BATS, which listed none of them"
  - "Ranges split only where a venue route stops answering; a route that starts later (BATS on 2008-10-17) is a venue coming into existence, not a move"
  - "Venue codes are IBKR primary-exchange codes (route ISLAND stored as NASDAQ), so listing_venue joins ohlcv_request.primary_exchange directly"
  - "A former venue equal to the current primary is not recorded as a move; D7 reports such a name instead of the writer inventing a closed span"
  - "listing_venue_writer is a manual oneshot (not chained into the nightly); D7's coverage check is the forcing function"
metrics:
  completed: 2026-10-06
  tasks: 2
  files: 13
---

# Phase 185 plan 24: D6 listing venue, docs and todo close-out summary

`listing_venue` (migration 408) now holds a point-in-time listing venue for all 931 1d-eligible
names (974 spans, every one of the 39 moved names with a closed former-venue span), written by
`services/listing_venue_writer.py` and watched by a new D7 check; the glossary, ownership
registry, onboarding SOP and operations runbook describe the phase 185 data layer; four folded
todos are closed and 433 is narrowed to its intraday half.

## Tasks

| Task | Name | Commit |
|------|------|--------|
| 1 RED | Failing tests: migration contract, inference, reconcile, D7 coverage | eb8531304 |
| 1 | Migration 408 (applied live, committed in the same step) | 716d30b4b |
| 1 GREEN | Writer, D7 check, live run | 3110c9263 |
| 2 | Glossary, registry, SOP, operations doc, todos, PRIORITIES | 7782e950f |

Migration number: 408 was free (`ls production/migrations | grep '^408_'` empty immediately before
`psql -f`); used as reserved.

## Live run (2026-10-06)

- Migration 408 applied; guards smoke-tested in a rolled-back transaction: overlap refused by the
  EXCLUDE, closed span immutable, venue UPDATE denied by the column grant, DELETE and TRUNCATE
  refused by the trigger (superuser included).
- Writer dry run, then `--apply`: batch `9556cb82-56d3-4c2b-9be2-953eb92baa4d` (stage
  `listing_venue`, completed), 892 names written with one open span, 39 moved names written with
  closed former spans, 0 conflicts, 0 names without observations. A second dry run reports 931
  unchanged (idempotent). The batch's `code_commit` carries `-dirty` (the writer ran before its
  commit; the code is identical to 3110c9263 apart from formatting).
- Acceptance: `select count(distinct symbol) from listing_venue` = 931 = 1d-eligible names with a
  D1 observation (931 of 931). Every moved 1d name in the inventory has a closed span (43 closed
  spans over 39 names: IEI and SHY carry two former spans, TLT three).
- D7 audit run once (49.6 s, exit 0): `listing_venue_coverage` 0 findings, 39 judged. Facts were
  not re-emitted: the 2026-10-05 session's facts already existed from the 06:00 UTC run. Other
  checks match the 185-23 summary's readings (stray_sources 27,317 and completeness 699 are the
  known pre-cutover 15m/1h names and the paused 5m lane).

Spans the inference marks `contested` in evidence (nearest-close winner differs from the
max-volume venue): MAR, MATX, SVRA, TLT (the 2007-08-17 to 08-31 AMEX slice), UAL, USAU, WDC.
Known wrong by domain knowledge: MAR (BATS, NYSE in fact) and WDC (ARCA, NYSE in fact); names whose
real listing route never answered in D1 (AZTA, C, JCI, SCHW, RIOT, USAU, MATX) necessarily get a
non-listing venue. Rows are permanent by design; correcting them needs a supersede mechanism
this plan did not build (see open items).

## Deviations from plan

1. [Rule 1 - Bug] Inference rule. The plan specified "max-volume venue per date range". Measured
   on the 45 moved names, venue-only volume gives BATS the 2008-onward range of AMD, ADI, CSX,
   HAS, MU, SLM, TXN and VTRS (all NYSE-listed then) because BATS printed more volume than the
   listing venue after it became an exchange. The rule now ranks routes by how often their close
   is the nearest to the official (Tradier) close, after dividing out each route's median ratio
   (handles series stored on another split scale, e.g. IBB at 1/3), with volume as the fallback
   and tie-break; and splits ranges only where a route stops answering. `infer_listing_spans`
   therefore takes `venue_bars` (close and volume per day) and `official_close` keyword arguments
   instead of volumes alone; the positional contract is unchanged.
2. [Rule 1 - Bug] D1 rows written by tests (`caller` `test-185-02`, SPY, primary_exchange NYSE)
   made SPY's latest SMART primary exchange NYSE. The writer's first-bar, SMART-head and primary
   reads exclude `caller LIKE 'test-%'`, and so does the audit's `route_disagreement` listing read
   (same bug, same file touched; todo 494's pollution).
3. [Rule 2] Evidence carries per-route scores, the max-volume venue and a `contested` flag, so
   a misattributed span is visible without rerunning the inference (T-185-24-02).
4. `ohlcv_venue_head` lists the `TRADIER` route as a venue (its definition predates migration
   438); the writer and the D7 check filter routes to `infra.ibkr.venue_fallback.exchanges`. The
   view itself is unchanged and documented in the operations doc.
5. The pre-commit glossary hook rewrote `tools/glossary_baseline.json` for todo 052's move and the
   commit carried it (expected; the path changed from pending/ to completed/).
6. Glossary also marks `synthetic fill` retired (185-25 left zero rows), a factual status fix.

## Handoff notes (from .continue-here.md)

- Integration baseline (todo 495): migrations 404 to 408 sit below the integration cutoff 433,
  so `indicagent_test` lacks their effects, now including `listing_venue`. 185-24 has landed, so
  the baseline and seeds should be regenerated (todo 486's method) and the cutoff raised; not done
  here. PRIORITIES row updated to say it is ready.
- Derived-timeframe empty rows are SMART-only: venue fallback is 1d-only (437), the 5m
  empty-history rows were deleted and re-record SMART-only, and the 15m/1h rows are kept and
  re-written from SMART's answer. Recorded in todo 433's status note.
- Todo 490 (nightly grid stage fails for A, AAP, ABBV, ACRS, ACVA, ADBE, ADP on the archive verify
  of twice-observed bars): still open, decision (archive observation history vs settle window)
  not taken here; it is due before 189-04. The nightly timer is inactive since 2026-10-02, so it
  has not failed again since.
- Todo 497: 186-27 sets `infra.bar_derivation.intraday_recovery_unlocked` and
  `rebuild_state_table`; todo 433 stays pending on it for intraday recovery.

## Known stubs

None.

## Threat flags

None beyond the plan's register: one new table with writer-role grants and a trigger, no network
surface.

## Open items for phase 185 completion

- Phase verification (`/gsd-verify-work 185`) and UAT have not run.
- Todo 495 baseline regen (integration DB lacks 404-408).
- Todo 490 decision before 189-04.
- `listing_venue` has no supersede path: a better inference cannot correct the MAR/WDC rows
  without a migration (a `supersedes` column, the `corporate_action` pattern). Worth a todo if
  any reader starts to depend on former venues.
- The listing venue writer is manual; names promoted later get rows only when someone reruns it
  (D7 flags moved names without a closed span, not unmoved names without rows).
- 9 IBKR-sourced moved 1d names (CSX, LDOS, MATX, MPB, NEXT, PEP, RIOT, RSPR, SVRA) keep
  SMART-only history; D7 `late_heads` reports them nightly.

## Gate

- `tests/unit/services`, `test_market_data_ohlcv_boundary.py`, `test_market_data_ohlcv_writer_boundary.py`,
  `test_migration_number_uniqueness.py`, `test_listing_venue_migration_contract.py`,
  `test_todo_priorities_link_integrity.py`, `test_service_base_class_compliance.py`: 1,154 passed.
- ruff and black clean on every touched Python file. No em dash in any added or removed doc line.
- The running HTF lane does not import any touched module (checked: loading
  `infrastructure_run_historical_pipeline.py` leaves `services.bar_reconciliation_audit` and
  `services.listing_venue_writer` out of `sys.modules`).

## Self-Check: PASSED

- Files exist: 408_listing_venue.sql, listing_venue_writer.py, both test files, this summary.
- Commits exist: eb8531304, 716d30b4b, 3110c9263, 7782e950f.
