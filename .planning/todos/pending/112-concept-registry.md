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

## Current actionable work

[058 — Build the Concept Registry MVP and seed `ensemble_strategy`](058-concept-registry-mvp-seed-ensemble-strategy.md)
— P1, unblocked (build trigger fired 2026-07-04). Deliberately deferred behind P0
measurement-integrity work as of 2026-07-13 (see PRIORITIES.md); implementation plan already
written and saved (`docs/plans/2026-07-13-concept-registry-mvp-implementation-plan.md`),
execution not started.

## Not yet a tracked item

- **Seeding the `regime_model` domain** (folded in from former todo 105, 2026-07-13) — sequenced
  behind 058, details now live in `concept-unified-registry.md`'s `regime_model` section
  ("Seeding sequence").
- `hmm_variant`, `ic_method`, and `confluence` domains are all fully vetted (gate shape,
  effective-N floor, schema fit) in the canonical doc's Domain Vetting section but have no real
  candidate yet — don't file anything until one exists.
