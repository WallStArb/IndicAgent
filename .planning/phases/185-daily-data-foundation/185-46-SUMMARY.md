---
phase: 185-daily-data-foundation
plan: 46
subsystem: data-integrity
tags: [tradier-retirement, ibkr-1d-primary, evidence, freshness, verdict-gate, grafana]
requires: [185-38, 185-41]
provides:
  - "Tradier daily timer disabled; freeze point last Tradier bar 2026-10-06 on all 1,529 names"
  - "docs/research/1d-primary-swap-evidence.md: rules R1-R6 pre-registered (40c1a2402), results second (07cef334e)"
  - "scripts/research/swap_1d_primary_measure.py: read-only --rate, --volume, --census, --classify"
  - "freshness_1d verdict (ninth 1d check), rebuild-only gate, APR key (migration 455), Grafana rule bar_freshness_1d_uid"
  - "check_data_layer_final_landed requires 185-47 and 185-48 SUMMARY files"
  - "dated amendment blocks in 189-10 and 185-35"
affects: [185-47, 185-48, 189-10, 185-35, 186-26]
key-files:
  created:
    - docs/research/1d-primary-swap-evidence.md
    - scripts/research/swap_1d_primary_measure.py
    - tests/unit/scripts/test_swap_1d_primary_measure.py
    - production/migrations/455_bar_freshness_1d_apr.sql
    - tests/unit/test_bar_freshness_apr_migration_contract.py
    - .planning/todos/pending/505-nightly-update-lane-exceeds-r4-measure-5m-pacing-ceiling.md
  modified:
    - src/intelligence/bars/integrity_checks.py
    - src/intelligence/bars/verdict_gate.py
    - services/rebuild_preconditions.py
    - services/bar_reconciliation_audit.py
    - tests/unit/bars/test_integrity_checks.py
    - tests/unit/bars/test_verdict_gate.py
    - tests/unit/test_rebuild_preconditions.py
    - tests/unit/services/test_bar_reconciliation_audit.py
    - production/grafana/provisioning/alerting/alert-rules.yml
    - .planning/phases/189-ibkr-history-fetch-consolidation-single-fetcher-coverage-led/189-10-PLAN.md
    - .planning/phases/185-daily-data-foundation/185-35-PLAN.md
    - .planning/todos/PRIORITIES.md
    - .planning/todos/completed/503-amend-swap-plans-to-two-generic-nightly-lanes.md
decisions:
  - "freshness_1d is the ninth entry of CHECKS_1D and is judged inside judge_name_1d (which already receives the run's last completed session), so D7 writes it with the other verdicts and the gauges and log iterate it without a special case"
  - "D7 records a zero failing count for every judged check, so the new alert (and the others) clears when failures stop instead of holding the last nonzero point for 36 h"
  - "The alert expression follows its neighbors' two-expression shape (A = last_over_time(...{check=\"freshness_1d\"}[36h]), C gt 0) rather than putting '> 0' in A, which would turn a clear into NoData"
  - "189-10 amendment names three new APR keys for migration 451: infra.backfill.update_overlap_sessions_1d, infra.backfill.update_overlap_days_5m, infra.backfill.gap_fill_interval_days"
requirements: [D-01, D-21, D-26]
metrics:
  completed: 2026-10-07
  duration: about 75 minutes
  tasks: 3
---

# Phase 185 Plan 46: Measure and prepare the 1d primary swap to IBKR Summary

The Tradier nightly is off, the swap's rules were fixed before any number existed, the IBKR 1d cost, volume basis and per-name classes are measured, and a stale 1d series is now a named, alerted verdict that gates the rebuild.

## Commits

| Task | Commit | What |
|---|---|---|
| 1 | 2c9ddc53b | Tradier timer disabled; 189-10 and 185-35 amendment blocks |
| 2 | 40c1a2402 | evidence doc header and Pre-registered rules, alone |
| 2 | dd7d85ba1 | tests for the measurement's pure functions |
| 2 | 07cef334e | measurement script, Results section, todo 505 filed, todo 503 closed |
| 3 | 37edffbc7 | tests for freshness_1d, gate, markers, D7 rows, migration contract |
| 3 | ea6d9d349 | freshness_1d, migration 455 (applied), rebuild gate, Grafana rule |

## Task 1

Before: indicagent-tradier-daily.timer enabled and active (next fire 2026-10-07 21:30 EDT), the service disabled and inactive, no loader process. After `systemctl disable --now`: timer disabled and inactive; `systemctl list-timers` no longer lists it. The loader was not run. Freeze point (read-only): max TRADIER 1d observation date 2026-10-06 on 1,529 names; latest loaded ohlcv_load row PBF 2026-10-07 11:52:38 UTC (2,748 tradier load rows in the 01:30 to 11:52 UTC window); the log ends with `tradier_daily.done` (1,455 loaded, 332 D1 observations landed) and `daily_stage_start` (166 names). Nothing was written to the database.

189-10 gained one dated block (A to E, with the two-lane queue, the overlap-verified update lane and the gap-fill cadence key) and "185-46" in depends_on; 185-35 gained one dated block dropping the Tradier fired-run checks. Nothing else in either changed.

## Task 2 key figures

- Census reproduces every plan-time count (1,529 active, 1,502 compute_1d, 1,037 with SMART TRADES, 492 without, 475 never asked, 647 late starts with 985,615 head bars, 34,266 Tradier-only interior dates on 442 names). D is 2026-10-07 today.
- Request rate (SMART TRADES 1d): 431 requests an hour (median of 7 busy hours), latency mean 1.93 s, median 0.15 s, p90 1.76 s, no_data 9.0%, failed 0.2%. The 431 comes from non-fetcher jobs mixing routes; all-route busy hours reached 942 to 998. The fetcher's own bound is serial: about 1,017 an hour. No fetcher `run summary:` for 1d exists yet.
- Nightly update lane vs R4 (120 min): 1d 90.2 min at the fetcher bound (212.9 at 431/h); 5m 40.2 min today (233 names) and 259.0 after the drain (1,502). Totals 130.4 today and 349.2 after the drain: R4 fails in every case. Todo 505 filed (measure the 5m pacing ceiling; 5m runs on the unmeasured default 58 per 10 minutes). Gap-fill lane per run: 1d 15.7 min (240 names), 5m at least 63.9 min.
- 5m restatement for 189-10 Task 2: floor 10.6 days becomes about 12.7 (11.7 to 14.0); the 12 to 18 day expectation becomes about 14.4 to 21.6 days, so its 18-day criterion is at risk.
- Volume IBKR/Tradier, last 250 sessions: p10 0.418, p50 0.541, p90 0.853 (35.9% of names below 0.5); full history p50 0.758; the yearly median falls from 0.95 (2006 to 2013) to 0.54 (2025, 2026). Five names unusable, listed.
- Classes over the 1,037 names with SMART: A 1,017, B 8 (CTVA, ELS, LION, MTCH, NEXN, RGEN, W, WEX), C 12; over all 1,529: C 504 (492 no_ibkr_yet). Heads: 662 present, 542 keepable, none on a class B name.
- Admission sweep dry run: admitted 841, write 73, route_185_37 113, keep_no_overlap 475. Its write set is not class B: B is a subset (all 8), the other 65 are names never Tradier-canonical, 72 of the 73 already hold an open symbol row.

## Task 3

`freshness_1d` counts the NYSE sessions after the latest canonical 1d bar, up to the last completed session, that no answered-empty span covers; it passes at or below `threshold.bar_integrity.freshness_max_lag_sessions_1d` (2). It is in `REBUILD_ONLY_CHECKS["1d"]` and `REBUILD_EXTRA_CHECKS`, not in `REQUIRED_CHECKS`; `fetch_d2_inputs` now passes the extra checks, so the 1d rebuild gate fails a stale name and names it. D7 writes 10 rows per compute_1d name. Migration 455 applied live under lock_timeout 10s (one config_history row). The Grafana API lists bar_freshness_1d_uid after the provisioning reload (17 rules). D7 was not run by hand; its next fire (06:00 UTC) emits the check. Precondition checked before editing rebuild_preconditions.py: no python process runs backfill_feature_factory, and none of the rebuild's landed markers exist, so no rebuild cell can have completed.

## Verification

- Task 1, 2 and 3 automated verify commands pass; the evidence doc's first commit has no Results section.
- Full `tests/unit/ -q`: exit 0, no failures (run before the Task 3 commits; the only later change renamed one test function to clear the duplicate-name pre-commit check).

## Deviations from Plan

1. [Rule 1 - Bug] D7 recorded the failing-names gauge only for checks with failures, so a cleared check never recorded 0 and its alert would hold the last nonzero point for 36 hours. Added `zero_for_judged` and merged zeros for every judged check at the gauge call site (ea6d9d349), with a test.
2. [Plan text adjusted] The alert expression keeps the neighbors' shape (threshold in condition C, not `> 0` in A); `> 0` in A would make a clear read as NoData.
3. [Plan text adjusted] `freshness_1d` takes a keyword `symbol` (the `Verdict` record needs it) and lives in `CHECKS_1D` and `judge_name_1d`; the plan's per-name loop placement is satisfied because D7 calls `judge_name_1d` there with the run's last session.
4. [Housekeeping] Todo 503 moved to completed (its last item, the 189-10 block, landed in Task 1) with its PRIORITIES row updated; todo 505 filed by R4 with a PRIORITIES row.
5. [Provenance] The evidence doc header says Claude (Opus 5.5), the model that wrote it, not Sonnet 5.5 as the plan text assumed.
6. [Pre-commit] The first Task 3 commit attempt failed the duplicate test name check (`test_seed_is_idempotent_and_history_written_once` exists in another migration contract test); renamed and recommitted. Nothing was amended.

## Findings for the next plans

- 185-47: 11 class C names (CART, CC, CNH, CUBE, EU, FLUT, FROG, LEA, LGND, SNEX, VSEC) already hold open primary-ibkr rows from 185-38. R3's hold row would overlap them and reverse that decision, and C1's "new 0 for class C" would be wrong for them. 185-47's amendment should treat any name with a 1d symbol row as decided (as `rows_to_write` does) and judge C1 by each name's effective policy from D. All 8 class B names already have their row; 185-47 adds none for them.
- 185-47: the 6 no_common names have SMART rows only on a pre-split scale (ETHA split 2026-10-02 recorded after IBKR's last fetch); 189-10 Task 1b's refresh step gives them current-scale answers. Rerun `--classify` after it.
- 189-10 Task 1: three new APR keys in migration 451 are named in its amendment (overlap 1d and 5m, gap-fill cadence); the 1d currency seed is 1.
- 189-10 Task 2: deduct the update-lane slice (130 min at the start of the drain, 349 at the end, average about 240); the 18-day criterion is at risk until todo 505 measures the 5m ceiling.
- The freshness alert fires from about two sessions after D until 189-10 launches the timer; that is expected.
- Prometheus currently returns no `bar_integrity_failing_names` series for any check over 36 h (queried 2026-10-07 13:40 EDT), so every bar_integrity rule is NoData today. Not investigated here (out of scope; may relate to todo 498's collector label drop); worth checking after the next D7 fire.
- logs/ibkr_history_fetcher.log and logs/backfill_feature_factory.log hold test-run events (fixture symbols AAA, BBB, CCC; test resource leases): some unit tests log to the production log files. Not fixed here.

## Known Stubs

None.

## Threat Flags

None beyond the plan's register: the measurement script opens read-only connections and a source scan test forbids write statements; the only database write is migration 455.

## Self-Check: PASSED

Files exist: the evidence doc, the script and its test, migration 455 and its contract test, todo 505, todo 503 in completed/. Commits 2c9ddc53b, 40c1a2402, dd7d85ba1, 07cef334e, 37edffbc7, ea6d9d349 are on origin/main. bar_freshness_1d_uid is listed by the Grafana API. The APR key is in config_state with value 2.
