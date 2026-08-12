# Stratification & Classification Registries

**Status:** Framework proposed, not built. All three components are design-complete or in-draft; nothing here has shipped code yet.
**Type:** Umbrella index — links to canonical docs for the stratification/classification doc cluster
**Last Updated:** 2026-07-16 (Tag Calibrator's ROADMAP Phase 146 status added — it was already fully specced and unblocked in ROADMAP.md but this index and its own canonical doc never named the phase; added the second Concept-Governance-Registries seam, via Controlled Vocabulary's label sets, found while scoping Phase 161's discussion). **Created:** 2026-07-13 — this index didn't exist before; the cluster was previously discoverable only by reading each doc's cross-references to the others, with no single entry point.

---

## What This Is

This is the sibling umbrella to [Concept Governance Registries](concept-governance-registries.md), scoped to a different question: not "what values are tuned" or "what research artifacts earned promotion," but **"what state is the market or instrument in, and what kind of thing is it"** — the stratification/classification layer that other measurement and governance systems condition on.

**Three related components, one shared theme (conditioning/classification axes, each independently extensible):**

| Component | What it governs | Canonical doc | Status |
|---|---|---|---|
| **StratificationDimension** | One shared provider contract for regime/conditioning labels (HMM price/vol, cross-sectional `regime_group`, and future dimensions) | [Stratification Dimension Unification](stratification-dimension-unification.md) | ⏳ Design proposal, `Protocol` defined; formalizing the actual contract is explicitly gated on Phase 144's D-05 empirical verdict, itself blocked on the current corpus re-run (see that doc's "Formalization revival note") |
| **Security Classification Hierarchy** | Multi-level instrument classification (GICS-style Sector→Industry Group→Industry→Sub-Industry, plus a finer custom taxonomy below it) | [Security Classification Hierarchy](stratification-security-classification-hierarchy.md) | ⏳ Draft design, unscheduled milestone (individual-equities era, no ROADMAP phase yet) |
| **Instrument Tag Calibrator** | Empirical calibration of instrument tags/exposure betas (risk_on, rate_sensitive, defensive, etc.) | [Instrument Tag Calibrator](stratification-instrument-tag-calibrator.md) | ⏳ Draft design, but **registered as ROADMAP Phase 146** (fully specced: TAG-01/02/03, 3 plans, `Depends on: Nothing upstream of Phase 141`) — unblocked, ready to plan now (2026-07-16, verified against live ROADMAP.md). **Cross-listed**, not duplicated: also appears as Type 3a in [Concept Governance Registries](concept-governance-registries.md) — the same measured tag values feed both a vocabulary (what tags exist) and a potential future stratification dimension (tags as a conditioning axis) |

**Currently live, ungoverned by any of the above:** `instruments.tag` assignments (71 tags / 410 instrument assignments, migrations 227/228) exist in the DB today, hand-typed (`source='human'`), not yet produced by the Tag Calibrator's empirical primitives.

---

## Why This Stays a Thin Index

`StratificationDimension`'s own proposal names a backlog of roughly a dozen more candidate dimensions (percentile-rank, microstructure, correlation/liquidity/posterior-weighted variants — see `stratification-dimension-unification.md`'s backlog paragraph). The point of keeping this doc a table of pointers, not a merged mega-doc, is that each new candidate dimension gets its own row and its own canonical doc when it's ready — exactly the same reasoning `concept-governance-registries.md` uses to stay thin. Don't fold future dimensions' full designs in here.

## Relationship to Concept Governance Registries

Independent umbrellas, **two real seams** (second one added 2026-07-16, found while scoping
Phase 161's Controlled Vocabulary discussion — previously only the first was documented):

1. **Promotion state → Concept Registry.** Once `StratificationDimension` providers exist as competing, evidence-gated entities, their promotion state (shadow/live per `regime_group`) is meant to live in Concept Registry's `regime_model`/`hmm_variant` domains (see `concept-unified-registry.md`'s Domains table), not on the provider itself. So this cluster defines *what a stratum is*; Concept Registry governs *whether a given provider of strata has earned adoption*. Seeding `regime_model` (see `concept-unified-registry.md`'s `regime_model` section, "Seeding sequence") is the connective-tissue work item, sequenced behind todo 058.
2. **Label sets → Controlled Vocabulary.** `stratification-dimension-unification.md`'s `StratificationDimension` `Protocol` declares `labels: list[str]  # from Vocabulary` — each dimension's valid label set is meant to be sourced from Controlled Vocabulary (Type 3b in the sibling umbrella), not hand-maintained per provider. `regime_hmm` and `regime_cross_sectional` are exactly the namespaces Phase 161 seeds first, so once `StratificationDimension` formalizes, it becomes a real consumer of Phase 161's output. Not a build dependency in either direction today — Phase 161 doesn't need `StratificationDimension` to exist first, and vice versa — just a forward pointer worth keeping visible.

**Prior art already applied here:** `StratificationDimension`'s `Protocol` design explicitly cites the archived v2.x I1-I7 plugin system's tier-registration pattern (`PatternPlugin` + `validate_tier()`) as validated internal precedent for "one interface, many pluggable, evidence-promoted providers" — see that doc's Contract section.

---

## Related Docs

- **StratificationDimension detail:** `docs/research/stratification-dimension-unification.md` — the provider contract, Open Questions, sequencing into v3.15 (Phases 144/145)
- **Classification Hierarchy detail:** `docs/research/stratification-security-classification-hierarchy.md` — GICS-style layer design, staging gates
- **Tag Calibrator detail:** `docs/research/stratification-instrument-tag-calibrator.md` — factor primitives, derivability
- **Concept Governance Registries (sibling umbrella):** `docs/research/concept-governance-registries.md`
- **Formalization gate:** `stratification-dimension-unification.md`'s "Formalization revival note"
- **Roadmap context:** v3.15 "Conditioning & Identity Foundation" (Phases 144, 145); Instrument Tag Calibrator is Phase 146 (unblocked, see table above). `.planning/ROADMAP.md`
- **Controlled Vocabulary (sibling umbrella's Type 3b, second seam above):** `docs/research/concept-controlled-vocabulary.md` — Phase 161, context gathered 2026-07-16 at `.planning/phases/161-controlled-vocabulary-system/161-CONTEXT.md`
