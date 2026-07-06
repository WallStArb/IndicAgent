# Phase 142 Redesign — Musk 5-Step + Renaissance Audit

Date: 2026-06-30
Status: Design reference — not yet implemented

This captures the requirements audit and simplification decisions made before Phase 142
implementation began. Use this when resuming Phase 142 or planning 142B/143/144.

---

## Step 1 — Requirements Audit

| Requirement | Verdict |
|---|---|
| EIC-01 EnsembleICEngine | Keep — IC(alpha_score, forward_return) is the entire point |
| EIC-02 IC decay curve → hold_max_bars | Keep — calibrating hold horizon from data is correct |
| EIC-03 Walk-forward stability gate | Keep — correctness check before 142B |
| EIC-04 Hard gate: ic_ci_lower > 0 in ≥60% cells | Keep, but 60% is unseeded — mark [initial_estimate] in APR, not baked in |
| FRAME-01 Cost model snapshot | **Delete** — real cost data doesn't exist until v4.0; snapshots alpha.cost.* at 0.0 = silent wrong answer |
| FRAME-02 AlphaFrameWriter 4-variant calibration grid | **Delete** — premature; proves nothing before single-variant P&L is established |
| FRAME-03 CounterfactualTracker | Keep |
| FRAME-04 State machine + IC-decay exit trigger | Keep — IC-decay exit (weekly IC cadence, not bar-level reversal) is exactly right |
| FRAME-05 corr(alpha_score_decile, mean_pnl_r) as gate | **Simplify** — primary gate is mean(counterfactual_pnl_r) > 0 at 95% CI; correlation becomes diagnostic column |

---

## Step 2 — Deletions

1. **FRAME-01 (cost model)** — out of Phase 142 entirely. Cost model belongs in v4.0 when actual
   fills, slippage, and commissions exist. Remove cost_r snapshot, net_expected_r computation,
   and alpha.cost.* APR loading from AlphaFrameWriter entirely.

2. **Calibration grid** (4 stop_atr_mult variants, grid_stop_atr_mults) — removed from Phase 142.
   Phase 142 answers: "does the signal produce positive counterfactual P&L with a sensible stop?"
   Not: "which of 4 stop variants maximizes corr(decile, P&L)?" The calibration grid becomes
   Phase 142B P2 after the primary frame proves signal is capturable at all.

---

## Step 3 — Simplifications

**AlphaFrameWriter:** One frame per alpha_event (frame_variant='primary'), one stop
(APR-seeded alpha.frame.stop_atr_mult, default 1.5). No calibration loop in Phase 142.
The calibration grid becomes a separate phase if Phase 142 exits with positive P&L.

**FRAME-05 → primary gate:** mean(counterfactual_pnl_r) > 0 at 95% CI (bootstrap, one-tailed)
on in-sample data. This is also the Phase 144 OOS gate — keep evaluation criteria identical.
The corr(alpha_score_decile, mean_pnl_r) metric becomes a diagnostic column in analysis,
not a selection mechanism.

**Phase gate clarification:** FRAME-05 becomes the Phase 142B exit gate, not a calibration
selection step. Pass → proceed to Phase 143. Fail → diagnose (frame geometry? IC decay? wrong TF?).

---

## Step 4 — What Renaissance Would Add

Two things the original spec was missing:

### 1. EIC-04 threshold is unseeded — own it

`ic_ci_lower > 0 in ≥60% of (symbol, tf, regime) cells` — the 60% is arbitrary.

APR key: `alpha.ensemble_ic.min_qualifying_fraction = 0.60` — [initial_estimate];
recalibrate after first corpus run reveals how many cells have sufficient N.
Don't bake a magic number into the gate.

### 3. Diagnostic-first failure mode

If Phase 142B fails (mean_pnl_r ≤ 0), the investigation order is:
1. Frame geometry wrong? (stop too tight, hold too short)
2. IC decay miscalibrated? (hold_max_bars from wrong regime)
3. Wrong timeframe? (alpha_events from TF with no IC)
4. Signal itself has no edge?

Define this triage upfront so failure is actionable, not a black box.

---

## Phase Sequence (post-audit)

- **Phase 142A** — EnsembleICEngine + walk-forward gate (EIC-01 through EIC-04)
- **Phase 142B P1** — AlphaFrameWriter (single variant), CounterfactualTracker, state machine + IC-decay exit
- **Phase 142B P2** — SHADOW-REVIEW.md published; shadow emissions begin; 60-day observation window
- **Phase 143** — OOS validation (if 142B passes)
- **Phase 144** — Live promotion gate
- **Phase 142C (deferred)** — Calibration grid (4 stop_atr_mult variants) if Phase 142 exits positive
