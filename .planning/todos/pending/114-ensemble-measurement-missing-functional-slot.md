---
status: pending
priority: P3
filed: 2026-07-13
source: naming-convention rigor pass (PrecedentEngine rename + ICEngine/MeasurementEngine
  discussion) — found while cross-checking glossary.md's Functional Layer Vocabulary
---

# Broaden `predictive measurement`'s definition to cover its ensemble-level recurrence

**Revised same day — original version of this todo proposed a new 8th slot; corrected after
further discussion to a simpler fix.** `docs/foundation/glossary.md`'s "AlphaEngine Functional
Layer Vocabulary" names 7 generic pipeline slots: `feature measurement -> feature synthesis ->
regime classifier -> predictive measurement -> ensemble optimizer -> alpha scorer -> alpha
emitter`.

`predictive measurement` is already explicitly generic over *method* ("IC is one predictive
measurement method; the slot can hold others" — MI, R²_OOS named as valid future
implementations). Its wording is narrower than its own intent, though: "measures whether each
**feature in the FeatureVector** predicts forward returns" — that's an accident of only
feature-level IC existing when it was first written, not a real conceptual boundary.

Phase 142A's ensemble-level measurement (`ensemble_ic_engine.py` -> `alpha_ensemble_ic`, read by
the EIC-04/FRAME-04 Phase 148 gates) does the *same operation* — IC of a predictor column against
forward returns, stratified by regime/tf/lookahead — just on a different input (`alpha_score`
instead of a feature column) and at a different pipeline position (after `alpha scorer`, instead
of before `ensemble optimizer`). Not a different kind of slot; the same slot recurring at a
second point in the pipeline on a different grain.

**What to do:** edit `predictive measurement`'s glossary entry to state it recurs at two pipeline
positions — feature-grain (pre-weighting, `ic_engine.py`) and ensemble-grain (post-scoring,
`ensemble_ic_engine.py`) — rather than adding a new slot name. Update the 7-slot pipeline diagram
to show the recurrence (e.g. an annotation or a second arrow back to the same slot name after
`alpha scorer`), not a new box. Cross-referenced from the `MeasurementEngine` glossary entry
already (2026-07-13) — this todo is the actual fix.

Cheap, docs-only, no code/schema change. Do during a future glossary/naming touch, not urgent on
its own.
