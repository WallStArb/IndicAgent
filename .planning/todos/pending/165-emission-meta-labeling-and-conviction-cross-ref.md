# 165 — Emission: meta-labeling gate (new) + conviction column (cross-ref, don't duplicate EM-CAL)

**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §9 (L6-1, L6-3).
**Reconciliation note:** a separate, independent Fable review of the emission layer already
exists — `docs/research/measurement-alpha-emission.md` (dated 2026-07-07) — with its own filed
todo, `.planning/todos/pending/065-emission-layer-calibration-proposals.md` (EM-CAL/EM-STAMP/
EM-RANK/EM-HYST). **L6-2 (hysteresis) from this doc directly duplicates EM-HYST — do not build
both, EM-HYST is the canonical version.** L6-1 (conviction column) partially overlaps EM-CAL but
proposes a different v1 mechanism (pure CI-margin geometry vs. EM-CAL's statistical calibration
sweep) — worth keeping as a cheap v1 that EM-CAL's calibrated version can later replace, not a
competing build. L6-3 (meta-labeling) is genuinely new, not covered by either doc.

## L6-1 — Continuous conviction column (v1, geometry-only; superseded by EM-CAL's calibrated version later)

Emit `conviction ∈ [0,1]` alongside the binary decision. v1 definition (no new models): CI margin
over the cost hurdle, e.g. `(alpha_ci_lower - cost_hurdle) / (alpha_ci_upper - alpha_ci_lower)`
clamped, for longs (mirrored for shorts) — pure geometry over columns already emitted. v2 replaces
it with EM-CAL/0c-calibrated P(sign correct) once that ships. Falsifiable via 142B frames:
conviction-weighted counterfactual Sharpe must beat flat-weighted on OOS frames, else the column
is decoration and says so. One column in `alpha_events` + ~20 lines in the publisher.

## L6-3 — Meta-labeling gate (post-142B, queued not built)

A secondary model taking the primary emission's context (regime, conviction, dispersion, recent
frame outcomes) and predicting P(this event's frame pays), used to size or veto — the classic
Lopez de Prado meta-labeling structure. A genuinely new model class in the stack, which is exactly
why it must wait for its training data (`alpha_frames` outcomes, 142B) and enter as a governed
predictor with its own OOS gate and shadow period. Named now so the frames schema keeps what it
needs (it does: frame outcome + event context join is sufficient) — no action before 142B ships.
