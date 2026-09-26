# Phase 176: Earnings-Season Calendar Primitive (todo 353) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-22
**Phase:** 176-earnings-season-calendar-primitive-todo-353
**Areas discussed:** Scope, Field scope

---

## Pre-discussion verification

The todo's own filing said to re-run the SQL proxy test with the corrected 14-42-day
post-quarter-end window (the original proxy used the wrong 0-42 window) before committing to
build. Done live before presenting gray areas:

| Metric | Original (wrong 0-42 window) | Corrected (14-42 window) |
|---|---|---|
| Ratio in-season/off-season | 4.3x | 1.90x |
| p-value | 1.2e-17 | 5.05e-05 |
| % symbols higher in-season | 81% | 67% (155/233) |

Effect confirmed real and still significant, but materially smaller than the todo's original
(flawed-window) claim. Presented to the user before the scope questions below.

---

## Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Standalone feature only | Ship is_earnings_season as a plain FeatureVector column, let it clear its own gate independently; defer the regime-conditioning integration to a follow-on phase | |
| Build both in this phase | Ship the standalone feature AND wire it into ic_engine.py's regime segmentation together | ✓ |

**User's choice:** Build both.
**Notes:** User invoked a "design this like Renaissance would" framing — think like a council of
senior Renaissance quants/engineers, channel Jim Simons' rigor, ruthlessly eliminate unnecessary
complexity, prioritize data integrity/clean data flow/DAG topology/SoC/async patterns. Explicit
verdict: "I think BOTH make sense." This framing was carried into CONTEXT.md's D-03 as a binding
design-principles decision, not just rationale for the scope call.

---

## Field scope

| Option | Description | Selected |
|--------|-------------|----------|
| Binary flag only | Matches the actual validated evidence; avoids shipping an unvalidated companion field | |
| Add days_since_quarter_end too | Ship both fields in the same migration | ✓ |

**User's choice:** Add days_since_quarter_end too.
**Notes:** No additional rationale given beyond the selection itself. Captured in CONTEXT.md
D-02 with an explicit note that the continuous companion has no proxy-test evidence of its own
and still needs its own `feature_ic_scores` gate pass — not exempted by is_earnings_season's
evidence.

---

## Claude's Discretion

- Exact implementation shape of the ic_engine.py regime-conditioning integration (new
  regime_group-style axis vs. stratification split vs. other) — left to research/planning.
- Whether days_since_quarter_end is raw days or normalized — left to planning.

## Deferred Ideas

None — discussion stayed within the phase's two workstreams.
