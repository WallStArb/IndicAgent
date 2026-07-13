---
**Created:** 2026-07-04
**Area:** intelligence / governance
**Type:** new_feature
**Priority:** P1
**Effort:** 1-2 sessions (migration + seeding script + one deterministic status-flipper wiring)
**Risk:** low (additive; no consumer reads `concept_registry` yet)
**Gate:** none — build trigger already fired (Phase 142B.1 complete 2026-07-04)
---

# 058 — Build the Concept Registry MVP and seed it from Phase 142B.1's ensemble-strategy outcomes

From the 2026-07-04 cluster review of `docs/research/concept-governance-registries.md` and its
consumers (`.planning/research/2026-07-04-concept-registry-cluster-fable-review.md`, F1/F2/F3/F7/F8).

## Status as of 2026-07-13: plan written, execution deliberately deferred; stays a todo, not a ROADMAP phase

A full task-by-task implementation plan was written and saved at
`docs/plans/2026-07-13-concept-registry-mvp-implementation-plan.md` (migrations 231/232 still
free as of this writing). A worktree was briefly opened to execute it, then redirected to todo
084 instead (ensemble ablation protocol, since shipped and closed) on the reasoning that the P0
measurement-integrity work (096/091/094, the corpus re-run) is the actual highest-leverage use of
time right now, and 058 is P1 governance/bookkeeping for a domain (`ensemble_strategy`) with zero
live consumers yet. Nothing is lost by the delay — the plan stays valid indefinitely, and the
worktree cost nothing to redirect.

**Not promoted to ROADMAP.md.** This fits PRIORITIES.md's own scope definition for `pending/`
todos exactly: a single self-contained, "1-2 session" deliverable, not a multi-plan phase needing
GSD's roadmap/wave/STATE.md machinery. The plan itself was deliberately written in
`superpowers:writing-plans` format for this reason, not GSD's `PLAN.md` format.

## Why this is P1, not deferred

Phase 142B.1 (Ensemble Weighting Methodology) completed 2026-07-04, firing the hub doc's own
named build trigger (topdown D9, via `ensemble_strategy` — the concrete, lower-risk domain #2
candidate). ROADMAP.md's Phase 142B.1 section says this explicitly: *"Next step once 142B.1
completes: a small follow-on item seeding `concept-governance-registries.md`'s four-table MVP
from 142B.1's E1-E4 `weight_version` rows... Not doing this promptly is how 'deferred' becomes
'deferred indefinitely.'"* As of this todo's creation, no work item tracked it — the review
confirmed this by grep over `.planning/todos/pending/`. This is exactly the "notebook nobody
reads" failure mode Concept Registry exists to prevent, happening to the registry itself.

## Scope

**1. Migration** — create the four-table MVP per `concept-governance-registries.md`'s "Minimal
Viable Version" section:
- `concept_registry` (identity, domain, status, lineage, enabled)
- `concept_gate` (per-concept gate + last-eval cache columns + `fdr_required`/`fdr_alpha`, plus
  a new evidence-mass floor field per review F3 — re-evaluation requires ≥ N new independent
  observations since last eval, not just "corpus has advanced")
- `concept_transition_log` (immutable audit trail) — **add a `corpus_build_ref` column**
  (CorpusManifest identity) beyond the MVP's original sketch; without it, invariant 2's
  re-evaluation guard has nothing to compare against but bare `triggered_at` timestamps (F3)
- `concept_annotation` (thesis/failure_mode/observation/open_question/implementation, typed
  `source = human | ai | empirical`)

**2. Seed `domain='ensemble_strategy'`** — verified against live DB 2026-07-04:
`ensemble_weights` holds only `weight_version='v1'` (103 rows). Seed:
- `ic_proportional` (`weight_version='v1'`) — status `active`, genesis `concept_transition_log`
  row (no real "promotion" event, just establishing the incumbent)
- E1 (shrunk-IC) and E2 (mean-variance `Σ⁻¹·IC`) — status `candidate`, `thesis` annotations
  (`source='human'`); these have shipped mechanisms (`shrinkage.py`, `mean_variance_weights()`)
  but no formal registry eval yet
- E3 (hierarchical partial pooling) and E4 (per-feature decay half-lives) — status `candidate`,
  `thesis` annotations only (`source='human'`), no code, no eval mechanism yet

Do **not** seed `concept_gate_template` — that table is reference-architecture only and
deliberately excluded from the MVP. Seed gates as per-concept `concept_gate` rows instead
(F7 — the hub doc's Domains-table footnote previously implied `concept_gate_template`, corrected
2026-07-04).

**3. Name the deterministic status-flipper (invariant 1)** — `ops_ensemble_weight_compare.py`'s
win-decision gate (142B.1-05) is the narrowly-scoped, no-LLM code path that flips status; wire it
to call a `ConceptRegistryService` method rather than writing `concept_registry` directly inline.

**4. `baseline_metric` winner's-curse guard (F8)** — at any promotion, store `baseline_metric` as
the mean of the `min_promotion_consecutive` evaluations, not the final one (the hub's own
documented interim fix). Proper ensemble-grain shrinkage is out of scope here — parked at
`intel-15-measurement-engine.md` OQ7 as a shared-kernel concern.

**5. Resolve and record per-stratum status (F2)** — `ops_ensemble_weight_compare.py` selects a
champion **per (tf, regime) stratum**; the MVP's single global `status` column can't represent
"E2 wins in `high_bear/1h`, E1 wins everywhere else." Recommended default (already written into
`concept-governance-registries.md`'s Build-trigger section 2026-07-04): `status` governs recipe
validity (has this method ever earned a win anywhere); per-stratum champion stays a *fact* in
`ensemble_weights` as today; `redundancy_group`'s "only one holds active" displacement rule is
disabled for this domain. Implement per that resolution unless building surfaces a reason not to.

**6. Document the invariant-6 exception for this domain** — E1-E4 are human-authored, so
mandatory `shadow_only` between candidate and active doesn't bind the way it would for an
AI-sourced concept. Document this the way `domain='feature'` already does (per the hub's
"Documented exception" clause): the OOS A/B judged by `EnsembleICEngine` on live corpus runs is
this domain's evidentiary substitute for a live shadow period.

**7. Do not migrate `feature_registry` in this item.** Phase 143's LIFECYCLE-01 amendments
(auto-`ic_demotion` → `shadow_only` instead of `deprecated`, new `shadow_only → active`
transition) are pending against `feature_registry` and not yet built. Migrate `domain='feature'`
in after Phase 143 lands, or have Phase 143 route through `concept_registry` directly if this
todo ships first (intel-14's OQ3 — check at build time, not a design decision here).

## References

- `.planning/research/2026-07-04-concept-registry-cluster-fable-review.md` — F1 (this todo's
  existence), F2 (per-stratum status), F3 (evidence-mass re-eval floor), F7 (seed material
  corrections), F8 (baseline_metric shrinkage gap)
- `docs/research/concept-governance-registries.md` — MVP schema, invariants, Domains table
- `.planning/ROADMAP.md` Phase 142B.1 (source of the E1-E4 candidates, complete 2026-07-04) and
  its Concept Registry landing-spot note
- `services/ensemble_trainer.py`, `scripts/ops/alpha/ops_ensemble_weight_compare.py` (or
  equivalent — the shipped 142B.1-05 win-decision judge)
- `docs/research/intel-14-integrity-monitor.md` OQ3 — feature_registry migration ordering check
- `docs/research/intel-15-measurement-engine.md` OQ7 — ensemble-grain shrinkage, parked not solved here
