---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 32
subsystem: corpus-rerun-data-gate
tags: [data-gate, apr, migration, market-calendar, survivorship, todo-593, todo-584]
requires: [186-30]
provides: [migration 579 (infra.corpus_rerun.* APR), services/corpus_rerun_apr.py load_corpus_rerun_apr, services/corpus_rerun_data_gate.py run_data_gate and DataGateResult, MarketCalendar.session_bounds]
affects: [186-31]
tech-stack:
  added: []
  patterns: [set-based fetch per (vendor, kind) streamed into per-(symbol, year, era) tallies, pure evaluate, one frozen APR snapshot per run]
key-files:
  created: [production/migrations/579_corpus_rerun_apr.sql, services/corpus_rerun_apr.py, services/corpus_rerun_data_gate.py, tests/unit/services/test_corpus_rerun_data_gate.py, tests/unit/test_corpus_rerun_apr_migration_contract.py, tests/unit/test_market_calendar.py]
  modified: [src/core/market_calendar.py]
decisions:
  - "All nine infra.corpus_rerun.* keys are read through one loader (services/corpus_rerun_apr.py), so the APR reader guard passes before 186-31 exists and every rerun step sees one snapshot"
  - "stored_bytes_per_spool_byte seeds at 0.37: 1379 over 3747 spool bytes of one fully populated row (feature_vectors is empty, so the row is synthetic; the contract test recomputes it)"
  - "Pre-calendar 1d sessions are counted from the start of each series, not from the proven start: every proven start is on or after 2000-01-03, so counting from it reports zero"
  - "A session's 5m bars are counted inside [open, close) only; Alpaca sip_rth rows include extended hours"
  - "Empty-history spans answer [verified_from, empty_through] (UTC dates), as the 1d verdict audit reads them"
requirements-completed: [D-19, D-35]
metrics:
  completed: 2026-11-05
  tasks: 2
---

# Phase 186 Plan 32: the corpus rerun data gate Summary

The 584 data gate is now a read-only measurement, `run_data_gate`. It checks every NYSE session
of every compute_1d name-year for a tradeable 1d bar and for 5m coverage from the era's policy
primary, and it returns a `DataGateResult` that 186-31's runner will persist to
`corpus_run.data_gate`. Migration 579 seeds the nine rerun APR keys and is applied live. No
compute was launched.

## Commits

- 9e7821ca6 feat(186-32): migration 579 seeds the corpus rerun APR, one loader reads it
- 161fec9c7 feat(186-32): the continuity data gate for the corpus rerun
- 055e2033d feat(186-32): answer-complete basis in the data gate (lead ruling 2026-11-05)

## Live dry run (2026-11-05, horizon 2026-11-01, read-only connection, 97 s)

The gate fails. It checked 1,502 names. 10 have no proven start (ACA, ACVA, BZH, CCO, CTVA, KVUE,
MSGS, PSKY, QRVO, WBD). No name has zero sessions, none has zero 1d sessions, and no name is
held. 13,785 name-years fail, across 1,392 names. 46,634 tradeable 1d sessions on 607 names
predate 2000-01-03.

Sessions by basis:

| era (5m pair) | sessions | bar-complete | answer-complete only | no_trades | empty-history | partial | missing |
|---|---|---|---|---|---|---|---|
| ibkr/named (before 2016-01-04) | 3,282,642 | 1,177,437 | 3,644 | 0 | 206 | 370 | 2,100,985 |
| alpaca/sip_rth (from 2016-01-04) | 3,664,325 | 3,102,647 | 1,498 | 0 | 0 | 547,938 | 12,242 |

Names and name-years:

| era | names | at depth (all bases) | at depth (bars alone) | partial | none | name-years failing |
|---|---|---|---|---|---|---|
| ibkr/named | 1,135 | 97 | 79 | 468 | 570 | 8,809 of 13,359 |
| alpaca/sip_rth | 1,492 | 848 | 848 | 644 | 0 | 4,976 of 14,993 |

"At depth" means a name's uncovered share in that era is within max_missing_session_fraction
(0.01). "None" means no session in the era is bar-complete or answer-complete.

Todo 534 counted 84 / 410 / 683 (at depth / partial / none) of 1,177 names. Its basis was the
earliest row against the 1d start. This gate's IBKR-era basis is continuity per session from the
proven start (1,135 names).

### The answer-complete basis (lead ruling 2026-11-05)

A thin session counts when it lies inside a completed vendor answer of the era's (vendor, kind).
On the live data:

- **ohlcv_load proves nothing for 5m.** On all 50,226 Alpaca 5m rows (the 521 campaign, the
  archive backfill and the nightly), requested_start equals first_bar and requested_end equals
  last_bar: the range is the span of the bars served, not the window asked. The campaign rows are
  10,000-bar chunks, which tile across any hole, and the campaign's request log
  (logs/alpaca_depth/) is not on disk. Alpaca 2016-01-04 to 2026-10-05 therefore stays
  bar-judged, and that span holds almost all of the 547,938 partial sessions. Note that
  gap_plan.LOAD_COVERAGE_* (read by the planner and the D7 audit) treats an applied Alpaca load as
  answering every slot of its range; this measurement contradicts that rule. Fixing it is out of
  this plan's scope (src/intelligence/bars/).
- **ohlcv_request pages are not completion records.** The Alpaca leaf writes one row per page,
  each claiming [resume point, window end]. Live example: AAOI on 2026-10-26, page 1 has 2,380
  bars and claims 10-06 to 10-26, and page 2 resumes at 10-22 22:50. A deadline stop after page 1
  would leave page 1 overclaiming. The gate proves a page up to the next page's start, and a
  window's last page only when its run asked again afterwards (the deadline stops every later
  request) and the window used fewer than infra.alpaca.nightly_max_requests pages. Pages with
  partial bars, failed or timeout prove nothing.
- Request evidence is the gap_plan.COVERAGE_EVIDENCE triples: IBKR SMART TRADES (2006 onward,
  625 names) and the Alpaca nightly's SIP 5Min (from 2026-10-06 only). The 1,498 Alpaca
  answer-complete sessions are October 2026. IBKR answers move 18 names to at depth.
- A zero-bar session counts only inside a no_data answer (no_trades). A bars answer with nothing
  stored could be a lost insert, so it stays missing.

## Deviations from plan

1. [Rule 3, blocking] Added `services/corpus_rerun_apr.py`, which is not in files_modified. The
   APR reader guard (tests/unit/test_table_and_apr_key_readers.py) fails any seeded key that has
   no reader, and 186-31 does not exist yet. One frozen loader now reads all nine keys, and 186-31
   imports it.
2. [Rule 1] Pre-calendar 1d sessions are counted from the start of each series rather than from
   the proven start. Every proven start is on or after the calendar's first session, so counting
   from the proven start reported 0 against the plan's 46,725 figure. 46,634 bars are counted
   today.
3. [Rule 1] 5m bars are counted only inside each session's [open, close). Alpaca sip_rth rows run
   from 09:00 to 23:55 UTC, so extended-hours bars would have made truncated sessions look
   covered.
4. `names_with_zero_1d_sessions` is reported as its own list instead of being folded into
   `names_with_zero_sessions`.
5. Per-era counts `names_at_depth`, `names_partial` and `names_none` were added so the result can
   be compared with todo 534's figures.
6. Per the lead ruling, the answer-complete basis was added after the first push (055e2033d). Field covered_5m was renamed bar_complete; answer_complete, no_trades and names_at_depth_by_bars were added.
7. The plan names no integration tests. The SQL is exercised by the live dry run, and the unit
   tests replace the fetch layer with fixture fakes and use the real calendar.
8. Reviews: AGY is out of quota (163 h) and so is Codex, so neither could run. The /review pass
   was my own and found two issues, both fixed: the survivorship caveat counted refused or held
   names, and an empty-history test was too weak to catch a double count (verified by mutation).
9. Test-first order was not kept for Task 2. The module was written before its tests, and two
   mutations confirmed the tests detect the intended defects.

## Notes

- primary_pair for an IBKR primary inside the Alpaca era yields (ibkr, fallback). Live IBKR 5m
  rows in that era are stored as (ibkr, named), but no 5m symbol policy row exists today, so
  no name resolves to that pair.
- tools/gate.py: the unit suite passed on the first run. The rerun after review fixes failed
  only on two tests owned by the concurrent todo 594/595 worker (the scrub-input allow-list and
  todo 595's PRIORITIES row). The targeted tests for this plan pass.
- The result record is about 1.4 MB of JSON with the full failing name-year list.

## Self-Check: PASSED

All created files exist on main; commits 9e7821ca6 and 161fec9c7 are on origin/main; migration
579 reads back through ConfigService live.
