# v3.0 Intelligence Lifecycle — Priority Matrix

**Date:** 2026-07-08. Full rewrite of the 2026-07-01 version (superseded — see git history for
the correction trail; this version states current facts only). Scope: v3.0 intelligence
lifecycle ideas (Feature Factory, IC, regime detection/stratification, ensemble, tagging,
AlphaEngine), pulled from wherever they live — doc/phase/todo location doesn't matter.

**Columns:** Effort (S/M/L/XL) · Risk (Low/Med/High) · Reward (scored against evidence, not
the idea doc's own claim — Med/unproven means "plausible, untested") · **Foundational** =
cheaper to do now than to retrofit once other things build on top of it — bumps priority
independent of raw effort/risk/reward.

**Operational context:** a 4th corpus rebuild is in progress as of this writing (started
2026-07-07 17:00, step 4/7 ic_engine). It carries `feature_vectors` from 10.1M to 36.7M rows —
the Phase 142.5 Renaissance primitives (91 new, 152 total) and the ETF universe expansion
(58→80 symbols) both landing in the corpus for the first time. `feature_ic_scores`,
`alpha_ensemble_ic`, and `alpha_events` are all empty until steps 4-7 finish. Several HIGH-tier
items below are sequenced behind this rebuild completing.

---

## HIGH — do first

| Idea | Effort | Risk | Reward | Note |
|---|---|---|---|---|
| Run the E1/E2 A/B judgment (`ops_ensemble_weight_compare.py`) | S | Low | High | Phase 142B.1 (COMPLETE 2026-07-04) built the E1 shrunk-IC and E2 mean-variance weighting variants plus the win-decision gate script, but deliberately did not run the actual judgment or promote a winner. That run is the standing next action — cheap, doesn't need the current rebuild to finish. |
| Re-run EIC-04 | — | — | High | Last run FAILED 2026-07-03 (0/50 qualifying cells at 0.60 threshold; EIC-05 diagnosis = data starvation, concentrated in one `5m`/`high_bear` cell). Blocked on the current corpus rebuild finishing — the whole point of re-running is to check whether the larger universe + Renaissance primitives fix the starvation. Phase 142B does not begin until this shows PASS or an operator override is recorded. |
| Interaction Primitives pilot (todo 037) | S | Low | High/cost | Measures ~20-30 hand-picked interaction primitives already specified in `renaissance-primitives-ohlcv.md` against real IC — settles whether atomic features are IC-saturated before anyone builds the full 30K-candidate Interaction Factory. Gate (Phase B corpus re-run) is satisfied; runnable once the current rebuild's `feature_ic_scores` exist. Gatekeeper for Phase 150's interaction layer — run before, not alongside. |
| Phase 143: Feature Lifecycle Routing | L (3 plans) | Low | High | PLANNED, depends only on Phase 141 (complete) — independently startable today, not blocked on anything else in this table. |
| Phase 144: Cross-Sectional Regime Model (`regime_group`) | L | Med | High | PLANNED. **Unblocked 2026-07-07** — the HMM weak-separation fallback decision is pre-committed (demote to shadow per weak regime_group, stratify on cross-sectional + volatility_pct; rates gets a pre-registered challenger). Ready for `/gsd-discuss-phase`. Batched into one `ic_engine` re-run with todo 026 P2b/P2c/P3, todo 041 (tag taxonomy audit), and `intel-12-stratification-dimension.md`'s first substitution test — plan as one unit, not four. **Foundational** — Cross-Group Lead-Lag IC and Phase 148 (AnalogEngine) both need clean peer groups this phase produces. |
| EM-CAL: empirical threshold calibration (todo 065) | S | Low | High | New 2026-07-08, from the Stage 4 Emission review. Current `alpha.quant.threshold.{tf}` seeds (1.5/1.2/1.0/0.8) are admitted guesses. Needs the current rebuild's fresh `feature_ic_scores`/`alpha_ensemble_ic` to calibrate against — don't run it against data mid-replacement. |

**Recently shipped (context, not action items):** HMM Numba JIT (40x speedup, Phase B/141 P2) ·
Phase 142A Ensemble IC Measurement (`alpha_ensemble_ic` schema + `EnsembleICEngine`, complete
2026-07-02, 10/10 verified) · Phase 142B.1 (E1/E2 variants + gate script, complete 2026-07-04) ·
Phase 142.5 Renaissance Primitives (91 new primitives, 152 total, complete 2026-07-07) · todo 030
cost-hurdle calibration (closed 2026-07-02) · todo 034 HMM walk-forward diagnostic (closed) ·
Canonical Simulator binding rule (no client builds its own counterfactual/replay path — routes
through `alpha_frames` + Invariant 1, enforced by pre-commit Check 9) · One Model, One Book
(`docs/foundation/principles.md` — one forecast per (symbol, tf, bar), binding on every row in
this table) · ETF Universe Expansion 58→80 (migrations 188/190, full backfill complete
2026-07-04 — removed as its own phase, `regime_group` routing for the new symbols is Phase 144's
job).

---

## MEDIUM — real value, not urgent, or reward genuinely unproven

| Idea | Effort | Risk | Reward | Note |
|---|---|---|---|---|
| Tag exposure-vs-sensitivity taxonomy audit (todo 041) | M | Low | Med, **load-bearing** | Batched into Phase 144's `ic_engine` re-run (see HIGH tier). Gates commodity/fx `regime_group` enablement directly — OIH/XLE/XOP carry both `eq_*` and `commodity_energy_*` tags and will raise `AmbiguousRegimeGroupError` the moment `commodity_energy` is enabled. |
| HMM regime audit — remaining P2b/P2c/P3 (todo 026) | S-M | Low-Med | Med | Batched into Phase 144's `ic_engine` re-run, not a standalone item. P0/P1a/P1b already shipped. Remaining: P2b (degenerate-model occupation-fraction gate), P2c (`hmm_churn` feature column), P3 (empirical threshold calibration for vix/breadth cuts). The heavier HMM-variant question (IOHMM/Hamilton/factor-augmented, see LOW tier) was resolved separately via the 2026-07-07 fallback pre-commitment — these three items are refinement, not a redesign. |
| Cross-Group Lead-Lag IC (`docs/research/cross-group-lead-lag-ic.md`) | M | Med | Med, unproven | Reuses existing `ic_engine` machinery. 6 candidate pairs identified (rates→precious metals cleanest). Real open risk: multiple pairs × lags × TFs needs the same BH-FDR discipline as cross-sectional IC. Gated on Phase 144 (needs clean peer groups on both sides of the join). |
| Phase 145: Empirical Instrument Tag Calibrator | L-XL | Med | High, latent | PLANNED. Evidence-gated into the Phase 144 batch: joins only if todo 041's audit shows tag calibration is load-bearing for group routing, not merely descriptive; otherwise trails independently (no hard dependency on Phase 148-150). |
| Phase 150: Feature Primitives Expansion + Theory-Motivated Interaction Layer | XL | Med | Med, uncertain | **Not the same scope as Phase 142.5** (which already shipped 91 OHLCV primitives, complete). This phase is the remaining ~60 candidates from todo 014 plus a capped (≤50) Theory-Motivated Interaction Layer — each interaction needs a stated finance-theory hypothesis, separate BH-FDR pool from atomics. Gated on the Interaction Primitives pilot (todo 037, HIGH tier) clearing first. Also the feeder for `intel-10` Confluence's gate 1 once ≥1 interaction term clears IC/OOS. |
| Volatility / Dispersion / Volume regime | S each | Low | Med-High, unproven | Consolidated under `intel-12-stratification-dimension.md`'s governance gate (structural-redundancy pre-filter → orthogonality study → substitution test) — the first substitution test runs as part of Phase 144's batch, not as independent triage per row. |
| `market_data_ohlcv` active-bars view (todo 035) | S | Low | Med | **Foundational.** 4 duplicated filters = correctness-drift risk; cheaper to fix before a 5th call site appears. |
| Zero-IC feature refinement (todo 033) | M | Low | Med | Fine either way — finds signal or confirms retirement. |
| Cross-sectional rank features (todo 013a) | M | Low | Med | Minor schema debt, not a signal question. |
| Phase 146: I7 Alpha Scorer Transition | L | Med | Med, conditional | PLANNED, conditional gate on Phase 141 CORPUS-07 (maps I7 plugins to `feature_vectors` dimensions). Default path is retirement-only, not conversion — most plugins are expected to be fully captured already. Not near-term actionable; CORPUS-07 hasn't been evaluated. |
| Phase 147: Alpha Scoring System + v2.x Retirement Gate | L | Med | High, eventual | PLANNED. Depends on Phase 146 complete + Phase 142A OOS data (exists but EIC-04 currently FAIL) + Phase 142B accumulating ≥60 trading days of closed `alpha_frames` (142B hasn't started — 0/2 plans). Real long-run value, multiple un-started phases deep — don't let it compete with 143/144 for near-term attention despite the eventual payoff. |
| IntegrityMonitor (Phase 151 + 152, `intel-14-integrity-monitor.md`) | XL | Low | High long-run, low now | Schedulable opportunistically any time after Phase 141 (complete) — Phase 151 depends only on `feature_vectors`; Phase 152 depends on Phase 142A (done) plus, for its E2B gate, Phase 142B's `alpha_frames` (not yet built). Insurance, not a fix — don't let it jump ahead of 143/144/147, which carry present-tense value. |

---

## LOW — downgraded, correctly gated, or no evidence yet

| Idea | Effort | Risk | Reward | Note |
|---|---|---|---|---|
| Session/time-of-day regime | S | V.Low | Downgraded | Cheap+safe isn't the same as valuable — no case made for why session effects matter at this system's (swing, not HFT) cadence. |
| Skew/tail regime | S | Low | Low-Med | Same governance gate as volume regime (intel-12), expect less even if cleared. |
| Factor regime | M | Med | Med | New infra (factor-return pipeline) for an arbitrary-threshold-prone payoff. |
| HMM variants — IOHMM / Hamilton / factor-augmented | L each | Med-High | Unproven | The deficiency question these were gated on is effectively answered by the 2026-07-07 fallback pre-commitment (demote-to-shadow + cross-sectional/vol_pct stratification chosen over building a heavier variant). Stays LOW — building one of these now would mean redoing work the chosen fallback already covers, and adds complexity against this codebase's own "simple features beat complex" principle. |
| Microstructure regime | XL | High | Med, far off | Needs order-flow infra that doesn't exist. |
| `ic_engine` pure function refactor (todo 032) | S | Low | Low | Hygiene, zero IC impact. |
| service_utils cleanup (todo 009) | S | Low | Low | Same. |
| Occam's Razor Evaluator | M | Low | Low now | Nothing complex to gate yet. |
| AnalogEngine (Phase 148/149) | XL | High | Speculative | Substrate ships and validates (embedding calibration, retrieval quality) before any full historical build — a cheap pilot step exists (`intel-13-analog-engine.md`). Stays LOW/XL/High-risk: gated on Phase 142A's OOS proof pattern generalizing, and hard-gated on v3.15 (Phases 144/145) completing first per `intel-13`'s own prerequisite. |
| Alternative Data Vectors (Phase 154) | L | Med | Med | Not actionable — no data source chosen. |
| Evolvable AI Agents / Alpha Search Orchestration | XL | High | Speculative | No evidence current single-model approach is insufficient. |

---

**Unverified, worth a direct read before relying on:** `docs/research/signal-08` (Intelligence
Vectors — may be the actual v3.0 Feature Factory precursor) and `docs/research/ai-02` (MLAgent —
check if `ensemble_trainer.py` already subsumes it).
