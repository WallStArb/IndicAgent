# v3.0 Intelligence Lifecycle — Priority Matrix

**Date:** 2026-07-08. Full rewrite of the 2026-07-01 version (superseded — see git history for
the correction trail; this version states current facts only). Scope: v3.0 intelligence
lifecycle ideas (Feature Factory, IC, regime detection/stratification, ensemble, tagging,
AlphaEngine), pulled from wherever they live — doc/phase/todo location doesn't matter.

**Columns:** Effort (S/M/L/XL) · Risk (Low/Med/High) · Reward (scored against evidence, not
the idea doc's own claim — Med/unproven means "plausible, untested") · **Foundational** =
cheaper to do now than to retrofit once other things build on top of it — bumps priority
independent of raw effort/risk/reward.

**Operational context (updated 2026-07-10):** Phase 142B (`alpha_frames` schema +
`AlphaFrameWriter` + `CounterfactualTracker`) and Phase 143 (Feature Lifecycle Routing, merged
with 149B) both shipped COMPLETE 2026-07-10 — see "Recently shipped." Todo 037 (Interaction
Primitives Pilot) also completed 2026-07-10, PASS verdict — see "Recently shipped" and
`docs/research/intel-feature-interaction-factory.md`. **`alpha_frames` still has 0 rows** —
Phase 142B shipped the writer/tracker machinery but the actual backfill run has not been
executed; this is the standing concrete next step (see HIGH tier Todos below), not gated on
anything. The 6th corpus rebuild (2026-07-09, `feature_ic_scores` 920,649 rows, `alpha_events`
12,258,206 rows) remains the trustworthy full-universe measurement base for everything here.

---

## HIGH — do first

**Todos and Phases are two different execution tracks, not one ranked queue.** A todo is a
single-session, run-it-now technical action — no formal workflow required. A phase goes through
the full `/gsd-discuss-phase → plan-phase → execute-phase → verify` pipeline and is a
multi-session commitment. They don't compete for the same "next slot": a todo can run today
while a phase's discussion is separately kicked off today. Ranking them on one list (as an
earlier version of this doc did) wrongly implied you must pick one before the other.

### Todos (run directly, no phase workflow needed)

**Single source of truth for todo-level prioritization is `.planning/todos/PRIORITIES.md`** —
not this table. That file ranks every actionable `pending/` todo (P0-P3) across the whole repo,
not just intelligence-lifecycle scope, and is the one place that ranking gets maintained.
Reorg'd 2026-07-10 specifically to stop this matrix and the todo system from independently
re-deriving the same priority judgment and silently drifting out of sync — see its own reorg
note for what moved. Top of its P0/P1 tiers as of 2026-07-10: todo 093 (`alpha_frames` backfill,
filed from this table's former entry — it had been tracked only as a matrix bullet, not a real
todo), todo 065 (EM-CAL), todo 091 (Fisher-z CI miscalibration), todo 092 (regime-model
threshold calibration, split out of todo 026's P3).

### Phases (each needs its own `/gsd-discuss-phase` cycle)

| Idea | Effort | Risk | Reward | Note |
|---|---|---|---|---|
| Phase 144: Cross-Sectional Regime Model (`regime_group`) | L | Med | High | PLANNED. **Foundational** — Cross-Group Lead-Lag IC and Phase 149 (AnalogEngine) both need clean peer groups this phase produces; cheaper to absorb this dependency now than retrofit later. Ready for `/gsd-discuss-phase`. Batches in todo 026 P1b/P2a/P2b/P2c, the tag taxonomy audit (folded 2026-07-13 into `stratification-instrument-tag-calibrator.md`'s "Open question" section, formerly todo 041), and `stratification-dimension-unification.md`'s first substitution test — plan as one unit, not four. (026's P3 was split back out to standalone todo 092, 2026-07-10 — fresh evidence flags it as a live-path IC suspect, not batch-hygiene that can wait for this phase.) Also the more direct lever on the sparse-IC problem (see EIC-04 result below): re-stratifying may recover signal currently smeared across weak regime buckets. **Now the only un-started HIGH-tier phase in this table** — Phase 143 shipped 2026-07-10, see "Recently shipped." |

**Recently shipped (context, not action items):** HMM Numba JIT (40x speedup, Phase B/141 P2) ·
Phase 142A Ensemble IC Measurement (`alpha_ensemble_ic` schema + `EnsembleICEngine`, complete
2026-07-02, 10/10 verified) · Phase 142B.1 (E1/E2 variants + gate script, complete 2026-07-04) ·
Phase 142.5 Renaissance Primitives (91 new primitives, 152 total, complete 2026-07-07; note two
of these, `new_high_flag`/`new_low_flag`, were later found mathematically redundant with
`dist_from_high`/`dist_from_low` and removed via migration 211 — 89 primitives, 150 columns as
of 2026-07-09) · todo 030 cost-hurdle calibration (closed 2026-07-02) · todo 034 HMM
walk-forward diagnostic (closed) · Canonical Simulator binding rule (no client builds its own
counterfactual/replay path — routes through `alpha_frames` + Invariant 1, enforced by pre-commit
Check 9) · One Model, One Book (`docs/foundation/principles.md` — one forecast per (symbol, tf,
bar), binding on every row in this table) · ETF Universe Expansion 58→80 (migrations 188/190,
full backfill complete 2026-07-04 — removed as its own phase, `regime_group` routing for the new
symbols is Phase 144's job) · **E1/E2 A/B judgment (2026-07-09):** ran against the fresh corpus,
E2 (mean-variance) LOSS in 20/20 strata (caveat: 16/20 fell back to `cluster_deflate_weights`,
not a clean E2 test); E1 (shrunk-IC) remains champion by default, nothing promoted · **EIC-04
re-run (2026-07-09):** FAILed at the stale 0.60 threshold (35/1585 = 2.21% qualifying, confirmed
genuine-but-sparse signal via p-value histogram, not data starvation), then the threshold itself
was recalibrated to 0.02 `[rca_analysis]` and re-verified PASS — Phase 142B is now unblocked on
this gate · todo 067 (ic_engine write_conn idle-timeout) — closed 2026-07-09, confirmed fixed by
the first clean end-to-end rebuild · **Todo 037 pilot (2026-07-10):** PASS -- 22.2% (192/864)
of interaction-primitive cells carried genuine incremental IC after controlling for parent
atomics, broad-based across all 8 features (6.5%-30.6% pass rate each) -- clears Phase 151's
evidence gate (does NOT revive the deferred combinatorial todo 019 design — Phase 151's own
curated ≤50-feature approach was independently justified on BH-FDR power grounds, see
`docs/research/intel-feature-interaction-factory.md`) · todo 088 (`hold_max_bars` fallback bug) —
fixed and re-calibrated 2026-07-09, 16/36 regime×tf cells now genuinely calibrated (remaining 20
correctly retain the `[initial_estimate]` seed pending 1h/1d decay-curve evidence) · **Phase
142B (2026-07-10):** `alpha_frames` schema + `AlphaFrameWriter` + `CounterfactualTracker` +
frozen `SHADOW-REVIEW.md` promotion criteria shipped, 2/2 plans verified — machinery only,
`alpha_frames` itself still has 0 rows, see the backfill todo above · **Phase 143 (2026-07-10):**
Feature Lifecycle Routing (merged with 149B) shipped, 3/3 plans verified — evidence-based
`feature_registry` promotion/demotion state machine, `ic_engine` post-run lifecycle hook,
`integrity_monitor` table + diagnostics SQL.

---

## MEDIUM — real value, not urgent, or reward genuinely unproven

| Idea | Effort | Risk | Reward | Note |
|---|---|---|---|---|
| Tag exposure-vs-sensitivity taxonomy audit (`stratification-instrument-tag-calibrator.md`'s "Open question," formerly todo 041) | M | Low | Med, **load-bearing** | Batched into Phase 144's `ic_engine` re-run (see HIGH tier). Gates commodity/fx `regime_group` enablement directly — OIH/XLE/XOP carry both `eq_*` and `commodity_energy_*` tags and will raise `AmbiguousRegimeGroupError` the moment `commodity_energy` is enabled. |
| Concept Registry MVP (`.planning/todos/pending/112-concept-registry.md`) | M | Low | Low now, Med long-run | Additive, no live consumer today (zero `concept_*` tables, zero rows would break). Reward isn't hypothetical, though — the exact failure it exists to prevent already happened once this session (todo 088/096 briefly and incorrectly merged, caught and reverted only because a human was watching closely). Full implementation plan already written (`docs/plans/2026-07-13-concept-registry-mvp-implementation-plan.md`); queued for `/gsd-discuss-phase` as Phase 160, 2026-07-13. Ranks above Controlled Vocabulary below on Reward — this one has a real incident as evidence, that one doesn't yet. |
| Controlled Vocabulary (`.planning/todos/pending/110-controlled-vocabulary.md`) | M | Low | Low | Additive, no live consumer, and unlike Concept Registry above, no incident has yet demonstrated the cost of not having it — scattered hardcoded enums have caused zero known bugs so far. Previously had zero todo tracking it at all (found 2026-07-13, not inherited). Queued for `/gsd-discuss-phase` as Phase 161, behind Concept Registry. |
| HMM regime audit — remaining P2b/P2c/P3 (todo 026) | S-M | Low-Med | Med | Batched into Phase 144's `ic_engine` re-run, not a standalone item. P0/P1a/P1b already shipped. Remaining: P2b (degenerate-model occupation-fraction gate), P2c (`hmm_churn` feature column), P3 (empirical threshold calibration for vix/breadth cuts). The heavier HMM-variant question (IOHMM/Hamilton/factor-augmented, see LOW tier) was resolved separately via the 2026-07-07 fallback pre-commitment — these three items are refinement, not a redesign. |
| Cross-Group Lead-Lag IC (`docs/research/cross-group-lead-lag-ic.md`) | M | Med | Med, unproven | Reuses existing `ic_engine` machinery. 6 candidate pairs identified (rates→precious metals cleanest). Real open risk: multiple pairs × lags × TFs needs the same BH-FDR discipline as cross-sectional IC. Gated on Phase 144 (needs clean peer groups on both sides of the join). |
| Phase 146: Empirical Instrument Tag Calibrator | L-XL | Med | High, latent | PLANNED. Evidence-gated into the Phase 144 batch: joins only if the tag taxonomy audit (above) shows tag calibration is load-bearing for group routing, not merely descriptive; otherwise trails independently (no hard dependency on Phase 149-151). |
| Phase 151: Feature Primitives Expansion + Theory-Motivated Interaction Layer | XL | Med | Med-High, evidence-backed | **Not the same scope as Phase 142.5** (which already shipped 89 primitives, complete). This phase is the remaining ~60 candidates from todo 014 plus a capped (≤50) Theory-Motivated Interaction Layer — each interaction needs a stated finance-theory hypothesis, separate BH-FDR pool from atomics. **Evidence gate cleared 2026-07-10** (todo 037 PASS, see "Recently shipped") — ready for `/gsd-discuss-phase`, no longer blocked. Also the feeder for `intel-10` Confluence's gate 1 once ≥1 interaction term clears IC/OOS. |
| Volatility / Dispersion / Volume regime | S each | Low | Med-High, unproven | Consolidated under `stratification-dimension-unification.md`'s governance gate (structural-redundancy pre-filter → orthogonality study → substitution test) — the first substitution test runs as part of Phase 144's batch, not as independent triage per row. |
| StratificationDimension formalization (`.planning/todos/pending/111-stratification-classification.md`) — **registered as ROADMAP Phase 145** (2026-07-13) | **not scoreable yet** | — | — | Blocked on Phase 144's D-05 empirical verdict (itself blocked on the in-progress 143.1-07 corpus re-run) — same gate every regime-candidate row on this page already respects. Don't force an Effort/Risk/Reward score before the row-grain decision (Option A vs. B, see `concept-unified-registry.md` Domain Vetting) has real evidence to ratify against. Revisit once that verdict lands. |
| `market_data_ohlcv` active-bars view (todo 035) | S | Low | Med | **Foundational.** 4 duplicated filters = correctness-drift risk; cheaper to fix before a 5th call site appears. |
| Zero-IC feature refinement (todo 033) | M | Low | Med | Fine either way — finds signal or confirms retirement. |
| Cross-sectional rank features (todo 013a) | M | Low | Med | Minor schema debt, not a signal question. |
| Phase 147: I7 Alpha Scorer Transition | L | Med | Med, conditional | PLANNED, conditional gate on Phase 141 CORPUS-07 (maps I7 plugins to `feature_vectors` dimensions). Default path is retirement-only, not conversion — most plugins are expected to be fully captured already. Not near-term actionable; CORPUS-07 hasn't been evaluated. |
| Phase 148: Alpha Scoring System + v2.x Retirement Gate | L | Med | High, eventual | PLANNED. Depends on Phase 147 complete + Phase 142A OOS data (exists, EIC-04 now PASS) + Phase 142B accumulating ≥60 trading days of closed `alpha_frames` (142B's writer/tracker machinery shipped 2026-07-10, but `alpha_frames` has 0 rows — the backfill run hasn't been executed yet, see HIGH tier Todos). Real long-run value, but still gated on that backfill running and 60 trading days actually accumulating after — don't let it compete with 144 for near-term attention despite the eventual payoff. |
| IntegrityMonitor (Phase 152 + 153, `intel-14-integrity-monitor.md`) | XL | Low | High long-run, low now | Schedulable opportunistically any time after Phase 141 (complete) — Phase 152 depends only on `feature_vectors`; Phase 153 depends on Phase 142A (done) plus, for its E2B gate, Phase 142B's `alpha_frames` (schema + writer shipped 2026-07-10, still 0 rows pending the backfill run). Insurance, not a fix — don't let it jump ahead of 144/148, which carry present-tense value. |

---

## LOW — downgraded, correctly gated, or no evidence yet

| Idea | Effort | Risk | Reward | Note |
|---|---|---|---|---|
| Session/time-of-day regime | S | V.Low | Downgraded | Cheap+safe isn't the same as valuable — no case made for why session effects matter at this system's (swing, not HFT) cadence. |
| Skew/tail regime | S | Low | Low-Med | Same governance gate as volume regime (`stratification-dimension-unification.md`), expect less even if cleared. |
| Factor regime | M | Med | Med | New infra (factor-return pipeline) for an arbitrary-threshold-prone payoff. |
| HMM variants — IOHMM / Hamilton / factor-augmented | L each | Med-High | Unproven | The deficiency question these were gated on is effectively answered by the 2026-07-07 fallback pre-commitment (demote-to-shadow + cross-sectional/vol_pct stratification chosen over building a heavier variant). Stays LOW — building one of these now would mean redoing work the chosen fallback already covers, and adds complexity against this codebase's own "simple features beat complex" principle. |
| Microstructure regime | XL | High | Med, far off | Needs order-flow infra that doesn't exist. |
| `ic_engine` pure function refactor (todo 032) | S | Low | Low | Hygiene, zero IC impact. |
| service_utils cleanup (todo 009) | S | Low | Low | Same. |
| Occam's Razor Evaluator | M | Low | Low now | Nothing complex to gate yet. |
| AnalogEngine (Phase 149/150) | XL | High | Speculative | Substrate ships and validates (embedding calibration, retrieval quality) before any full historical build — a cheap pilot step exists (`intel-13-analog-engine.md`). Stays LOW/XL/High-risk: gated on Phase 142A's OOS proof pattern generalizing, and hard-gated on v3.15 (Phases 144/146) completing first per `intel-13`'s own prerequisite. |
| Alternative Data Vectors (Phase 155) | L | Med | Med | Not actionable — no data source chosen. |
| Evolvable AI Agents / Alpha Search Orchestration | XL | High | Speculative | No evidence current single-model approach is insufficient. |

---

**Unverified, worth a direct read before relying on:** `docs/research/signal-08` (Intelligence
Vectors — may be the actual v3.0 Feature Factory precursor) and `docs/research/ai-02` (MLAgent —
check if `ensemble_trainer.py` already subsumes it).
