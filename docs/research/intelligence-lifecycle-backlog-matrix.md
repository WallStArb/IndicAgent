# v3.0 Intelligence Lifecycle — Priority Matrix

**Last rewritten:** 2026-07-08 (a full rewrite of an earlier 2026-07-01 version, itself
superseded — see git history for the correction trail). **Filename is stable, not date-stamped**
as of 2026-07-13 — this doc is a living reference, edited in place as facts change (see
"Operational context" below for an example), not re-dated on every revision. Update this line on
the next full rewrite; don't rename the file to match. Scope: v3.0 intelligence lifecycle ideas
(Feature Factory, IC, regime detection/stratification, ensemble, tagging, AlphaEngine), pulled
from wherever they live — doc/phase/todo location doesn't matter.

**Columns:** Effort (S/M/L/XL) · Risk (Low/Med/High) · Reward (scored against evidence, not
the idea doc's own claim — Med/unproven means "plausible, untested") · **Foundational** =
cheaper to do now than to retrofit once other things build on top of it — bumps priority
independent of raw effort/risk/reward.

**Operational context (updated 2026-07-21):** This table went stale between 2026-07-08 and
2026-07-21 — Phase 143.1 (Measurement and Eligibility Integrity) shipped COMPLETE in that
window (8/8 plans, 143.1-08 shadow-mode verdict: HOLD, `alpha.ensemble.sign_symmetric` stays
`false`), along with Phase 160 (Concept Registry MVP) and Phase 161 (Controlled Vocabulary) —
see "Recently shipped," rows for both removed from MEDIUM below since they're no longer
open work. `alpha_frames` backfill also ran (todo 093, 23.15M rows, see todo 161's closeout) —
the "0 rows" caveat below is stale, kept only as a dated marker. **Four phases (162/163/164/165)
were registered since the last full rewrite and had never been scored** (same gap this table
caught itself making with Phases 156-159 last time) — all four now scored: Phase 162 in HIGH
(a live stability bug, not just throughput), Phases 163/165 in MEDIUM, Phase 164 in MEDIUM but
lower-ranked (least ready, real raw-price-trap risk). **Phase 144 is now COMPLETE (2026-07-22)**
— its D-05 verdict landed (F1 not triggered, F2 triggered for 15m/5m; full detail in ROADMAP.md's
Phase 144 section), unblocking Phase 145 (not yet scored — see its row below). The
measurement base is now the 143.1-07 corpus rebuild (2026-07-19) plus todos 124/160's
`market_data_ohlcv_tradeable` correctness fix (2026-07-21) — treat any pre-2026-07-21 IC number
sourced from `feature_vectors.true_range_pct` as suspect until todo 147's third CV re-check
(still outstanding, see PRIORITIES.md) confirms parity.

**Corrected 2026-07-22, then corrected again same day** (via `/gsd-discuss-phase 147` —
worth recording the wrong turn, not just the fix): first pass found Phase 147 mis-filed
"CANCELLED 2026-07-14" (superseded 2026-07-19, todo 056 revived it) and, reading ROADMAP.md's
"Depends on: Phase 147 complete" line at face value, concluded Phase 147 was the sole gate on
Phase 148 — moved both to HIGH on that basis. **That "Depends on" line was itself stale and
never got caught** — SCORE-01/02/03 (Phase 148's actual gates) read only `alpha_frames`/
`alpha_ensemble_ic`/`alpha_strategy_scores`, pure v3.0 tables with zero I7 lineage; the only
place Phase 147 ever connected to Phase 148 was SCORE-04's old v2.x comparison, which the
2026-07-19 rewrite already downgraded to "documentation only, not a gate" — the dependency
line just never got updated to match. **Phase 148 is unblocked today, independent of Phase
147.** Phase 147 stays HIGH-ish only in the sense that it's cheap due diligence worth doing
eventually (does the archived, zero-live-consumer I7 system hold any signal not already in
the v3.0 Feature Factory) — it is not gating anything and should not compete with Phase 148
for near-term attention. This is independent of both Phase 144's D-05 track (regime-model
refinement, blocked on the symbol_hmm restoration fix) and Phase 162 (infra throughput,
separate concurrent session) — parallel tracks, not one queue.

**Updated 2026-07-22, later same day:** Phase 148 finalized — renamed (dropped "v2.x
Decommission" from the title, never matched actual scope), cross-AI reviewed, replanned with
review fixes, independently verified PASS WITH CONCERNS. Execution-ready. Separately, before
executing it, a sanity check on whether Phase 148 was really the right next step (not just
deference to the stored order) surfaced that todo 160's real root cause was one level deeper
than its own filing understood: `ops_known_corrupt_print_cleanup.py`'s candidate discovery was
itself broken (gated behind `forward_returns` suspect flags, structurally blind to
corruption confined to `high`/`low`), not just missing 2 rows. Fixed the discovery mechanism
directly rather than hand-patching known-bad rows — found and corrected 40 bars across 14
symbols (20x the previously-known count). This mattered because Phase 148's Gate 2 is
irreversible (run once ever) and reads `alpha_frames`, which is downstream of the same
feature computation this bug corrupted — worth fixing before spending that one shot, not
after. Recompute in progress at session-note time; todo 147's third CV re-check and both
todos' closure to follow.

**Updated 2026-07-23:** Both Phase 148 and Phase 162 executed and closed same session (see
their HIGH-tier rows below for outcome detail). Phase 148 delivered the actual verdict this
whole table's top priority existed to produce: Gate 1 (signal proof) PASS, Gate 2 (execution
proof) FAIL — do not promote to live capital. **This creates a new HIGH-tier item, Phase 166
(Frame/Execution Recalibration)**, registered same day from todo 174 — the pre-registered
"if Gate 2 fails but Gate 1 passes: frame problem" playbook, now the actual highest-priority
open item on this table. Phase 162 shipped its whole-cell fingerprint mechanism, empirically
proven equivalent to forced recompute; a real BLOCKER found via code review (per-symbol
watermark scoping) and fixed same session.

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
| Phase 144: Cross-Sectional Regime Model (`regime_group`) | L | Med | High | **COMPLETE 2026-07-22** (6/6 plans, D-05 verdict landed). The symbol_hmm restoration fix (`dual_write_symbol_hmm`, migration 247) unblocked D-05, which then ran for real: **F1 not triggered** (TLT's per-symbol HMM stays deficient, demotion holds — matches the original 2026-07-02 finding) and **F2 triggered for 15m/5m** (rates cross-sectional is ALSO deficient at high frequency — pre-registered build trigger for a factor-augmented HMM challenger, pending confirmation `volatility_pct` hasn't already passed its own substitution gate for rates). Full verdict in ROADMAP.md's Phase 144 section. Cross-Group Lead-Lag IC and Phase 145 are now unblocked by this row closing — see their own rows for current status. |
| Phase 166: Frame/Execution Recalibration | TBD | TBD | High | **NEW 2026-07-23**, registered from todo 174. **The actual highest-priority item on this table now** — Phase 148's OOS gates delivered the split verdict this whole table's Phase 148 row existed to produce (Gate 1 PASS, Gate 2 FAIL), and this is ROADMAP's own pre-registered playbook for exactly that outcome: diagnose why the frame simulation (stop/target/hold) fails to capture the proven signal (Gate 1) as profitable OOS P&L, and recalibrate against the EIC-02 IC decay curve. Not yet planned — `/gsd-discuss-phase 166` is the next step, no Effort/Risk score yet (same "don't leave unscored indefinitely" gap this table has caught itself making before). Gates Phases 149-159 (portfolio/execution/risk infra) from proceeding until it produces a real Gate 2 PASS. |
| Phase 162: ic_engine Corpus Pipeline Throughput | M-L | Med | High | **COMPLETE 2026-07-23** (4/4 plans). Whole-cell `ic_cell_fingerprints` mechanism shipped and empirically proven equivalent to a forced `--refresh` recompute (`ops_ic_fingerprint_equivalence.py`, byte-identical `feature_ic_scores`, ~80x faster on skip). The Med risk rating proved warranted, not just cautious: post-execution code review found a real BLOCKER (CR-01) in the per-symbol fingerprint watermark's cross-sectional scoping — exactly the "silent-wrong-IC risk, not just a crash" this row flagged in advance — found and fixed same session, independently re-verified. 3 of 7 success criteria (full-corpus wall-clock, surgical-invalidation timing, thread benchmark) need an actual 80-symbol corpus run to close empirically, tracked in `162-HUMAN-UAT.md`, not blocking. Bundled todos 122/129(partial)/133/134/139/140 — closed. |
| Phase 148: Alpha Scoring System (OOS Proof Gates) | L | Med | High | **COMPLETE 2026-07-22 (5/5 plans) — VERDICT: do not promote to live capital.** Gate 1 (signal proof) PASS (140/640 = 21.875% of 5m/15m cells qualify, >10x the 2% floor). Gate 2 (execution proof) FAIL, decisively — 3 of 5 SHADOW-REVIEW criteria, ~960% max drawdown vs a 0.25 ceiling, not a borderline call under any methodology variant tested. Full evidence: `docs/plans/2026-07-22-phase148-promotion-decision.md`. **This delivered the milestone's defining answer — the signal is real, the current frame/execution design doesn't yet capture it profitably.** Direct follow-on: Phase 166 (new row above). |
| Phase 147: I7 CORPUS-07 Evaluation | S | Low | Low (due diligence, not alpha) | **Downgraded 2026-07-22** — not a gate on anything (see Phase 148's row: the dependency was stale). Scope: map each of the 35 registered I7 plugins (`shadow_registry`, `component_type='i7_plugin'`, zero ever promoted/evaluated live) to `feature_vectors` dimensions + Phase 141 IC results; default outcome retirement, rare survivors register as ordinary v3.0 features. The pipeline that would run these plugins (`indicagent-intelligence-pipeline.service`) has been `failed` since 2026-07-17 with its `ExecStart` target deleted from disk — zero live blast radius either way. Worth doing eventually for "never drop data that could contain signal" completeness; do not let it compete with Phase 166 for attention. Not planned yet. |

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
frozen `concept-promotion-reversion-gate.md` promotion criteria shipped, 2/2 plans verified,
backfill has since run (todo 093, 23.15M rows) · **Phase 143 (2026-07-10):**
Feature Lifecycle Routing (merged with 149B) shipped, 3/3 plans verified — evidence-based
`feature_registry` promotion/demotion state machine, `ic_engine` post-run lifecycle hook,
`integrity_monitor` table + diagnostics SQL · **Phase 143.1 (2026-07-21):** Measurement and
Eligibility Integrity, 8/8 plans — shadow-mode champion/challenger validation (143.1-08)
concluded **HOLD**, `alpha.ensemble.sign_symmetric` stays `false` (confirmed twice: pooled and
via todo 165's regime-stratified re-evaluation); this is the gate the sign-symmetric ensemble
redesign (todo 094) was waiting on, now closed with a definitive negative result, not a stall ·
**Phase 160 (2026-07-13-ish, closed 2026-07-21 window):** Concept Registry MVP, 4/4 plans —
4-table schema + `ConceptRegistryService`/API/dashboard, live · **Phase 161:** Controlled
Vocabulary System, 4/4 plans (2026-07-18) — schema + `VocabularyService` + drift audit + API
route, 23/24 truths verified · **Todos 164/165 (2026-07-21):** regime-stratified OOS promotion
gate (`evaluate_frame_gate` generalized with a grouping-key + coverage-floor param) and
per-timeframe ensemble eligibility (`1h` now writes 5/7 regimes, was 0/7) — both closed, merged
to `main` · **Phase 148 (2026-07-22):** Alpha Scoring System, 5/5 plans — the milestone's
defining OOS proof gates ran exactly once each (D-04): Gate 1 (signal proof) PASS, Gate 2
(execution proof) FAIL, 3/5 SHADOW-REVIEW criteria, ~960% max drawdown. VERDICT: do not
promote v3.0 AlphaEngine to live capital. Direct follow-on registered as Phase 166 (see HIGH
tier) · **Phase 162 (2026-07-23):** ic_engine Corpus Pipeline Throughput, 4/4 plans —
whole-cell fingerprint mechanism, empirically proven equivalent to forced recompute; 1 real
BLOCKER (CR-01, per-symbol watermark scoping) found via code review and fixed same session.

---

## MEDIUM — real value, not urgent, or reward genuinely unproven

| Idea | Effort | Risk | Reward | Note |
|---|---|---|---|---|
| Tag exposure-vs-sensitivity taxonomy audit (`stratification-instrument-tag-calibrator.md`'s "Open question," formerly todo 041) | M | Low | Med, **load-bearing** | Batched into Phase 144's `ic_engine` re-run (see HIGH tier). Gates commodity/fx `regime_group` enablement directly — OIH/XLE/XOP carry both `eq_*` and `commodity_energy_*` tags and will raise `AmbiguousRegimeGroupError` the moment `commodity_energy` is enabled. |
| Phase 163: VP/SR Structural Primitives | M | Low | Med-High | **Newly scored 2026-07-21** (registered 2026-07-20, fully planned 2026-07-21 — 3/3 plans, all Fable/Codex review rounds resolved, execution-ready via `/gsd-execute-phase 163`, not yet run). Closes todo 153, a real "can we trust this data" gap: `poc_dist_atr`/`va_position`/`sr_support_dist`/`sr_resist_dist` are stuck at constant `FeatureCache` defaults in both live and batch, making their `feature_ic_scores.ic_value=0` a constant-input artifact, not a measured null result. Self-contained, no cross-phase dependency, same computation cost as the archived plugin it ports. Reward scored Med-High (not evidence-backed like Phase 151) because fixing a known-corrupt input is closer to a correctness fix than a speculative new feature — but no IC pilot has run on it yet, so not scored High outright. Highest-readiness item in this tier. |
| Phase 165: Swing/Fib/Trend Structure Primitives | L | Low-Med | Med, unproven | **Newly scored 2026-07-21** (context/research done 2026-07-21, Fable-reviewed, not yet planned — `/gsd-plan-phase 165` is the next step). 41 new columns across 5 files (swing/momentum/trend-structure/fibonacci-zones/session-levels). Risk scored Low-Med rather than Med because the research pass already found and pre-scoped fixes for 2 silent-wrong-answer bugs before any code was written — lower execution risk than a typical first-pass port. Reward stays "unproven" on this table's own convention (Phase 151 only earned "evidence-backed" after todo 037's pilot; no equivalent pilot has run for these primitives) — one candidate addition (Fibonacci extensions) was already deliberately deferred by its own research pass as premature scaling. |
| Phase 164: SMC Institutional Footprint Primitives | L | Med | Med, unproven | **Newly scored 2026-07-21** (registered 2026-07-20, not planned — no CONTEXT/RESEARCH/PLAN yet, least ready of the three primitive-expansion phases). Ports order blocks/FVG/liquidity sweeps/supply-demand zones/AMD cycle/breaker-mitigation/BOS-CHoCH from archived v2.x `smc_context` plugins. Risk scored Med (not Low like 163) because ROADMAP.md already flags the same raw-price-vs-ATR-companion trap Phase 163's D-16/D-17 caught mid-review — real risk of repeating a known bug class during the port, not hypothetical. Sequenced after 163 for shared conventions, no hard code dependency, so it can slip without blocking anything. |
| HMM regime audit — remaining P4a/P4b + seed-stability check (todo 026) | S-M | Low | Low-Med | **Corrected 2026-07-14** (prior row text was stale): P0/P1a/P1b/P2b/P2c all shipped, P2a forked to standalone todo 108, P3 forked to standalone todo 092 (now MEDIUM-tier itself, live-path evidence). The only scope left in 026 is the rolling-refit pilot (P4a/P4b) plus its bundled seed-stability check — both GATED on a 4-condition decision gate that has never cleared, and currently inert: `alpha.regime.equity_model_enabled=true` routes every live IC measurement around the per-symbol HMM this targets, so the leak contaminates nothing today (2026-07-09 finding). The 2026-07-07 fallback pre-commitment (demote-to-shadow) already shipped the cheap governance-level mitigation. One legitimate re-activation trigger remains: F5 in `fable-2026-07-07-phase144-conditioning-decision.md`, if the TLT model-class-mismatch diagnosis is ever challenged. Correctly stays in `deferred/`, not ranked in PRIORITIES.md by that file's own pending/-only scope. |
| Cross-sectional regime grid shape never validated (`.planning/todos/pending/135-cross-sectional-regime-grid-shape-never-validated.md`) | S-M | Low | Med, **load-bearing** | Filed 2026-07-18. The equity (3×3=9 cell) and rates (3×2=6 cell) cross-sectional grids were fixed by design, never selected via a BIC-style or IC-separation model-selection study the way HMM's K=5 was (Phase 140.5 P2). Distinct from todo 092 (cut-point values within the existing grid) — this is whether the cell count itself is right. High load-bearing weight given `equity_model_enabled=true` routes essentially all live IC measurement through this grid today. Natural sequencing: after todo 092's cut-point recalibration, alongside Phase 145's substitution-test machinery (which will re-litigate "how many cells" per new candidate dimension anyway). |
| Cross-Group Lead-Lag IC (`docs/research/cross-group-lead-lag-ic.md`) | M | Med | Med, unproven | Reuses existing `ic_engine` machinery. 6 candidate pairs identified (rates→precious metals cleanest). Real open risk: multiple pairs × lags × TFs needs the same BH-FDR discipline as cross-sectional IC. Gated on Phase 144 (needs clean peer groups on both sides of the join). |
| Phase 146: Empirical Instrument Tag Calibrator | L-XL | Med | High, latent | **SHIPPED 2026-07-17** (5/5 plans) — stale row, this table hadn't caught up. `TagCalibrator` live-verified: 11/12 measurable tags carry real `source='empirical'` rows. See STATE.md's phase summary table. |
| Phase 151: Feature Primitives Expansion + Theory-Motivated Interaction Layer | XL | Med | Med-High, evidence-backed | **Not the same scope as Phase 142.5** (which already shipped 89 primitives, complete). This phase is the remaining ~60 candidates from todo 014 plus a capped (≤50) Theory-Motivated Interaction Layer — each interaction needs a stated finance-theory hypothesis, separate BH-FDR pool from atomics. **Evidence gate cleared 2026-07-10** (todo 037 PASS, see "Recently shipped") — ready for `/gsd-discuss-phase`, no longer blocked. Also the feeder for `intel-10` Confluence's gate 1 once ≥1 interaction term clears IC/OOS. |
| Volatility / Dispersion / Volume regime | S each | Low | Med-High, unproven | Consolidated under `stratification-dimension-unification.md`'s governance gate (structural-redundancy pre-filter → orthogonality study → substitution test) — the first substitution test runs as part of Phase 144's batch, not as independent triage per row. |
| StratificationDimension formalization (`.planning/todos/pending/111-stratification-classification.md`) — **registered as ROADMAP Phase 145** (2026-07-13) | **not yet scored** | — | — | **Updated 2026-07-22:** its blocking gate cleared — Phase 144's D-05 verdict landed (F1 not triggered, F2 triggered for 15m/5m; see Phase 144's row above). Unblocked for `/gsd-plan-phase 145`, but this row itself still needs a real Effort/Risk/Reward pass once planning starts — the row-grain decision (Option A vs. B, `concept-unified-registry.md` Domain Vetting) can now be informed by real evidence instead of planned blind. Don't leave this "not yet scored" indefinitely now that its gate is clear — same gap this table has caught itself making twice before (Phases 156-159, then 162-165). |
| `market_data_ohlcv` active-bars view (todo 035) | S | Low | Med | **Foundational.** 4 duplicated filters = correctness-drift risk; cheaper to fix before a 5th call site appears. |
| Zero-IC feature refinement (todo 033) | M | Low | Med | Fine either way — finds signal or confirms retirement. |
| Cross-sectional rank features (todo 013a) | M | Low | Med | Minor schema debt, not a signal question. |
| ~~Phase 147: I7 Alpha Scorer Transition~~ | — | — | — | **Moved to HIGH tier 2026-07-22, then downgraded within HIGH same day** — see HIGH tier: not cancelled, but not a gate on anything either. |
| ~~Phase 148: Alpha Scoring System (OOS Proof Gates)~~ | — | — | — | **COMPLETE 2026-07-22** — see HIGH tier's "Recently shipped" section for the verdict. |
| IntegrityMonitor (Phase 152 + 153, `intel-14-integrity-monitor.md`) | XL | Low | High long-run, low now | Schedulable opportunistically any time after Phase 141 (complete) — Phase 152 depends only on `feature_vectors`; Phase 153 depends on Phase 142A (done) plus, for its E2B gate, Phase 142B's `alpha_frames` (schema + writer shipped 2026-07-10; backfill has since run, todo 093 closed). Insurance, not a fix — don't let it jump ahead of 144/148, which carry present-tense value. |
| Phase 156: Portfolio State Foundation | L | Low | High, eventual | Scored 2026-07-18 (todo 113 — Phases 156-159 numbered 2026-07-12, four days after this matrix's last rewrite, never scored). Hard-gated on v3.2 complete + `alpha_events` schema frozen — far out on the dependency graph, but "far out" and "low value" are different questions: this is the persisted-portfolio substrate every downstream execution phase reads instead of recomputing exposure inline. |
| Phase 157: Position Sizing & Risk Management | L-XL | Med | High, eventual | Scored 2026-07-18. Depends on Phase 156. Portfolio Kelly + risk ceilings + kill switch — the layer that turns a measured edge into a bounded capital allocation. Real design risk (Portfolio Kelly covariance vs. EnsembleBuilder's feature-space covariance are different matrices per the phase's own note — conflating them produces wrong sizes with no error signal) but well-specified. |
| Phase 158: Live Execution Layer | L-XL | **High** | High, eventual | Scored 2026-07-18. Depends on Phase 157. **Highest risk of the four** — explicitly the first phase where a connectivity/execution bug has a direct capital consequence (a missed exit) rather than a stale measurement. IBKR reconnect/resilience (surviving IBC's known 11:59pm nightly restart) must be designed and tested before any live capital flows through it. |
| Phase 159: Cost Calibration Feedback Loop + Execution Scoring | M-L | Low | High, eventual | Scored 2026-07-18. Depends on Phase 158 (needs real fills to regress against). Closes the loop between predicted and realized slippage; keeps signal quality and execution quality scored independently so neither hides behind the other. Lower risk than 158 — pure measurement/calibration over data 158 already produced. |

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
