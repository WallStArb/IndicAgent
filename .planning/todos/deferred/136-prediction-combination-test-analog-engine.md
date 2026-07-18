---
status: deferred
priority: not yet triaged
filed: 2026-07-18
corrected: 2026-07-18 (same-day Fable review caught two defects — see "Correction" below)
source: docs/priorities reconciliation pass — found while resolving the orphaned
  "Unified Orthogonalization Layer" plan doc (Phase 162 numbering collision)
gate: PrecedentEngine (ROADMAP Phase 150) must exist and be emitting scores before this is runnable
---

# Precedent predictor family — does it add ensemble-level IC beyond parametric features?

## Correction (2026-07-18, same-day Fable review)

Originally filed as "AlphaEngine vs. AnalogEngine incremental-R² combination test" — wrong on
two counts, both caught same-day:

1. **Stale naming.** "AnalogEngine" was renamed to **PrecedentEngine** 2026-07-09 (ROADMAP.md),
   *before* this todo was filed 2026-07-18 — cited a doc (`intel-13-analog-engine.md`) that
   doesn't exist. Should have verified before citing, per this project's own "verify then delete,
   don't flag" convention.
2. **Architecturally moot premise.** Decision D4 (`.planning/ROADMAP.md`, PRECEDENT-01 section)
   already settles this: precedent outputs are "ordinary predictor[s]... entering the same
   pipeline as every parametric feature, **not a second system**." There is no second engine
   emitting an independently-combinable score stream — one measurement engine, one ensemble, one
   book. A 2-engine incremental-R² combination test has no architecture to run against.

## What (corrected)

The real residual question, once PrecedentEngine (Phase 150) exists: does the **precedent
predictor family** (case-based/nearest-neighbor predictors PrecedentEngine emits into
`feature_ic_scores`/`predictor_ic_scores`) add ensemble-level IC beyond the parametric feature
family, after the ensemble's existing Ledoit-Wolf `|corr|` cluster deflation has already run? A
family-level ablation (with vs. without precedent predictors in the ensemble), not a combination
test between two parallel systems — there's only one system, per D4.

Some of the original math spec still applies conceptually (incremental value measurement), but
the mechanism is different: this is an ablation on `ensemble_trainer`'s existing weighting output,
not a new weekly batch combining two score streams. Needs its own design pass when picked up, not
a literal reuse of `docs/research/unified-orthogonalization-layer.md`'s Phase 162.2 math as
originally filed.

## Why deferred, not pending

PrecedentEngine (ROADMAP Phase 150) doesn't exist yet. Not urgent — nothing to ablate until the
predictor family is live and measured.

## Gate

Revive once Phase 150 ships and the precedent predictor family has real rows in
`feature_ic_scores`/`predictor_ic_scores`. At that point this is a real, well-specified ablation
question — not a design question, and not the combination-test shape originally filed here.

## References

- `.planning/ROADMAP.md` — Phase 150 ("PrecedentEngine — Case Predictors + Measurement
  Integration"), and the D4 decision (PRECEDENT-01 section) this correction is built on
- `docs/research/intel-precedent-engine.md` — PrecedentEngine spec (current name/location,
  corrected from the stale "intel-13-analog-engine.md" citation)
