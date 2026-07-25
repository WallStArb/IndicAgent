---
status: deferred
priority: P3
filed: 2026-07-24
source: conversation about whether Phase 151's rejection of the original Interaction Factory
  generator (todo 019) was final, or whether the underlying BH-FDR power-collapse problem has
  known statistical fixes
gate: Phase 151 executed and its IC-sweep hit rate / false-discovery behavior known — this todo
  should not be picked up before that data exists, see reasoning below
---

# Interaction Factory v2 — power-preserving candidate generation (design only, not decided)

## What this is

Todo 019 ("Interaction Factory") was closed 2026-07-19 as REJECTED — not for lack of evidence
(todo 037's pilot actually supports pursuing interaction effects), but because flat BH-FDR
correction at ~30,000 simultaneous candidates loses meaningful statistical power and produces
~1,500 expected false discoveries regardless of pre-screening. That is a real problem with the
*specific mechanism* proposed (generate everything, correct once, flat) — it does not prove no
systematic, low-human-bias generator can work at all.

`docs/research/intel-feature-interaction-factory.md` now has a "v2 Design — Power-Preserving
Candidate Generation" section (added 2026-07-24) proposing a combination of: constrained
generation against a small structural-axis list instead of full cross-product (~200 candidates,
not 30K), two-stage/hierarchical screening (cheap disjoint-split prefilter before the expensive
walk-forward pass), knockoff filters (Barber & Candès — the literature's purpose-built answer to
FDR control without power collapse at high N), an effect-size floor alongside the p-value gate,
a redundancy pre-filter (reusing `stratification-dimension-unification.md`'s existing governance
pattern), and a replication requirement (same bar todo 179's Gate 2 diagnostic already applied).

**Full design, rationale, and citations: `docs/research/intel-feature-interaction-factory.md`'s
v2 section — don't re-derive here.**

## Gate

Do not start this before Phase 151 has actually executed and its curated ≤50-feature
Theory-Motivated Interaction Layer has a real IC-sweep hit rate and false-discovery result.
Building a more elaborate discovery mechanism before the simpler one has run even once means
designing against a guess about how much signal it leaves on the table — the same "prove edge
before production infra" violation this project applies elsewhere, aimed at research
infrastructure this time. Once Phase 151 lands, revisit: if its hit rate looks saturated (few
survivors, mostly explainable by the hand-picked hypotheses), a systematic generator is more
justified. If it already finds a lot, the marginal value of a bigger, harder-to-build mechanism
is less clear.

## Effort

Not estimated — design-only todo. A real build would need at minimum: a knockoff-filter
implementation review/validation, the constrained-axis generator, a two-stage screening
pipeline, and a decision on where results land (reuses `feature_registry`/`concept_registry`
per the original doc's "Architecture" section — no new subsystem). Comparable scope to Phase 151
itself; do not underestimate this by treating it as a small addendum.

## References

- `docs/research/intel-feature-interaction-factory.md` — full v2 design section
- `.planning/todos/completed/019-interaction-factory.md` — the original mechanism, why it was
  rejected (statistical-power ground, not evidence)
- `.planning/todos/completed/037-interaction-primitives-pilot-ic-test.md` — the evidence trigger
  that started this whole line of investigation
- ROADMAP.md's Phase 151 section — the curated layer this todo's gate depends on
- `docs/research/stratification-dimension-unification.md` — precedent for the redundancy
  pre-filter → orthogonality → substitution governance pattern this design reuses
