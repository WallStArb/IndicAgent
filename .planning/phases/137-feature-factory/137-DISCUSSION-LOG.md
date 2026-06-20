# Phase 137: Feature Factory - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-20
**Phase:** 137-feature-factory
**Areas discussed:** I7 cutover timing, Missing canonical refs, pipeline_version migration
**Session:** Update to prior context (prior context: 2026-06-20 council deliberation)

---

## I7 Cutover Timing

**Background:** The prior CONTEXT had an internal conflict — D-09 said I5-I7 is archived and removed from dispatch in Phase 137, but the Deferred section said I5-I7 "remains live in production during Phase 137."

| Option | Description | Selected |
|--------|-------------|----------|
| Phase 137 ends with cutover | Feature Factory is built, backfill verified, wired into IntelligencePipeline, then plugin registry dispatch removed and I5-I7 archived as Phase 137's final task. | ✓ |
| Phase 137 adds Feature Factory in parallel only | I7 keeps running throughout Phase 137; cutover is Phase 138's opening task. | |

**User's choice:** Phase 137 ends with cutover.

---

| Option | Description | Selected |
|--------|-------------|----------|
| Wire in shadow, validate, then cut | FeatureFactory runs alongside I7 for N days with both tables receiving writes, spot-check, then atomic cutover. | |
| Wire and cut atomically | Once FeatureFactory passes unit tests and backfill verification, wire and remove plugin dispatch in one deploy. No parallel period. | ✓ |

**User's choice:** Atomic wire-and-cut (user challenged the need for shadow period).

**Notes:** User asked why we would run both in parallel if I7 is being retired. This is the correct call: I7 and FeatureFactory are not equivalent systems writing to the same table — they write to different tables, produce different outputs, and serve different purposes. Shadow mode is for replacing equivalent systems to compare outputs. There is nothing to compare here. Validation comes from unit tests + backfill verification + live smoke test, not from parallel execution.

---

| Option | Description | Selected |
|--------|-------------|----------|
| Backfill verified + live bar flowing + I7 archived | Phase 137 done when: feature_vectors rows within 5% of theoretical max per (symbol,tf), live 1m bar produces FeatureVector row, I5-I7 in archive, zero plugin dispatch refs in IntelligencePipeline, unit tests green. | ✓ |
| Unit tests green only | Phase 137 done when unit tests pass; live verification is Phase 138's job. | |

**User's choice:** Full done gate (backfill verified + live bar + I7 archived).

---

## Missing Canonical Refs

**Background:** Two docs written during the 2026-06-20 methodology session were not referenced in the prior CONTEXT: `v30-alphaengine-strategy.md` (strategic "why") and `v30-i7-transition.md` (I7 transition path).

| Option | Description | Selected |
|--------|-------------|----------|
| Archive all of I5-I7 intact — deletion is Phase 138's job | Phase 137 moves all I5/I6/I7 code to archive/ without modification. Phase 138 IC discovery determines which plugins survive as alpha scorers; Phase 138 prunes the rest. | ✓ |
| Archive I5/I6 only; restructure I7 into alpha_scorers/ | Phase 137 begins the I7 transformation. | |

**User's choice:** Archive all of I5-I7 intact — Phase 138 handles the transformation.

**Notes:** Both missing docs added to canonical refs in CONTEXT. The I7 transition doc specifically informs the archival approach: preserve everything, Phase 138 is responsible for IC-based pruning and alpha scorer transformation.

---

## pipeline_version Migration

**Background:** STATE.md from the prior session noted "pipeline_version migration required on `intelligence_features` before Phase 137." The IC spec §IV.1 says "no migration needed" because `feature_vectors` already has `pipeline_version` in its DDL.

| Option | Description | Selected |
|--------|-------------|----------|
| No — IC spec resolved this | IC spec confirms `feature_vectors` has pipeline_version in DDL. `intelligence_features` is not used in v3.0. The STATE note was resolved during methodology work. | ✓ |
| Yes — add pipeline_version to intelligence_features | Add a watermark column to intelligence_features to mark where v2.x data ends. | |

**User's choice:** No migration needed — resolved by IC spec.

**Notes:** Captured as D-13 in CONTEXT to explicitly close the open item from STATE.md.

---

## Claude's Discretion

None — all three areas had clear user decisions.

## Deferred Ideas

None — discussion stayed within Phase 137 scope. User's Renaissance council framing note applied throughout: treat each decision as a first-principles structural choice, not a preference.
