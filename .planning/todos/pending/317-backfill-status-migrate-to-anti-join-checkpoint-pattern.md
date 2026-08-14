# 317 - Migrate `backfill_feature_factory.py`'s compute-stage checkpoint to the codebase's established anti-join pattern

**Filed:** 2026-08-14
**Source:** `/simplify`'s altitude-angle review of [[todo 316]]'s fix (the `_load_fv_presence_map`
reconciliation check). The reviewer found this codebase already has a named, established pattern
for exactly the problem class todo 316 hit -- flagged as a legitimate structural follow-up, not
bundled into 316 to avoid scope creep on an already-landed fix.

## What

`backfill_feature_factory.py`'s compute-stage checkpoint is the **only** place in `services/*.py`
using a side-table `status='complete'` flag (`backfill_status`) to track "is this (symbol, tf)
pair done" -- confirmed via repo-wide grep, zero other matches. Every other batch writer in the
codebase queries the **target table itself** as the checkpoint:

- `alpha_frame_writer.py`'s own documented "Pattern 4: anti-join checkpoint" (`LEFT JOIN
  alpha_frames af ... WHERE af.frame_id IS NULL`)
- `regime_writer.py`: `feature_vectors.regime IS NULL` directly on the target column
- `ic_engine.py`: deleted a decoupled `.pkl`-file checkpoint system outright (todo 122, refactor
  162-03) for this identical root cause -- a checkpoint artifact separate from the write target
  can silently desync from it.

`backfill_status`'s `status='complete'` flag is structurally the same anti-pattern: a side-table
proxy for "does `feature_vectors` have this data" that can drift from reality with nothing to
catch it until a human notices (which is exactly what happened -- see todo 316, 80 symbols silently
missing for 2+ weeks). Todo 316's fix reconciles the two after the fact (query both, compare, warn
on mismatch); this todo is the deeper fix -- eliminate the second source of truth entirely.

## Why not done in todo 316

Two reasons this is a separate, larger piece of work, not a bundle-in:
1. `backfill_status` isn't purely a compute-stage checkpoint -- it also carries `fetch_complete`
   (Stage 1's IBKR-fetch-vs-`market_data_ohlcv` checkpoint, a different write path with no
   `feature_vectors`-side equivalent) and `rows_written`/`theoretical_max` (the D-06 coverage-gate
   bookkeeping `_log_coverage_report` depends on). A full anti-join conversion has to either
   preserve these some other way or prove they're no longer needed -- real design work.
2. No second live instance of this anti-pattern exists today (confirmed via grep) -- generalizing
   into a shared `_batch_utils.py` helper at N=1 would be premature abstraction. This todo is about
   retiring the one instance, not building infrastructure for a problem that hasn't recurred.

## What to do

1. Design what an anti-join version of the compute-stage checkpoint looks like: likely
   `LEFT JOIN feature_vectors fv ON fv.symbol = bs.symbol AND fv.tf = bs.tf WHERE fv.symbol IS
   NULL` (or the `_load_fv_presence_map` set-based check from todo 316, promoted from "reconcile"
   to "sole source of truth" -- drop the `status='complete'` skip condition entirely once this
   lands, only checking presence).
2. Decide what happens to `rows_written`/`theoretical_max`/D-06 coverage reporting -- these still
   need *some* home; likely stays in `backfill_status` as pure bookkeeping/observability, just no
   longer load-bearing for the skip decision itself.
3. Keep `fetch_complete` on `backfill_status` as-is -- Stage 1 (IBKR fetch) has no equivalent
   target-table anti-join available (there's no "the fetch already happened" signal cheaper to
   derive from `market_data_ohlcv` directly than tracking it explicitly); this todo is scoped to
   Stage 2 (compute) only.
4. Once landed, todo 316's `_load_fv_presence_map`/`checkpoint_desynced` reconciliation logic
   becomes dead code -- remove it, since there's no longer a second source of truth to desync from.

## Status

pending, P2 -- real architectural debt (confirmed: this codebase has already treated "separate
checkpoint desyncs from target" as a recurring failure class worth eliminating, twice), but not
urgent: todo 316's reconciliation check makes the current design safe (self-detecting, self-healing
via warning + recompute) even though it isn't the cleanest shape. No live blast radius today beyond
what 316 already fixed.

## Where

- `services/backfill_feature_factory.py` -- `run_compute_stage()`, `_load_status_map`,
  `_load_fv_presence_map` (todo 316), `backfill_status` schema
- `services/alpha_frame_writer.py` -- reference implementation ("Pattern 4")
- `services/regime_writer.py` -- second reference implementation (NULL-on-target)
