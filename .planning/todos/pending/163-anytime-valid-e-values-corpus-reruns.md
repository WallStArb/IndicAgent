# 163 — Anytime-valid inference (e-values) across corpus reruns

**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §7 (L4-1),
executive summary item 6.
**Priority:** medium-high — genuinely new math for this codebase; pilot on one tf before any
wider rollout, per the source doc's own caution.
**Gate:** none structural, but deliberately staged as a pilot, not a full rollout, given it's a
new statistical primitive for the project.

## Problem

The corpus has been rebuilt 3+ times and reruns are now routine cadence. Each rerun recomputes
p-values over heavily overlapping data, and the BH-FDR correction is *within-run* only — nothing
accounts for the same hypothesis ("momentum_z_fast predicts 5m returns in high_bear") having now
been examined N times, with promotion possible after whichever look happens to flatter it.
Classical p-values don't compose across looks; e-values do (multiply across runs, Ville's
inequality gives always-valid error control).

## Proposal

Persist a per-cell e-process updated each corpus run (a likelihood-ratio or universal-inference
e-value on the IC sign is enough). Promotion requires cumulative e-value > 1/alpha, demotion
symmetric. Evidence becomes a running account rather than a per-run snapshot — "wait for another
rerun and see if it passes" stops being a free re-roll. This directly hardens the Concept
Registry invariant #2 ("no re-roll on same corpus build") into its stronger form: no free re-roll
on *any* build.

## Verdict path / mechanics

The e-process is self-checkable against the canary predictors (todo 152) — canary e-values must
decay toward zero. This *removes* an unaccounted multiplicity surface rather than adding one. A
kernel function (`ic_math.py` sibling) + one column per cell + manifest plumbing; no new service.
Pilot on one tf first given this is genuinely new math for the codebase.
