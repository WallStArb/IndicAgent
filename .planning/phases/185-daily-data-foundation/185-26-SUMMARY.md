---
phase: 185-daily-data-foundation
plan: 26
subsystem: bars / nightly backfill
tags: [D-21, tradier, nightly, split-detection]
requires: [185-22, 185-23, 185-25]
provides: [nightly Tradier 1d leg, Tradier-owned IBKR 1d skip, split-aware Tradier refetch, tradier_refused audit check]
affects: [infrastructure_nightly_backfill, infrastructure_run_tradier_daily, bar_derivation daily guard, bar_reconciliation_audit, corporate_action]
key-files:
  created:
    - production/migrations/440_tradier_nightly_apr.sql
    - tests/unit/scripts/test_nightly_tradier_leg.py
  modified:
    - scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py
    - scripts/infrastructure/backfill/infrastructure_nightly_backfill.py
    - services/bar_derivation.py
    - services/bar_reconciliation_audit.py
    - tests/unit/scripts/test_tradier_daily_plan.py
    - tests/unit/scripts/conftest.py
    - tests/unit/services/test_bar_derivation_daily.py
decisions:
  - "Tradier ownership is 'some load was accepted' (ever loaded), not 'the latest load was accepted': under the latest-load predicate a refused nightly refetch handed the name back to D2, which would overwrite its stored bars from D1 (including the refused Tradier answer). D2, the IBKR skip, the nightly selection and the audit share one predicate (TRADIER_OWNED_SQL)"
  - "The IBKR skip is done in the nightly by splitting legs (compute_tradier_owned fetches the stack minus 1d; owned compute_1d_only names drop out), so infrastructure_run_historical_pipeline.py, which the running HTF lane imports, is untouched"
  - "A refetch split is recognised only when the changed bars are exactly a prefix of the overlap, all stored by Tradier, at least threshold.seam.min_run long, constant within threshold.seam.rel_tol, and snapped by infer_split; a first load over IBKR bars is a source change, never a split"
  - "Loader refusals exit EXIT_REFUSED (4), distinct from 1 (runtime error) and 2 (argparse); the nightly maps 4 to success"
metrics:
  completed: 2026-10-06
  tasks: 2
---

# Phase 185 plan 26: nightly Tradier 1d leg and the Tradier-owned skip

The nightly now refetches every Tradier-owned name in full from Tradier before its IBKR legs, which no longer fetch 1d for those names; a refetch that carries a vendor split back-adjustment is recorded as a corporate action and accepted, and every other refusal keeps the stored bars and surfaces in the D7 audit.

## Nightly stage list (for relay to the phase 189 session)

Order of `infrastructure_nightly_backfill.py` after this plan; new or changed stages marked:

1. Status file `started` (unchanged, 185-23).
2. NEW `tradier_daily`: `infrastructure_run_tradier_daily.py --nightly`, gated by APR `infra.tradier.nightly_enabled` (seeded true). Selection: active equities with no non-placeholder 1d bars and no accepted load, plus every Tradier-owned name, each refetched in full from `infra.tradier.history_start` to yesterday. Writes D1 (`ohlcv_request`/`ohlcv_observation`, source tradier, route TRADIER), `ohlcv_load`, `ohlcv_revision`, `market_data_ohlcv` 1d (source tradier), and `corporate_action` (inferred_by `tradier_refetch`). No IBKR, no lease. Exit 0 or 4 (refusals) count as success; anything else fails the night but the IBKR legs still run.
3. CHANGED IBKR leg selection: now runs after step 2 (so names loaded tonight are already owned) and reads the owned set in one query (`TRADIER_OWNED_SQL`, the D2 guard's predicate). Dispatches become `compute` (non-owned, full stack), NEW `compute_tradier_owned` (owned compute names, `--timeframes 1h,15m,5m,1m`, the delegate default minus 1d) and `compute_1d_only` (non-owned only; owned names drop out). With the switch off, the dispatches equal the old two legs. Logged as `nightly_backfill.tradier_owned_skip`.
4. Split detect, daily stage, grid stage (unchanged; the daily stage skips owned names through D2's guard as before).
5. `_finish` status file and `job_completed_total` (unchanged), then the D7 reconciliation audit on every path (unchanged), which gains the `tradier_refused` check.

The phase 189 fetcher (`ibkr_history_fetcher.py`) reads ownership from D2's probe SQL, so it inherits the ever-loaded predicate with no change on its side; it still has to carry step 2 as a non-IBKR leg.

## Measurements (2026-10-06)

- Tradier leg, `--nightly --dry-run` against live Tradier (read-only, nothing written): 1,293 names selected (1,266 owned plus 27 with no 1d bars), 106 s wall clock at concurrency 4. Outcomes: 1,266 loaded, 27 short_history (the 27 names stay with IBKR). Totals: 1,265 new bars (one session per name), 556 changed bars, 0 gated, 1 split.
- The split is ETHA: a constant stored/fresh close ratio of 1/3 across all 552 stored bars, a 1-for-3 reverse split back-adjusted by Tradier, effective (last old-scale day) 2026-10-02. The other 4 changed bars are single-bar vendor revisions on 4 names, under the 2% gate.
- IBKR 1d skip, planned from the live tables (read-only): compute leg 233 names, 205 owned; compute_1d_only leg 698 names, 538 owned. 743 of 931 nightly 1d symbol fetches are skipped; IBKR 1d is left with 188 names (28 compute plus 160 1d-only), matching the plan's estimate. Each skipped name is at least one overlap request, so at least 743 requests a night leave the 58-per-10-minute budget (about 2 h of pacing).
- Not measured on a real night: `indicagent-nightly-backfill.timer` is inactive (last run 2026-10-02, no next trigger), and the task constraints ruled out a live write run. The first real night logs `nightly_backfill.tradier_owned_skip` (n_1d_skipped) and `nightly_backfill.tradier_leg_done` (seconds); record both from that run. The first live leg also writes ETHA's corporate_action row and its 552 ohlcv_revision rows.

## Task commits

| Task | Commit | Notes |
|------|--------|-------|
| 1 RED | 6d6a6b538 | failing split-aware refetch tests |
| 1 GREEN | 01a600582 | loader split inference, corporate_action write, --nightly, EXIT_REFUSED, migration 440 (applied) |
| 2 | 86c28df52 | nightly leg, skip, D2 predicate, audit check, tests |

## Deviations from plan

1. [Rule 1 - Bug] D2 ownership predicate. The plan said "names whose latest ohlcv_load is loaded, same predicate as the D2 guard". With that predicate a nightly refusal (gated, short_history, failed) on an owned name makes the latest load non-loaded: the IBKR leg would fetch it again and D2 would re-derive it from D1, whose latest observation is the refused Tradier answer, overwriting the stored bars the plan says must stay. The guard in `services/bar_derivation.py` now uses the ever-loaded predicate; live data is unaffected today (every name's ownership is the same under both: 1,266 owned, 263 never loaded). bar_derivation.py is not in the HTF lane's import set; the lane's own daily stage at exit runs it as a fresh subprocess and picks up the new SQL, where it changes nothing for current data.
2. [Rule 2 - Missing] Audit check `tradier_refused` in `services/bar_reconciliation_audit.py`: the plan's truths require refusals to appear in the 185-23 audit, which did not read `ohlcv_load`. It reports owned names whose latest load was refused (never by exit code).
3. [Rule 2 - Test safety] `tests/unit/scripts/conftest.py` now mocks the nightly's Tradier leg alongside the audit, so no test that drives `nightly.main()` can spawn a live load (todo 494).
4. `infrastructure_run_historical_pipeline.py` is listed in the plan's files but was not edited (the skip lives in the nightly's leg split; the lane imports that module). The nightly imports its `_DEFAULT_TIMEFRAMES` constant.
5. Migration 440 also widens `corporate_action.inferred_by` to admit `tradier_refetch` (the loader's split record needs it); it was committed with task 1 because the loader writes it.
6. Task 2's tests were written after its code (no separate RED commit for task 2); task 1 followed RED then GREEN.

## Known limits

- `infer_split`'s snap (p, q up to 50, absolute tolerance 0.01) accepts nearly any constant ratio away from 1, so a uniform whole-history rescale by a non-split factor would be recorded as a split. Tradier daily history is split-adjusted only (XOM closes equal IBKR TRADES in 2016 and 2020), so dividend back-adjustment does not trigger it; a ratio within 0.01 of 1 snaps to 1/1 and stays gated.
- The 27 short_history names with no 1d bars are refetched (and refused) every night until IBKR fills them; about 27 Tradier requests a night.

## Gate

- `tests/unit/scripts tests/unit/services`, the three market_data_ohlcv boundary tests and migration number uniqueness: all passed (2 pre-existing skips in test_research_cost_hurdle.py).
- ruff and black clean on every touched file.

## Self-Check: PASSED

- Files exist: 440_tradier_nightly_apr.sql, test_nightly_tradier_leg.py, this summary.
- Commits exist: 6d6a6b538, 01a600582, 86c28df52.
