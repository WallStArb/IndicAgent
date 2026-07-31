# Phase 168: Cost-Hurdle-Adjusted Spread Construction (T3 Follow-On) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-31
**Phase:** 168-cost-hurdle-adjusted-spread-construction-t3-follow-on
**Areas discussed:** Decision granularity, Parallel vs. in-place construction, Cost-floor value
for live gating, This phase's Validation Gate

---

## Decision granularity

| Option | Description | Selected |
|--------|-------------|----------|
| Leg-level hysteresis | Keep a symbol in the book unless a challenger clears a cost-adjusted margin to swap in | ✓ |
| Portfolio-level gate | Only execute the full re-rank this bar if aggregate benefit exceeds aggregate cost | |

**User's choice:** Selected for discussion alongside the other three areas, then directed
Claude to reason through all four "like a Renaissance council" rather than pick from the menu.
Claude recommended leg-level hysteresis (item 5's own wording is per-instrument "ranking
changes," not an all-or-nothing bar-level decision; extends the existing `one_way_turnover()`
function rather than adding new infrastructure). User confirmed by proceeding to the follow-up
question on liquidity taxonomy, implicitly accepting all four recommendations.
**Notes:** Portfolio-level gate rejected as economically wrong — the cost of swapping symbol A
is independent of whether symbol B also needs swapping.

---

## Parallel vs. in-place construction

| Option | Description | Selected |
|--------|-------------|----------|
| Parallel construction_name | New row (`ctf_momentum_decile_ls_cost_gated`) alongside Phase 167's baseline | ✓ |
| In-place modification | Modify `cross_sectional_spread_tracker.py` behind a flag | |

**User's choice:** Parallel, via the same confirmation pattern above.
**Notes:** Justified by this project's own shadow-parity precedent (v2.1 dual-write/parity-audit
pattern, Phase 142B counterfactual-before-capital) and Phase 167's own D-03, which explicitly
calls for "its own before/after comparison" — impossible if the baseline is overwritten.

---

## Cost-floor value for live gating

| Option | Description | Selected |
|--------|-------------|----------|
| Flat universe-wide value | Reuse Phase 167's already-validated binding 10bp tier | ✓ |
| Per-symbol liquidity-tier-aware floor | Todo 030's blended breakdown (liquid core / sector / illiquid intl) | |

**User's choice:** Flat value for this phase; explicitly asked a follow-up ("should we build
per-symbol liquidity taxonomy for later?") confirming interest in the deferred option.
**Notes:** Grepped the codebase first — confirmed no `liquidity_tier` tag or equivalent exists
anywhere; todo 030's breakdown was never built as queryable infrastructure, only described in a
doc. Claude recommended deferring a real per-symbol version to a future phase, built empirically
(Corwin-Schultz spread estimator or Amihud illiquidity ratio from existing OHLCV data) rather
than as a hand-typed 3-bucket label — connecting it to `TagCalibrator`'s (Phase 146) measured-
vs-definitional-tag precedent. User did not push back on this framing.

---

## This phase's Validation Gate

| Option | Description | Selected |
|--------|-------------|----------|
| Four-part gate | Sharpe-delta CI + gross-spread-no-regression + turnover-as-diagnostic + re-run shuffled null | ✓ |
| Simple Sharpe comparison | Single point-estimate Sharpe comparison, no additional checks | |

**User's choice:** Four-part gate, via the same confirmation pattern.
**Notes:** Justified by the project's standing statistical discipline (bootstrap CI on the
delta, not two overlapping point estimates) and the risk that hysteresis could mask gross-signal
decay behind cost savings alone.

---

## Claude's Discretion

- Exact hysteresis band width / margin formula — left to research/planning.
- Whether the before/after comparison lives as a new analysis script (T3-script precedent) or a
  permanent view/report over `construction_spreads` — left to planning.

## Deferred Ideas

- **Per-symbol empirical liquidity-tier cost floor** — raised explicitly by the user as a
  direct follow-up question after the four decisions were confirmed. Discussed in depth (see
  Cost-floor value section above and CONTEXT.md's Deferred Ideas). Explicitly gated on Phase
  168 shipping and its own D-04 gate resolving first; should become its own future phase once
  that happens, not a `pending/` todo.
