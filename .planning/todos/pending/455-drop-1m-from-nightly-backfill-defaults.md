---
status: pending
priority: P2
filed: 2026-09-29
source: nightly backfill review 2026-09-29 (1m consumer check)
---

# Drop 1m from the nightly backfill and the pipeline default timeframes

## What

`_DEFAULT_TIMEFRAMES = "1d,1h,15m,5m,1m"` in
`scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` includes 1m, and the
nightly's `compute` leg (`scripts/infrastructure/backfill/infrastructure_nightly_backfill.py`)
passes no `--timeframes`, so every night fetches a 90-day 1m window (`"1m": (90, True)`) for the
compute-eligible symbols (233 symbols had 1m bars in the last 30 days, newest 2026-09-28 19:59
UTC). The compute stack (`feature.factory.target_timeframes`) is 5m, 15m, 1h, 1d.

## Consumer check (2026-09-29)

- Only compute reader: `ret_div_1m_5m` (`services/backfill_feature_factory.py` line ~1522, built at
  tf 5m). Active in `concept_registry` since phase 151. Documented coverage is about 1% (1m spans
  2026-03-23 to 2026-06-23 against 5m from 2006), and todo 445's result shows `n_sessions: 0`, NaN IC.
- Nothing under `src/intelligence/research`, `src/intelligence/statistics` or `scripts/research`
  reads 1m.
- The 1m checks in `bar_auditor`, `signal_auditor` and `feature_vector_pipeline` sit on the
  streaming path, whose services are `inactive (dead)`. The v2.x plugins that request 1m have no
  live consumer.

## Fix

1. Give the nightly's compute leg an explicit `--timeframes 1d,1h,15m,5m`, and remove 1m from
   `_DEFAULT_TIMEFRAMES` (check the `--timeframes` help text and any test pinning the default).
2. Decide `ret_div_1m_5m`: deprecate through `ConceptRegistryService` (never a direct status
   write), or keep it and accept it stays near-empty. Phase 186 plan 15 moves this feature into
   the kernel path with a "Test C (1m to 5m)" availability test, so settle it with that plan
   before deleting anything.
3. Existing 1m rows are raw market data and stay (permanent).

## Constraints

The pipeline script cannot be edited while the nightly or a bulk lane is running (they load it at
start; check `ps` first, and the lane loops relaunch it every attempt, so edit between attempts
only if a lane is idle). Land it after todo 449's htf lane, or during a gap.

## Why

Each night's 1m fetch is about 90 days x 233 symbols of IBKR history requests under the
`ibkr_history_stream` lease, which the priority-tier nightly holds ahead of the todo 449 bulk lanes.
