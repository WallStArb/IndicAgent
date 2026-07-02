---
title: EnsembleICEngine never produces a pooled cross-sectional (symbol='POOLED') row
status: pending
discovered_by: phase-142A (code review, WR-02)
discovered: 2026-07-02
resolves_phase: null
---

## What

`EnsembleICEngine._execute_inner` builds `symbol_tf_pairs` exclusively from
`SELECT DISTINCT symbol, tf FROM alpha_events`, which (confirmed against the live DB)
only ever contains real ticker symbols — never `symbol = 'POOLED'`. As a result the
engine never constructs or dispatches a pooled cross-sectional alpha_score series, so
every row it writes has `is_pooled = false`.

This means, despite being fully built out:
- Migration 195's `alpha_ensemble_ic_pooled_symbol_consistent` CHECK constraint is
  only ever exercised on the `is_pooled = false` branch.
- `_calibrate_hold_max_bars`'s `if row.get("is_pooled"): continue` exclusion
  (`services/ensemble_ic_engine.py`) is dead code.
- EIC-05 diagnosis Section 2 ("Pooled vs per-symbol IC gap", designed to flag
  "REGIME GRANULARITY ISSUE") can never populate `pooled_ci_lower` and is a
  permanent no-op (`scripts/ops/alpha/ops_ensemble_ic_diagnosis.py:152-181`).

Full finding: `.planning/phases/142A-ensemble-ic-measurement-planned/142A-REVIEW.md` (WR-02).

## Why it matters

The migration schema, `is_pooled` field, and diagnosis tooling all assume this
capability exists — an operator reading the diagnosis report's Section 2 would
reasonably expect it to be populated. Right now it's silently dead, which risks
someone concluding "no regime granularity issue" when the section simply never runs.

## Suggested approach

Two options (from the review):
1. Add a pooled cross-sectional pass to `_execute_inner` that aggregates
   `alpha_score` across all symbols per (tf, regime) and dispatches one additional
   `symbol='POOLED'` worker task per (tf, regime) — matching the design
   `feature_ic_scores`/`ensemble_trainer.py` already use for `symbol='POOLED'` rows.
2. If pooled cross-sectional measurement is deliberately deferred to a later phase
   (e.g. Phase 142B+), update the migration comment, diagnosis script Section 2, and
   the module docstring to say so explicitly rather than leaving fully-built-but-dead
   machinery with no note.
