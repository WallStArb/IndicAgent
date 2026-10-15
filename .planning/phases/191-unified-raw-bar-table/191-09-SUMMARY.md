---
phase: 191-unified-raw-bar-table
plan: 09
subsystem: data-layer
tags: [ohlcv_raw, d7, bar-auditor, lineage, venue-head, cutover-window]
requires: [191-08, 191-10, 191-11]
provides: [D7 over raw, bar_auditor over raw, canonical_bar_lineage over raw, ohlcv_venue_head over raw, cutover window closed]
affects: [191-12, 191-16, 186-26]
tech-stack:
  added: []
  patterns: [value as of a time read back through the revision log, set join instead of a per-row probe into a compressed hypertable, baseline harness at a fixed now]
key-files:
  created:
    - production/migrations/491_canonical_bar_lineage_over_raw.sql
    - production/migrations/492_ohlcv_venue_head_over_raw.sql
    - .planning/phases/191-unified-raw-bar-table/191-09-D7-BASELINE-DIFF.json
  modified:
    - services/bar_reconciliation_audit.py
    - services/bar_auditor.py
    - tests/unit/services/test_bar_reconciliation_audit.py
    - tests/unit/services/test_bar_auditor_gaps.py
    - tests/unit/test_canonical_bar_lineage_view_migration_contract.py
    - tests/unit/test_ohlcv_observation_migration_contract.py
decisions:
  - "canonical_bar_lineage keeps raw-only lineage: a canonical bar whose value raw displaced to ohlcv_revision is lineage_missing (canonical behind a restatement is a real finding); revision rows carry request ids on only 7,560 of 3.9M 1d rows, so a fallback could not preserve null-ness anyway"
  - "D7's ADJUSTED_LAST pairing reads both series as raw held them when the latest run with both series ended (run end plus infra.selection_gate.request_load_match_s), back through the revision log by displacing-load time; same reading as plan 10's value-as-of-serve, without depending on revision request ids"
  - "bar_auditor plans gaps over IBKR's own raw rows for 5m too (the fetch planner's reads), not canonical 5m, which holds Alpaca sessions"
metrics:
  completed: 2026-10-15
---

# Phase 191 Plan 09: D7, the bar auditor and the lineage and venue-head views read ohlcv_raw

D7, the bar auditor, `canonical_bar_lineage` and `ohlcv_venue_head` no longer read
`ohlcv_observation` or `ohlcv_intraday_raw_archive`. Each change was compared against a baseline
taken on the old stores before any edit, every difference is explained, and the three held
units are cleared and resumed, which closes the cutover window.

## Tasks

| Task | Commit | Result |
|------|--------|--------|
| 1 lineage view (migration 491) | 1513a7d50 | 7,136,562 bars; 23,569 ids differ, each an earlier equal serve; 2,285 newly NULL, all canonical values raw displaced to the revision log |
| 2 venue head (migration 492) | 7ea18274c | 327 rows both ways; 10 differ only in smart_head_date (AES, BKNG), pre_move unchanged; n_bars lower on 109 rows |
| 3a bar_auditor | eccc76745 | 60 plan cells: 15m and 1h 40/40 equal; 7 of 20 5m cells differ (canonical 5m holds Alpaca sessions) |
| 3b D7 | e20808496 | baseline diff at two fixed nows, zero unexplained (191-09-D7-BASELINE-DIFF.json) |

## Balance checks

Lineage (Task 1). The old view's output was saved before 491 was applied and joined to the new
view per bar. Null-ness: old 0, new 2,285 (241 names). Every one of the 2,285 has a raw row at
the key whose value differs from canonical and an `ohlcv_revision` row holding canonical's
value: CTVA 1,848 (2019-05-24..2026-09-30), GYRE 132 (2015), and 1 to 4 sessions of about 240
names restated by IBKR re-serves of 2026-10-05..12. Canonical is behind raw there; the daily
stage owes the re-derivation. The count grows while the fetcher re-serves (2,315 visible at the
last harness run). Ids: 23,569 bars (49 names) carry a different request id, and for every one
the new id is an observation of the old store with the bar's exact value, answered no later
than the old id (raw keeps the request of the first serve of a value; 447 returned the latest).

Venue head (Task 2). Two-way EXCEPT over (symbol, route, first, last, smart head, pre_move):
10 rows each way, all AES and BKNG, whose SMART history was served back to 1999 on 2026-10-15,
after the observation store froze (2026-10-13 15:21 UTC). pre_move is unchanged on every row.
n_bars is lower on 109 rows and never higher: the observation store counted repeat serves of a
date. No reader uses n_bars.

D7 (Task 3). A harness ran every D7 loader whose reads change at a fixed now
(2026-10-15T21:00Z, and 2026-10-01T12:00Z where the old store still holds the judged sessions),
before any view change and again on the raw code. Results:

| check | old (findings/judged) | new | reason |
|-------|------|-----|--------|
| route_disagreement (10-01) | 0/144 | 0/144 | equal |
| adjusted_vs_trades (10-01) | 1/4,653 | 1/3,724 | same finding; the 2026-09-30 ADJUSTED_LAST bar was answered at 19:59 UTC, before its session closed; the raw reading leaves out a bar answered on its own date (D-191-J) |
| partial_daily (10-15) | 0/2,994 | 0/3,941 | raw holds the serves of 2026-10-13..15 |
| daily_vs_intraday (10-15) | 11/230 | 12/235 | AMD 2026-10-12 volume, re-served 2026-10-15 19:47 UTC (8,314,910 to 8,359,647) |
| late_heads | 25/94 | 27/94 | AES and BKNG: SMART history now reaches 1999, canonical starts 2000-01-03 |
| listing_venue_coverage | 19/58 | 19/58 | equal |
| grid parity reference (10 names) | | | archive rows equal raw ibkr named rows |
| vendor_agreement | | | n_both higher every year: 63 names hold 134,392 pre-2026 SMART rows served after the freeze |
| lineage_missing | 0 | 2,310 visible, 2 hidden | Task 1 |

## Deviations from plan

1. [Rule 1, performance] Migration 491 is a set join, not a LATERAL probe. The first version
   probed compressed raw per bar: 13 s for AAPL's 6,734 bars, about 4 hours for the view, which
   D7 reads whole. The join reads the view in 49 s (447 took 42 s). It was applied, measured,
   cancelled by PID and replaced in the same commit. `ibkr_venue` is not mapped: no canonical 1d
   row has that source and 447 returned NULL for it.
2. [Plan predates D-191-N] Null-ness is not identical (plan criterion). Under last-wins a
   canonical value raw has displaced has no current raw row, and revision rows carry request
   ids on only 7,560 of 3.9M 1d rows, so the new view cannot return the old id. The 2,285 are
   listed by class above; they clear when the daily stage applies.
3. [Plan predates D-191-N, plan 10 refinement] ADJUSTED_LAST pairing reads both series as raw held
   them when the run ended (last answer plus `infra.selection_gate.request_load_match_s`),
   back through the revision log by the displacing load's time. A first version reused
   `pair_d1_series`; it pairs by the run's own request ids, which last-wins moves to the first
   serve of an unchanged value, so ADJUSTED_LAST days a run re-served unchanged were lost.
   Tests: TRADES restated after the run (displaced value pairs, restated never), the run's own
   TRADES answer (pairs although restated later), TRADES unchanged while the name split later
   (pairs), whole-history asks and forming bars.
4. D7's late_heads reads the moved-name inventory (`ohlcv_venue_head`) for the first venue bar
   and the SMART head in one query, replacing a per-symbol SMART head query.
5. [Rule 2] bar_auditor's answered windows exclude a refused load's window, as the fetch planner
   does (third review of 191-07, finding 3), with the APR match window.
6. D7 was edited in a scratch worktree while the fetcher (which imports the module) ran; the
   fetcher timer was stopped, the run allowed to finish, the change copied in, tested and
   committed, and the timer restarted.
7. `tests/integration/test_ohlcv_observation_store.py` reads no lineage, so it is unchanged.
   `tests/integration/test_d2_single_writer_live.py` asserts no visible bar lacks lineage; it
   fails live until the daily stage applies (deviation 2).

## Window

The fetcher timer was stopped at 21:39 UTC, its run ended 22:52 UTC, the D7 change was committed
(e20808496) and the timer restarted 22:52 UTC. All three held units were cleared with
`191-09-D7-BASELINE-DIFF.json` and resumed 22:52:58 UTC: the D7 timer started (resume_action
start) and fired at once for the missed 06:00 run, so the first raw-based D7 run started
22:52:58 UTC; the D7 service and bar-auditor had resume_action none and stay inactive as before
the window. `logs/raw_cutover_window.json` holds no units: the window is closed. Held units
remaining: none.

## Canonical 1d

Canonical 1d ends at 2026-10-12 on 1,492 names; the latest complete session is 2026-10-15.
The daily stage last applied 2026-10-11 06:12 UTC; its 2026-10-15 18:31 UTC run derived 1,497
names (27,455 new rows) and failed whole on the GYRE refusal (revision ratio 0.0283 over 4,665
rows, todo 535 item 40), so nothing was written. Raw IBKR smart_trades holds 2026-10-13 and
2026-10-14 for 428 names so far (1d catch-up in progress).

## Verification

- Targeted: lineage and observation migration contracts, lineage boundary, single writer,
  rebuild preconditions, label_inputs, data_bar_check, listing_venue_writer, D7, auditor,
  auditor gaps: pass.
- `grep -nE "(FROM|JOIN|INTO|COPY)\s+(ohlcv_observation|ohlcv_intraday_raw_archive)" services/bar_reconciliation_audit.py services/bar_auditor.py`: empty.
- `pg_get_viewdef` of both views: no `ohlcv_observation`.
- Full unit suite (`.venv/bin/pytest tests/unit/ -q`) on main after the last code commit: passes.

## Known stubs

None.

## Self-check: PASSED

- Commits 1513a7d50, 7ea18274c, eccc76745 and e20808496 exist; migrations 491 and 492 and the
  baseline diff file exist; both migrations applied live.
- The first raw-based D7 run (started 22:52:58 UTC) was still running when this summary was
  committed, with no error logged; its verdict rows are the 186-26 gate refresh.
