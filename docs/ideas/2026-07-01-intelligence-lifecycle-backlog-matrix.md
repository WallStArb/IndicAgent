# v3.0 Intelligence Lifecycle — Priority Matrix

**Date:** 2026-07-01. Working triage, not a roadmap commitment. Scope: v3.0 intelligence
lifecycle ideas (Feature Factory, IC, regime detection/stratification, ensemble, tagging,
AlphaEngine), pulled from wherever they live — doc/phase/todo location doesn't matter.

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
| HMM Numba JIT (ROADMAP Phase B, Tasks 8-10) | M-L | Med | V.High | **Already in progress** — part of the corpus-fix phase running right now (`src/intelligence/hmm_jit.py` + wire into `regime_writer.py`). Gates nearly everything below and Phase 147. |
| Post-corpus cost-hurdle calibration (030) | S | Low* | High | *Wrong if run before 034 resolves. ~1hr, cheapest real reward, no roadmap phase — todo-only, correctly so (pure calibration, not a build). |
| Interaction Primitives pilot (037) | S | Low | High/cost | Gatekeeper for the XL primitives-expansion item below (Phase 147) — run before, not alongside. Todo-only, no phase needed for a pilot. |
| `regime_group` dispatcher (migration 189, corrected) | L | Med | High | **Foundational.** Not yet in ROADMAP.md as its own phase — only exists as `docs/plans/2026-07-01-cross-sectional-regime-model.md`. Should get a phase number before migration 189 ships. |
| Phase 142A: Ensemble IC Measurement | L | Med | High | **Actual next roadmap phase**, currently blocked only on Phase B (Numba JIT + corpus fixes) finishing. Unlocks `is_shadow` (011a) and Phase 150 below. |
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
| HMM regime audit P1-P3 (026, P0/Numba already promoted above) | L | Med | High | Follows Phase B's Numba work, not ahead of it. |
| Cross-Group Lead-Lag IC (`docs/ideas/cross-group-lead-lag-ic.md`) | M | Med | Med, unproven | Reuses existing `ic_engine` machinery (new join pattern: group A's regime/feature vs. group B's forward returns, not new infra). 6 candidate pairs identified (rates→precious metals is the theoretically cleanest). Real open risk: testing multiple pairs × lags × TFs needs the same BH-FDR discipline as cross-sectional IC, not ad hoc pair-by-pair testing. **Gated on Phase 151 (`regime_group`)** — needs clean peer groups on both sides of the join before it's buildable at all. |
| HMM non-causal-fit diagnostic (034 Step 1) | S | ~0 | Contingent | Run the query; don't build the fix until it says to — already tried once, killed for no baseline. |
| Volatility regime P1 | S | Low | Med-High, unproven | Doc's own claim, not measured. Best candidate to test the stratification thesis. |
| Dispersion regime P2 | S | Low | Med | Same "unproven" caveat. |
| Instrument Tag Calibrator (040/148) | L-XL | Med | High, **latent** | Verified: routing ignores `weight` today — nothing consumes calibrated weight yet. Sound, not urgent. |
| ETF Universe Expansion 58→79 (migration 188) | L | Med | Med | **Foundational** for tag/regime-group work, but "more symbols = better IC" is assumed, not shown. Not in ROADMAP.md as its own phase — plan-only, same gap as `regime_group`. |
| Feature Primitives Expansion (~60, 014/147) | **XL** (not L) | Med | Med, uncertain | Cross-check against the existing 54-feature baseline (`docs/plans/2026-06-20-alphaengine-architecture.md`) first — unchecked duplicates are collinearity risk, not new info. |
| Comomentum Crowding Metric | M | Low | Med, rising | Sequence with primitives expansion above — crowding risk scales with feature count. |
| Volume regime P6 + orthogonality study | S+S | Low | Med, contingent | Study before build, as already gated in the stratification doc. |
| `market_data_ohlcv` active-bars view (035) | S | Low | Med | **Foundational.** 4 duplicated filters = correctness-drift risk; cheaper to fix before a 5th call site appears. |
| Zero-IC feature refinement (033) | M | Low | Med | Fine either way — finds signal or confirms retirement. |
| Cross-sectional rank features (013a) | M | Low | Med | Minor schema debt, not a signal question. |
| IntegrityMonitor platform (149A/B/150) | XL | Low | High long-run, low now | Insurance, not a fix. Don't let it jump items with present-tense value. |

---

## LOW — downgraded, correctly gated, or no evidence yet

| Idea | Effort | Risk | Reward | Note |
|---|---|---|---|---|
| Session/time-of-day regime P7 | S | V.Low | **Downgraded** | Cheap+safe isn't the same as valuable — no case made for why session effects matter at this system's (swing, not HFT) cadence. |
| Skew/tail regime P8 | S | Low | Low-Med | Same gate as P6, expect less even if cleared. |
| Factor regime P3 | M | Med | Med | New infra (factor-return pipeline) for an arbitrary-threshold-prone payoff. |
| HMM variants — IOHMM/Hamilton/factor-augmented (P4) | L each | Med-High | Unproven | Gated on proof current HMM is deficient. Adding complexity contradicts this codebase's own "simple features beat complex" principle. |
| Microstructure regime P5 | XL | High | Med, far off | Needs order-flow infra that doesn't exist. |
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
