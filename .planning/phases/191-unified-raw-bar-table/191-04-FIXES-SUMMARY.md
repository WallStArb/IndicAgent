# 191-04 and 191-05 review fixes summary

Source: independent review `review_claude_04-05.md` (findings 1, 3, 7, 9, 11, 12 fixed, 4 reporting half only). Findings 2, 5, 6 are amended into plans 06/07/08/10, 8 (apply migration 477) and 10 (needs data) are not done here. No migration was applied; no unit was resumed.

## Fixed

| Finding | Fix | Commit |
|---|---|---|
| 3 (HIGH) | `ops_raw_cutover_window.py resume` refuses a unit whose dependency closure is uncleared (`UNIT_DEPENDENCIES`: fetcher timer needs its service, which needs `indicagent-bar-derivation.service`; `FETCHER_RUNS_MODULES` records split_detection, bar_hold and coverage as in-process, covered by clearing the fetcher service). The fetcher pair also refuses until `191-06`, `191-08`, `191-10` have SUMMARY files; `--override-fetcher-plan-gate` overrides it and the use is logged to `logs/raw_cutover_window_overrides.log` and the record. Test checks the map against the systemd files. | 774a84eab |
| 9 | `open` writes the record (state `opening`) with each unit's pre-stop active state before stopping anything; a re-run reuses it. | 774a84eab |
| 1 (HIGH) | D-191-J. `session_complete_at`; live 1d persister drops bars of a session still open at `answered_at` (request row kept); `--revisions` and the balance check skip value runs first served before the close; `--prune-forming-revisions` rebuilt the affected symbols. | 4450da415 |
| 7 | `hold_pending` skips values already pending for the key (read through the series' refused loads so the revision primary key is the access path); a refusal settles the item `ok` with `held` and `n_held` on the outcome (no failure counted, no full-window refetch), the run summary carries `n_held_series` and `n_held` and the run is `partial`. | 64c004f63 |
| 11, 12 | `UnmappedObservation` (ValueError subclass): the persister skips that request, the walk continues, the item ends `error` with an `unmapped_kind:` message and an `unmapped` field; CI test that the APR venue seed is a subset of `VENUE_ROUTES`. Both sinks remember a flush that failed after its COPY and drop already-written request_ids before the next write. | 7f786daf0 |
| 4 (reporting) | `LoadResult.n_refused_series`, shared `load_status`; `ops_bar_nightly` and `ops_bar_load` do not print APPLIED when rows were held; the nightly summary carries `refused` and `held` and exits non-zero on held rows. | bb59304e2 |

## Finding 1 data repair

Dry run found 929 stale reconstruction rows (all ibkr smart_trades) in 929 symbols, matching the review. `--prune-forming-revisions --apply` deleted and rewrote the reconstruction loads of those symbols (DML, one transaction per symbol): 695 loads and 6,880 revisions written. Reconstruction revisions went 8,014 to 7,085 (exactly 929 fewer), reconstruction loads 1,293 to 834 (loads of the affected symbols were regenerated; loads that held only forming rows are gone). A second dry run reports 0 affected symbols. AAPL 2026-09-30: the forming run (old_close 336.06) is gone, the run first served after the close remains; AAPL balance is 19 runs, 0 missing, 19 stored.

## Deviations and limits

- Coverage is already not credited for a refused chunk (the persist helper skips it). The review's other fix (skip the coverage upsert when selection wrote nothing for an alpaca-only slot set) is not done; it depends on plan 07 seeding Alpaca policy spans, so Alpaca 5m loads still do not reach canonical until then. Do not run `ops_bar_nightly` or `ops_bar_load` before plan 07.
- A refusal now settles an item `ok` rather than `error`. This changes the earlier contract that a refusal fails the item; the visibility moved to the outcome, the run summary and the `partial` status. A held 5m series is asked again by the update lane after the next session close (not the full window), and the dedupe keeps that from multiplying the hold.
- `--reconcile` (ops_raw_backfill) also logs displaced raw 1d values as superseded and was not filtered for forming bars; it was not in scope and not changed. Re-check it before relying on its 1d revision evidence.
- The four running `--check` shards loaded the old code. Their revision balance for symbols rebuilt during their run compares against the unfiltered expectation, so any revision-side imbalance they report for the 929 symbols is an artifact; rerun the revision check with the current code before reading it.
- No grace period after the close (D-191-J): a bar answered at the close instant is complete.
- The planner still reads `ohlcv_observation` for 1d and asks the forming session each run; with the filter no partial bar is stored, so the session stays a gap until it is seen whole. Moving the planner to raw is plan 06.

## State of held units

`logs/raw_cutover_window.json`: 10 units, none cleared, none resumed (3 timers with resume action `start`, 7 services `none`). The resume guard now also refuses the fetcher pair until plans 06, 08, 10 have summaries.

## Verification

Touched-area suites pass (cutover window, raw backfill, history fetch item and fetcher, raw writer, ingress contract, request writer, vendor kind, bar load, session). Full `tests/unit` passes (exit 0, two pre-existing skips).
