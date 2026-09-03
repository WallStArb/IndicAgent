# Phase 171: HMM Walk-Forward Regime Labeling (Parameter-Lookahead Fix) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-07
**Phase:** 171-hmm-walk-forward-regime-labeling-parameter-lookahead-fix
**Areas discussed:** No-context gate, Todo cross-reference/fold, Governing design principle,
Rollout staging, 1d timeframe calibration, Multi-seed HMM restart (todo 108)

---

## No-Context Gate (pre-discussion, in /gsd-plan-phase 171)

| Option | Description | Selected |
|--------|-------------|----------|
| Continue without context | Plan directly from ROADMAP.md's 5 requirements + research | |
| Run discuss-phase first | Capture design decisions before planning — recommended given this phase triggers a full corpus recompute (regime + ic_engine), same blast radius as an HMM_RANDOM_STATE change | ✓ |

**User's choice:** Run discuss-phase first.
**Notes:** Led directly into this session.

---

## Todo Cross-Reference / Fold

`todo.match-phase 171` returned 64 matches, nearly all at a uniform 0.6 keyword-overlap score
against generic terms ("2026", "todo", "phase") — noise, not signal. Filtered manually to 4
candidates with genuine domain overlap on `regime_writer.py` / HMM fitting mechanics.

| Todo | Description | Selected |
|------|-------------|----------|
| 229 — HMM retry logic (ALREADY FIXED, needs bookkeeping) | Convergence-check bug already fixed and committed 2026-08-05 (`ba8a74ef`); pending file + PRIORITIES.md stale | ✓ |
| 226 — n_iter=200 cap headroom check | Logging already wired; this rerun is the full-corpus measurement the todo's own text requires before any cap change | ✓ |
| 108 — Multi-seed HMM restart validation | Mechanism built, empirical validation not yet attempted; needs live corpus compute time | ✓ |
| 167 — Equity cross-sectional vs symbol-HMM falsifier | Different regime system but consumes the same downstream ic_engine pass this phase triggers | ✓ |

**User's choice:** Fold all 4.
**Notes:** User also stated a governing design directive at this point (captured as its own area
below) rather than answering a specific gray-area question — reflected as D-00 in CONTEXT.md.

---

## Governing Design Principle

Not a multiple-choice gray area — a direct user directive, stated in free text:

> "We want to design this like Renaissance would. Ask yourself how would a senior
> engineer/quant at Renaissance think about this and think like a council of senior engineers
> and architects. What would Jim Simons demand? Approach the problem with absolute rigor,
> treating the codebase as a complex, highly efficient system where data integrity is
> paramount. Channel Jim Simons by ruthlessly eliminating unnecessary complexity, prioritizing
> clean data flow, and guarding against hidden biases or edge-case failures. Ensure the
> architecture emphasizes component reuse, separation of concerns (SoC), well-structured
> directed acyclic graphs (DAGs) for data pipelines, and highly optimized asynchronous
> patterns. We want to ensure we are aligned with our core principles of modularity & reuse."

**Notes:** This reinforces (does not contradict) `CLAUDE.md`'s own existing Design mindset
section — treated as a locked governing principle (D-00 in CONTEXT.md) that shapes how the
remaining 3 gray areas below were framed and answered, not a new standalone decision.

---

## Rollout Staging

| Option | Description | Selected |
|--------|-------------|----------|
| Staged pilot -> full refit | 5-10 symbols, explicit go/no-go gate, exercises `_hmm_seed_stability_check` for the first time against real data before the full 231-symbol blast radius | ✓ |
| Flip and refit everything in one pass | Simpler, one mechanism, no staging state — justifiable if treating Gate 4 + the 3-symbol instability measurement as sufficient prior evidence | |

**User's choice:** Staged pilot -> full refit.
**Notes:** Matches Phase 168 D-02 / Phase 166 D-03 precedent, cited in the question itself.

---

## 1d Timeframe Calibration

| Option | Description | Selected |
|--------|-------------|----------|
| Derive via density-scaling heuristic | Same "~1yr refit / ~2yr warmup" rule as 5m/15m, scaled by 1d's own bar density; disclosed as `[initial_estimate]` | ✓ |
| Run a dedicated small 1d pilot first | More rigorous, matches how 1h/15m got real numbers, but needs ~20yr history per symbol and adds a full measurement pass | |
| Exclude 1d from this rollout | Ship 1h/15m/5m only, defer 1d as its own follow-on todo | |

**User's choice:** Derive via density-scaling heuristic.
**Notes:** 1d already has known-weak statistical power in this corpus (todo 166: ~32x fewer
effective-N than 15m) — marginal rigor gain of a dedicated pilot judged smaller than for other tfs.

---

## Multi-Seed HMM Restart (Todo 108)

| Option | Description | Selected |
|--------|-------------|----------|
| Defer — keep n_restarts=1 for this rerun | Isolates this phase to one experimental variable, matching Phase 167 D-03's "don't conflate two unproven changes" precedent | |
| Test multi-seed now, same pass | Real compute budget already committed; marginal cost on top rather than a separate future pass | ✓ |

**User's choice:** Test multi-seed now, same pass.
**Notes:** Claude flagged the attribution risk (can't tell whether a result-change came from
walk-forward or multi-seed if both move at once in the live rollout) and proposed a mitigation —
run `n_restarts=1` and `n_restarts>1` as parallel comparison arms during the pilot (reusing Phase
168 D-02's parallel-construction pattern) rather than a blind default switch. Captured as D-03 in
CONTEXT.md; user did not object to the mitigation when it was presented in the final "ready for
context" confirmation.

---

## Claude's Discretion

- Exact pilot symbol selection (span bar-density/liquidity profiles across all 4 tfs)
- Exact go/no-go gate statistical thresholds for the pilot (reuse existing bootstrap CI machinery)
- Documentation shape for the `iters_used`/cap-headroom data (own report vs. folded into
  completion notes)

## Deferred Ideas

None — discussion stayed within phase scope.
