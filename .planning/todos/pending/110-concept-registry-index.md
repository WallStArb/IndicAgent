---
status: pending
priority: index
filed: 2026-07-13
source: doc-organization session — consolidating scattered Concept Registry sub-items
  under one entry point, per user request
---

# Concept Registry — index

Single entry point for Concept Registry (Type 2 of `docs/research/concept-governance-registries.md`).
Canonical design doc: `docs/research/concept-unified-registry.md`. This todo is a pointer, not a
build spec — full scope lives in each sub-item below; don't duplicate content here.

**Status:** Design complete (survived 4 review passes, 2026-07-04 through 07-09). Zero
`concept_*` tables exist. Feature Registry (separate live sibling system) already implements the
same lifecycle pattern for `domain='feature'` — 61 rows.

## Sub-items

| Todo | Priority | Status | Gate |
|---|---|---|---|
| [058](058-concept-registry-mvp-seed-ensemble-strategy.md) — Build the 4-table MVP, seed `ensemble_strategy` | P1 | pending | None — build trigger fired 2026-07-04. Deliberately deferred behind P0 measurement-integrity work as of 2026-07-13 (see PRIORITIES.md); plan written and saved (`docs/plans/2026-07-13-concept-registry-mvp-implementation-plan.md`), execution not started |
| [105](105-concept-registry-regime-model-domain-seed.md) — Seed `regime_model` domain from Phase 144 evidence | P3 | pending | Sequenced behind 058 (needs the MVP tables to exist first) |

**Not yet a tracked item:** `hmm_variant`, `ic_method`, and `confluence` domains are all fully
vetted (gate shape, effective-N floor, schema fit) in `concept-unified-registry.md`'s Domain
Vetting section but have no todo — correctly so, since none has a real candidate yet. Don't file
one until a candidate exists in one of them.
