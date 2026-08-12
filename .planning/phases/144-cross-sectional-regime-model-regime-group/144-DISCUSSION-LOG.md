# Phase 144: Cross-Sectional Regime Model (`regime_group`) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-12
**Phase:** 144-Cross-Sectional Regime Model (`regime_group`)
**Areas discussed:** Deliverable scope, Acceptance gate, Rebuild sequencing

---

## Deliverable scope

| Option | Description | Selected |
|--------|-------------|----------|
| Mechanism only (recommended) | Phase 144 = exactly the plan doc's Tasks 0-9 (migration + signal modules + dispatcher + ic_engine routing). Todo 026 P2b/P2c stay separate pending todos. | ✓ (by verified evidence) |
| Bundle P2b/P2c in | Add the occupation-fraction degenerate-model gate and hmm_churn column to this phase's plan. | |

**User's choice:** Free-text — "what would renaissance abd jim simons do - we want a strong
institutional foundation with reusable microservices."

**Notes:** Investigated rather than picked directly. Verified against live code/schema that
todo 026 P2b (occupation-fraction gate) and P2c (`hmm_churn` column) were already shipped
2026-07-06 via Phase 143 Plan 01 (LIFECYCLE-00) — `feature_vectors.hmm_churn` column live,
`feature.hmm.min_state_occupation`/`feature.hmm.churn_window` APR keys live. The bundling
question was moot: nothing left to bundle. This resolved cleanly to "mechanism only" on the
evidence, consistent with the user's stated preference for minimal, modular, non-redundant
scope. Corrected stale status in `.planning/todos/deferred/026-hmm-regime-audit-optimization.md`
and `.planning/ROADMAP.md`'s v3.15 batching paragraph (both still said P2b/P2c were open).

---

## Acceptance gate

| Option | Description | Selected |
|--------|-------------|----------|
| Include the Step 1 gate (recommended) | Phase 144 isn't "done" until the widened Step 1 (TLT vs rates group separation) actually runs and F1/F2 falsifiers are checked. | ✓ |
| Code-complete now, measure later | Verification = migration + dispatcher + routing + unit tests only; measurement becomes a separate follow-up todo. | |

**User's choice:** "Include the Step 1 gate (recommended)"

**Notes:** Matches "earn promotion through proof" — a regime label nobody re-measured isn't
proven, it's deployed. Sequenced after the corpus rebuild per the next question.

---

## Rebuild sequencing

| Option | Description | Selected |
|--------|-------------|----------|
| Build now, measure after 143.1-07 lands (recommended) | Plan/execute code+migration immediately; defer the full run + batched ic_engine re-run until 143.1-07 finishes. | ✓ |
| Wait for 143.1-07 entirely | Hold all planning/execution until the current corpus rebuild is fully done. | |

**User's choice:** "Build now, measure after 143.1-07 lands (recommended)"

**Notes:** Matches the Fable decision doc's own sequencing note — code work doesn't touch the
in-flight rebuild; only the re-measurement step needs to queue (single-writer discipline on
derived tables).

---

## Claude's Discretion

- Exact migration number (plan doc's literal "189" is stale; corpus is at migration 228 as of
  2026-07-12).
- Whether to keep `equity_regime_model.py` as a deprecated rollback fallback — follow the plan
  doc's Task 1 (yes, no functional changes) unless a reason emerges not to.
- Building the commodity/fx signal modules now (spec'd, tested) even though their groups ship
  `enabled: false` — build them per the plan doc's File Map rather than defer, since todo 041
  only gates enablement.

## Deferred Ideas

- concept_registry row-grain question for the `regime_model` domain (Fable decision doc §6 Input
  3) — `concept_registry` doesn't exist as a table yet; revisit when that MVP work is actually
  scheduled (todo 058 covers domain #1, `ensemble_strategy`, first).
- Todo 039 (tag-stratified IC population check) — explicitly designed as a follow-on requiring
  `regime_group` to exist first; correctly stays after this phase, not folded in.
- Todo 038 (cross-sectional collinearity diagnostic) — tangentially related, scoped to HMM input
  diagnostics rather than regime routing; not folded in.
