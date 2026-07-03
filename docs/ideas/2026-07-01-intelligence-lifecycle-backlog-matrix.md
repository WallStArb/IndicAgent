# v3.0 Intelligence Lifecycle — Priority Matrix

**Date:** 2026-07-01. **Informed by:** `.planning/research/2026-07-01-v3-architecture-review.md` (Fable 5) — the 2026-07-02 refresh below applies that review's findings to several rows. Working triage, not a roadmap commitment. Scope: v3.0 intelligence
lifecycle ideas (Feature Factory, IC, regime detection/stratification, ensemble, tagging,
AlphaEngine), pulled from wherever they live — doc/phase/todo location doesn't matter.

**Refreshed 2026-07-02 — checked against actual code/DB state, not re-assessed by assertion:**
`feature_ic_scores` is now populated (256,566 rows) — several items gated on "corpus not ready"
are unblocked. `regime_group` dispatcher (Phase 151) was already a real ROADMAP.md phase, not
"plan-only" as this doc claimed — that claim was wrong even on 2026-07-01, not just stale.
Direct code checks (`grep`, not doc claims) show 026's P0/P1a/P1b already shipped and P2a
partially shipped — see HMM regime audit row. New item added: Phase 142B.1 (Ensemble Weighting
Methodology), inserted into ROADMAP.md 2026-07-01/02, didn't exist when this matrix was written.
See row-level notes for what changed and why.

**Refreshed 2026-07-02 evening — second pass, more has shipped:** Phase 142A is now COMPLETE
(not "next roadmap phase"). Phase 142B.1 has a phase plan (5 plans, 3 waves — E1 shrinkage +
E2 mean-variance + A/B judging), not just a proposed row. HMM Numba JIT is fully shipped, not
"in progress." todo 026's Decision Gate Step 1 has been **run** (2026-07-02): pooled SPY+TLT
result was a methodology artifact; per-symbol split shows SPY's HMM labels separate IC
reasonably, TLT's don't at all — asset-class-dependent quality, not a single verdict. Most
importantly: **the regime-stratification rows below (Volatility/Dispersion/Volume/Session/
Skew-Tail/Factor regime, HMM variants, Microstructure regime) are now consolidated** into
`docs/ideas/intel-12-stratification-dimension.md` — one unified governance gate
(structural-redundancy pre-filter → orthogonality study → substitution test) replaces this
matrix's per-row triage for that whole cluster; treat those rows as historical, read intel-12
for current status. AnalogEngine (Phase 145/146, LOW tier below) is similarly rescoped in
`docs/ideas/intel-13-analog-engine.md` — the "no cheap pilot step" gap that row flags is
resolved (the substrate ships and validates first, by design).

**Columns:** Effort (S/M/L/XL) · Risk (Low/Med/High) · Reward (scored against evidence, not
the idea doc's own claim — Med/unproven means "plausible, untested") · **Foundational** =
cheaper to do now than to retrofit once other things build on top of it — bumps priority
independent of raw effort/risk/reward.

---

## HIGH — do first

**Cross-referenced against `ROADMAP.md` this pass — two corrections made:** the `regime_group`
migration number collided with Phase 142A's already-claimed migration 187 (renumbered to 189,
fixed in the plan doc); `is_shadow` is not a do-it-now item, its own gate note requires Phase
142A complete (`alpha_ensemble_ic` table must exist first) — demoted below.

| Idea | Effort | Risk | Reward | Note |
|---|---|---|---|---|
| HMM Numba JIT (ROADMAP Phase B, Tasks 8-10) | M-L | Med | V.High | **SHIPPED** (2026-07-02 correction — was "in progress"). `src/intelligence/hmm_jit.py` wired into `regime_writer.py`, Phase 141 P2. |
| Post-corpus cost-hurdle calibration (030) | S | Low* | High | *Wrong if run before 034 resolves. ~1hr, cheapest real reward, no roadmap phase — todo-only, correctly so (pure calibration, not a build). |
| Interaction Primitives pilot (037) | S | Low | High/cost | Gatekeeper for the XL primitives-expansion item below (Phase 147) — run before, not alongside. Todo-only, no phase needed for a pilot. |
| `regime_group` dispatcher (migration 189) | L | Med | High | **Correction 2026-07-02: this row's "not yet in ROADMAP.md" claim was wrong** — Phase 151 already exists as its own ROADMAP.md phase. Status per the 2026-07-01 architecture review (`.planning/research/2026-07-01-v3-architecture-review.md` §4): execution-ready, 0/9 tasks started, live problem not a future one (15/58 corpus symbols mislabeled today). Two policy gaps found and fixed in the plan doc itself: unrouted symbols (GLD/SLV/VNQ/IBIT) now excluded+logged instead of silently defaulting to equity; commodity-group enablement now has an explicit dependency edge on todo 041 (tag taxonomy — see MEDIUM tier). Still **foundational** — Cross-Group Lead-Lag IC below can't build without it. |
| Phase 142A: Ensemble IC Measurement | L | Med | High | **COMPLETE** (2026-07-02 correction — was "next roadmap phase"). `alpha_ensemble_ic` schema + `EnsembleICEngine` + hold_max_bars calibration + EIC-04/05 shipped, 10/10 verification truths. Unlocked `is_shadow` (011a), Phase 150, and Phase 142B.1. |
| Phase 142B.1: Ensemble Weighting Methodology (E1-E4) | S per variant | Low-Med | High | **Now has a phase plan** (2026-07-02 correction — was "new, not on this matrix"): 5 plans, 3 waves (E1 shrinkage + E2 mean-variance + A/B judging). E1 (shrunk-IC inputs, rides on already-scoped todo 029) is the cheapest, highest-value item here. E2 (mean-variance `Σ⁻¹·IC`) reuses existing infra. Every variant is a new `weight_version` — zero schema cost for A/B. Judged by Phase 142A's `EnsembleICEngine`, which is now complete. |
| Phase 150: EnsembleHealthMonitor | M | Low-Med | High | Correctly roadmapped, depends on Phase 142A (`alpha_ensemble_ic`). Live-safety gate, matters more as system nears real capital. |
| Phase 143: Feature Vector Lifecycle + Alpha Decay | L | Low | High | Correctly roadmapped, depends only on Phase 141 (complete) — independently startable, not blocked on 142A. |

**Demoted from this tier after the cross-reference:**
- **`is_shadow` col on `alpha_events` (011a)** — Effort S, Risk Low, Reward High, but its own
  gate says "Phase 142A complete." Cannot ship before 142A lands. Queue it right behind 142A,
  not alongside today's do-first items.

---

## MEDIUM — real value, not urgent, or reward genuinely unproven

| Idea | Effort | Risk | Reward | Note |
|---|---|---|---|---|
| HMM regime audit — remaining P2b/P2c/P3 (026) | S-M (down from L) | Low-Med | Med | **Corrected 2026-07-02 — this row overstated remaining scope.** Direct code check: P0 (Numba JIT), P1a (causal expanding rank), P1b (TF-normalized windows) are already shipped, not pending. P2a is partially shipped (retry-once-with-doubled-iterations on non-convergence + held-out-LL diagnostic exists, but not literally "multiple restarts, pick max log-likelihood" as specced — a looser variant of the same idea). What's actually left: P2b (degenerate-model occupation-fraction gate), P2c (`hmm_churn` feature column, not in schema), P3 (empirical threshold calibration for vix/breadth cuts — APR keys exist with seed defaults, no calibration has run). None of these are on ROADMAP.md as a phase; all are ungated, actionable, just unscheduled. |
| Cross-Group Lead-Lag IC (`docs/ideas/cross-group-lead-lag-ic.md`) | M | Med | Med, unproven | Reuses existing `ic_engine` machinery (new join pattern: group A's regime/feature vs. group B's forward returns, not new infra). 6 candidate pairs identified (rates→precious metals is the theoretically cleanest). Real open risk: testing multiple pairs × lags × TFs needs the same BH-FDR discipline as cross-sectional IC, not ad hoc pair-by-pair testing. **Gated on Phase 151 (`regime_group`)** — needs clean peer groups on both sides of the join before it's buildable at all; Phase 151 is execution-ready per the row above, so this is closer than "gated" alone implies. |
| HMM non-causal-fit diagnostic / 026 Decision-Gate Step 1 (034) | S | ~0 | Contingent | **Unblocked 2026-07-02** — `feature_ic_scores` is now populated (256,566 rows), so the baseline-separation query (`trending_up` vs `trending_down` mean IC gap) is runnable today, not waiting on corpus completion anymore. This is the literal next step in the master sequence from the 2026-07-01 architecture review (Phase B → 026 Step 1 → 142A → Phase 151). Still don't build todo 026's Rolling HMM Refit / Expanding Scaler items (its priority-tier `P4a`/`P4b`) until the query result says to — already tried once, killed for no baseline. |
| Tag exposure-vs-sensitivity taxonomy audit (041) | M | Low | Med, **now load-bearing** | **New row 2026-07-02** — previously absent from this matrix. Discovered dependency: Phase 151's commodity/fx regime groups cannot be enabled without this (OIH/XLE/XOP carry both `eq_*` and `commodity_*` tags; enabling `commodity_energy` today raises `AmbiguousRegimeGroupError` at ic_engine startup). Was implicitly MEDIUM/latent (feeds Instrument Tag Calibrator, 040/148); now explicitly gates Phase 151's second-stage rollout, not just the calibrator. |
| Volatility regime | S | Low | Med-High, unproven | Doc's own claim, not measured. Best candidate to test the stratification thesis. |
| Dispersion regime | S | Low | Med | Same "unproven" caveat. |
| Instrument Tag Calibrator (040/148) | L-XL | Med | High, **latent** | Verified: routing ignores `weight` today — nothing consumes calibrated weight yet. Sound, not urgent. |
| ETF Universe Expansion 58→79 (migration 188) | L | Med | Med | **Foundational** for tag/regime-group work, but "more symbols = better IC" is assumed, not shown. Not in ROADMAP.md as its own phase — plan-only, same gap as `regime_group`. |
| Feature Primitives Expansion (~60, 014/147) | **XL** (not L) | Med | Med, uncertain | Cross-check against the existing 54-feature baseline (`docs/plans/2026-06-20-alphaengine-architecture.md`) first — unchecked duplicates are collinearity risk, not new info. |
| Comomentum Crowding Metric | M | Low | Med, rising | Sequence with primitives expansion above — crowding risk scales with feature count. |
| Volume regime + orthogonality study | S+S | Low | Med, contingent | Study before build, as already gated in the stratification doc. |
| `market_data_ohlcv` active-bars view (035) | S | Low | Med | **Foundational.** 4 duplicated filters = correctness-drift risk; cheaper to fix before a 5th call site appears. |
| Zero-IC feature refinement (033) | M | Low | Med | Fine either way — finds signal or confirms retirement. |
| Cross-sectional rank features (013a) | M | Low | Med | Minor schema debt, not a signal question. |
| IntegrityMonitor platform (149A/B/150) | XL | Low | High long-run, low now | Insurance, not a fix. Don't let it jump items with present-tense value. |

---

## LOW — downgraded, correctly gated, or no evidence yet

| Idea | Effort | Risk | Reward | Note |
|---|---|---|---|---|
| Session/time-of-day regime | S | V.Low | **Downgraded** | Cheap+safe isn't the same as valuable — no case made for why session effects matter at this system's (swing, not HFT) cadence. |
| Skew/tail regime | S | Low | Low-Med | Same gate as volume regime, expect less even if cleared. |
| Factor regime | M | Med | Med | New infra (factor-return pipeline) for an arbitrary-threshold-prone payoff. |
| HMM variants — IOHMM / Hamilton / factor-augmented | L each | Med-High | Unproven | Gated on proof current HMM is deficient (todo 026 Decision Gate — Step 1 now runnable, see MEDIUM tier). **Added 2026-07-02:** the IOHMM and factor-augmented variants turn out to structurally depend on Phase 151 — IOHMM's exogenous inputs (VIX, breadth, yield spread) are literally Phase 151's signal-module outputs; the factor-augmented variant's "cross-sectional factor returns" reuse Phase 151's peer-resolution mechanism. Building either before Phase 151 ships means redoing work Phase 151 will obsolete — one more reason these stay LOW regardless of the gate outcome. The Hamilton variant has no such dependency, is a pure per-symbol simplification, but still gated on the same deficiency proof. Adding complexity contradicts this codebase's own "simple features beat complex" principle either way. |
| Microstructure regime | XL | High | Med, far off | Needs order-flow infra that doesn't exist. |
| `ic_engine` pure function refactor (032) | S | Low | Low | Hygiene, zero IC impact. |
| service_utils cleanup (009) | S | Low | Low | Same. |
| Occam's Razor Evaluator | M | Low | Low now | Nothing complex to gate yet. |
| AnalogEngine (Phase 145/146) | XL | **High** | Speculative | Gap: unlike other XL items, has no cheap pilot step defined. Needs one before scheduling. |
| Alternative Data Vectors (149) | L | Med | Med | Not actionable — no data source chosen. |
| Evolvable AI Agents / Alpha Search Orchestration | XL | High | Speculative | No evidence current single-model approach is insufficient. |

---

**Unverified, worth a direct read before relying on:** `docs/ideas/signal-08` (Intelligence
Vectors — may be the actual v3.0 Feature Factory precursor) and `docs/ideas/ai-02` (MLAgent —
check if `ensemble_trainer.py` already subsumes it).
