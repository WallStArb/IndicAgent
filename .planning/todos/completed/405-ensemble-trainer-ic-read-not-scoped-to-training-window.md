---
status: completed
priority: P2
filed: 2026-09-24
source: post-176 bundle code review (todo 389 finding), verified against services/ensemble_trainer.py
---

# ensemble_trainer's stratum IC read is not scoped to a training window

## What

`EnsembleTrainer._process_stratum` (`services/ensemble_trainer.py`, the `ic_rows` query) selects
eligible `feature_ic_scores` rows by symbol/tf/regime/significance only. It has no
`training_window_end` filter, so once more than one window exists every window's rows compete in
`select_features_per_stratum`, including rows computed under older code or a since-deleted scale
(todo 389 removed 5m/15m `fast`). Today only one window exists (2025-12-24 05:15 UTC), and the
post-176 recompute archives and deletes every invalidated cell's rows across all lookaheads, so
nothing is wrong yet.

## Fix direction

Pin the read to one window: the same `--training-window-end` the pipeline passes to ic_engine and
feature_lifecycle (or `alpha.validation.oos_start`). Consider also filtering to
`alpha.ic.active_scales.{tf}` lookaheads so a deleted scale can never be selected from old rows.
Land before a second training window is ever written.

## Update 2026-09-24

c6750d700 (Phase 179 stratum_fit extraction, todos 408/409) made the failure loud: a stratum
whose selected IC rows span more than one `training_window_end` now raises `ValueError` instead
of silently mixing windows. The read itself is still unpinned, so this todo stays open: the first
second window would stop the trainer rather than corrupt it.

## Closure (2026-09-24)

Wider than filed: the trainer's startup gate, meta-FDR pass-rate query and strata enumeration
were unscoped too (the meta-FDR mix would have been silent; the stratum_fit guard only covers the
stratum read), and ops_ic_shrinkage had the same flaw, with its leave-one-out prior bucketed on
(group_name, regime, tf) across windows. Fixed: both take `--training-window-end` (the pipeline
passes `$TRAINING_WINDOW_END`), and when it is omitted they use the only window the eligible or
reliable rows carry and raise on two or more. Every read is pinned to that window, the trainer
passes it explicitly to `_process_stratum`, and the shrinkage bucket key now includes
training_window_end. Live check at the 2025-12-24 window: scoped and unscoped counts are
identical (1,910,542 reliable rows, 69,346 pooled cells), so today's output is unchanged. Scale
filtering (the todo's "consider") is not added: the window pin already excludes rows from a scale
deleted before that window's recompute.
