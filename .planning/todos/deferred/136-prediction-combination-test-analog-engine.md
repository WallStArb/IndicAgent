---
status: deferred
priority: not yet triaged
filed: 2026-07-18
source: docs/priorities reconciliation pass — found while resolving the orphaned
  "Unified Orthogonalization Layer" plan doc (Phase 162 numbering collision)
gate: AnalogEngine (Phase 149+) must exist and be emitting scores before this is runnable
---

# Prediction-level combination test — does AlphaEngine + AnalogEngine beat either alone?

## What

Once AnalogEngine exists and emits scores alongside AlphaEngine, test whether combining the two
predictions adds incremental value over the better single method — not assumed, measured.

Full math spec already written (not lost, just premature): `docs/research/unified-orthogonalization-layer.md`'s
Phase 162.2 section (superseded as a phase, math kept as reference) —
`incremental_r2_combination(scores_a, scores_b, targets, weight_grid)`: compute OOS R² for each
method independently, grid-search combination weights, bootstrap CI on the incremental R² delta.
Decision framework already specced too: adopt combination if ΔR² consistently positive, retire
the weaker method if ΔR² ≈ 0, investigate regime-dependence if ΔR² is variable.

## Why deferred, not pending

AnalogEngine (ROADMAP Phase 149+) doesn't exist yet — the test's own dependency ("both prediction
engines emitting") can't be satisfied. Not urgent: there's nothing to combine yet, and this
doesn't block AnalogEngine's own build.

## Gate

Revive once AnalogEngine is shipping real scores. At that point this becomes a real, well-
specified measurement task (weekly batch, `prediction_combination_results` table, existing
bootstrap-CI machinery) — not a design question.

## References

- `docs/research/unified-orthogonalization-layer.md` — full math spec (Phase 162.2 section)
- `docs/research/intel-13-analog-engine.md` (or current name) — AnalogEngine spec, the actual gate
