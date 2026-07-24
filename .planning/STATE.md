---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: AlphaEngine Validation + Alpha Scoring
status: ready_to_execute
stopped_at: >-
  Tier 1 validation (todo 179) now RUN AND ANSWERED, same day as Phase 163's completion.
  Confirmed by direct code read: neither ensemble_trainer.py's eligibility predicate nor
  alpha_publisher.py's emission gate validates a stratum's realized OOS outcome -- both are
  pure feature-level statistical significance gates. Built and ran a day-clustered
  bootstrap+FDR validation (scripts/analysis/regime_eligibility_joint_stratification_validation.py,
  reuses evaluate_frame_gate verbatim) stratified jointly on (tf, direction,
  cross_sectional_regime, symbol_hmm_regime) against the champion OOS population: ZERO
  cells pass at any granularity tested, coarse or joint -- including the two buckets
  (high_neutral, mid_bull-ranging) that looked promising under naive per-trade averaging in
  todo 179's earlier informal check. A regime_eligibility_gate.py built today would find
  nothing to let through. This closes off the "maybe a finer regime cut finds hidden edge"
  hope and reinforces Phase 148's Gate 2 FAIL at the finest resolution tested yet. Full
  detail in todo 179's final section. **Real open question now: does this ensemble
  construction (current feature set + IC-weighted linear combination + barrier execution)
  have ANY OOS-detectable edge at the frame level at all -- a strategic fork (invest in
  better features/signal via Phase 164/165, or accept no live edge yet on this branch) that
  needs a decision, not another diagnostic.** Also closed todo 168 (14-symbol regime-
  coverage gap, root cause was a compressed hypertable from migration 201, not a modeling
  bug) and shipped todo 169 (coverage monitor, built and tested, not yet deployed). v3.1
  milestone still NOT complete -- phases 145, 147, 149, 150, 151, 155-159, 164, 165 remain
  unexecuted.
last_updated: 2026-07-24T12:15:00.000Z
progress:
  total_phases: 12
  completed_phases: 9
  total_plans: 45
  completed_plans: 65
  percent: 75
---

# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Alpha must be demonstrated empirically before any ensemble weight is assigned.

**Current focus (updated 2026-07-24):** Milestone v3.1's defining question (Phase 148, do not
promote v3.0 AlphaEngine to live capital — Gate 1 PASS, Gate 2 FAIL) still stands. Phase 166
tried to fix Gate 2 via frame/execution recalibration (scalar + structural stop/target
candidates) — both failed, and its own recorded next step was to finish the structural
candidate's Part 2 (todos 175/176) once Phase 163 landed. **That plan is now overridden.**

A same-day investigation (2026-07-24, not run through GSD — a direct Renaissance-council-style
review of "is this generating real alpha," full detail in
[[project_todo179_gate2_concentration_regime_diagnostic]]) found, via a chain of independently
falsified hypotheses (concentration/sizing helps Sharpe but doesn't fix drawdown; sign-symmetric
shadow test made things worse, not better; asset-class regime-mismatch ruled out empirically),
a decisive final result: **`mid_bull`'s raw, completely un-barriered forward return (pulled
directly from `forward_returns`, zero stop/target/hold involved) is negative at every horizon
tested.** No frame-layer fix — stop distance, hold time, or structural S/R placement — can turn
a genuinely negative raw return into a profitable trade. Phase 166 already tried two stop/target
variants; a third (the structural candidate, todos 175/176) would fail for the identical reason
and should NOT be pursued next.

**The real next step: is there any regime-conditional expectancy floor at emission time at
all, or does the ensemble only ever check feature-level significance?** `ensemble_trainer.py`'s
eligibility predicate operates per-feature (is this predictor's IC significant for this
`(tf,regime)` stratum); `alpha_publisher.py`'s only gate is a per-bar CI check on that bar's
score. Neither validates the STRATUM'S actual realized outcome before continuing to emit in it
— Gate 1/Gate 2/gate166 measure that, but as one-off milestone scripts never wired back into
what gets emitted. The proposed fix (not yet built): a `regime_eligibility_gate.py` oneshot,
reusing `evaluate_frame_gate`/`frame_gate_passes` verbatim (no new statistics), writing to the
existing `gate_evaluations` table, consulted by `alpha_publisher.py` as one more preload/skip
condition alongside its existing CI gate. **Must be stratified jointly on
`(cross_sectional_regime, symbol_hmm_regime, direction, tf)`, not cross-sectional regime alone**
— per-symbol HMM state reveals real heterogeneity within `mid_bull` (a `ranging` sub-bucket near
breakeven vs. `trending_up`/`transition_down` genuinely bad) that a single-axis gate would blur.
**This has now been validated (2026-07-24) — zero cells pass at any granularity, coarse or
joint.** See todo 179's final section for full detail. A `regime_eligibility_gate.py` is NOT
worth building on the current champion population — there is nothing for it to let through.

**This surfaced a Layer 1 (regime labeling) foundation problem that had to be fixed before any
of the above can be trusted.** Todo 168 (7 symbols with zero per-symbol HMM regime coverage) was
bigger than filed — the new coverage monitor (todo 169) found 14, not 7. Root cause for most:
`feature_vectors`' entire hypertable was compressed as a side effect of migration 201 (float32
conversion), not a modeling bug — decompressed, confirmed fix, **CLOSED**. Full detail:
[[project_todo168_regime_coverage_compression_wall]]. Remaining Layer 1 gaps, still fully open:
**todo 092** (equity regime cut-point calibration — arbitrary 0.40/0.60 cuts, population 12-17x
imbalanced, never checked against the real distribution) and **todo 167** (equity's
cross-sectional-vs-symbol-HMM stratification choice never falsifier-tested, unlike rates').
Both should resolve before fully trusting the regime-eligibility gate above.

Phase 144 (Cross-Sectional Regime Model) is COMPLETE (6/6) — D-05 verdict: F1 not triggered
(TLT's per-symbol HMM stays deficient), F2 triggered for 15m/5m rates. Phase 143.1 is COMPLETE
(8/8) — HOLD verdict on sign-symmetric ensemble weighting, confirmed twice (now three times,
counting today's shadow-test re-confirmation). Phase 162 (ic_engine Corpus Pipeline Throughput)
is COMPLETE (4/4). Phase 163 (VP/SR Structural Primitives) is COMPLETE (2026-07-24) — its output
is exactly what the now-deprioritized structural candidate needed, so completing it doesn't
change the "don't pursue Part 2" call above.

**Next actions, priority order:**

*Tier 1 — ANSWERED 2026-07-24, mechanism found:* The regime-eligibility hypothesis has been
validated (day-clustered bootstrap + BH-FDR on the joint `(cross_sectional_regime,
symbol_hmm_regime, direction, tf)` stratification, reusing `evaluate_frame_gate`) — zero
cells pass, at any granularity, coarse or joint. Digging into WHY (Renaissance-council
challenge: how can Gate 1 pass 10x margin while Gate 2 fails everywhere?) found the actual
mechanism, confirmed directly against `gate_evaluations`' live evidence: **Gate 1's IC is
pooled across ALL regimes per (symbol, tf, lookahead) — it never checked whether the
relationship holds up regime-by-regime.** Broken out by regime (`alpha_ensemble_ic`'s own
`is_pooled=false` rows, computed but never consulted by the gate), `high_neutral` is
consistently where the real signal concentrates (83% sign-agreement with the pooled IC) —
corroborating this file's own earlier naive-average finding and the Tier-1 validation's
`high_neutral` cell missing a clean bootstrap pass by exactly 1 day-cluster. **`mid_bull`/
`low_bull` — with `mid_bull` dominating trade volume and shown catastrophically
unprofitable by every regime-stratified test — sit right at a coin flip (58-59%
sign-agreement, barely above the 50% no-information baseline).** `alpha_publisher`'s
emission gate is regime-blind (a single per-tf CI/cost
hurdle) and ends up firing overwhelmingly into `mid_bull`/`mid_neutral`/`high_neutral` by
trade count — not necessarily the regimes where the per-symbol IC is actually correctly
signed. Full detail and the regime-by-regime table: todo 179's mechanism section.
**Recommended next step, cheaper than either building new features or abandoning this
branch:** confirm whether `high_neutral` alone — the strongest candidate across three
independent methods today — can clear a full rigorous bootstrap CI given a slightly larger
OOS window or a re-examined day-cluster floor; if yes, fix is architectural (make
`alpha_publisher`'s eligibility/threshold regime-conditional) rather than a
features-vs-give-up choice. This is a decision point, not something to build unilaterally —
raised with the user 2026-07-24.

*Tier 2 — regime-labeling foundation, should resolve before fully trusting Tier 1:* todo 092
(equity regime cut-point calibration) · todo 167 (equity cross-sectional-vs-symbol-HMM
falsifier, needs a real D-05-equivalent gate built) · todo 169's timer (script/tests/units all
built, `systemctl enable` on the live host not yet done — deliberate, flagged as a real infra
change).

*Tier 3 — ready now, independent of the above:* todo 088 (`hold_max_bars` type safety) · todo
170 (`volatility_pct` substitution probe for rates) · todo 129 (revived cross-service
short-lived-conn helper) · todos 172/173 (non-blocking Phase 148 findings) · todo 009 Parts A-D.

*Tier 4 — deprioritized, do not resume without re-reading why:* todo 176 (historical
`feature_vectors` VP/SR backfill) and todo 175 (structural candidate Part 2) — both exist only
to serve the now-overridden "pursue the structural candidate" plan. Phase 145
(StratificationDimension Formalization, unblocked but not planned) and Phase 165 (Swing/Fib/Trend
Structure Primitives, researched, needs `/gsd-plan-phase 165`) — not wrong to do, just not the
highest-value next step given Tier 1.

*Tier 5 — real value, not urgent:* Phase 147 (I7 CORPUS-07 due diligence, cheap, gates nothing)
plus the full P2/P3 tier in `.planning/todos/PRIORITIES.md`.

*Tier 6 — explicitly gated, do not start planning yet:* Phases 149-159 (PrecedentEngine, Feature
Primitives Expansion, Alt Data, Portfolio State, Position Sizing, Live Execution, Cost
Calibration) — zero planning artifacts, v4.0-adjacent scope. Per "prove edge before production
infra," this gate is now MORE binding: building portfolio/execution/risk infrastructure before
Tier 1 resolves whether there's a real, tradeable regime-conditional edge would be building on
an unproven foundation twice over.

**Execution plan:** `docs/plans/2026-06-30-alphaengine-v1-execution-plan.md`

## v3.0 Phase Summary (SHIPPED 2026-06-25)

| Phase | Name | Status |
|-------|------|--------|
| 137 | Feature Factory | COMPLETE (7/7 plans, 2026-06-21) |
| 138 | IC Engine + Forward Returns | COMPLETE (9/9 plans, 2026-06-23) |
| 139 | Ensemble + Alpha Emission | COMPLETE (3/3 plans, 2026-06-24; 14/14 verification truths) |
| 140 | IC Engine Correctness | COMPLETE (4/4 plans, 2026-06-25) |

## v3.1 Phase Summary (IN PROGRESS)

| Phase | Name | Status |
|-------|------|--------|
| 140.5 | Corpus Foundations + Feature Governance | COMPLETE (5/5 plans) |
| 141 | Corpus Quality Gate + IC Validation | COMPLETE (3/3 plans) |
| 141.1 | Measurement and Decision Integrity Foundation | COMPLETE (4/4 plans) |
| 142A | Ensemble IC Measurement | COMPLETE (2/2 plans) — EIC-04 current verdict PASS 54/1425=3.79%, see [Corpus pipeline state](project_corpus_pipeline_state.md) for the live number |
| 142B.1 | Ensemble Weighting Methodology | COMPLETE (5/5 plans) — E1 (shrunk-IC) is champion; E2 (mean-variance) rejected |
| 142.5 | Renaissance Primitives | COMPLETE (8/8 plans) — 89 primitives live in Feature Factory, 150 total `FeatureVector` fields |
| 142B | Frame Simulation + Counterfactual Tracking | COMPLETE (2/2 plans) — `alpha_frames` hypertable + `AlphaFrameWriter` + `CounterfactualTracker` live |
| 143 | Feature Lifecycle Routing (merged with 149B) | COMPLETE (3/3 plans) — `feature_registry` evidence-based promotion/demotion + `integrity_monitor` table live |
| 143.1 | Measurement and Eligibility Integrity | COMPLETE (8/8 plans, 2026-07-21) — 143.1-08 shadow-mode validation VERDICT: HOLD (`alpha.ensemble.sign_symmetric` stays false); see Session's "2026-07-21" closeout subsection below |
| 144 | Cross-Sectional Regime Model (`regime_group`) | COMPLETE (6/6 plans, 2026-07-22) — D-05 verdict: F1 not triggered (TLT HMM stays deficient, demotion holds), F2 triggered for 15m/5m (rates cross-sectional also deficient there); see Current focus |
| 146 | Empirical Instrument Tag Calibrator | COMPLETE (5/5 plans, 2026-07-17) — `TagCalibrator` live-verified: 11/12 measurable tags carry real `source='empirical'` rows |
| 160 | Concept Registry MVP | COMPLETE (4/4 plans) — 4-table schema + `ConceptRegistryService`/`ConceptRegistryAPI`/`ConceptRegistryDashboard` live |
| 161 | Controlled Vocabulary System | COMPLETE (4/4 plans, 2026-07-18) — schema + `VocabularyService` + `vocabulary_drift` audit + `/api/vocabulary/{namespace}` route, live-verified (VERIFICATION.md: passed, 23/24 truths, 1 accepted YAGNI override) |
| 148 | Alpha Scoring System (OOS Proof Gates) | COMPLETE (5/5 plans, 2026-07-22) — the actual proof-of-alpha milestone: Gate 1 PASS, Gate 2 FAIL, VERDICT do not promote to live capital; see ROADMAP.md's Phase 148 section and `docs/plans/2026-07-22-phase148-promotion-decision.md` for full evidence |
| 162 | ic_engine Corpus Pipeline Throughput | COMPLETE (4/4 plans, 2026-07-23) — whole-cell fingerprint mechanism, equivalence-proven; CR-01 blocker found via code review and fixed same session; 3 success criteria need a full-corpus run to close empirically, see `162-HUMAN-UAT.md` |
| 166 | Frame/Execution Recalibration | COMPLETE (6/6 plans, 4 waves, 2026-07-23) — baseline and scalar candidates FAIL gate166 decisively; structural candidate halted pending Phase 163. **Part 2 (todos 175/176) since deprioritized 2026-07-24 by todo 179's decisive finding — see Current focus.** |
| 163 | VP/SR Structural Primitives | COMPLETE (3/3 plans, 2026-07-24, verification 15/15 must-haves) — closes todo 153. 17 new `feature_vectors` columns live on the compute path; historical backfill still open (todo 176, now deprioritized alongside Phase 166 Part 2) |

Current row counts and every downstream measurement number live in
[Corpus pipeline state](project_corpus_pipeline_state.md) — that file is the single source of
truth; don't duplicate counts here.

**Dual regime system (both live):**

- `feature_vectors.regime` — 5 per-symbol HMM labels (trending_down/transition_down/ranging/transition_up/trending_up), written by `regime_writer.py` (K=5, causal forward-filter)
- `market_regimes` — cross-sectional labels keyed by `regime_group` (a named peer group with a pluggable regime signal: `breadth_vol` for equity, `curve_credit` for rates; commodity/fx modules ship disabled), written by `cross_sectional_regime_model.py` (Phase 144, replaced `equity_regime_model.py`); `ic_engine` stratifies on these

## Key Decisions (load-bearing — don't re-derive)

- **HMM_RANDOM_STATE = 42** — changing invalidates all feature_ic_scores, requires full re-run
- **Pooled IC (is_pooled=true)** — cross-sectional POOLED strata ARE the ensemble training eligibility source. `ensemble_trainer.py` reads `WHERE symbol='POOLED' AND is_pooled=true AND regime != '_pooled'` (lines 317, 430-431, 469, 540)
- **IC Sharpe gate** — sharpe_window_size=2000 RAW bars; gate is n_raw_bars >= 20,000; stride divides inside _compute_ic_rolling_metrics
- **regime_label_source DEFAULT** — 'forward_filter' (not 'filtered') in both forward_returns and feature_ic_scores
- **APR key** — alpha.ic.subsample_min_stride is a floor: actual_stride = max(min_stride, lookahead_bars)
- **Gradient naming** — return_fast/mid/slow/extended; momentum_z_fast/mid/slow; volatility_rank_z
- **ON CONFLICT for partial indexes** — use column list + WHERE clause, not ON CONSTRAINT (TimescaleDB)
- **Corpus re-run required** after Phase A ic_engine methodology fixes (028 P0/P2/P3/P4 change IC scores corpus-wide)

## Corpus Pipeline Gotcha

`--compute-only` silently skips all symbols if backfill_status is empty. After any truncation, seed first:

```sql
INSERT INTO backfill_status (symbol, tf, fetch_complete, status)
SELECT DISTINCT symbol, timeframe, true, 'pending'
FROM market_data_ohlcv WHERE timeframe IN ('5m', '15m', '1h', '1d')
ON CONFLICT (symbol, tf) DO UPDATE SET fetch_complete = true;
```

## Roadmap Evolution

- Phase 162 added (2026-07-18): ic_engine Corpus Pipeline Throughput — bundles todos 134/133/122/139/140/129/009E. **PLANNED 2026-07-22** (4 plans, 4 sequential waves — `162-01` structural extraction/memory-bounding, `162-02` per-tf bootstrap threads, `162-03` fingerprint table + watermarks + `.pkl` deletion, `162-04` equivalence harness). Research + pattern-map + plan-checker all passed (0 blockers); skipped `/gsd-discuss-phase` since two prior Fable design passes already served as its equivalent — see ROADMAP.md's Phase 162 section and `162-RESEARCH.md`/`162-PATTERNS.md`/`162-VALIDATION.md`. `143.1-07`'s resource-contention gate cleared before this session (143.1 is complete); no other blocker. Not yet executed — `/gsd-execute-phase 162` is the next step, gated only on `ps aux | grep ic_engine` being clear.
- Phase 163 added (2026-07-20): VP/SR Structural Primitives — closes todo 153 (poc_dist_atr/va_position/sr_support_dist/sr_resist_dist permanently stuck at constant defaults since v3 rebuild). Sibling atomic-expansion item to Phase 151, not folded into it. No dependency on the in-flight todo-147 CV recheck or 094 shadow-mode validation running elsewhere. Scope widened same day: port ctx_VolumeProfile (I4, 18 fields) instead of the thinner i3_structure/market_profile.py originally identified — self-contained, no known bugs, same computation cost. The third Fable review (rolling-track POC primitives, D-18) resolved same session — **PLANNED, reviewed, and execution-ready** (verified directly 2026-07-20: both `163-01-PLAN.md`/`163-02-PLAN.md` grep-confirm "12 new" column phrasing and both `poc_rolling_dist_atr`/`poc_session_rolling_divergence_atr` present). **As of 2026-07-23, Phase 163 execution is now a real Wave-0 prerequisite for Phase 166's structural candidate** (discovered during Phase 166's research — `sr_support_dist`/`sr_resist_dist` are 100% NULL until it runs). Still not yet executed — `/gsd-execute-phase 163` is the next action.
- Phase 164 added (2026-07-20): SMC Institutional Footprint Primitives — atomic distance/strength/duration/count primitives ported from the archived v2.x smc_context plugins (order blocks, FVG, liquidity sweeps/pools, supply/demand zones, AMD cycle, breaker/mitigation blocks, BOS/CHoCH). All self-contained on already-live shared utils, no cross-plugin dependency chain. Sequenced after Phase 163 for shared conventions, not a hard code dependency. Registered in ROADMAP.md with a raw-price-vs-ATR-companion warning (see Phase 163's D-16/D-17 lesson) but NOT planned — no CONTEXT.md/RESEARCH.md/PLAN.md yet.
- Phase 166 added (2026-07-23): Frame/Execution Recalibration — the direct follow-on to Phase 148's Gate 2 FAIL verdict, per that phase's own pre-registered "frame problem, recalibrate against IC decay curve" playbook. Formalizes todo 174's investigation scope (never-calibrated `stop_atr_mult`/`target_r_multiple`/`hold_max_bars` APR defaults, `mid_bull`-only OOS coverage question, possible porting of v2.x's structural/regime-adaptive stop hierarchy). Discussed same day: structural candidate scope was broadened mid-discussion to the full v2.x confluence toolkit (zone_engine.py + SMC/swing/fib/anchored-VWAP), then research found the full toolkit's feature columns 100% absent from v3's live schema — resolved to a two-part structural candidate (Part 1: VP/SR confluence, Phase-163-gated, built now; Part 2: SMC/swing/fib/anchored-VWAP, deferred to todo 175). **PLANNED same day** (6 plans, 4 waves, `gsd-plan-checker` VERIFICATION PASSED, decision-coverage gate 6/6). Real dependencies: Phase 148 (complete) and now Phase 163 (planned, not yet executed — Wave 0 prerequisite). Not gated on Phase 165. Next action: execute Phase 163, then `/gsd-execute-phase 166`.

## Session

**Last session:** 2026-07-24T11:30:00.000Z
**Stopped At:** Phase 163 executed and verified (15/15 must-haves). Same-day ad hoc investigation (not a GSD phase) found the actual cause of Gate 2's failure and overrode Phase 166's own recommended next step — see the 2026-07-24 session closeout below for the full chain, and `.planning/todos/pending/179-gate166-concurrent-exposure-diagnostic.md` for the complete reasoning trail. Also closed todo 168 (regime-coverage gap, root cause was a compressed hypertable, not a modeling bug) and shipped todo 169 (coverage monitor).

**Resume File / exact next action:** Do NOT run `/gsd-execute-phase` for anything related to Phase 166 Part 2 (todos 175/176) — that plan is deprioritized, see below. The real next action: read `services/ensemble_trainer.py`'s eligibility predicate (`_eligibility_where`) and `services/alpha_publisher.py`'s emission gate to confirm precisely whether either validates a stratum's actual realized outcome before continuing to emit in it, or only feature-level statistical significance. Then validate the regime-eligibility hypothesis properly — day-clustered bootstrap + BH-FDR on the joint `(cross_sectional_regime, symbol_hmm_regime, direction, tf)` stratification, reusing `evaluate_frame_gate` verbatim — before designing or building anything. This is Tier 1 in the "Next actions" list under Project Reference above.

**This session's full arc (for context if resuming cold):** Started from todo 153 (VP/SR features permanently null) → Fable research → discovered a better port source (`ctx_VolumeProfile`) than originally proposed → caught and fixed a raw-price-as-ML-feature bug in that scoping (D-16) → planned Phase 163 via direct `gsd-planner` dispatch (bypassing the full `/gsd-plan-phase` skill since CONTEXT.md/RESEARCH.md were already hand-written) → got an independent Fable review of the whole corrected scope, which caught 2 more issues (D-17: dropped `in_lvn`, undocumented `va_width_atr` collinearity) → both fixed in the already-written plans → user caught a further gap (rolling-track signal computed but unused) → third Fable review dispatched, in flight at session end. Also: filed todo 158 (unrelated live-path bug found incidentally: `above_wk_vwap` frozen at 0.0 in live pipeline, batch path is correct) and closed out the todo-147 CV recheck's A/B rerun analysis (encouraging but not fully closed — see PRIORITIES.md's todo-147 entry, the direct `true_range_pct` CV re-check is still outstanding). Phase 164 (SMC Institutional Footprint Primitives) registered but not planned — deliberately deferred to a future session/prioritization call.

**Note (2026-07-20, concurrent todo-track session):** the paragraph above's "filed todo 158" /
"closed out... (encouraging but not fully closed)" is a stale snapshot from mid-flight — see the
dedicated subsection below for what actually happened on that track. Left this paragraph
unedited rather than risk a racy overwrite of the phase-track's own resume notes above.

### Todo-track resume point (concurrent session, same day — 158/159/147/124/160)

**Stopped at:** Todo 158 fully fixed, merged to `main` (commit `803d8893`). Investigating todo
147's outstanding CV re-check surfaced a real, deeper data-integrity bug (todo 124/160) that is
now the next concrete action, not yet started.

**What happened, in order:**

1. **Todo 158** (`above_wk_vwap` frozen at 0.0 on the live path) — root-caused via
   `systematic-debugging`, fixed with one line in `_process_bar_compute` (`cache.advance_bar(...)`
   after `FeatureFactory.compute()`), TDD regression test added, `/simplify` clean, Codex peer
   review (AGY was out of quota). Merged to `main`.

2. **Todo 159** filed from that Codex review: `FeatureCache` isn't warmed from the bar history
   `_seed_bar_history_from_db()` already loads at startup, so `above_wk_vwap`/`hmm_duration`
   still start cold after every restart. Not started.

3. **Todo 147's outstanding CV re-check** (the `true_range_pct` per-(tf,regime) CV pull its
   "Fix / next step" section asked for, never run before this session) — ran it: `low_bull`
   still ~150-300x every clean regime's CV, NOT at parity despite 151/154's correction pass.

4. Traced why: `VWO`/`DIA` were never flagged at all (candidate-discovery gap). `KRE` WAS
   correctly flagged `price_sanity_status='confirmed_corrupt'` with `forward_returns`
   recomputed sane — but `feature_vectors.true_range_pct` for that same bar is still corrupt,
   because `backfill_feature_factory.py` reads raw `market_data_ohlcv` directly instead of the
   `price_sanity_status`-filtering `market_data_ohlcv_tradeable` view. The flag never reaches
   feature computation.

5. This reclassified **todo 124** (previously P3, "style/DRY only" — that assessment predates
   `price_sanity_status`, written 2026-07-16) to **P1**, now the real fix owner. Filed
   **todo 160** as the evidence trail/reproduction. Both PRIORITIES.md and two memory files
   were corrected after an initial (wrong) framing that assumed all 3 rows were simply
   uncorrected — first commit `0b57fa22`, correction commit `2a1d3a78`.

**Exact next action:** Todo 124's real fix — migrate `services/backfill_feature_factory.py`
from raw `market_data_ohlcv` reads to `market_data_ohlcv_tradeable`. Do this file first (proven
correctness impact), not the other 13 files in 124's Tier-2 list (still style/DRY-only as far as
evidence shows). After that lands: redo the DELETE + recompute for `KRE` (and newly-flagged
`VWO`/`DIA` — flag them first via `ops_known_corrupt_print_cleanup.py --symbols VWO DIA
--apply`), then re-run todo 147's CV check a third time, then close 147 if parity holds.

**Also worth a quick look before the 124 fix, low-cost sanity check:** `regime_writer.py` and
`forward_return_writer.py` share the identical `volume > 0`-only exposure pattern as
`backfill_feature_factory.py` (same allow-list entry, same stale 2026-07-16 audit) but haven't
been checked for a live reproduction — todo 124's text now flags this, not yet investigated.

**Priority docs status (checked this session, per user request):** `.planning/todos/PRIORITIES.md`
verified in sync with `pending/` (only 2 unreferenced numbers, 012/032, both intentional
merge-pointer stubs to todo 009, not real gaps). `docs/research/intelligence-lifecycle-backlog-matrix.md`
("the priority matrix") is genuinely stale — last rewritten 2026-07-08, predates Phase 144 going
code-complete, Phase 143.1's near-completion, and Phases 162/163/164/165 all being registered.
It already correctly defers todo-level ranking to PRIORITIES.md (no drift there), but its own
"Phases" table and "Operational context" note need a refresh — not done this session, flagged
here rather than silently left stale. ROADMAP.md spot-checked consistent with STATE.md (Phase
144 header deliberately still says PLANNED per its own documented reason, not a bug).

### Session closeout (2026-07-21) — 143.1-08 resolved, merged to main; Phase 143.1 is COMPLETE

**Todo 124's real fix landed** (the "exact next action" the prior subsection stopped at):
`backfill_feature_factory.py`, `regime_writer.py`, `forward_return_writer.py` all migrated
`market_data_ohlcv` → `market_data_ohlcv_tradeable` (the sibling-file sanity check that
subsection flagged as "worth a quick look" — done, same fix, same commit). `/simplify`-clean,
full unit suite green. Data recompute (KRE/VWO/DIA, todo 147's third CV re-check) still not
done — deliberately held to avoid DB contention with the concurrent 143.1-08 backfill below;
still the next action for that track.

**Todo 159 fixed and closed**: `FeatureCache` now warms `above_wk_vwap` from seeded bar
history at `_get_cache()`'s first call per (symbol, tf) — `hmm_duration` deliberately left cold
(would fabricate a duration, not recover a real one). 3 regression tests, moved to
`completed/`.

**Phase 165 (Swing/Fib/Trend Structure Primitives) fully scoped**: Fable-researched
`165-CONTEXT.md`/`165-RESEARCH.md` committed — 41 new columns across 5 files
(`swing_detector`/`swing_momentum`/`trend_structure`/`fibonacci_zones`/`session_levels`), 2
silent-wrong-answer bugs found and scoped for fixing during port, 3 tangential ideas proposed
and council-rigor-tested (2 accepted as free columns off existing computation, 1 — Fibonacci
extensions — explicitly deferred as premature scaling of an unproven hypothesis family). Not
planned yet (`/gsd-plan-phase 165` is the next step whenever picked back up). Phase 163 also
got a real post-review correction (D-19: 5 free S/R fields — `resistance_strength`/
`support_strength`/`resistance_age_bars`/`support_age_bars`/`sr_level_count` — found via Codex
cross-AI review, folded into the plan before execution; migration 243 is now 17 new columns,
not 12). **Phase 163 is still execution-ready (`/gsd-execute-phase 163`), not yet run.**

**143.1-08 (shadow-mode champion/challenger validation) is DONE — VERDICT: HOLD.**
`alpha.ensemble.sign_symmetric` stays `false`; criteria 2/3/4 (mean-P&L CI, Sharpe, max
drawdown) all fail decisively for the sign-symmetric challenger, not a close call. Emission
mechanism confirmed working as designed regardless (challenger: 69.83% short vs champion's
0.335%). **Phase 143.1 (Measurement and Eligibility Integrity) is now COMPLETE (8/8 plans)** —
the "Phases" table above still says "IN PROGRESS (7/8 plans)"; next session should flip this to
COMPLETE and re-check whether Phase 144's D-05 acceptance gate re-run (the next actual
milestone step) is now unblocked.

**Along the way:** the `counterfactual_tracker --backfill` this validation depended on had
zero progress across 3 attempts (~18h wall-clock) before a real root cause was found and fixed
— `ProcessPoolExecutor.map()`'s head-of-line-blocking ordering compounded by 358x per-row
TimescaleDB chunk-routing overhead (1,034 chunks). Fixed, verified (78min corrected run, 23.15M
rows), closed as **todo 161**. Sanity-checking the resulting numbers before trusting them (not
just accepting extreme Sharpe/drawdown values at face value) surfaced a real, separate,
cross-cutting data-quality gap: ATR-based stop distances have no minimum-price-fraction floor,
producing R-multiples down to **-926R** on thin-volatility FX/commodity ETFs at 5m — filed as
**todo 162 (P1)**, confirmed via a trimmed-outlier check that it doesn't change the HOLD
verdict itself, just inflates the tail statistics' magnitude. Honest limit: could not verify
whether this contaminated any *past* gate evaluation (E6/FRAME-04) since the underlying
`alpha_frames` rows from before this session have since been superseded — flagged as a
plausible risk, not a confirmed retroactive finding.

**Merge:** the worktree branch (`worktree-agent-acc3e6a78746c2514`) carrying all of the above
was merged to `main` via a regular merge commit (`c9622932` — not fast-forward, histories had
diverged; verified zero real conflicts via `git merge-tree` before merging, confirmed empirically
correct when the merge itself applied cleanly), full unit suite green post-merge, pushed to
`origin/main`. Worktree removed, branch deleted, `git worktree prune` run — zero worktrees
remain.

**Todo 162 resolved same day, after this closeout was first written** (fix landed
`5db6c298`): went with the skip-and-count direction (widened `degenerate_atr_skip_count`
guard via `alpha.frame.min_stop_price_fraction`, migration 243, seed 0.001
`[initial_estimate]`), not a widened-stop-distance floor — a floor would have silently
fabricated `target_price` too, since it's derived from `stop_distance`. Filed a deferred
follow-up (todo 163, gated on Phase 163 actually shipping real `sr_support_dist`/
`sr_resist_dist`) for the separate question of whether frame geometry should become
S/R-aware once that data exists — cross-referenced from Phase 163's own CONTEXT.md.

**Next actions, in order:** (1) Todo 147's third CV re-check (KRE/VWO/DIA recompute, now that
124's fix is live and DB contention has cleared). (2) Phase 144's D-05
acceptance gate re-run, now that 143.1 is complete. (3) Phase 163 execution
(`/gsd-execute-phase 163`) — ready, independent of the above. (4) Phase 165 planning
(`/gsd-plan-phase 165`) — ready, independent of the above.

### Session closeout (2026-07-21, later same day) — todos 164/165 implementation plan executed and merged

This session picked up mid-flight work that neither this file nor `main`'s working tree
accurately reflected: a full implementation plan
(`docs/superpowers/plans/2026-07-21-regime-stratified-promotion-and-per-timeframe-eligibility.md`,
found investigating 143.1-08's HOLD verdict) had already been executed 9 commits deep in an
active worktree (`worktree-todo-164-165-ensemble-eligibility`), while `main`'s working tree
held stray, redundant, uncommitted duplicates of the worktree's earliest commit (confirmed
byte-identical/formatting-only diffs before discarding them).

**Todo 165 (regime-stratified OOS promotion gate) — shipped.** `evaluate_frame_gate`
(`services/counterfactual_tracker.py`) generalized with a grouping-key + day-cluster
coverage-floor parameter; wired into `scripts/analysis/phase143_1_08_shadow_validation.py`'s
C2/C7 criteria; new pre-registered `alpha.validation.regime_gate_min_clusters` APR key
(migration 244, seed 20, explicitly not tunable post-hoc). Re-run against real 143.1-08 data:
**verdict unchanged, still HOLD** — every cell with adequate coverage failed criterion 2
decisively for both champion and challenger; 6 of 8 champion cells and 6 of 14 challenger
cells had insufficient day-cluster coverage and were excluded from the gate rather than
counted pass/fail (a partial, honest regime-by-regime verdict, not a complete one). Full
output in `143.1-08-SHADOW-VALIDATION.md` section 7.

**Todo 164 (`1h` portion) — shipped, with a real emergent finding along the way.** Per-tf
APR resolution added for `min_passing_features`/`max_feature_weight`/`meta_fdr_min_cells`
(`_resolve_per_tf`/`_assert_feasible_thresholds`, `services/ensemble_trainer.py`) plus a
startup feasibility assertion. Migration 245 (seeding `1h`'s `min_passing_features=3`/
`max_feature_weight=0.34`) alone proved **insufficient** on live re-run — `1h` still wrote
zero strata on every regime. Root-caused one gate upstream to `meta_fdr_min_cells`; fixed
with an emergent migration 246 (`meta_fdr_min_cells.1h=2`, live-queried against
`feature_ic_scores` before seeding, not guessed). Live-verified via a full completed
`ensemble_trainer.py --sign-symmetric` run: `1h` now writes 5 of 7 regimes (`high_bear`,
`low_bull`, `mid_bear`, `mid_bull`, `mid_neutral`), previously 0 of 7. `low_neutral` and
`high_neutral` remain unfixed (documented, not silently dropped) — `low_neutral` is one
meta-eligible feature short of the floor, `high_neutral` has zero IC rows entirely, a
deeper population gap. `5m`/`15m`/`1d` confirmed byte-identical to pre-existing baseline
(no per-tf key set for them). `1d`'s genuinely different small-sample power problem split
out to new **todo 166** (P2, pending) rather than papered over with the same fix.

**Both todos closed** (moved to `completed/`, `PRIORITIES.md` updated). **Cleanup:** ~50M
total leftover debug rows removed from `ensemble_alpha`/`ensemble_weights` across two
throwaway `weight_version`s (`debug_1h_investigation`, `debug_164_1h_verify2`) that a prior
session's live-verification runs had left behind — one was still actively writing when this
session started and had to be waited out rather than killed (would have orphaned the
in-flight batch write). Full unit suite green (`.venv/bin/pytest tests/unit/ -q`, both in
the worktree and again on `main` post-merge). Merged via fast-forward (`main` was already an
ancestor of the worktree branch — no divergence, unlike the 143.1-08 merge earlier this
session), pushed to `origin/main` (`24ca4da1`). Worktree removed, branch deleted,
`git worktree prune` run — zero worktrees remain.

**Next actions, in order:** (1) Todo 147's third CV re-check — unchanged from above, still
the longest-outstanding item. (2) Phase 144's D-05 acceptance gate re-run. (3) Phase 163
execution (`/gsd-execute-phase 163`) — ready. (4) Phase 165 planning (`/gsd-plan-phase 165`)
— ready. (5) Todo 166 (1d small-sample statistical treatment, P2) — newly filed, needs real
design work, not urgent. (6) Consider whether Phase 144's D-05 gate and Phase 148's OOS
proof gates should adopt the same regime-stratified evaluation pattern todo 165 just proved
out — flagged as a likely-shared mechanism in todo 165's original filing, not yet checked.

### Session closeout (2026-07-22) — symbol_hmm restoration complete + Phase 148 planning merged

Two concurrent sessions converged on `main` today; this subsection reconciles both rather
than letting one silently overwrite the other's STATE.md edit (real merge conflict on this
file's header/current-focus block, resolved by hand — see the merge commit for the full
before/after).

**Track A (this session, worktree `worktree-restore-symbol-hmm-ic-measurement`): symbol_hmm
restoration, all 5 tasks complete.** `dual_write_symbol_hmm` threaded through `ic_engine.py`
end-to-end (`083b3db6`), migration 247 seeding it `true` for `rates` only (`8695673e`),
live-verified via a scoped 12-symbol re-run (`TLT` got 6,045 fresh `symbol_hmm` rows,
existing `cross_sectional` rows and equity symbols confirmed untouched). Phase 144's D-05
gate re-run then produced a real verdict for the first time (previously years of `(no
rows)`/INCONCLUSIVE): **F1 not triggered** (TLT's per-symbol HMM stays deficient, demotion
holds) and **F2 triggered for 15m/5m** (rates cross-sectional also deficient at high
frequency — pre-registered build trigger for a factor-augmented HMM challenger, pending a
`volatility_pct` substitution-gate check). **Phase 144 closes COMPLETE.** Phase 145
(gated on this exact verdict) is now unblocked, not yet started. Three follow-ups filed:
todo 167 (equity's analogous falsifier question never tested), todo 168 (7 corpus symbols
with zero per-symbol HMM regime coverage at all — `LQD`/`PFF`/`RSP`/`USMV`/`UUP`/`VWO`/`XRT`,
a real pre-existing `regime_writer.py` gap), todo 169 (the missing systemic monitor that
would have caught 168's gap years earlier). Recorded a trigger, not executed: don't flip
`rates.dual_write_symbol_hmm` back to `false` until a full corpus rebuild reproduces F1's
non-trigger result on more than this scoped 12-symbol sample.

Also on this same worktree: Phase 162 (ic_engine Corpus Pipeline Throughput) was fully
planned (research, pattern map, validation strategy, 4 plans across 4 waves), cross-AI
reviewed (Codex found one real HIGH-severity gap — a stale `existing_keys` snapshot that
could silently skip a just-invalidated cell — fixed by removing the parameter entirely, not
just passing an empty set), and independently re-verified by `gsd-plan-checker` (0 blockers,
all 20 live `existing_keys` occurrences traced and accounted for). Not yet executed.

**Track B (concurrent session): Phase 148 fully planned, Phase 147 dependency corrected.**
`/gsd-discuss-phase 147` found Phase 147 (I7 CORPUS-07 due-diligence on a dead system) does
NOT gate Phase 148 — the ROADMAP "Depends on: Phase 147" line was stale (SCORE-01/02/03 read
only pure v3.0 tables; the one real connection, SCORE-04, was already downgraded to
documentation-only 2026-07-19). Phase 148 (the two independent OOS proof gates — signal proof

+ execution proof — this whole measurement pipeline exists to produce) is unblocked today,

prerequisites already met by a wide margin, fully planned (5 plans, 3 waves), not yet
executed.

**Merge:** real (non-fast-forward) merge, `main` had diverged (`d7c74da9` vs this worktree's
tip) with no file overlap except this file and ROADMAP.md's Phase 144/145 sections, both
resolved by hand reconciling both tracks' content rather than discarding either side. Full
unit suite green post-merge. Pushed to `origin/main`.

**Next actions, in order — Phase 148 execution first per track B's own reasoning (the actual
proof-of-alpha path), everything else independent of it:** (1) Phase 148 execution
(`/gsd-execute-phase 148`) — re-run FRAME-04 against the post-143.1 corpus first (stale
16/17-cells-fail result predates 143.1's fix). (2) Todo 147's third CV re-check (KRE/VWO/DIA)
— longest-outstanding independent item. (3) Todo 088 (`hold_max_bars` type safety) — small,
unblocked. (4) Phase 163 execution — planned, ready. (5) Phase 162 execution — planned,
reviewed, ready; gated only on `ps aux | grep ic_engine` clear. (6) Phase 165 planning —
ready. (7) Phase 145 planning — newly unblocked by Phase 144's verdict, read it first. (8)
Phase 147 whenever convenient — cheap, not gating anything.

### Session closeout (2026-07-22, later same day) — Phase 148 finalized, todo 160's real scope found and fixed

Picked up from the prior subsection's Phase 148 memory-file handoff. Cleaned up Phase 148's
remaining doc debt first: finished the migration-numbering correction notes in
`148-RESEARCH.md`/`148-PATTERNS.md` (148-01-PLAN.md itself was already correct at migration
248), added the missing Gate 2 reproduction-tolerance assertion to `148-05-PLAN.md` Task 2
(now asserts freshly-computed `c2_ci_lower`/`c3_sharpe`/`c4_max_dd` match the known 143.1-08
baseline within 1e-6, not just "a row exists"). Renamed the phase itself (title + directory,
`148-alpha-scoring-system-v2-x-decommission-planned` → `148-alpha-scoring-system-planned`) to
drop the "v2.x Decommission" framing — the phase's own CONTEXT.md already states decommission
is explicitly out of scope (todo 056 owns it), the title never matched what the phase does.

**Cross-AI review (Antigravity + Codex) ran clean.** Both converged independently on the same
3 concerns from different angles: (1) `evaluate_frame_gate` group-key reuse — 148-02's 4-tuple
call and 148-04's `(direction, regime)` call both risked breaking against the helper's real
signature; (2) irreversible one-shot gates lacked a pre-run integrity snapshot and atomic
write; (3) validation was lighter than the irreversible stakes warrant, no dry-run escape
hatch for dev-time testing. Replanned all 5 plans to fix these. The group-key fix turned out
load-bearing: read `evaluate_frame_gate`'s live source directly and confirmed it hard-crashes
(`ValueError: too many values to unpack`) on anything but a 2-tuple — the original 148-02 plan
would have failed on first execution, not just "risked" a mismap as the reviewers guessed.
Fixed to call per-cohort with a 2-tuple, matching an existing production precedent
(`phase143_1_08_shadow_validation.py`). Independently verified by `gsd-plan-checker`: **PASS
WITH CONCERNS, no blockers** — confirmed the group-key fix against live source itself before
trusting it, confirmed the dry-run/atomicity revisions didn't complicate the core Gate-1-before-
Gate-2 sequencing, confirmed migration numbering and the tolerance assertion both survived the
replan intact. One hygiene-only finding (leaked tool-wrapper tags at the end of all 5 plan
files) fixed before committing. **Phase 148 is now execution-ready** — planned, reviewed,
replanned with fixes, independently verified.

**Sanity-checked whether Phase 148 was actually the right next step before executing it** (user
asked directly) — found a real answer, not just deference to the stored priority order: todo
160 (P0, corrupt-print correction) was still open, and its root cause traces into the exact
tables Gate 2 reads (`alpha_frames`' underlying feature computation via ATR-based stop
distances). Gate 2 is irreversible (D-04, run once ever) — spending that one shot on a
population with a known, cheap-to-fix contamination was the wrong trade. Investigated further:
the automated flagging tool (`ops_known_corrupt_print_cleanup.py`) couldn't even find the two
known-bad rows (VWO/DIA) — its candidate discovery was gated behind `forward_returns` suspect
flags, structurally blind to corruption confined to `high`/`low` with a sane `open`/`close`
(confirmed live: only 18-20 of 320 registered (symbol,tf) pairs were ever discoverable that
way). **Fixed the discovery mechanism itself** (scan all registered pairs directly via
`backfill_status`, not a derived-return proxy) rather than hand-patching the 2 known rows —
the systemic fix, not the symptom. Live full-corpus dry-run under the fix found **40
CONFIRMED_CORRUPT bars across 14 symbols** (DBC/DIA/EDV/EFA/EWG/FXI/GLD/IWM/RSP/SPY/UUP/VWO/
VYM/XRT), 20x the previously-known count — every one the identical clean
`isolated_spike_neighbors_agree` signature (tightly-agreeing neighbors, single-field
order-of-magnitude outlier). SPY's $1441.65 spike on a ~$142 bar was the most consequential
single find given SPY's weight across the corpus. Applied after human review (both the
dry-run report and an explicit user confirmation given the blast radius grew from 2 symbols to
14). 28 rows correctly stayed classified MARKET_EVENT (the known 2010-05-06 Flash Crash
cluster, cross-symbol corroborated) and excluded from correction.

**Recompute hit a real infrastructure lesson along the way.** `backfill_feature_factory.py
--compute-only` at its default worker count (12) OOM-killed twice in a row at nearly identical
elapsed time (~5-6 min) regardless of whether an external timeout was involved — confirmed via
`journalctl -k` (not guessed): python worker processes at 2.3-2.9GB RSS each, 12 concurrent
workers computing full-history features for large symbols (390K+ bars) exceeded available
memory. Fixed by dropping to `--workers 4` (the script's existing, previously-undocumented-in-
practice `--workers` flag / `infra.feature_factory.workers` APR key) — completed cleanly.
**New gotcha for `docs/reference/gotchas.md` if not already there:** this script's default
worker count is unsafe for a full 14-symbol multi-timeframe recompute on this machine's
available RAM; use `--workers 4` for any recompute touching more than a handful of symbols at
once.

**Reconciled todo-level and phase-level prioritization into one view** (user requested this
explicitly) — the two tracks (`.planning/todos/PRIORITIES.md` P0-P3 tiers and ROADMAP.md's
phase queue) had never been merged into a single ranked view before. Five tiers, written into
this file's "Next actions" section above: Tier 1 (todo 160/147 close-out, then Phase 148
execution) → Tier 2 (Phase 163/162 execution, todos 088/168/169/170, all ready and independent
of 148) → Tier 3 (Phase 145/165, need planning first) → Tier 4 (Phase 147 + the full P2/P3 todo
backlog, real value but not urgent) → Tier 5 (Phases 149-159, explicitly gated behind Phase
148's verdict per "prove edge before production infra" — v4.0-adjacent scope with zero
planning artifacts, should not get planning time yet).

**Next actions, in order:** see this file's "Next actions" section under Project Reference
(the reconciled Tier 1-5 view) — do not re-derive a separate list here.

### Session closeout (2026-07-22/23) — Phase 148 executed: both irreversible gates run, verdict DO NOT PROMOTE

Continuing from the prior subsection's Phase 148 finalization, executed the phase via
`/gsd-execute-phase 148` — 3 waves, 5 plans, ~5.5h wall-clock including two coordinator
round-trips for irreversible-action decisions.

**Wave 1** (148-01, migration 248 + Wave 0 test scaffolds) and **Wave 2** (148-02 AlphaScorer,
148-03 Gate 1 script, 148-04 Gate 2 script — 3 parallel worktree executors, no file overlap)
completed cleanly, merged, full test suite green throughout. Wave 2 hit a mid-run session-limit
interruption on all 3 parallel agents simultaneously; resumed each from its preserved
uncommitted worktree state via `SendMessage` rather than restarting — no work lost.

**Wave 3** (148-05, the two irreversible one-shot gates) is where the real substance happened:

1. **Gate 1's mandated dry-run pre-flight found `forward_returns` had zero rows for the entire
   OOS window** (`bar_ts >= 2025-12-24T05:15:00Z`), across all 320 registered (symbol, tf)
   pairs — not the partial insufficient-N the plan anticipated. The executor correctly halted
   rather than force through or self-authorize a fix. Traced (independently re-verified, not
   just trusted): `docs/plans/OOS-EVAL-PROTOCOL.md`'s deliberate holdout-clamp design means
   `forward_return_writer.py` has never been invoked with a `--training-window-end` past
   `oos_start` — and `ensemble_ic_engine.py` (source of the long-cited "EIC-04 PASS") is
   explicitly in-sample-only by its own docstring ("OOS half reserved for Phase 144" — which
   never actually built that). Read the protocol doc in full: it forbids using the OOS window
   for feature selection/calibration/weighting/tuning, none of which describes computing
   `forward_returns` itself (a fixed, parameter-free, deterministic transform). Got explicit
   user sign-off given the stakes, then backfilled (`forward_return_writer.py
   --training-window-end 2026-07-07T16:45:00Z`, full 80-symbol active universe, no
   --symbols filter, in-sample side untouched via `ON CONFLICT DO NOTHING`) — 1,141,051 real
   OOS rows landed. Resumed the executor from the dry-run pre-flight.

2. **Gate 1 ran for real (irreversible, D-04): PASS.** 640 5m/15m cells, all reliable
   (zero insufficient-N once the label substrate existed), 140/640 (21.875%) qualify against a
   2% floor — 10x margin. Coverage gap discovered only after this irreversible run (cannot be
   corrected): `ensemble_alpha` itself has zero OOS rows at `tf=1h` (any weight_version) and
   `tf=1d` (champion weight_version) — a separate, pre-existing gap, not this gate's
   methodology. Filed as **todo 173**, disclosed plainly in the decision record rather than
   presented as a full 4-timeframe pass.

3. **Gate 2's mandated dry-run pre-flight found a tolerance failure**: `c4_max_dd` missed the
   plan's 1e-6 reproduction tolerance against the frozen 143.1-08 baseline by four orders of
   magnitude. Root-caused (both by the executor and independently re-verified by direct
   computation against live data): the champion OOS population has ~22-way ties at the
   `bar_ts` grain (33,892 rows, 1,534 distinct timestamps — genuinely simultaneous
   cross-sectional positions). `_max_drawdown` is a path-dependent statistic computed via
   unordered-tie `ORDER BY bar_ts ASC` in both the original 143.1-08 script and the new Gate 2
   script — meaning **the frozen 143.1-08 baseline itself was never a reproducible number**,
   just whatever TimescaleDB parallel-chunk-scan interleaving happened on 2026-07-21. The
   executor's first fix (a `frame_id` tie-break) was deterministic but conceptually wrong —
   same-`bar_ts` frames are simultaneous, not sequential, so any row-ordering is economically
   meaningless. Directed the correct fix instead: aggregate (SUM) `pnl_r` per distinct `bar_ts`
   BEFORE the cumulative walk — eliminates the tie-break question structurally rather than
   picking one arbitrarily. Verified this independently via a standalone computation against
   live data before directing the fix. Produced a third distinct number
   (`c4_max_dd=9.596266492204732`) — but the verdict is identical under all three numbers
   tested (original 9.598, wrong tie-break 9.606, correct aggregation 9.596): catastrophic
   ~960% drawdown against a 0.25 threshold, never close.

4. **Gate 2's first real-run attempt crashed** (non-finite floats in a jsonb write — Python's
   bare `Infinity`/`NaN` tokens aren't valid JSON per RFC 8259). Confirmed the transaction
   rolled back cleanly (zero partial rows, zero look-log entries) before retrying — the D-04
   one-shot was not consumed by the failed attempt. Fixed with a recursive sanitizer, retried.

5. **Gate 2 ran for real (irreversible, D-04): FAIL.** 3 of 5 SHADOW-REVIEW criteria fail
   (mean P&L CI, Sharpe, max drawdown), matching D-06's "known going in" framing exactly — not
   a surprise. Regime-stratified companion (D-07): only 2 of 8 champion cells clear
   `min_clusters=20` coverage, both `mid_bull`, both fail — the champion's OOS window is too
   narrow (single-regime) to speak to regime-conditional performance. A related order-
   sensitivity symptom (CI drift in a coverage-excluded cell, different root cause) surfaced
   and was filed as **todo 172**, not fixed inline (doesn't affect the counted verdict).

**Both gates verified live-DB-side (not just trusted from agent reports):** exactly 1
`gate_evaluations` row per gate, zero `gate_id='FRAME-04'` rows, Gate 1's `run_ts` precedes
Gate 2's, exactly 2 `gate_look_log.jsonl` entries matching the DB timestamps precisely.

**Promotion decision, written and merged**: `docs/plans/2026-07-22-phase148-promotion-decision.md`
— **do not promote the v3.0 AlphaEngine to live trading capital at this time.** Real signal
exists (Gate 1) but the current frame/execution design does not capture it as profitable OOS
P&L (Gate 2) — per this project's core value, a signal that can't yet be turned into profitable
trades is not a promotable system. Diagnosing/fixing Gate 2's failure is explicitly out of
scope for this phase.

Merged all 3 waves to `main` via fast-forward/regular merges as appropriate, full unit suite
green after every merge, worktrees cleaned up (zero orphans), pushed
(`d96f9ec2` → `ee614124` → `a0ddaf48` → `22980f89`).

**Next actions:** see this file's "Next actions" section above (reconciled Tier 1-5 view,
updated post-Phase-148). The highest-value open question is whether/how to scope a frame/
execution recalibration to address Gate 2's failure — not yet a todo or phase, flagged as
Tier 1's own open item rather than started unprompted.

### Session closeout (2026-07-24) — Phase 163 executed; Gate 2's real cause found; Phase 166 Part 2 overridden; Layer-1 regime foundation fixed

This session ran outside the normal GSD phase-execution flow — user asked for a Renaissance-
council-style strategic review ("are we generating real alpha"), which turned into: executing
Phase 163, a full diagnostic investigation of why Gate 2 fails, and a Layer 1 (regime labeling)
infrastructure fix found along the way. Full reasoning trail preserved in
`.planning/todos/pending/179-gate166-concurrent-exposure-diagnostic.md` and
`.planning/todos/completed/168-seven-symbols-zero-per-symbol-hmm-regime-labels.md` — read those
before re-deriving anything below.

**Phase 163 executed and verified** (15/15 must-haves) — see Phase Summary table above.

**Gate 2 diagnostic (todo 179), in the order hypotheses were tested and either confirmed or
falsified — don't re-run any of these:**
1. Concentration/position-sizing: real (triples Sharpe via a risk-budget sweep), but drawdown
   floors at ~11x vs the 0.25 threshold regardless of budget — falsifies "it's purely a sizing
   artifact."
2. Single-symbol standalone test (zero basket, zero portfolio math): XLE/PPLT/XOP each show
   negative Sharpe and catastrophic `mid_bull` losses completely alone — proves the deficiency
   isn't basket-level.
3. Sign-symmetric shadow test (143.1-08, already-run data, re-examined): unlocking shorts made
   things WORSE (Sharpe -4.14, drawdown 360,733%), not better — rules out "should have gone
   short instead."
4. Full regime sweep (all 9 equity cross-sectional cells): the ensemble has literally zero
   eligible features for 4 of 9 regimes (silent skip, not a bug) — confirmed those 4 regimes DID
   occur in the OOS window, the model just never fires there.
5. Per-symbol HMM axis crossed against cross-sectional regime (never checked before user asked
   "why only 2 regimes?"): reveals real heterogeneity within `mid_bull` — a `ranging` sub-bucket
   near breakeven vs. `trending_up`/`transition_down` genuinely bad. Any fix must stratify on
   both axes jointly, not cross-sectional regime alone.
6. Asset-class regime-mismatch hypothesis (commodity ETFs getting a wrong equity-breadth regime
   signal): tested directly, FALSIFIED — equity-tagged symbols lose worse than commodity-tagged
   ones in the same regimes.
7. **Decisive test:** pulled `mid_bull`'s raw, completely un-barriered forward return straight
   from `forward_returns` (same table/method as Gate 1) — negative at every horizon, gets worse
   with longer holds. This is not an execution artifact; it's what the market did. **Overrides
   Phase 166's own recommended next step** (finishing the structural S/R candidate, todos
   175/176) — a third stop-placement variant cannot fix a genuinely negative raw return, and
   Phase 166 already tried two. Real next step: does `ensemble_trainer.py` have any
   regime-conditional expectancy floor at emission time, or only feature-level significance?
   Not yet answered — read the code before designing anything.

**Layer 1 (regime labeling) foundation work, found necessary along the way, not originally
planned:** built `services/regime_coverage_auditor.py` (todo 169) as a cheap completeness
canary — it immediately found 14 symbols with zero per-symbol HMM regime coverage, not the 7
known at filing (todo 168). Root-caused via direct, live testing (not guessed): most were a
compressed-hypertable write wall (migration 201's float64->float32 conversion recompressed
`feature_vectors` as a documented, deliberate final step — not a policy bug), not a modeling
problem. Decompressed (~20GB, trivial against 742GB free), confirmed fix directly for every
symbol. Remaining ~23 (symbol,tf) cells are genuine HMM-fit limits (tested and ruled out:
`min_state_occupation` miscalibration via a corpus-wide distribution check, and `min_hold_bars`
smoothing via direct testing) — documented as reasoned exclusions in `regime_writer.py`'s module
docstring. **Todo 168 CLOSED.** Full detail:
`.planning/todos/completed/168-seven-symbols-zero-per-symbol-hmm-regime-labels.md`.

**A real operational incident happened and was cleanly resolved, worth knowing about:**
running several `regime_writer.py` invocations back-to-back with `timeout`-based kills left an
orphaned write transaction pileup in Postgres (3 backends, one lock-blocking the next) — caught
via `pg_stat_activity`, resolved with `pg_terminate_backend()`, confirmed zero pending locks and
zero partial writes afterward. No lasting damage, but a reminder: always confirm zero orphaned
processes/connections between `regime_writer.py` invocations, not just before the next one.

**Cleanup done this session:** removed 3 dead todos (`012`, `032` — stale merge-redirect stubs;
`153` — resolved by Phase 163, verified live), pruned an orphaned merged worktree
(`restore-symbol-hmm-ic-measurement`), added missing test coverage for the new
`regime_coverage_auditor.py`, added its systemd unit files (not yet enabled on the live host —
a real infra change, deliberately left for explicit go-ahead), compacted `MEMORY.md` from 19.6KB
to 14.8KB (moved sprawling investigation detail into topic files, cut fully-resolved historical
narrative per this project's own "no resolved history" memory rule).

**Next actions, in order:** see "Next actions" under Project Reference above (Tier 1-6,
rewritten this session) — Tier 1 (validate the regime-eligibility hypothesis properly, read
`ensemble_trainer.py`/`alpha_publisher.py` first) is the highest-value open item. Do not resume
todos 175/176 (structural candidate Part 2) without re-reading why they were deprioritized.
