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

## Update 2026-09-24: landed, live verification pending

Fixed on main (this commit): the forward_returns, feature_vectors and market_regimes watermark
queries are bounded `<= training_window_end`, the same comparison every cell fetch uses, and
`_compute_upstream_watermark` takes the window as a required keyword. Found alongside: the
feature_vectors component is MAX/COUNT only and its comment relied on "a feature-code change moves
code_content_key", but ic_engine never imported the producers, so a producer-code change plus a
`--refresh` rewrote values under a valid fingerprint. `_checkpoint_content_key` now imports
`backfill_feature_factory` (feature_factory) and `regime_writer` (owner of `regime_volatility`
and 15 other columns) so their code is hashed; the import is inside the function (main process
only), not at module top, to keep ~300 MB out of every forkserver worker.

Close after: the next full recompute completes, `--dry-run-validity` reports 0 invalid cells,
the 411 catch-up adds post-window bars, and `--dry-run-validity` still reports 0 invalid.

## Triage 2026-09-26 (backlog review with the owner)

On the feature critical path: todo 435 wires `feature_vectors` into the research layer, so fresh, complete, correct features are a book input.
