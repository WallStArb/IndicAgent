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
- (branch 186-32-ask-view, merged after migration 581 lands) review fixes: complete asks only, real-SQL integration test

## Live dry run (2026-11-05 evening, horizon 2026-11-01, read-only, 90 s)

On the ask rule (below) with no 581 asks recorded yet, the answer-complete basis contributes
nothing, so this is the bar-judged gate. The run used an empty temporary `ohlcv_ask_current`,
because 581 is not live yet. The gate fails. It checked 1,502 names. 10 have no proven start
(ACA, ACVA, BZH, CCO, CTVA, KVUE, MSGS, PSKY, QRVO, WBD), and none is held. 13,934 name-years
fail, across 1,396 names. 46,634 tradeable 1d sessions on 607 names predate 2000-01-03.

| era (5m pair) | sessions | bar-complete | answer-complete | no_trades | empty-history | partial | missing |
|---|---|---|---|---|---|---|---|
| ibkr/named (before 2016-01-04) | 3,282,642 | 1,180,944 | 0 | 0 | 206 | 4,014 | 2,097,478 |
| alpaca/sip_rth (from 2016-01-04) | 3,664,325 | 3,102,647 | 0 | 0 | 0 | 549,436 | 12,242 |

| era | names | at depth | partial | none | name-years failing |
|---|---|---|---|---|---|
| ibkr/named | 1,135 | 79 | 486 | 570 | 8,956 of 13,359 |
| alpaca/sip_rth | 1,492 | 848 | 641 | 3 | 4,978 of 14,993 |

The two earlier answer rules were withdrawn after review:

- The pre-review page rule cleared 3,644 IBKR and 1,498 Alpaca sessions and moved 18 names to at
  depth. It is withdrawn because those passes were false.
- The interim review-fix rule (only intermediate pages count, and the bars must be in raw) cleared
  163 IBKR sessions and 0 Alpaca sessions.

Todo 534 counted 84 / 410 / 683 (at depth / partial / none) of 1,177 names, measured from the
earliest row against the 1d start. This gate measures continuity per session from the proven start.

### Answer-complete basis: complete asks only (lead rulings 2026-11-05)

A session also counts as covered when it lies inside a complete ask of the era's coverage
evidence, read from `ohlcv_ask_current`. That view comes from migration 581, which the todo 596
worker owns. An ask is complete when it has a terminal page, its pages are gap-free and no page
failed or timed out. Each page's request row commits together with its bars, so a page row also
proves its bars were stored.

- The gate counts an ask only if it is complete and `has_partial` is false.
- Legacy request rows (no ask_id) are not in the view, so they never count. That covers every
  row written before 581 and every unpaginated IBKR request.
- A session with bars inside such an ask is answer-complete. A session with zero bars counts only
  inside an ask that served no bars; it is reported as no_trades.
- Withdrawn by the review: request pages without asks. A failed Alpaca page writes no row, so
  the page before it looks like the last page. A request row also does not prove its bars were
  stored (dry runs; loads that failed after the fetch, e.g. PSKY, WBD and QRVO on 2026-10-26).
- ohlcv_load never proves completeness. On all 50,226 Alpaca 5m rows, the requested range equals
  the span of the bars served.

### Notes for the lead and 186-31

- Bar-complete counts IBKR volume-0 raw bars as served slots. IBKR serves a bar with volume 0
  for a no-trade slot, so these are its own "no trades" answers, consistent with the no-trade
  ruling. The independent review measured 19,702 sessions on 185 names in 2014 that depend on
  this.
- Two jobs belong to 186-31's runner, not this pure module: writing corpus_run.data_gate and the
  caveat in one transaction, and deduping the caveat on its `code` (caveats are append-only).

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
