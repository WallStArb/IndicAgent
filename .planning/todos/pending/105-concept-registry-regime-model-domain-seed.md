---
status: pending
priority: P3
filed: 2026-07-12
source: Phase 144 execution session — user question on Concept Registry / Security
  Classification Hierarchy overlap with regime_group
---

# Seed Concept Registry's `regime_model` domain from Phase 144's `regime_group` evidence

## Finding

Phase 144 (`regime_group`) ships two things that are exactly the shape
`docs/research/platform-unified-concept-registry.md`'s `regime_model` domain is designed to
govern, but Concept Registry itself doesn't exist yet (only its MVP build is tracked, todo 058,
seeded with `ensemble_strategy` as domain #1 — `regime_model` is vetted in that doc's Domain
Vetting section but explicitly not seeded into the live `domain` CHECK):

1. **`alpha.regime.groups[].enabled`** — a flat APR boolean per group (equity/rates enabled,
   commodity/fx disabled pending todo 041). This is an ungoverned on/off flag where Concept
   Registry would instead carry a status enum (`active`/`shadow`/`deprecated`/`candidate`) with
   an evidence-backed transition log.
2. **Phase 144's own D-05 acceptance gate** (`144-06-PLAN.md` — TLT-vs-rates cross-sectional IC
   separation, pre-committed falsifiers F1/F2, todo 026's 0.01/0.05 bands) produces exactly the
   kind of promotion/demotion evidence `concept_transition_log` exists to store permanently and
   queryably. As shipped, this verdict lands in a SUMMARY.md and a todo file — the "notebook
   nobody reads" failure mode the Concept Registry doc explicitly calls out.

## Not yet done

- Concept Registry itself is unbuilt (0 `concept_*` tables as of todo 058's filing).
- Once todo 058 ships (`ensemble_strategy` domain MVP), this todo is the natural follow-on:
  seed `regime_model` as domain #2, using Phase 144's `alpha.regime.groups` config + the D-05
  gate's verdict as the first real rows/transition-log entries.
- The concept_registry row-grain question (one row per dimension vs. one row per
  `(dimension, regime_group)`) is flagged as open in Phase 144's CONTEXT.md (citing
  `docs/research/fable-2026-07-07-phase144-conditioning-decision.md` §6 Input 3) — resolve at
  this todo's build time, not before; both options are fully specced in the Concept Registry
  doc's Domain Vetting section already.
- Not urgent: no live consumer reads `regime_model` lifecycle state today (Phase 144's APR
  boolean works fine operationally); this is a governance/auditability upgrade, not a
  correctness fix. Sequenced behind todo 058.

## References

- `docs/research/platform-unified-concept-registry.md` (Domain Vetting section — `regime_model`
  already fully specced: gate shape, effective-N floor, schema fit)
- `.planning/todos/pending/058-concept-registry-mvp-seed-ensemble-strategy.md` (prerequisite —
  builds the 4-table MVP this todo would extend)
- `.planning/phases/144-cross-sectional-regime-model-regime-group-planned/144-CONTEXT.md`
  (Deferred section — the row-grain question)
- `.planning/phases/144-cross-sectional-regime-model-regime-group-planned/144-06-PLAN.md` (the
  D-05 acceptance gate whose verdict this todo would eventually migrate into
  `concept_transition_log`)
