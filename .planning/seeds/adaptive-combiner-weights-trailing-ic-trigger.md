---
title: Adaptive Combiner Weights (EWMA/Kalman trailing-IC weighter update)
trigger_condition: "feature_ic_scores_history has >= 3 distinct training_window_end snapshots"
planted_date: 2026-08-07
status: dormant
---

# Adaptive Combiner Weights — queued behind real trailing-IC data existing

Signal-Extraction candidate `adaptive_combiner_weights`: let `ensemble_trainer.py`'s shrunk-IC
weights drift continuously (EWMA/Kalman) instead of only on periodic batch recomputes. Blocked
today on data, not design — `feature_ic_scores_history` has exactly one `training_window_end`
snapshot, mathematically degenerate for fitting a halflife. Accumulates for free via
`ic_engine.py`'s existing archive-before-overwrite step every full corpus recompute; not worth
accelerating artificially.

**Full design, cost/consumer analysis, and duplicate-tracking reconciliation (todo 080's L5-4):**
`docs/research/measurement-adaptive-combiner-weights.md`. This file is only the trigger tracker —
don't duplicate that doc's reasoning here.

## When this trigger fires

`SELECT count(DISTINCT training_window_end) FROM feature_ic_scores_history` >= 3. Promote to a
todo, write a pre-registered halflife grid (exact values fixed before running — three halflives
spanning an order of magnitude, motivated by recompute cadence, BH-FDR across the grid), compare
OOS IC/Sharpe against current periodic-batch weights.

## References

- `docs/research/measurement-adaptive-combiner-weights.md` — full design
- `docs/research/data-edge-source-thesis.md` — thesis summary
