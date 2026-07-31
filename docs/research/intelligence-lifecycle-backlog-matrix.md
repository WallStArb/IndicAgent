# v3.0 Intelligence Lifecycle — Priority Matrix

**Last rewritten:** 2026-07-08, full **Operational context refresh 2026-07-26, touched up 2026-07-27, 2026-07-31** (Phase 167 completion, Phase 164 planning, T5 1d replication, Phase 168 planned) (the dated
append-log format this doc had drifted into was cut — see git history if the historical
narrative is ever needed; resolved items live in `.planning/todos/completed/` and ROADMAP.md's
Phase Summary tables). **Filename is stable, not date-stamped**
as of 2026-07-13 — this doc is a living reference, edited in place as facts change (see
"Operational context" below for an example), not re-dated on every revision. Update this line on
the next full rewrite; don't rename the file to match. Scope: v3.0 intelligence lifecycle ideas
(Feature Factory, IC, regime detection/stratification, ensemble, tagging, AlphaEngine), pulled
from wherever they live — doc/phase/todo location doesn't matter.

**Columns:** Effort (S/M/L/XL) · Risk (Low/Med/High) · Reward (scored against evidence, not
the idea doc's own claim — Med/unproven means "plausible, untested") · **Foundational** =
cheaper to do now than to retrofit once other things build on top of it — bumps priority
independent of raw effort/risk/reward.

**Operational context (rewritten 2026-07-26 — prior dated append-log cut; resolved history
lives in git log / `.planning/todos/completed/` / ROADMAP.md's Phase Summary tables, not
duplicated here per this project's "no resolved history" convention):**

The milestone's defining question (Phase 148, 2026-07-22) has a verdict: **Gate 1 (signal
proof) PASS, Gate 2 (execution proof) FAIL — do not promote the current per-symbol directional
construction to live capital.** Phase 166's frame/execution recalibration couldn't fix it
(both candidates failed gate166's drawdown ceiling), and todo 179's exhaustive investigation
(2026-07-24) found why: `mid_bull`'s raw, un-barriered forward return is negative at every
horizon — a genuine market-data finding, not a frame or execution defect. No stop/target/hold
tuning fixes a genuinely negative raw return.

**That closed "recalibrate the existing construction" and opened a three-way fork: invest in
more features (Phase 151/164/165), invest in a different construction/model over the *existing*
features (Edge Source Thesis T3/T5), or accept no OOS-detectable edge on this branch.** Resolved
2026-07-26: **T3 (cross-sectional long-short) passed decisively**, both lookahead scales,
against a shuffled-ranking-null guard — the first thesis anywhere in the tree to clear its own
bar (`docs/research/data-edge-source-thesis.md`). **Registered as ROADMAP.md Phase 167
(Cross-Sectional Trade Construction) and now COMPLETE (2026-07-27, 6/6 plans)** — both live
Validation Gates PASSED against the real OOS population (`gate1_passes=true`,
`gate2_passes_overall=true`), the first construction anywhere in this project to clear both,
unlike Phase 148's per-symbol directional construction which failed Gate 2. This clears Phase
156-159's (execution/sizing) stated precondition, but **the user redirected priority 2026-07-27
away from 156-159** toward validating the features/regimes/IC/ensemble signal-generation stack
first — do not resume 156-159 scoping without the user re-raising it. T5 (non-linear combiner)
cleared its canary-leakage check 2026-07-26 (todo 184, CLOSED) then partially replicated at
equity/1d 2026-07-27: confirmed **small, not large** — magnitude collapsed ~16x from the
original 1h finding (0.258 → 0.0164); 15m replication (the tf Phase 167 actually trades)
deferred on memory contention, see todo 188. Per Musk's 5-step mandate (question the requirement
before accelerating), **Phase 164/165's feature-expansion track stays deprioritized behind
Phase 167** — Phase 164 is planned and execution-ready (4 plans, 2026-07-25) but not the next
priority; no evidence yet that more features are the bottleneck when the existing 150 already
produced a passing construction.

**Caveat closed 2026-07-27:** todo 179's original sweep ran under cross-sectional regime labels
later found miscalibrated and fixed the same day (todo 092). Todo 183's corpus recompute
completed 2026-07-27T21:55 UTC; todo 179's sweep was re-run the same day against the live,
corrected labels (270 cells, zero pass) — the "no edge" verdict is now confirmed, not
provisional. Doesn't affect T3/Phase 167's own result (no regime dependency).

**2026-07-30/31: a real correctness bug (todo 208) was found and fixed in `forward_return_writer.py`'s
same-ET-session completeness gate** — it was silently zeroing 1h's `slow`/`extended` completeness
for a reason that doesn't hold up under the horizon-response diagnostic. Fixed for all intraday
tfs, `forward_returns` truncated and rebuilt clean (35.6M rows) under the corrected definition,
and the full corpus pipeline relaunched from `regime_writer`. **A full 80-symbol `ic_engine` pass
is in flight as of this writing** (started 13:19 EDT 2026-07-30, ~49/80 symbols done as of
2026-07-31 ~20:35 UTC, ETA ~2026-08-01 midday/early afternoon) — nothing that reads
`feature_ic_scores`/`ensemble_alpha` should start until it completes. The diagnostic itself
resolved cleanly: today's session-gate fix is confirmed correct, and migration 269's provisional
per-tf lookahead grid is confirmed not wrong under the corrected semantics — **this run is
trustworthy, not a third rebuild waiting to happen.** Separately, `ic_engine`'s bootstrap CI
(todo 215) was vectorized and measured at ~1.3x real speedup (contention-limited, below the 2.4x
isolated benchmark) — kept as the standing config, no further tuning without a dedicated
idle-box benchmark. Canary RNG seeding (todo 203) fixed; a sibling POOLED-gate anomaly (todo 204)
remains undiagnosed pending this run's output. **Phase 168 (Cost-Hurdle-Adjusted Spread
Construction, T3 follow-on)** was scoped and planned 2026-07-31 as a parallel, zero-compute-
contention track alongside the live `ic_engine` run — 5 plans/4 waves, cross-AI reviewed
(Codex+Agy), ready to execute (`/gsd:execute-phase 168`), not yet run. See its row in the HIGH
tier's Phases table below.

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
| **Phase 167: Cross-Sectional Trade Construction (T3)** | M | Low-Med | **High, proven** | **COMPLETE 2026-07-27 (6/6 plans).** `services/cross_sectional_spread_tracker.py` productionized T3, applied the todo 030 cost-hurdle sweep, backfilled the full 2006-2026 corpus into `construction_spreads` (24,924 bars), and ran both live Validation Gates against the real OOS population: Gate 1 (shadow spread Sharpe) and Gate 2 (attribution honesty) both PASSED — the first construction in project history to clear both, unlike Phase 148's per-symbol directional construction. Clears Phase 156-159's stated precondition; **whether to proceed is the user's decision — redirected 2026-07-27 toward validating the signal-generation stack first, not automatic.** See `docs/research/trade-construction-layer.md`, `docs/research/data-edge-source-thesis.md`. |
| Phase 168: Cost-Hurdle-Adjusted Spread Construction (T3 follow-on) | M | Low-Med | High, evidence-backed | **PLANNED 2026-07-31** (5 plans, 4 waves, `gsd-plan-checker` PASSED, decision coverage 4/4). Applies todo 030's cost-hurdle sweep as a construction-layer change (which symbols/legs survive realistic transaction costs), no new features. Cross-AI reviewed (Codex + Agy/Antigravity), 9 findings incorporated via targeted revision. Scoped as a zero-compute-contention parallel track while the in-flight `ic_engine` recompute runs. Execution-ready (`/gsd:execute-phase 168`), not yet run. See `docs/research/trade-construction-layer.md`. |
| Phase 144: Cross-Sectional Regime Model (`regime_group`) | L | Med | High | **COMPLETE 2026-07-22** (6/6 plans, D-05 verdict landed). The symbol_hmm restoration fix (`dual_write_symbol_hmm`, migration 247) unblocked D-05, which then ran for real: **F1 not triggered** (TLT's per-symbol HMM stays deficient, demotion holds — matches the original 2026-07-02 finding) and **F2 triggered for 15m/5m** (rates cross-sectional is ALSO deficient at high frequency — pre-registered build trigger for a factor-augmented HMM challenger, pending confirmation `volatility_pct` hasn't already passed its own substitution gate for rates). Full verdict in ROADMAP.md's Phase 144 section. Cross-Group Lead-Lag IC and Phase 145 are now unblocked by this row closing — see their own rows for current status. |
| Phase 166: Frame/Execution Recalibration | L | Med | High | **COMPLETE 2026-07-23** (6/6 plans, registered from todo 174). **VERDICT: neither candidate promoted** — baseline and scalar (retuned stop/target) both fail gate166's max-drawdown ceiling (9.60x and 26.18x vs. 0.25). Direct follow-on (todo 179, same day) found the real cause: `mid_bull`'s raw un-barriered forward return is negative at every horizon — a market-data finding, not an execution-frame defect. Closes the "recalibrate the frame" hypothesis conclusively; reframes the open question to Phase 151/164/165 (invest in features) vs. accept-no-edge (see Operational context above). No longer gates anything — still gates Phases 149-159 in the sense that neither fork is resolved yet. |
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
| Phase 163: VP/SR Structural Primitives | M | Low | Med-High | **COMPLETE 2026-07-24** (3/3 plans, verified 15/15 must-haves). Closed todo 153, a real "can we trust this data" gap: `poc_dist_atr`/`va_position`/`sr_support_dist`/`sr_resist_dist` were stuck at constant `FeatureCache` defaults in both live and batch, making their `feature_ic_scores.ic_value=0` a constant-input artifact, not a measured null result — now live. Was also a Wave-0 prerequisite for Phase 166's structural candidate (see that row). Historical `feature_vectors` backfill for the 17 new columns tracked separately as todo 176. |
| Phase 165: Swing/Fib/Trend Structure Primitives | L | Low-Med | Med, unproven | Context/research done 2026-07-21, Fable-reviewed, not yet planned. 41 new columns across 5 files (swing/momentum/trend-structure/fibonacci-zones/session-levels). Risk scored Low-Med because the research pass already found and pre-scoped fixes for 2 silent-wrong-answer bugs before any code was written. Reward stays "unproven" (no pilot has run for these primitives, unlike Phase 151's todo 037 or Phase 167's T3). **Deprioritized behind Phase 167 as of 2026-07-26** — no evidence more features are the bottleneck when Phase 167's construction already found signal in the existing 150. |
| Phase 164: SMC Institutional Footprint Primitives | L | Med | Med, unproven | **Planned 2026-07-25** (4 plans, 4 waves, `gsd-plan-checker` VERIFICATION PASSED; RESEARCH.md/PATTERNS.md/VALIDATION.md all complete) — execution-ready, not yet executed. Ports order blocks/FVG/liquidity sweeps/supply-demand zones/AMD cycle/breaker-mitigation/BOS-CHoCH from archived v2.x `smc_context` plugins. Risk scored Med (not Low like 163) because ROADMAP.md already flags the same raw-price-vs-ATR-companion trap Phase 163's D-16/D-17 caught mid-review. Sequenced after 163 for shared conventions, no hard code dependency. **Deprioritized behind Phase 167 as of 2026-07-26**, same reasoning as Phase 165's row above — `/gsd-execute-phase 164` remains available whenever feature-expansion work is picked back up. |
| HMM regime audit — remaining P4a/P4b + seed-stability check (todo 026) | S-M | Low | Low-Med | **Corrected 2026-07-14** (prior row text was stale): P0/P1a/P1b/P2b/P2c all shipped, P2a forked to standalone todo 108, P3 forked to standalone todo 092 (now MEDIUM-tier itself, live-path evidence). The only scope left in 026 is the rolling-refit pilot (P4a/P4b) plus its bundled seed-stability check — both GATED on a 4-condition decision gate that has never cleared, and currently inert: `alpha.regime.equity_model_enabled=true` routes every live IC measurement around the per-symbol HMM this targets, so the leak contaminates nothing today (2026-07-09 finding). The 2026-07-07 fallback pre-commitment (demote-to-shadow) already shipped the cheap governance-level mitigation. One legitimate re-activation trigger remains: F5 in `fable-2026-07-07-phase144-conditioning-decision.md`, if the TLT model-class-mismatch diagnosis is ever challenged. Correctly stays in `deferred/`, not ranked in PRIORITIES.md by that file's own pending/-only scope. |
| Cross-sectional regime grid shape never validated (`.planning/todos/pending/135-cross-sectional-regime-grid-shape-never-validated.md`) | S-M | Low | Med, **load-bearing** | Filed 2026-07-18. The equity (3×3=9 cell) and rates (3×2=6 cell) cross-sectional grids were fixed by design, never selected via a BIC-style or IC-separation model-selection study the way HMM's K=5 was (Phase 140.5 P2). Distinct from todo 092 (cut-point values within the existing grid) — this is whether the cell count itself is right. High load-bearing weight given `equity_model_enabled=true` routes essentially all live IC measurement through this grid today. Natural sequencing: after todo 092's cut-point recalibration, alongside Phase 145's substitution-test machinery (which will re-litigate "how many cells" per new candidate dimension anyway). |
| Cross-Group Lead-Lag IC (`docs/research/cross-group-lead-lag-ic.md`) | M | Med | Med, unproven | Reuses existing `ic_engine` machinery. 6 candidate pairs identified (rates→precious metals cleanest). Real open risk: multiple pairs × lags × TFs needs the same BH-FDR discipline as cross-sectional IC. Gated on Phase 144 (needs clean peer groups on both sides of the join). |
| Phase 146: Empirical Instrument Tag Calibrator | L-XL | Med | High, latent | **SHIPPED 2026-07-17** (5/5 plans) — stale row, this table hadn't caught up. `TagCalibrator` live-verified: 11/12 measurable tags carry real `source='empirical'` rows. See STATE.md's phase summary table. |
| Phase 151: Feature Primitives Expansion + Theory-Motivated Interaction Layer | XL | Med | Med-High, evidence-backed | **PLANNED 2026-07-24** (8 plans, 7 waves, `gsd-plan-checker` VERIFICATION PASSED after 1 revision; `/gsd-plan-phase 151`, no `/gsd-discuss-phase` run — ROADMAP's own Phase 151 section, already Fable-reviewed across all 4 candidate sources, served as the locked-decision source instead). Not the same scope as Phase 142.5 (which already shipped 89 primitives, complete) — this is todos 066/104/123/180's 28 tier-0 atomics + 5 named tier-1 interactions, plus a 10-feature curated Theory-Motivated Interaction Layer (≤50 cap, each with a stated finance-theory hypothesis, separate BH-FDR pool from atomics). **Evidence gate cleared 2026-07-10** (todo 037 PASS, see "Recently shipped"). Planned ahead of the Gate-2/todo-179 fork being resolved, at explicit user direction. **That fork resolved 2026-07-26 toward Phase 167 (see Operational context above) — Phase 151 stays planned and ready but is not the next execution priority.** `/gsd-execute-phase 151` remains available whenever feature-expansion work is picked back up. Also the feeder for `intel-10` Confluence's gate 1 once ≥1 interaction term clears IC/OOS. |
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
