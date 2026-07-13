---
status: pending
priority: P3
filed: 2026-07-13
source: doc-organization session — consolidating 106/076/041 (all folded into design docs
  2026-07-13) into one tracked item per user request
---

# Stratification & Classification Registries

Single todo for this cluster. Umbrella doc: `docs/research/stratification-governance-registries.md`.
Canonical docs: `stratification-dimension-unification.md`, `stratification-security-
classification-hierarchy.md`, `stratification-instrument-tag-calibrator.md`.

## Current state, by component

**StratificationDimension (provider contract):** design complete, `Protocol` written. Real work
remaining — writing the actual code, ratifying the `concept_registry` row-grain decision (Option
A vs. B, both fully specced in `concept-unified-registry.md`'s Domain Vetting section) — is
gated on Phase 144's D-05 empirical verdict, currently `BLOCKED-ON-143.1-07` (the corpus re-run
in progress as of filing). See that doc's "Formalization revival note" for the full trigger.

**New candidate dimensions** (correlation regime, liquidity regime, posterior-weighted soft
stratification): specced in `stratification-dimension-unification.md`'s backlog paragraph.
Enter through the same substitution-test + orthogonality gate as every other candidate once the
contract above is real — not a bespoke build, and not gated separately from it.

**Security Classification Hierarchy (GICS-style):** draft design, unscheduled milestone
(individual-equities era, no ROADMAP phase yet). No near-term action.

**Instrument Tag Calibrator:** draft design. Separately, its own canonical doc carries an open
question (tag_vocabulary's 6-category taxonomy has 3-4 concrete design flaws — see
`stratification-instrument-tag-calibrator.md`'s "Open question" section) that should resolve
before or alongside this calibrator's own build, and independently before commodity/fx
`regime_group` entries are ever enabled (unrelated gate, own timing).

## Not yet done

Revive the StratificationDimension formalization once Phase 144's D-05 verdict lands. Everything
else here (new candidates, tag taxonomy audit) either enters through that same gate or has its
own independent, unrelated trigger — see each component's canonical doc, not duplicated here.
