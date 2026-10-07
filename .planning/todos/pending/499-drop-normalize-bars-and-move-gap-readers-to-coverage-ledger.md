---
status: pending
priority: P2
filed: 2026-10-07
source: plan 185-32 (synthetic-fill fences), handoff to the phase 189 session
---

# Drop normalize_bars from the fetcher item, delete its fill path, and move the 5m/1m gap readers onto the coverage ledger

## What

Plan 185-32 fenced every synthetic_fill path out of `market_data_ohlcv`: migration 444's CHECK
constraint refuses the row, and `tests/unit/test_market_data_ohlcv_no_synthetic_fill.py` fails CI on a
new `normalize_bars` call or synthetic_fill row build. Two TEMPORARY allow-list entries remain, both
`retire: todo 499`:

- `scripts/infrastructure/backfill/_history_fetch_item.py` calls `normalize_bars` behind
  `if not real_bars_only:`. Since 185-32 added 4h to the pipeline's `_REAL_BARS_ONLY_TFS`,
  `real_bars_only_for` is true for every timeframe, so the branch is unreachable (its `store_bars` fill
  and the `normalize_bars` import go with it).
- `src/core/bar_normalizer.py`: `normalize_bars` itself, and `SOURCE_SYNTHETIC_FILL` once nothing reads
  it outside the read/refusal allow-list.

Also from 185-32, in phase 189 files: the fetcher's `--normalize` flag and `_normalize` method were
removed (they called the pipeline's deleted `run_normalize`), and `Candidates.scope_contracts` in
`ibkr_history_fetcher.py` now has no reader.

## Fix

1. Drop the fill branch and the import from `_history_fetch_item.py`; remove its entry from
   `_NORMALIZE_CALLERS`.
2. Delete `normalize_bars` (and its tests in `tests/unit/core/test_bar_normalizer.py`), remove its
   entry from `_SYNTHETIC_BUILDERS`; drop `scope_contracts` if nothing else needs it.
3. Move the placeholder-coverage gap readers onto `ohlcv_coverage`: the record planner's 5m path
   (`_d1_gaps.py`, paused with todo 462), the pipeline's 1m `detect_gaps` (dormant), and
   `services/bar_auditor.py`'s 1m audit (unit disabled). Their states are in the provider matrix of
   `docs/foundation/canonical-truth-registry.md`.

189-08's rename or retirement of `infrastructure_run_historical_pipeline.py` inherits 185-32's two
changes: the `--normalize` mode is gone and 4h is real bars only. `ops_head_rerun.py` (185-28) invokes
the pipeline by path.

## Why it matters

The fences hold today, but a reachable-looking fill function invites a new caller, and gap readers that
were built around placeholder coverage should read the coverage ledger, not infer coverage from rows.

## Progress (plan 189-08, 2026-10-07)

- Fix step 1 done in 1be02ae51: `_history_fetch_item.py` no longer imports or calls
  `normalize_bars` or `store_bars` (the unreachable fill branch is gone), and its
  `_NORMALIZE_CALLERS` entry in `tests/unit/test_market_data_ohlcv_no_synthetic_fill.py` is
  removed (the dict is now empty). The fetcher's `--normalize` mode was already gone (185-32).
- `Candidates.scope_contracts` (no reader) dropped from `ibkr_history_fetcher.py` in the same commit.
- Left open on purpose, so this todo is not closed: step 2 (delete `normalize_bars` and the
  `src/core/bar_normalizer.py` TEMPORARY entry, `retire: todo 499`) is planned in 185-42; closing
  the todo now would fail the 185-44 expiry guard on that entry. Step 3 (move the 5m/1m
  placeholder-coverage gap readers onto `ohlcv_coverage`) has no plan yet.

