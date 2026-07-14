---
status: completed
priority: P3
filed: 2026-07-12
closed: 2026-07-13
source: user-observed pattern, discussed and stress-tested 2026-07-12
---

# Get a Fable rigor pass on the quarterly-seasonality/OPEX idea before it enters Phase 151

**Closed 2026-07-13, Fable review complete.** Full result: `docs/research/signal-temporal-atomic-primitives.md`
(promoted from `docs/ideas/signal-quarterly-seasonality-opex-risk-off.md`, which stays as the
retracted-analysis worked example, not further edited). All 5 open questions answered; scope
confirmed inside Phase 151 (`.planning/ROADMAP.md`'s "Calendar primitive candidates" block,
corrected to match this review's findings). Key resolution: `is_opex_day` was rejected at the
atomic tier (a binary flag selects a point in a cycle, which is a hypothesis, so it belongs in the
interaction pool) and reframed as two tier-1 candidates, `opex_flag` (monthly, the clean
mechanical probe) and `quad_witching_flag` (quarterly, tests amplification); splitting them is
the actual test design, since quad-witching alone can't separate expiration mechanics from
quarter-end seasonality. New atomic candidates: `quarter_cycle_sin/cos` (primary instrument,
well-powered), `tdom_sin/cos`, `minute_of_hour_sin/cos`. Bonus finding: `days_to_month_end` is
exactly redundant with `month_position` (removal filed as todo 115). Vocabulary: `calendar
primitive` is the canonical term (glossary/naming-system entries added same session).

**Concept doc:** `docs/ideas/signal-quarterly-seasonality-opex-risk-off.md` — this todo is the
review-gating step; do not build anything from this idea before that doc has been through
Fable review and promoted to `docs/research/`.

## What this is

User-observed pattern: broad market weakness in roughly weeks 9-11 of the calendar quarter,
rebound into quarter-end (window dressing), strength into earnings season — possibly tied
mechanically to quarterly ("quad-witching") OPEX, the 3rd Friday of the quarter's final month.

An ad hoc same-session empirical check found a shape matching the hypothesis, but the check
itself was retracted for a real statistical error (naive row-count treated as independent N
when the true cluster count — distinct quarter-episodes — was ~350x smaller; see the concept
doc's "What was actually tested" section for the full worked example). The pattern's direction
is plausible enough to be worth a real test; the specific numbers from that session are not
evidence of anything and should not be cited.

## What's needed

A Fable pass on the concept doc's five open questions (primitive design, OPEX-specific test
precision, statistical power given quad-witching's 4x/year frequency, which testing
methodology applies — the todo-037 interaction-pilot pattern vs. SHADOW-REVIEW's day-clustered
bootstrap — and whether this belongs inside Phase 151's existing scope or needs separate
treatment). Concept doc has the full context; don't re-derive it here.

## Gate

None to start the Fable review itself. Building anything from this (new primitive, new
interaction candidate) is gated on that review landing and the doc being promoted to
`docs/research/`.

## Effort

Fable review: small (one dispatch, doc already has the open questions scoped). Any resulting
build work is separately scoped once the review lands — not estimated here.
