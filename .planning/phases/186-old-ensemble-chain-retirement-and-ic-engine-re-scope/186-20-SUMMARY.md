---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 20
subsystem: testing
tags: [parity, ic, feature_ic_scores, pooled_rank_ic, replay]
requires:
  - phase: 186-10
    provides: pooled_rank_ic, align_features, targets
  - phase: 186-14
    provides: ic_measure writer assembly (make_tf_context, fetch_long_form, load_params)
provides:
  - parity replay core and live harness for stored POOLED cross-sectional cells
  - committed parity report with the writer-path cell, the artifact 186-23's gate reads
affects: [186-23, 186-26, 186-28]
tech-stack:
  added: []
  patterns:
    - "replay a stored legacy cell with the legacy arithmetic replica to attribute every difference"
key-files:
  created:
    - tests/unit/measure/parity_replay.py
    - tests/unit/measure/test_parity_harness.py
    - tests/integration/test_ic_parity_replay.py
    - .planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-20-PARITY-REPORT.md
  modified:
    - pytest.ini
key-decisions:
  - "Owner decision 2026-10-01: restated parity criterion accepted; pooled_rank_ic is not changed"
requirements-completed: [D-21, R-06, D-15]
duration: about 4h
completed: 2026-10-01
---

# Phase 186 Plan 20: parity replay of stored pooled cells Summary

A read-only harness replayed 1,080 stored POOLED cells; row sets reproduce exactly, a replica of ic_engine's arithmetic reproduces 1,078 of them, and every fresh-versus-stored difference (136 cells) has a named cause. One frozen cell recomputed through ic_measure's own assembly equals the harness replay with delta 0.0.

## Commits (branch phase-186-20)

- `de1ec2d9f` test: parity replay core and CI-clean synthetic tests
- `992de423f` test: parity harness replays stored POOLED cells; report committed
- the task 3 commit: writer-path parity cell and the restated verdict
- this SUMMARY commit

## D-01 gate (tasks 1 and 3)

`ps aux | grep -E "ic_engine|ic_measure|backfill_feature_factory|regime_writer|rebuild"` empty; `logs/ic_engine.log` empty and `.log.1` ends 2026-09-30 19:21 UTC with ic_measure bulk-load writes only (no corpus run); `pg_stat_activity` query on `feature_ic_scores` returned 0 rows. Pass. Task 3 re-checked via the live runs: `feature_ic_scores` stayed at 10,616,092 rows after every run.

## Sample (fixed before running)

30 features via `random.Random(18620).sample(sorted(candidates), 30)` from 255 candidates (300 FeatureVector fields; 40 broadcast and 5 regime columns excluded). Labels per tf: top 3 by stored POOLED rows (all commodity, plus fx `weak_dollar_risk_off` on 1h and 1d). 12 (tf, horizon) pairs x 30 x 3 labels = 1,080 cells; 1h horizons 20 and 60 excluded (180 cells). The feature and label lists are in the report.

## Parity result

- n_independent: 0 mismatches in cells whose feature is finite on the strided rows (27 mismatches elsewhere, all partly-missing features, whose fresh count excludes non-finite rows).
- Stored `ic_value` reproduced within the float32 bound: 944 of 1,080 (44 within 1e-9). Max delta among reproduced cells 4.2e-6.
- Legacy-arithmetic replica reproduces 1,078 of 1,080 stored cells; the other 2 are float32 summation noise in the stored value (5.99e-6 against a committed bound of 4.53e-6; fresh and replica agree to 3.7e-9).
- 136 cells differ from the fresh function, unexplained 0: 66 NaN-denominator zeros (39 all-missing columns, 27 partly-missing columns whose finite IC reaches 4.57e-2), 68 rank-scope (max 1.08e-4), 2 float32 noise.
- Kernel targets over 11.7M rows: 0 end-of-window, 0 gap, 2,772,485 session-crossing (refused by the kernel by design), 447,977 entry or exit opens absent from the tradeable panel, 326,224 other.

## Writer-path parity cell

Key: `1d / up_secondary_neutral (group commodity) / yield_slope_momentum_product / horizon 1`, stored ic_value 0.022089984267950058, n_independent 6168. Through `build_target_panels` -> `research_panel.load` -> `make_tf_context` (`stack_grid`, `map_slots`, `SlotMap.present`) -> `fetch_long_form` -> `ctx.stack` -> `scatter_features` (asserted equal to `align_features`) -> `existing_rows` plus the label-bar mask -> `observation_rows` -> `pooled_rank_ic`: 0.022089497508545795, n 6168. Harness kernel replay: identical, delta 0.0 against 1e-9. PASS. Peer source: `market_regimes` plus `alpha.regime.groups` (live; it must survive 186-21's APR deletion).

## Deviations from Plan

1. **Owner decision, 2026-10-01 (recorded as the coordinator relayed it).** The plan's 1e-9 criterion cannot hold because stored values are float32 results, and the replay found value differences. The owner accepted the restated criterion: the legacy-arithmetic replica reproduces every stored cell (1,078 of 1,080, the other 2 attributed to float32 summation noise in the stored value) and every fresh-versus-stored difference is attributed to a named cause (66 NaN-denominator zeros, 68 rank-scope, 2 float32 noise). `pooled_rank_ic` is not changed. The report verdict states this in place of "GATE NOT MET AS WRITTEN".
2. **Tolerance:** `2 * eps32 * ceil(log2 n)`, committed in the harness before any live result; the strict 1e-9 count is reported beside it, and the writer-path cell is held to 1e-9.
3. **Added kernel causes:** session-crossing and absent tradeable open, so the plan's three buckets do not leave most 5m differences as "other". Added float32-noise and legacy-replica attribution.
4. **`pytest.ini`** gains the `parity` marker (strict markers); not in `files_modified`.
5. **Live DSN constant** in the integration test (under pytest `Settings` points at the test database) and an override of the autouse test-database rebuild fixture.
6. **Peer routing** is a read-only replica of ic_engine's logic so the test survives 186-23's deletion of ic_engine.
7. **Determinism repro not run:** nothing under `src/intelligence/research/` or `statistics/` was edited.

## Relays

- **For the research lane:** stored `feature_ic_scores` POOLED rows hold `ic_value` 0.0 for any feature with a non-finite value among the strided rows (66 of the 1,080 sampled cells; a finite IC up to 4.57e-2 existed on the complete rows). This produces false negatives only, never a false positive. Any claim citing a pooled row should check the feature is finite across the cell. The table is dropped whole by 186-28.
- **186-18 market_regimes orphan cleanup run:** this plan's parity report and summary are on main once merged, so the cleanup run (owned by 186-26 task 1 per todo 420) is no longer blocked by 186-20.
- **186-23:** the report path its gate greps for exists and carries the writer-path cell section.
- **Todo 439:** the D-19 IC purge is discharged by 186-28's whole-table drop; the todo stays open until then.

## Known Stubs

None.

## Threat Flags

None. Read-only reads of the live database; no write session, no migrations.

## Self-Check: PASSED

Report, harness, tests present; `feature_ic_scores` count 10,616,092 unchanged; both parity tests exit 0.
