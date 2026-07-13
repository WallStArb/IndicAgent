---
status: pending
priority: index
filed: 2026-07-13
source: doc-organization session — consolidating scattered Stratification/Classification
  sub-items under one entry point, per user request
---

# Stratification & Classification Registries — index

Single entry point for the stratification/classification doc cluster. Umbrella doc:
`docs/research/stratification-governance-registries.md`. This todo is a pointer, not a build
spec — full scope lives in each sub-item below; don't duplicate content here.

## Sub-items

| Todo | Priority | Status | Gate |
|---|---|---|---|
| [106](../deferred/106-formalize-stratification-dimension-contract.md) — Formalize the `StratificationDimension` provider contract | P3 | deferred | Phase 144's D-05 empirical verdict (`BLOCKED-ON-143.1-07`, the corpus re-run currently in progress) — design-only, not a build |
| [076](../deferred/076-new-stratification-dimensions-correlation-liquidity-posterior.md) — New candidate dimensions (correlation/liquidity/posterior-weighted IC) | medium-high | deferred | Letter of the gate ("Phase 144 must ship first") is now satisfied — Phase 144 is code-complete. Practically still follows the same corpus-run/D-05 checkpoint as 106 before reviving |
| [041](../deferred/041-tag-vocabulary-category-audit.md) — Audit the 6-category `tag_vocabulary` taxonomy | P3 | deferred | Unrelated timing — gated on commodity/fx `regime_group` enablement, not on the corpus run |

**Not yet a tracked item:** Security Classification Hierarchy (`stratification-security-
classification-hierarchy.md`) and the Instrument Tag Calibrator's actual empirical calibration
build (`stratification-instrument-tag-calibrator.md`) both have design-complete docs but no build
todo — same gap as Controlled Vocabulary (see todo 111). Neither is scheduled; don't file a todo
until one is actually being planned.
