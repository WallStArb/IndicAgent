---
status: planned
priority: P2
filed: 2026-08-04
source: brainstorming session tracing todo 179's closed "is there an expectancy floor at
  emission time" question -- confirmed via direct code read that alpha_publisher.py's
  emission gate has none. Scoped as pure reusable infrastructure (no live consumer),
  since todo 179 itself closed with no proven edge anywhere in the construction that
  would have used it.
---

# Extract `frame_gate_passes`/`evaluate_frame_gate` into `src/intelligence/statistics/gate_math.py`, add `evaluate_stratum_expectancy_gate`

## What

`services/counterfactual_tracker.py` defines the day-clustered bootstrap gate machinery
(`frame_gate_passes`, `evaluate_frame_gate`) that `services/cross_sectional_spread_tracker.py`
already cross-imports -- a Ring 2 service reaching into another Ring 2 service's internals for
what is actually generic statistics with zero DB/Kafka/daemon dependency of its own. Extract it
into a proper Ring 1 module (`src/intelligence/statistics/gate_math.py`, mirroring
`ic_math.py`'s existing precedent for exactly this situation), and add one new named
specialization -- `evaluate_stratum_expectancy_gate` -- for the `(regime, direction)`
stratification question todo 179 had to answer ad hoc with a scratchpad script.

Pure reusable infrastructure only. No live wiring into `alpha_publisher.py` or any
construction -- todo 179 (`.planning/todos/completed/179-gate166-concurrent-exposure-
diagnostic.md`) already closed with "zero regime/direction slice in the per-symbol directional
construction shows a real, replicating, non-circular positive expectancy," so there is
currently nothing proven to gate. This exists as tested, ready infrastructure for whenever a
real consumer needs it.

## Design + plan

- Design doc: `docs/plans/2026-08-04-stratum-expectancy-gate-design.md`
- Implementation plan: `docs/plans/2026-08-04-stratum-expectancy-gate-plan.md` (4 tasks:
  extraction + equivalence test, repoint `counterfactual_tracker.py`, repoint
  `cross_sectional_spread_tracker.py`, add `evaluate_stratum_expectancy_gate` + tests)

## Cross-refs

- [todo 179](../completed/179-gate166-concurrent-exposure-diagnostic.md) -- the closed
  investigation whose open code-level question this answers
