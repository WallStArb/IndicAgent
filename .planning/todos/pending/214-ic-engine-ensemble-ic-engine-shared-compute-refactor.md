---
status: pending
priority: P2
filed: 2026-07-30
source: user question mid-session, prompted by todo 210's root cause -- filed rather than
  actioned since it landed mid-way through a live forward_returns rebuild
---

# `ic_engine.py` (5,239 lines) and `ensemble_ic_engine.py` (1,523 lines) independently
# duplicate the same per-(symbol/pooled, tf, scale) compute pattern -- exactly the
# duplication that let todo 210's bug exist undetected

## Problem

`ic_engine.py` is 5,239 lines; `ensemble_ic_engine.py` is 1,523. Both implement their own
version of: fetch returns/completeness per scale, iterate scales (`_SCALES` or
`active_scales_for(tf)`), rank-IC computation, walk-forward folds. `ensemble_ic_engine.py`
was clearly written by copying `ic_engine.py`'s shape rather than sharing it — and the
copy silently diverged: `ic_engine.py` correctly masks on `complete_{scale}` before
computing IC; `ensemble_ic_engine.py`'s `_run_ensemble_ic_worker` never did (todo 210).
That's not a one-off mistake, it's what happens when the same logic exists in two places
with no shared source of truth — the next divergence is only a matter of time.

## Why not fixed now

Found mid-session while a live `forward_returns` rebuild (todo 208) is in flight. Refactoring
the compute path while its correctness semantics are actively changing would conflate two
different kinds of change and make it much harder to verify either is right. Do this once
the current IC measurement chain (208's fix, a fresh corpus rebuild, 210/209/211's fixes) is
proven stable again — refactoring on top of settled, verified behavior, not moving semantics.

## What to look at

- Extract the shared per-(entity, tf, scale) compute core (fetch → mask on `complete_{scale}`
  → subsample/stride → rank-IC → walk-forward folds) into one function/class both
  `ic_engine.py` and `ensemble_ic_engine.py` call, instead of two independent
  implementations.
- Audit whether `ic_engine.py`'s 5,239 lines split cleanly along existing seams (per-symbol
  vs. cross-sectional/pooled compute, IC math, DB I/O, CLI/orchestration) — likely several
  files' worth of responsibility currently living in one module.
- Whatever shape this takes, the goal is one path both engines call, not a second
  hand-synced copy — that's what silently broke this time.

## Sizing

Real, multi-file refactor — not a quick pass. Scope as its own plan once picked up, not a
quick task.
