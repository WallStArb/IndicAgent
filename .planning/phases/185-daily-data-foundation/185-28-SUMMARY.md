---
phase: 185-daily-data-foundation
plan: 28
subsystem: bars / D1 head classification, empty history, venue inventory
tags: [D-16, D-20, D-27, D-28, ohlcv_venue_head, ohlcv_empty_history, late_names, gap_closure]
requires: [185-24, 185-27]
provides: [IBKR-only ohlcv_venue_head (migration 442), IBKR-only late-name classification, classify_head aligned with the empty-history reconcile rule, 0 contradicted 1d empty-history rows]
affects: [ops_data_bar_check condition 3 (shares classify_head and _load_requests), label_inputs, listing_venue_writer, bar_reconciliation_audit (view readers, unchanged)]
tech-stack:
  added: []
  patterns: ["classify_head judges a head by the same D-20 rule reconcile_empty_history confirms spans by: SMART plus every non-primary venue, a SMART full-depth bars answer counting as the head's answer"]
key-files:
  created:
    - production/migrations/442_ohlcv_venue_head_excludes_tradier.sql
  modified:
    - scripts/ops/bars/ops_head_rerun.py
    - tests/unit/scripts/test_head_rerun.py
decisions:
  - "Late-name requests are filtered on ohlcv_request.source = 'ibkr' in Python at load (route TRADIER named in the comment and guard), so the rule is testable with fakes and covers any future non-IBKR source."
  - "classify_head no longer requires the primary venue's answer: the provider never asks it (SMART routes there) and reconcile_empty_history does not require it. Before this, verified_empty was unreachable (0 of 410 names)."
  - "A SMART bars answer for the oldest window counts as SMART's answer when its first bar is at or after the stored head (the reconcile's implied-span rule); a first bar before the stored head (zero-volume prints the tradeable view hides) leaves the name unresolved."
  - "The re-ask asked only the 3 of the orchestrator's 7 names still unresolved after the two classify_head fixes (IDR, SGHC, UUUU); BLBD, FRHC, KN, OGS resolve verified_empty from their stored answers."
metrics:
  duration: 75min
  completed: 2026-10-07
  tasks: 2
  files: 3
---

# Phase 185 plan 28: IBKR-only venue inventory, late-name classification and the 6 empty-history rows

`ohlcv_venue_head` and the late-name classification now read IBKR routes only, the 6 contradicted 1d empty-history rows are gone, and `classify_head` judges a head by the same rule the empty-history reconcile uses. Of the plan's 7 IBKR-sourced late names, 4 resolve (verified_empty) and 3 stay unresolved (IDR, SGHC, UUUU: ISLAND answered `failed` for the head window). Removing TRADIER also exposed 9 more unresolved IBKR-sourced names and 13 more Tradier-owned ones (DAL was already one), so D-28 condition 3 is still red. The residue is listed below.

## Task 1: view, load filter, reconcile

- Migration 442 is `CREATE OR REPLACE VIEW ohlcv_venue_head` with `route <> 'TRADIER'` added. It keeps the same 7 columns in the same order (symbol, route, first_bar_date, last_bar_date, n_bars, smart_head_date, pre_move). 442 was free on disk right before `psql -f`, and the migration was applied live and committed together (b89718168).
- `_load_requests` now selects `source` and `primary_exchange` and drops every non-`ibkr` source and route TRADIER. `_moved_detail` reads IBKR venue routes only.
- Reconcile: `reconcile_empty_history(conn, '1d', 'ibkr', symbols=[CYRX, IBEX, KURA, MARA, ODFL, POWI])` ran once on an autocommit psycopg connection and returned `{'kept': 0, 'deleted': 6, 'inserted': 0, 'extended': 0}`. This deletes IBKR-provider empty-history facts because stored Tradier bars sit inside their spans (`_confirmed_spans` drops a span holding a stored bar). That is acceptable: the spans are derived facts, rebuildable from the IBKR answers kept in D1. `_empty_history.py` was not edited.

| Measure | Before | After |
|---|---|---|
| `ohlcv_venue_head` rows with route TRADIER | 1,529 (492 pre_move) | 0 |
| `ohlcv_venue_head` rows (all) | 1,828 | 299 (119 pre_move on 45 names, the IBKR part, unchanged) |
| View columns | 7 | 7 (same list) |
| 1d `ohlcv_empty_history` rows for the 6 names | 6 | 0 |
| 1d `ohlcv_empty_history` rows (all) | 111 | 105 |
| D7 `unconfirmed_empty` for 1d (computed read-only with the auditor's own SQL and `check_unconfirmed_empty`) | 6 (CYRX, IBEX, KURA, MARA, ODFL, POWI) | 0 |

## Task 2: late names

### Dispositions (410 late names, `--report-only`)

| Disposition | Plan start (TRADIER counted) | After the load filter, both classify_head fixes and the re-ask |
|---|---|---|
| moved | 320 | 27 |
| reached_window_start | 72 | 316 |
| verified_empty | 0 | 41 |
| unresolved | 18 (17 IBKR-sourced + DAL) | 26 (12 IBKR-sourced + 14 Tradier-owned) |

Most of the 320 "moved" names counted as moved only because of their TRADIER answer. Under IBKR answers they are reached_window_start.

Unresolved IBKR-sourced names, step by step:

1. With TRADIER counted: 17.
2. Excluding TRADIER only: 53. The classification had two defects that the TRADIER answers had been hiding (see deviations).
3. After the primary-venue fix: 35.
4. After the SMART-bars fix: 12.
5. After the re-ask: still 12.

### The re-ask

- Preconditions: 185-27 was committed (cf7676d47). There were no `lease:` or `lock:` sessions in `pg_stat_activity`. `indicagent-ibkr-history-fetcher.service` was inactive and its timer was not listed. The gateway was authed ("Login has completed" 2026-10-06 23:59 UTC), and no pipeline process was running.
- A scratch harness (not committed, like 185-30's) did the following:
  - ran the campaign preflight for client 49
  - held `FetcherLock` (holder `ops-185-28-reask:49`)
  - probed client 41: ping True, SPY qualified, head 1993-01-29
  - called `ops_head_rerun._run_chunk(["IDR", "SGHC", "UUUU"])`, which is the script's own pipeline invocation: client 49, `--lease-tier priority`, 1d, `compute_1d`
- The pipeline took and released `ibkr_history_stream` itself. The fetcher service and timer were not touched. DAL was not passed.
- Fetch run `a281ca38-6ad4-4336-bbdf-9bf0ace959a2` made 5 requests, all SMART, with 0 fetch errors and 414 observations:
  - IDR: 2011-02-22 to 2013-09-27, bars, 405 observations
  - UUUU: 2013-12-03 to 2013-12-04, no_data
  - IDR, SGHC, UUUU: the 2026-10-05 to 2026-10-07 tail, 3 observations each
- The chained D2 daily stage, batch `4fe85b6a-311e-4e5a-9cd2-831907e9a804`, completed with derived 3 and 8 changed bars, all `missing` (new sessions) and 0 value changes.
- No venue was asked. The re-ask cannot re-ask these heads through this path: the 1d gap planner (`_d1_gaps.detect_gaps_1d_from_d1`, 185-18) counts SMART's `no_data` window, or SMART bars from the head on, as coverage. The head is therefore never a gap, and the provider's venue fallback fires only inside a SMART walk that starts late. The dispositions of IDR, SGHC and UUUU did not change.

### Residue: unresolved IBKR-sourced late names (condition 3 stays red)

Each row shows the latest answer per required route for the oldest SMART window.

| Name | SMART head | Oldest SMART window | Primary | Latest answers | Why unresolved / next action |
|---|---|---|---|---|---|
| IDR | 2011-02-24 | 2008-01-03 to 2011-02-22 | AMEX | SMART bars, NYSE no_data, ARCA no_data, ISLAND failed, BATS no_data | ISLAND `failed` (no error code, 4 of 4 attempts) |
| SGHC | 2020-11-23 | 2006-10-05 to 2020-11-20 | NYSE | SMART no_data, ARCA no_data, ISLAND failed, AMEX no_data, BATS no_data | ISLAND `failed` (4 of 4) |
| UUUU | 2013-12-04 | 2006-10-05 to 2013-12-03 | AMEX | SMART no_data, NYSE no_data, ARCA no_data, ISLAND failed, BATS no_data | ISLAND `failed` (4 of 4) |
| BMNR | 2012-04-19 | 2006-10-09 to 2020-12-19 | NYSE | SMART bars, ARCA no_data, ISLAND failed, AMEX no_data, BATS no_data | ISLAND `failed` |
| CPS | 2013-10-17 | 2006-10-05 to 2013-10-16 | NYSE | SMART no_data, ARCA no_data, ISLAND failed, AMEX no_data, BATS no_data | ISLAND `failed` (4 of 4) |
| FUBO | 2015-11-11 | 2006-10-09 to 2018-01-09 | NYSE | SMART bars, ARCA no_data, ISLAND failed, AMEX no_data, BATS no_data | ISLAND `failed` |
| QXO | 2017-04-19 | 2006-10-09 to 2017-05-06 | NYSE | SMART bars, ARCA no_data, ISLAND failed, AMEX no_data, BATS no_data | ISLAND `failed` |
| SD | 2007-11-06 | 2006-10-09 to 2011-05-21 | NYSE | SMART bars, ARCA no_data, ISLAND failed, AMEX no_data, BATS no_data | ISLAND `failed` |
| CRH | 2023-09-25 | 2023-09-21 to 2023-09-22 | NYSE | SMART bars, no venue asked | No SMART request with a window_start covers the head; the oldest window is a 2-day gap fill |
| LION | 2022-03-01 | 2006-10-17 to 2007-03-14 | NYSE | SMART failed (7 attempts), no venue asked | SMART itself fails on the old window |
| OLED | 2013-06-24 | 2008-01-03 to 2013-02-19 | NASDAQ | SMART bars from 2012-05-30 (352 zero-volume), venues no_data | SMART serves zero-volume bars before the tradeable head |
| RCAT | 2007-05-11 | 2006-10-12 to 2013-09-26 | NASDAQ | SMART bars from 2006-09-28 (4,189 zero-volume), no venue asked | Same class as OLED |

Next actions:

- ISLAND `failed` (8 names): every one is NYSE- or AMEX-listed and ISLAND fails on every attempt. Decide whether ISLAND `failed` with no error code on a non-Nasdaq name is a definitive "no listing" answer (an owner/D-20 rule change) or keep asking it through a head re-ask path.
- CRH and LION: need a head re-ask whose window starts at the 1d depth.
- OLED and RCAT: need a rule for SMART zero-volume prints before the tradeable head, which belongs with 185-33's IBKR orphan-bar rule.

The current shipped path cannot re-ask a covered head (see the re-ask), so a head re-ask belongs in the phase 189 fetcher. No disposition or exception was set by hand.

### Tradier-owned unresolved late names (out of condition 3 scope once 185-34 lands)

ARES, CHTR, DAL, ECH, HNRG, IBP, IHF, INDA, IYZ, MARA, OCUL, ODFL, PARR, USL: 14 names. Only DAL was unresolved before. The other 13 were "moved" only on their TRADIER answer.

### D-28 gate after this plan (`ops_data_bar_check`, read-only, 2026-10-07 00:3x UTC)

4/7 pass, the same count as before.

- `late_name_dispositions` FAIL: 26 unresolved of 410.
- `no_pre_move_bars_visible` FAIL: still 91,059. Migration 442 did not change this count, so the TRADIER rows were not its source. 185-34 must find what does drive it.
- `scrub_pass_complete` FAIL: 28/72 (185-34's scope).

## Handoff to phase 189

`ops_head_rerun.py` invokes `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` by path (`_PIPELINE`, `_run_chunk`), so 189-08's retirement or rename of the pipeline must move this invocation to the new fetcher. The fetcher also needs a head re-ask mode: the D1 gap planner treats an answered SMART head window as covered, so neither the pipeline nor a gap-driven fetcher re-asks former venues for a late name. That is the only way left to resolve the 8 ISLAND-failed names plus CRH and LION. The pipeline itself takes only `ibkr_history_stream`. Like 185-30, this plan held `FetcherLock` from an uncommitted harness. No phase 189 file was edited.

## Verification

- `pytest tests/unit/scripts/test_head_rerun.py tests/unit/test_migration_number_uniqueness.py`: passed. `test_head_rerun.py` now has 16 tests, using fakes only.
- `test_data_bar_check.py` passed, as did the 185-44 guards (`test_single_writer_registry`, `test_table_and_apr_key_readers`, `test_temporary_allow_list_expiry`) and `pytest tests/unit -k boundary`.
- ruff and black are clean on the touched files.
- Full `pytest tests/unit/ -q`: exit 0. The project config prints no count line, so no pass count is recorded; there were 5 skips, all pre-existing (sleeve config removed, scripts.analysis missing, HMM degenerate).
- Acceptance:
  - empty-history count for the 6 names = 0: met
  - `ohlcv_venue_head` TRADIER rows = 0: met
  - every IBKR-sourced late name resolved or named with its per-route answers: met by naming; 12 remain unresolved

## Deviations from plan

### Auto-fixed issues

**1. [Rule 1 - Bug] classify_head required the primary venue's answer, which is never asked**
- Found during: task 2 diagnosis.
- Issue: the provider skips the venue whose alias equals the contract's primary exchange (`ibkr._fetch_pre_move_history`), and `_confirmed_spans` does not require it either. `classify_head` required every venue, so verified_empty was unreachable (0 of 410).
- Fix: drop the venue matching the primary recorded on the latest SMART answer. `HeadRequest` gains `primary_exchange`.
- Commits: 5be6c9ffe (RED), d79322cc4.

**2. [Rule 1 - Bug] classify_head required SMART no_data where SMART answers the head with bars**
- Found during: task 2 diagnosis.
- Issue: a full-depth 1d SMART request returns bars from the listing on, and the reconcile counts that as SMART's answer for the implied empty span. `classify_head` required `no_data`, so 23 IBKR-sourced names whose every venue answered no_data stayed unresolved. Several of them (BLBD, KN, OGS, FRHC) hold confirmed empty-history rows.
- Fix: a SMART bars answer whose first bar is at or after the stored head counts as the head's answer.
- Commits: aee39d61d (RED), cff6e8754.

Both fixes change D7 condition 3, which shares `classify_head`. That is intended: the gate now agrees with the stored empty-history facts.

### Plan expectations that differed from the data

- Expected 7 IBKR-sourced unresolved names. Measured: 17 with TRADIER counted, 53 after excluding it before the fixes, 12 after.
- The re-ask was expected to ask "every route under verify-only". It asked SMART gap windows only, because the head is already covered in D1 (see the re-ask section). It is recorded as residue, not patched: the pipeline is a phase 189 retiring file outside this plan.
- `ohlcv_venue_head` TRADIER rows: the VERIFICATION text cited 492. That is the pre_move count; the TRADIER total was 1,529.

## Affects 185-31 / 185-34

- 185-34 condition 3 exclusion must cover 14 Tradier-owned names, not DAL alone.
- After it, condition 3 still fails on the 12 IBKR-sourced names above unless their rule or a head re-ask lands.
- Condition 4's 91,059 is not driven by TRADIER venue rows.
- `ohlcv_venue_head` pre_move now covers 45 names (IBKR venues only), and the moved count under classify_head is 27.

## Known stubs

None.

## Threat flags

None. The only write paths were the planned view change and the reconcile, plus the pipeline's own D1 capture and D2 stage under the lease and lock.

## TDD gate compliance

- RED 1b762c3af, GREEN b89718168 (task 1).
- RED 5be6c9ffe, GREEN d79322cc4 (deviation 1).
- RED aee39d61d, GREEN cff6e8754 (deviation 2).

## Commits

- 1b762c3af test(185-28): failing tests for IBKR-only head requests at load
- b89718168 feat(185-28): IBKR-only venue head view and late-name requests
- 5be6c9ffe test(185-28): failing test for the primary venue in verified_empty
- d79322cc4 fix(185-28): classify_head does not require the primary venue's answer
- aee39d61d test(185-28): failing test for SMART bars answering the oldest head window
- cff6e8754 fix(185-28): SMART bars from the stored head answer the oldest head window

## Self-Check: PASSED

- `production/migrations/442_ohlcv_venue_head_excludes_tradier.sql`, `scripts/ops/bars/ops_head_rerun.py` and `tests/unit/scripts/test_head_rerun.py` exist.
- All six task commits resolve in `git log`.
- The live acceptance queries return 0 and 0.
