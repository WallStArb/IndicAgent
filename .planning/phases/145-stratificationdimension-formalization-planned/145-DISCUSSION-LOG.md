# Phase 145: StratificationDimension Formalization - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-06
**Phase:** 145-StratificationDimension Formalization
**Areas discussed:** Row-grain ratification, todo 167 sequencing, statistical rigor
(multiple-testing correction, effective-N), causal enforcement, candidate-pool scope

---

## Row-grain (Option A vs Option B)

| Option | Description | Selected |
|--------|-------------|----------|
| Option A | One `concept_registry` row per dimension, global status; needs an undesigned satellite fact table to recover per-`regime_group` granularity | |
| Option B | One row per `(dimension, regime_group)`, encoded in `name`; zero new columns, independent status + transition log per cell | ✓ |
| Leave open for planner | Don't pre-commit, let `/gsd-plan-phase` decide | |

**User's choice:** Option B, ratified directly (no AskUserQuestion menu — user asked
for a direct "council" verdict instead, per their explicit collaboration-style
preference).
**Notes:** Forced by Phase 144's D-05 finding (HMM live for `equity`, deficient for
`rates` simultaneously) — a single global status column cannot represent that.

---

## Todo 167 sequencing

| Option | Description | Selected |
|--------|-------------|----------|
| Proceed agnostic now | Write the contract now, let Option B's per-cell state absorb todo 167's eventual result | ✓ |
| Block Phase 145 until todo 167 resolves | Wait for the equity falsifier verdict first | |
| Fold todo 167's execution into Phase 145 | Make running the equity-scoped gate part of this phase's deliverables | |

**User's choice:** Proceed agnostic now; do not fold execution in.
**Notes:** Todo 167 is queued behind an in-flight corpus rebuild with no committed
ETA — blocking or folding both cost real calendar time or scope for no schema
benefit, since Option B already isolates the equity cell independently.

---

## Statistical and causal rigor (raised by user's "council of Renaissance quants"
framing, not from the original candidate gray-area list)

Three gaps identified against the existing design docs, discussed and ratified
directly rather than via multiple-choice:

1. **No multiple-testing correction across the ~15-candidate pool** — `confluence`
   already specs BH-FDR across its discovery batch; `regime_model` doesn't. Added
   as D-03: log every candidate test to `concept_transition_log`, require
   FDR-corrected significance before promotion, new APR key
   `alpha.regime_stratification.fdr_alpha`.
2. **Raw-bar N instead of effective N** — HMM/percentile-rank states are
   autocorrelated by construction (`min_hold_bars` smoothing). Added as D-04:
   derive the effective-N floor from regime-transition counts before the
   substitution test is trusted.
3. **`causality_basis` declared but not enforced** — matches the shape of three
   prior real incidents in this codebase (CTF join leak, HMM parameter lookahead,
   `canary_acausal_placebo` anomaly). Added as D-05: mandatory acausal-placebo
   registration test per provider, generalizing the existing
   `ops_canary_integrity_assert.py` mechanism.

**User's choice:** All three adopted as new phase scope, explicitly acknowledged as
additions beyond the roadmap's original Phase 145 description, not re-derivations.

---

## Candidate-pool scope for this phase

| Option | Description | Selected |
|--------|-------------|----------|
| One pilot only (`volatility_pct`) | Validate the corrected gate stack against a single well-understood, zero-schema-change candidate before opening the pool | ✓ |
| Multiple candidates in parallel | Test several candidates from the table simultaneously | |

**User's choice:** One pilot only.
**Notes:** Interacts productively with the new FDR correction (D-03) — fewer tests
run before the correction mechanism itself is proven reduces the FDR budget spent
while it's still unvalidated.

---

## Claude's Discretion

- Exact APR key shape/naming for `alpha.regime_stratification.fdr_alpha`
- Implementation shape of the acausal-placebo registration check (pytest fixture vs.
  standalone script vs. decorator-enforced runtime check)
- Whether the effective-N floor is a one-time empirical study or a runtime-computed
  value per gate invocation

## Deferred Ideas

- Data-driven (non-human-curated) candidate-dimension generation — named as a known
  limitation, not scoped to any phase
- Running todo 167's own equity-falsifier gate — stays independent work
- The other 14+ candidate dimensions beyond `volatility_pct` — stay backlog
