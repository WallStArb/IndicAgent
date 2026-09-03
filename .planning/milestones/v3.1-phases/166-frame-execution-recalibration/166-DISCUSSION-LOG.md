# Phase 166: Frame/Execution Recalibration - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-23
**Phase:** 166-frame-execution-recalibration
**Areas discussed:** Fold todos, Scope boundary, Recalibration approach, Regime-window coverage

---

## Fold todos

| Option | Description | Selected |
|--------|-------------|----------|
| 088 — hold_max_bars censoring not tracked | Existing EIC-02 calibration can't distinguish confirmed decay from censored data | ✓ |
| 096 — hold horizon vs feature lookahead mismatch | P0, fix shipped, but full corpus recalibration post-fix unconfirmed | ✓ |
| 172 — path-dependent frame statistics sweep | Same bug class that broke Gate 2's c4 reproducibility | ✓ |
| 173 — ensemble_alpha 1h/1d OOS scoring gap | Zero OOS rows at 1h/1d for champion weight_version | ✓ |

**User's choice:** All four folded.
**Notes:** User reiterated the Renaissance/Jim Simons rigor framing (ruthless simplicity, clean
DAG data flow, guard against hidden bias, component reuse, SoC, async patterns) and explicitly
asked that v2.x's trade lifecycle / trade_framer logic be evaluated for reuse in v3.

---

## Scope boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Diagnose + implement + produce new proposal | Measure IC-decay-vs-frame mismatch, design and implement a new mechanism, validate via a new gate | ✓ |
| Diagnose only | Produce IC-decay-curve comparison and regime-window verdict only, implementation deferred | |

**User's choice:** Diagnose + implement + produce new proposal.
**Notes:** None.

---

## Recalibration approach

| Option | Description | Selected |
|--------|-------------|----------|
| Empirically compare both, let data pick the winner | Build both a scalar-per-(regime,tf) candidate (extend EIC-02) and a structural v2.x-ported candidate; score both, keep the winner | ✓ |
| Commit to porting the structural hierarchy directly | Skip the scalar baseline, go straight to v2.x's VP/SR structure-snap logic | |
| Scalar-per-(regime,tf) only | Mirror EIC-02's hold_max_bars pattern for stop/target, skip structural entirely | |

**User's choice:** Empirically compare both.
**Notes:** Directly satisfies the user's ask to evaluate v2.x trade_framer reuse — as a
competing empirical candidate, not an a priori adoption.

---

## Regime-window coverage

| Option | Description | Selected |
|--------|-------------|----------|
| Report as a parallel finding, don't gate on it | Disclose the mid_bull-only coverage limitation transparently, scope any verdict to what the data can say | ✓ |
| Treat as a hard prerequisite | Require resolving OOS-window coverage (bigger corpus/regime-expansion scope) before recalibrating | |

**User's choice:** Report as a parallel finding.
**Notes:** Resolving this for real implies a much larger corpus rebuild spanning multiple market
regimes — out of scope here, filed as a deferred idea for a possible future todo.

---

## Claude's Discretion

- New validation gate's exact `gate_id`/naming and whether it reuses `SHADOW-REVIEW.md`'s five
  frozen criteria or defines new ones — left to planning.

## Deferred Ideas

- Multi-regime OOS corpus expansion to resolve regime-window sufficiency for real — likely its
  own future phase/todo if Phase 166's evidence makes the gap concrete enough to act on.
