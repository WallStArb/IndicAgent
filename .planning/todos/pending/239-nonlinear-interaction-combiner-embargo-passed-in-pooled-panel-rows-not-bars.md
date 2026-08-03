---
status: pending
priority: P1
filed: 2026-08-03
source: rigor review of `docs/research/data-edge-source-thesis.md` -- verifying the doc's
  claimed "24-bar embargo" against the code that implements it
---

# `nonlinear_interaction_combiner`'s walk-forward embargo is measured in pooled-panel ROWS, not bars

## Status (2026-08-03)

Code fix landed: commit `816032e2` adds `_pooled_panel_folds()` to
`scripts/analysis/_nonlinear_interaction_combiner_shared.py`, building walk-forward folds over
the distinct `bar_ts` index (via `build_walk_forward_folds`, unchanged) and mapping bar-index
boundaries back to row slices -- the "better" fix this todo names, not the multiply-by-rows-
per-bar approximation. Unit-tested (`tests/unit/test_nonlinear_interaction_combiner_shared.py`)
against synthetic uneven-symbols-per-bar panels, including a degenerate-case equivalence check
against `build_walk_forward_folds` called directly. Peer-reviewed (independent agent, verified
correct against the real corpus's actual per-tf bar counts).

**Still open:** the actual re-run across 1h/1d/15m/5m under the corrected methodology, and
recording whether the published numbers move -- this todo's own "Fix" section calls for exactly
that, and it hasn't happened yet (multi-hour, DB-heavy job, deliberately not started
opportunistically alongside other concurrent work in this repo). Leaving `status: pending` until
that re-run lands.

## What

`scripts/analysis/_nonlinear_interaction_combiner_shared.py` calls:

```python
n_valid = len(X)
folds = build_walk_forward_folds(n_valid=n_valid, n_folds=n_folds, embargo_bars=embargo_bars, ...)
```

`X` is the **pooled** panel -- every symbol x every bar, sorted `ORDER BY bar_ts ASC, symbol ASC`
(`FV_SQL`, same file). So `n_valid` is a row count of ~80 rows per distinct `bar_ts`, and
`build_walk_forward_folds` (`src/intelligence/statistics/ic_math.py:572`) does all of its
boundary arithmetic -- `test_start = train_end + embargo_bars` -- in **row index units**.

The per-tf constants are written and commented as if they were bars:

| Script | `_EMBARGO_BARS` | Comment / intent | Actual wall-clock separation |
|---|---|---|---|
| `nonlinear_interaction_combiner_lightgbm_check.py` (1h) | 24 | "1 day of 1h bars" | 24 rows / ~80 per bar ≈ **0.3 bars** |
| `nonlinear_interaction_combiner_replication_15m.py` | 96 | 1 day of 15m bars | ≈ **1.2 bars** |
| `nonlinear_interaction_combiner_replication_1d.py` | 5 | 5 days | ≈ **0.06 bars** |

The intended ~1-day train/test separation is, in every case, under two bars -- and at 1h and 1d,
under one. The fold boundary also lands at an arbitrary row index, so it splits *inside* a single
`bar_ts`: some symbols of that bar are in train, the rest in test.

## Why it is a P1 and not a P0

The magnitude is bounded and small, by arithmetic, not by hope. With `n_folds=5` there are 5
boundaries; the target is `return_fast` (`alpha.ic.lookahead.fast = 1`, executable open-to-open,
so realized ~2 bars ahead). Rows whose target window overlaps the test segment are confined to
~2 bars x ~80 symbols ≈ 160 rows per boundary, ~800 rows total, against ~2M (1h) to ~8.5M (15m)
training rows. **This does not plausibly explain a 0.18-0.25 cross-sectional-neutral point_ic.**

It is still wrong, it is still cited as a rigor credential in
`docs/research/data-edge-source-thesis.md`, and it is cheap to fix.

## Fix

Convert the embargo to bar units at the call site before it reaches `build_walk_forward_folds`
(multiply by the panel's rows-per-bar, or -- better -- build folds over the distinct `bar_ts`
index and map back to row slices, which also removes the split-inside-a-bar behavior). Then
re-run 1h/15m/1d and record whether the numbers move. `build_walk_forward_folds` itself is
correct and shared with `ic_engine.py`/`ensemble_ic_engine.py`, where `n_valid` genuinely IS a
bar count -- **do not change the shared function**; the defect is local to the
nonlinear_interaction_combiner callers' pooled-panel usage.

## Cross-refs

- `docs/research/data-edge-source-thesis.md` -- nonlinear_interaction_combiner section (claim corrected there
  2026-08-03, pointing here)
- [todo 240](240-nonlinear-interaction-combiner-baseline-is-single-feature-not-the-linear-ensemble.md) -- the other
  pre-registration gap found in the same review
