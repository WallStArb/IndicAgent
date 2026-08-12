---
status: promoted
priority: P1
filed: 2026-07-22
promoted: 2026-07-23 — formalized as ROADMAP Phase 166 (Frame/Execution Recalibration),
  not yet planned (`/gsd-discuss-phase 166` next). This file's scope note stays the source
  record; do not duplicate its content into the phase doc, reference it.
source: Phase 148-05's promotion decision record (docs/plans/archive/2026-07-22-phase148-promotion-decision.md)
  explicitly deferred this diagnosis as out of scope for Phase 148 itself; ROADMAP.md's own
  Phase 148 design (~line 1378, written when the phase was planned) pre-registered the playbook
  for this exact outcome but no unit of work exists yet to run it.
---

# Diagnose why Gate 2 (execution proof) failed and whether frame/stop/target/hold recalibration can fix it

## Problem

Phase 148 closed 2026-07-22 with a split verdict: Gate 1 (signal proof) PASS, Gate 2 (execution
proof) FAIL on 3 of 5 SHADOW-REVIEW criteria (c2 mean P&L CI, c3 Sharpe 0.385 vs >0.5 required,
c4 max drawdown 9.6x vs <0.25 ceiling -- catastrophic, not borderline, under every methodology
variant tested). Promotion decision: do not promote the v3.0 AlphaEngine to live trading capital.

`alpha_score` genuinely predicts forward returns out-of-sample (Gate 1), but the specific frame
simulation -- stop at `alpha.frame.stop_atr_mult`, target at `alpha.frame.target_r_multiple`,
hold horizon from `alpha.frame.hold_max_bars.<regime>.<tf>` -- does not turn that signal into
profitable OOS P&L under the current calibration. ROADMAP.md's own Phase 148 design anticipated
this exact split outcome and wrote the fix directly into the phase spec: *"If Gate 2 fails but
Gate 1 passes: frame problem -- recalibrate stop/target/hold against IC decay curve, not the
ensemble."* That recalibration has never been scoped, planned, or started.

The regime-stratified companion in the promotion decision record narrows where to look: only 2
of 8 (direction, regime) cells had enough OOS day-coverage to evaluate at all (`min_clusters=20`),
both `mid_bull` (the one regime the champion's OOS window happens to sit in), and both failed
(-0.077 long, -0.278 short). Six of eight cells lack enough independent day-clusters to say
anything -- the OOS window itself may be too narrow/single-regime to characterize this fairly,
separate from whatever is wrong with the frame geometry.

## Why this matters

This is the actual next step toward the milestone's core value ("Alpha must be demonstrated
empirically before any ensemble weight is assigned") -- Gate 1 proved the signal is real; this
is the remaining blocker between that and live capital. Not diagnosing it leaves Phase 148's
finding as a dead end rather than a next action.

## Scope note

Not scoped in detail here (this is a capture, not a plan) -- likely needs its own phase given
the surface area, not a single-session todo:

1. Pull the EIC-02 IC decay curve per (regime, tf) and compare against the current
   `alpha.frame.hold_max_bars.<regime>.<tf>` / `stop_atr_mult` / `target_r_multiple` APR values --
   were these ever empirically calibrated against IC decay, or are they still
   `[initial_estimate]` defaults never revisited since Phase 142B?
2. Investigate whether the `mid_bull`-only OOS window coverage (2/8 cells) is itself distorting
   the pooled verdict before concluding the frame geometry is definitively broken -- the
   regime-stratified data suggests the OOS sample may be too narrow to separate "bad frame" from
   "unlucky regime window," per the same regime-conditional-edge finding todo 165 already proved
   on adjacent data.
3. Check whether the ~22-way `bar_ts` tie / simultaneous-position structure that broke Gate 2's
   `c4_max_dd` reproducibility (fixed in 148-05, see todo 172) has any bearing on real portfolio
   sizing/risk assumptions embedded in the frame construction itself, not just the measurement
   script.
4. Determine whether this needs new OOS data (implying a real corpus rebuild) or can be
   evaluated against the same in-sample `alpha_frames` data already held, before touching the
   already-consumed Gate 2 (D-04 -- Gate 2 itself cannot be re-run this milestone; any
   recalibration work produces a NEW proposal to validate later, not a redo of the existing FAIL).

## Sizing

Investigation-first, likely phase-scoped (`/gsd-discuss-phase` candidate) given it touches
`AlphaFrameWriter`/`CounterfactualTracker` frame construction, EIC-02's IC decay methodology, and
regime-window sufficiency -- not a quick single-session fix.

## References

- `docs/plans/archive/2026-07-22-phase148-promotion-decision.md` -- full Gate 2 verdict, evidence, and
  the explicit "diagnosing why is out of scope for this phase" deferral
- `.planning/ROADMAP.md` (~line 1378) -- the pre-registered "frame problem, recalibrate against
  IC decay curve" playbook this todo exists to execute
- `docs/plans/SHADOW-REVIEW.md` -- the frozen five criteria Gate 2 evaluated against
- [172](172-path-dependent-frame-statistics-order-sensitivity-sweep.md) -- adjacent
  reproducibility bug found during Gate 2, may be relevant to frame construction review
- [173](173-ensemble-alpha-1h-1d-oos-scoring-gap.md) -- adjacent coverage gap, Gate 1 side
- `.planning/phases/143.1-measurement-and-eligibility-integrity-fisher-z-ci-bootstrap-/143.1-08-SHADOW-VALIDATION.md`
  sections 6-7 -- champion's original regime-conditional-edge finding (todo 165), same pattern
  observed here
