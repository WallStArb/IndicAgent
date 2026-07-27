---
status: pending
priority: P2
filed: 2026-07-26
source: /simplify altitude review of scripts/analysis/t5_nonlinear_combiner_lightgbm_check.py
---

# `ic_math.py` has a per-symbol circular block bootstrap but no cross-sectional (pooled-panel) variant — every future T3/T5-style dollar-neutral test approximates this ad hoc

## Finding

`circular_block_bootstrap_ic_serial` (`src/intelligence/statistics/ic_math.py`) was built for a
single time series per symbol — `block_size` means "consecutive observations of one symbol's
own history." T5's within-bar_ts (cross-sectional-neutral) rigor check needed a block bootstrap
over a POOLED, multi-symbol panel instead, where a legitimate resampling block should span a
short window of TIME across the WHOLE symbol universe (matching how `ic_engine.py`'s own
cross-sectional pass already chunks by time via `cs_chunk_ts`, not by symbol).

The script approximates this with `block_size = n_symbols_per_bar * _CROSS_SECTIONAL_BLOCK_BARS`
— a reasonable first pass, explicitly not a final calibration (same category of approximation
todo 133 solved properly for `cross_sectional_bootstrap_threads` via real measurement, not a
guessed constant). Any future T3/T5-style cross-sectional/dollar-neutral construction test will
need the identical machinery and will either reinvent this same fudge or, worse, get the block
structure wrong in a way that under/overstates significance.

## Fix

Add a cross-sectional block bootstrap variant to `ic_math.py` — e.g.
`cross_sectional_block_bootstrap_ic(X_raw, Y_raw, bar_ts_groups, n_bar_blocks, n_boot, rng)` —
that resamples blocks of N consecutive bar_ts values (each block carrying its full
cross-section), analogous to `_circular_block_bootstrap_ic`'s per-symbol time-block design but
operating on a panel. Calibrate `n_bar_blocks` empirically per tf, same discipline as todo
133's `bootstrap_block_size`/`cross_sectional_bootstrap_threads` — measure real wall-clock and
CI-width sensitivity, don't guess a constant.

## Why this wasn't fixed inline

Lower urgency than todo 185 (the demeaning primitive) — the current approximation is
conservative enough for an exploratory falsification test and the script says so explicitly.
Building and calibrating a new statistical primitive is real, standalone work that shouldn't
block a one-off research script; do this once a second consumer (a real T3/T5 production
candidate, not just the exploratory test) actually needs it.

## References

- `scripts/analysis/t5_nonlinear_combiner_lightgbm_check.py` — the approximated `block_size`,
  see the "Rigor pass" section and its trailing note
- `.planning/todos/completed/133-cross-sectional-bootstrap-threads-not-per-tf.md` — the
  measure-first calibration discipline this todo should follow
- `src/intelligence/statistics/ic_math.py:207` (`_circular_block_bootstrap_ic`) — the
  per-symbol sibling this primitive generalizes
