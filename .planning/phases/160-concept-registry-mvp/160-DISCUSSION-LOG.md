# Phase 160: Concept Registry MVP - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-14
**Phase:** 160-Concept Registry MVP
**Areas discussed:** Scope of domain='feature' migration timing

---

## Scope: bundle domain='feature' migration now, or keep it deferred?

**Context presented:** Phase 160 already has a complete design (4 review passes) and a full
task-by-task implementation plan with zero open questions — 7 tasks, no UI component, scope
locked to `domain='ensemble_strategy'` per the plan doc's existing scope guard. One stale
reference found (Task 6 cites "todo 109" for the deferred `feature` migration follow-up, but 109
is already taken by a completed, unrelated todo).

| Option | Description | Selected |
|--------|-------------|----------|
| Skip straight to plan-phase | Design/plan already fully decided; capture as-is and move to `/gsd-plan-phase 160`. | |
| Discuss deferred `domain='feature'` migration timing | Revisit whether the 61 live `feature_registry` rows should migrate into Concept Registry alongside this phase instead of after. | ✓ |
| Discuss something else | Open-ended. | |

**User's choice:** Discuss the `domain='feature'` migration timing, explicitly asking that the
decision be made applying Renaissance/Simons-style engineering rigor (data integrity paramount,
prove-before-build, minimal complexity, guard against hidden bias, SoC/DAG discipline, automate
only what's proven).

**Analysis presented:**
- `feature_registry` is a live, hot write path — `ic_engine.py`'s post-run lifecycle hook
  (Phase 143) writes to it on every corpus epoch; a corpus rerun (143.1-07) was actively writing
  to it during this discussion.
- `ensemble_strategy` is near-static — the correct domain to prove `ConceptRegistryService`'s
  transactional apply logic on for the first time, before trusting it with a hot-path domain.
  Same "earn promotion through proof" pattern already applied elsewhere this project (todo 080).
- Migrating `feature` now would require simultaneously rewiring the already-shipped LIFECYCLE
  hook (Phase 143) to write through the new service — a second live-pipeline integration point
  in the same phase, doubling blast radius against a pipeline this session spent significant
  effort protecting.
- No forcing incident exists for `feature` (unlike the 058/112 duplicate-tracker case, which did
  force action). `feature_registry` works correctly today; migrating it is valid future
  consolidation, not urgent.

**Notes:** User accepted this analysis (no pushback). Decision: keep `domain='feature'`
migration deferred, as a separate follow-on phase/todo sequenced after `ensemble_strategy`'s
governance has run live through at least one real promotion/demotion cycle, and scoped to
include the `ic_engine.py` rewiring as part of that follow-on's own task list (not assumed
trivial). Recorded as D-01/D-02 in CONTEXT.md.

Also recorded during this exchange, not separately discussed:
- **D-03:** stale "todo 109" reference in the plan doc's Task 6 — corrected note added to
  CONTEXT.md; 109 is taken by an unrelated completed todo, Task 6's follow-up needs a fresh
  number when it actually files.
- **D-04:** `domain='regime_model'`'s row-grain question, flagged by Phase 144's own CONTEXT.md
  as deferred to "when concept_registry MVP work is scheduled" — checked against the canonical
  design doc, found already fully specced with a recommendation (not a forced decision),
  correctly re-deferred until `regime_model` has a real candidate to seed. Not re-opened as a
  gray area for this phase — judged scope creep to decide here.

---

## Claude's Discretion

- Exact migration numbers (232/233 in the plan doc) — verify against live migration tip at
  plan/execute time rather than trusting the plan doc's snapshot, given this project's history
  of duplicate-migration-number collisions (todo 101).
- All other implementation detail (schema DDL, service method signatures, gate defaults, test
  coverage) — already fully specified in the existing plan doc, follow as-is.

## Deferred Ideas

- `domain='feature'` migration into Concept Registry — real future work, not lost. See D-02.
- `domain='regime_model'` row-grain decision — already specced, deferred to whichever phase
  first seeds real `regime_model` candidates. See D-04.
