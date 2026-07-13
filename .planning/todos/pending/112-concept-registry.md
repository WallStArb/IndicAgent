---
status: pending
priority: P1
filed: 2026-07-13
source: doc-organization session — consolidating Concept Registry's entry point to match
  Controlled Vocabulary (110) and Stratification & Classification (111)
---

# Concept Registry

Single todo for this system (Type 2 of `docs/research/concept-governance-registries.md`).
Canonical design doc: `docs/research/concept-unified-registry.md`.

**Status:** Design complete (survived 4 review passes, 2026-07-04 through 07-09). Zero
`concept_*` tables exist. Feature Registry (separate live sibling system) already implements the
same lifecycle pattern for `domain='feature'` — 61 rows.

## Scope

Build the four-table MVP (`concept_registry` / `concept_gate` / `concept_transition_log` incl. a
`corpus_build_ref` column / `concept_annotation`), then seed `domain='ensemble_strategy'` from
Phase 142B.1's outcomes: `ic_proportional` as the `active` incumbent (genesis transition row),
E1 (shrunk-IC) and E2 (mean-variance) as evaluated-mechanism `candidate` rows, E3/E4 as
thesis-only `candidate` rows. Beyond the schema and seed data, four design decisions ship with
it: (1) name `ops_ensemble_weight_compare.py`'s win-decision gate as the sole deterministic
status-flipper (invariant 1); (2) `baseline_metric` stores the mean of `min_promotion_consecutive`
evaluations, not the final one, as a winner's-curse guard; (3) per-stratum status resolution —
`status` governs recipe validity, per-stratum champion stays a fact in `ensemble_weights`,
`redundancy_group` displacement disabled for this domain; (4) document the domain's invariant-6
exception (human-authored candidates, OOS A/B as the live-evidence substitute). Explicitly not in
scope: migrating `feature_registry` in (blocked on Phase 143's LIFECYCLE-01 amendments landing
against it first).

Full task-by-task breakdown already written: `docs/plans/2026-07-13-concept-registry-mvp-
implementation-plan.md` (the actual execution spec). [058](../completed/058-concept-registry-mvp-seed-ensemble-strategy.md)
is the original 2026-07-04 scope todo this section summarizes — closed 2026-07-13 as a
duplicate, kept only as frozen historical record for its existing citations.

**Status:** P1, unblocked (build trigger fired 2026-07-04). Deliberately deferred behind P0
measurement-integrity work as of 2026-07-13 (see PRIORITIES.md); plan written, execution not
started.

## Not yet a tracked item

- **Seeding the `regime_model` domain** (folded in from former todo 105, 2026-07-13) — sequenced
  behind 058, details now live in `concept-unified-registry.md`'s `regime_model` section
  ("Seeding sequence").
- `hmm_variant`, `ic_method`, and `confluence` domains are all fully vetted (gate shape,
  effective-N floor, schema fit) in the canonical doc's Domain Vetting section but have no real
  candidate yet — don't file anything until one exists.
