---
status: pending
priority: P1
filed: 2026-09-24
source: found while scoping todo 411's feature catch-up, read against services/ic_engine.py
---

# ic_engine's upstream watermark is not clamped to training_window_end

## What

`_compute_upstream_watermark` (`services/ic_engine.py`, ~line 1140-1170) fingerprints each cell's
inputs with `SELECT MAX(bar_ts), COUNT(*) FROM feature_vectors WHERE symbol = ANY(...) AND tf =
...` and the same over `forward_returns`, with no `bar_ts < training_window_end` bound. IC itself
only reads rows before `training_window_end` (clamped to `alpha.validation.oos_start`), so rows
after the holdout boundary can't change any IC value, but they do move the watermark.

## Why it matters

- Any feature compute for new bars (todo 411's catch-up, or a nightly feature step) invalidates
  every completed cell, forcing a full ~9.5h recompute that changes nothing.
- Doing that catch-up while a recompute is live or resumable throws away its completed cells.
- Blocks automating feature freshness (411 step 2): each nightly run would trigger a full
  recompute.

## What to do

Bound both watermark queries (and any other component, e.g. `market_regimes`, check each) by
`bar_ts < training_window_end`, matching what the cell actually reads. This moves every stored
watermark once, so land it with the next planned full recompute, never mid-run (CLAUDE.md
ic_engine mid-run rule). Test: inserting rows after training_window_end leaves the watermark
unchanged; inserting one before moves it.
