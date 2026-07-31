---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: AlphaEngine Validation + Alpha Scoring
status: ready_to_execute
stopped_at: Phase 168 context gathered
last_updated: "2026-07-31T10:53:33.339Z"
progress:
  total_phases: 12
  completed_phases: 9
  total_plans: 45
  completed_plans: 44
  percent: 75
---

# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Alpha must be demonstrated empirically before any ensemble weight is assigned.

**Guiding lens (Renaissance / Musk, per CLAUDE.md's north star):** every claim in this section
must be empirically demonstrated, not assumed -- T3 below earned its place by clearing a
shuffled-ranking-null guard, not by a plausible story. Before building anything, apply Musk's
5-step mandate: question whether the requirement is real, delete before adding, simplify,
accelerate, automate -- in that order. This is why Phase 167 (cheap, already-proven) is
sequenced ahead of Phase 151/164/165 (expensive, unproven): don't accelerate feature-expansion
work that hasn't been shown to be the actual bottleneck.

**Current focus (updated 2026-07-30):** Milestone v3.1's defining verdict stands: Phase 148
found Gate 1 (signal proof) PASS but Gate 2 (execution proof) FAIL -- do not promote the
per-symbol directional construction to live capital. Phase 167 (Cross-Sectional Trade
Construction, T3) resolved the fork this opened -- **COMPLETE 2026-07-27, both live Validation
Gates PASSED** (`gate1_passes=true`, `gate2_passes_overall=true`), the first construction in the
tree to clear both. T2 (regime-conditional persistence) is CONFIRMED DEAD (270 cells tested,
zero pass on live corrected labels). T5 (non-linear combiner) is confirmed SMALL, not LARGE (1d
replication collapsed ~16x from the original 1h finding; 15m replication, the directly
actionable tf, still pending -- todo 188). Full detail on all three: `docs/research/data-edge-source-thesis.md`.
Phase 144/143.1/162/163/164/165/167 are all COMPLETE -- see Phase Summary table below, not
duplicated here.

**Current saga (2026-07-30): the per-tf-active-scale-set branch landed, exposed the session-gate
bug it was named after, and that's now fixed too.** The branch (`ic_engine.py`'s hardcoded
`_SCALES` tuple -> per-tf `active_scales_for(tf)`, migration 271) was already merged to
`origin/main` by a concurrent session before this session fetched -- reconciled cleanly (reset
local `main` to `origin/main`, cherry-picked this session's own STATE-realignment work on top,
resolved one todo-numbering collision). Full history: `git log --oneline` around commit
`46dc307d` (the merge) and `9a1a6ca2`/`2b5e6c60` (the reconciliation). **Lesson banked in
[[feedback_concurrent_sessions_shared_dir]]: `git fetch origin` before trusting local git state
or a prior memory snapshot as current -- local can be an entire merge behind origin.**

That branch's own final review flagged [todo 208](.planning/todos/pending/208-intraday-same-session-forward-return-gate-inconsistent-with-trade-construction.md):
`forward_return_writer.py`'s same-ET-session completeness gate was silently zeroing 1h's
`slow`/`extended` completeness and capping `mid` at 53.5%, for a reason (session boundaries)
that doesn't apply anywhere else in this codebase's trade-construction layer. **Fixed same day**
-- `complete_{scale}` now means "the forward bar exists," identically at every tf, matching how
1d always worked; migration 272 reverted 1h's now-unjustified `active_scales` exclusion;
`forward_returns` truncated and rebuilt clean under the corrected definition; corpus pipeline
relaunched from step 3, **on step 5/8 (`ic_engine`, started 2026-07-30 13:19 EDT, confirmed
writing real rows to `feature_ic_scores` as of the last check this session -- re-verify via
`ps aux | grep ic_engine` and `tail logs/corpus_pipeline/resume_20260730_1240.log`
before trusting this in a later session, historically ~27h total). Do not start new corpus-write
work until it completes.**

**Same-day follow-through on the `_SCALES`-hardcoding cleanup cluster** (plan:
`docs/plans/2026-07-30-ic-scale-cleanup-plan.md`, all commits on `main`, tests green
throughout): Task 1/todo 210 -- `ensemble_ic_engine.py`'s worker never checked
`complete_{scale}` in either fetch path (a real measurement-integrity gap, not just wasted
compute) and iterated the flat `_SCALES` tuple instead of `active_scales_for(tf)`, both fixed.
Task 2/todo 209 -- `ops_vol_normalized_target_ab.py` migrated to a new `_load_active_scales`
helper. Task 3/todo 211 (part 1 of 2) -- `ops_ensemble_ablation.py` migrated to a per-tf
`AblationConfig` (mirrors `ICEngineConfig`'s shape exactly); **this surfaced a second,
independent bug in the same file**, not caught by the original 211 filing: `AblationConfig`
was still reading the pre-todo-146 flat global `alpha.ic.lookahead.{scale}` keys (no `{tf}`
component) -- the script's own code carried a self-aware runtime warning about this, citing
todo 202 as the tracker, but todo 202 closed without ever picking it up. Fixed in the same
commit as the `_SCALES` migration. **Remaining: Task 4/todo 211 (part 2) --
`ops_interaction_primitives_pilot.py` -- same `_SCALES` migration, plus its own independent
stale-lookahead-key bug (same class as the one just found), not yet started.**

Todo 210 (`ensemble_ic_engine.py`'s worker loop never checked `complete_{scale}` at all -- a
real measurement-integrity gap, not just wasted compute) plus its two sibling `_SCALES`-cleanup
todos (209, 211) and a trivial fix (212, corpus_manifest_verifier's empty-list bug, CLOSED) are
scoped in `docs/plans/2026-07-30-ic-scale-cleanup-plan.md`, ready to execute once `ic_engine`
settles. Todo 214 (ic_engine.py/ensemble_ic_engine.py's duplicated per-scale compute logic --
the root cause that let 210 exist undetected) is filed, deliberately deferred until this chain
is stable. A design doc on the grid's actual per-tf VALUES,
`docs/research/2026-07-30-forward-return-horizon-grid-refactor.md` (v1.2), recommends aligning
each tf's measured horizons to that tf's real holding period via the existing (but currently
starved) `_select_hold_bars_from_decay` decay walk, rather than a uniform or arbitrary grid --
live evidence: `hold_max_bars` is pinned at the 60-bar ceiling in *every* regime for 1h and 1d
today, meaning that walk has never once converged for either tf.

Todo 146's per-tf lookahead grid (migration 269) is no longer blocked by 208's *premise*
(session-boundedness is resolved), but its *values* remain open pending the research doc's
characterization step (`ops_lookahead_horizon_response.py`, safe to run now, needs one small
`_OVERNIGHT_HORIZON_GRIDS` gap closed for 5m first) plus the in-flight `ic_engine` run's real
measurement. Canary RNG pseudo-replication fixed ([todo 203](.planning/todos/pending/203-canary-rng-seed-not-per-symbol-cross-sectional-pseudo-replication.md));
sibling `canary_acausal_placebo` POOLED-gate anomaly still undiagnosed
([todo 204](.planning/todos/pending/204-canary-acausal-placebo-pooled-not-detected.md)).

**Next actions, priority order:**

*Tier 1 -- decision point, REDIRECTED 2026-07-27 by explicit user instruction:* Phase 156-159
(execution/sizing) is NOT the priority even though its precondition is cleared. User wants the
features/regimes/IC/ensemble signal-generation stack validated first ("real proven signals")
before any execution-layer investment. Do not resume Phase 156-159 scoping without the user
re-raising it.

*Tier 1b -- CLOSED 2026-07-27:* todo 183's corpus recompute completed; todo 179's regime sweep
re-run under corrected labels; final T2 verdict is dead, confirmed live. No longer a blocker.

*Tier 2 -- serves the redirected priority:* todo 188 (T5 15m replication, deferred on memory
contention -- see above); the open `alpha_ensemble_ic`/`alpha_events` question (is the linear-only combiner adequate, or
does it need revision -- confirmed `ensemble_trainer.py`'s `resolve_stratum_weights` is linear
combination only; `alpha_events` confirmed sparse/emission-gated, not a dense full-universe
ranking input without further work; not yet investigated further). Phase 151 (Feature
Primitives Expansion, already planned) is the next-tier option if these don't pan out.

*Tier 2b -- concretely staged, waiting on Tier -1's pipeline to exit:* todo 167 (equity
cross-sectional-vs-symbol-HMM stratification falsifier, never tested unlike rates'). Migration
262 applied (`dual_write_symbol_hmm=true` for equity), falsifier gate script written and
verified (`scripts/analysis/equity_regime_separation_gate.py`, generalized from Phase 144's D-05
gate). **The in-flight `ic_engine` run (Tier -1) is a full, unscoped pass -- check whether it
already covers the 49 equity symbols this todo needs before assuming a second scoped run is
still required once it completes.**

*Tier 3 -- ready now, independent of the pipeline:* `docs/plans/2026-07-30-ic-scale-cleanup-plan.md`'s
Tasks 2-4 (todos 209/211, three ops scripts still importing a flat `_SCALES` tuple -- pure
mechanical migrations, unit-testable without live data). Task 1 (todo 210, the real
measurement-integrity fix in `ensemble_ic_engine.py`) is also codeable/testable now via mocks;
only its live-data verification step needs `ensemble_alpha` repopulated. Also: todos 172/173
(non-blocking Phase 148 findings), todo 009 Parts A-D.

*Tier 4 -- deprioritized, do not resume without re-reading why:* Phase 151 (Feature Primitives
Expansion, planned and ready but not the next priority -- see Guiding lens above), Phase 145
(StratificationDimension Formalization, unblocked but not planned), todo 175 (structural
candidate Part 2 -- exists only to serve an overridden plan, see todo 179).

*Tier 0 -- CLOSED 2026-07-29:* the combined `backfill_feature_factory.py --compute-only
--refresh` pass landed Phase 164/165's 77 new columns and Phase 163's deferred VP/SR historical
backfill (todo 176). Its regime-wipe side effect (todo 205) and the resulting repair pipeline
are ALSO fully closed as of 2026-07-30 -- not the pipeline currently running (see Tier -1).

*Tier -1 -- ACTIVE, supersedes every tier below until it clears:* the corpus pipeline relaunched
2026-07-30 from step 3 (`forward_return_writer`, to pick up todo 208's session-gate fix) is on
step 5/8 (`ic_engine`, started 13:19 EDT 2026-07-30). **Verified live 2026-07-31T10:38 UTC via
`logs/ic_engine.log`: 25/80 symbols done** (`progress: "25/80"` on the last `symbol_computed`
line). At that pace (~17.3h for 25 symbols), full completion is **~38h more remaining (~2026-08-02
midday)** -- noticeably slower than the "historically ~27h" baseline, consistent with two
already-known compounding factors: `threads=2`'s measured 1.28-1.35x speedup (not the 2.4x
isolated-worker benchmark, per todo 215) and the corpus now carrying 244 feature columns/symbol
(the historical baseline predates Phase 163/164/165's +77 columns). Nothing that reads
`feature_ic_scores` or `ensemble_weights` should start until it completes. Re-verify before
trusting this in a later session: `ps aux | grep ic_engine`, `tail -30 logs/ic_engine.log | grep
symbol_computed`, `tail -15 logs/corpus_pipeline/resume_20260730_1240.log`.

A same-day partial-data check (safe, read-only, ran alongside the live pipeline) found
`ctf_momentum` at 15m holding up on the first 21 symbols computed under the corrected corpus:
872 cells, 91.4% positive sign, 63% passing the bootstrap CI gate, mean IC 0.0527, mean IC
Sharpe 0.4389, BIL (T-bill ETF, near-zero movement) the one sensible outlier. **Early
reinforcement of Phase 167/T3's already-proven result, not new evidence** -- `bh_adjusted_p` is
NULL for all rows so far (FDR correction is a corpus-wide pass that only runs once at the very
end), so this is a legitimate partial read of real per-cell stats, not a final verdict.

*Tier 5 -- gate status changed 2026-07-27:* Phase 156-159 (Portfolio State/Sizing/Execution/Cost)
was gated on Phase 167 producing a proven signal -- **that gate cleared: Phase 167's both
Validation Gates PASSED.** Whether to actually begin Phase 156-159 is still the user's decision,
not automatic. Phase 149/150/155 (PrecedentEngine, Alt Data) -- v4.0-adjacent, no case made yet.
Phase 147 (I7 due diligence) -- cheap, gates nothing.

Full P2/P3 todo backlog: `.planning/todos/PRIORITIES.md`. Idea-level scoring:
`docs/research/intelligence-lifecycle-backlog-matrix.md`.

**Execution plan:** `docs/plans/archive/2026-06-30-alphaengine-v1-execution-plan.md`

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
| 142A | Ensemble IC Measurement | COMPLETE (2/2 plans) -- EIC-04 current verdict PASS 54/1425=3.79%, see [Corpus pipeline state](project_corpus_pipeline_state.md) for the live number |
| 142B.1 | Ensemble Weighting Methodology | COMPLETE (5/5 plans) -- E1 (shrunk-IC) is champion; E2 (mean-variance) rejected |
| 142.5 | Renaissance Primitives | COMPLETE (8/8 plans) -- 89 primitives live in Feature Factory, 150 total `FeatureVector` fields |
| 142B | Frame Simulation + Counterfactual Tracking | COMPLETE (2/2 plans) -- `alpha_frames` hypertable + `AlphaFrameWriter` + `CounterfactualTracker` live |
| 143 | Feature Lifecycle Routing (merged with 149B) | COMPLETE (3/3 plans) -- `feature_registry` evidence-based promotion/demotion + `integrity_monitor` table live |
| 143.1 | Measurement and Eligibility Integrity | COMPLETE (8/8 plans, 2026-07-21) -- 143.1-08 shadow-mode validation VERDICT: HOLD (`alpha.ensemble.sign_symmetric` stays false) |
| 144 | Cross-Sectional Regime Model (`regime_group`) | COMPLETE (6/6 plans, 2026-07-22) -- D-05 verdict: F1 not triggered (TLT HMM stays deficient, demotion holds), F2 triggered for 15m/5m (rates cross-sectional also deficient there) |
| 146 | Empirical Instrument Tag Calibrator | COMPLETE (5/5 plans, 2026-07-17) -- `TagCalibrator` live-verified: 11/12 measurable tags carry real `source='empirical'` rows |
| 160 | Concept Registry MVP | COMPLETE (4/4 plans) -- 4-table schema + `ConceptRegistryService`/`ConceptRegistryAPI`/`ConceptRegistryDashboard` live |
| 161 | Controlled Vocabulary System | COMPLETE (4/4 plans, 2026-07-18) -- schema + `VocabularyService` + `vocabulary_drift` audit + `/api/vocabulary/{namespace}` route, live-verified (VERIFICATION.md: passed, 23/24 truths, 1 accepted YAGNI override) |
| 148 | Alpha Scoring System (OOS Proof Gates) | COMPLETE (5/5 plans, 2026-07-22) -- the actual proof-of-alpha milestone: Gate 1 PASS, Gate 2 FAIL, VERDICT do not promote to live capital; see ROADMAP.md's Phase 148 section and `docs/plans/2026-07-22-phase148-promotion-decision.md` for full evidence |
| 162 | ic_engine Corpus Pipeline Throughput | COMPLETE (4/4 plans, 2026-07-23) -- whole-cell fingerprint mechanism, equivalence-proven |
| 166 | Frame/Execution Recalibration | COMPLETE (6/6 plans, 4 waves, 2026-07-23) -- baseline and scalar candidates FAIL gate166 decisively; structural candidate halted pending Phase 163. Part 2 (todos 175/176) deprioritized by todo 179's finding. |
| 163 | VP/SR Structural Primitives | COMPLETE (3/3 plans, 2026-07-24, verification 15/15 must-haves) -- closes todo 153. Historical backfill still open (todo 176, deprioritized) |
| 167 | Cross-Sectional Trade Construction (T3) | COMPLETE (6/6 plans, 2026-07-27) -- both live Validation Gates PASSED (gate1_passes=true, gate2_passes_overall=true); Phase 156-159's stated precondition is now met. See Current Focus. |
| 164 | SMC Institutional Footprint Primitives | COMPLETE (4/4 plans, 2026-07-28) -- all 36 SMC FeatureVector fields now real computed values in both FeatureFactory.compute() and compute_batch(). Plan 01 (data contract): 36 new feature_vectors columns + registry rows + FeatureVector fields (172->208 total), 39 feature.smc.* APR keys, FeatureCache.update_overnight_range() AMD mutator built. Plan 02 (order blocks + stateless breaker/mitigation): 7 fields via _compute_order_blocks(); 2 bugs caught and fixed during TDD. Plan 03 (FVG + liquidity sweeps + liquidity pools): 12 fields via _compute_fvg()/_compute_liquidity_sweeps()/_compute_liquidity_pools() (single-tf descoped, PWH/PWL/PDH/PDL dropped); an FVG selection bug found and fixed. Plan 04 (supply/demand zones + BOS/CHoCH + AMD cycle): final 18 fields via _compute_supply_demand_zones()/_compute_bos_choch()/_derive_amd_cycle(); update_overnight_range() wired into compute_batch(), the live per-bar handler, and the warm-up replay block, closing the AMD state-lifecycle cold-start gap. Historical backfill for all 36 columns deliberately deferred to the consolidated 163/164/165 recompute pass (todo 176). |
| 165 | Swing/Fib/Trend/Session Structure Primitives | COMPLETE (5/5 plans, 2026-07-28) -- migration 267 adds 41 new feature_vectors columns + registry rows (group_name='session') for swing detection (7), trend structure (6), swing momentum (8), fibonacci zones (4), session levels (16); zero raw price levels or raw bar indices (D-02/D-04); all 41 fields float \| None, no fake-numeric defaults (D-01). 17 feature.swing.*/feature.trend_structure.*/feature.swing_momentum.*/feature.fib.*/feature.session_levels.* APR keys wired into both live and batch FeatureFactoryConfig sites. `_compute_swing_structure()`/`_compute_trend_structure()` (13 cols, shared `find_peaks`/`find_troughs` pass, D-06), `_compute_swing_momentum()`/`_compute_fib_zones()` (12 cols, deletes the archived cross-plugin fallback outright per D-05), `update_session_levels()` FeatureCache mutator (22 new internal state fields, D-07/D-08/D-09) + `_derive_session_levels()` (final 16 cols) all wired into both `compute()`/`compute_batch()`. Phase-closing gate (`test_phase165_all_41_fields_non_constant_batch`) confirms all 41 columns produce real values; `feature_registry` DB check confirms 41 rows with `added_phase='165'`. Every plan's mutation-verification pass (commit `a748d13d` discipline) surfaced and fixed a real bug in the plan's own tests or comments (a `math.isclose` `rel_tol` masking, a structurally-blind accumulator-collision test, a vacuous live/batch parity check, and a post-merge causal-safety-lint false positive) -- the discipline earned its keep every time it ran. Historical `feature_vectors` backfill for all 41 columns deliberately deferred to the consolidated 163/164/165 recompute pass (todo 176 / STATE.md Tier 0). |

Current row counts and every downstream measurement number live in
[Corpus pipeline state](project_corpus_pipeline_state.md) -- that file is the single source of
truth; don't duplicate counts here.

**Dual regime system (both live):**

- `feature_vectors.regime` -- 5 per-symbol HMM labels (trending_down/transition_down/ranging/transition_up/trending_up), written by `regime_writer.py` (K=5, causal forward-filter)
- `market_regimes` -- cross-sectional labels keyed by `regime_group` (a named peer group with a pluggable regime signal: `breadth_vol` for equity, `curve_credit` for rates; commodity/fx modules ship disabled), written by `cross_sectional_regime_model.py` (Phase 144, replaced `equity_regime_model.py`); `ic_engine` stratifies on these

## Key Decisions (load-bearing -- don't re-derive)

- **HMM_RANDOM_STATE = 42** -- changing invalidates all feature_ic_scores, requires full re-run
- **Pooled IC (is_pooled=true)** -- cross-sectional POOLED strata ARE the ensemble training eligibility source. `ensemble_trainer.py` reads `WHERE symbol='POOLED' AND is_pooled=true AND regime != '_pooled'` (lines 317, 430-431, 469, 540)
- **IC Sharpe gate** -- sharpe_window_size=2000 RAW bars; gate is n_raw_bars >= 20,000; stride divides inside _compute_ic_rolling_metrics
- **regime_label_source DEFAULT** -- 'forward_filter' (not 'filtered') in both forward_returns and feature_ic_scores
- **APR key** -- alpha.ic.subsample_min_stride is a floor: actual_stride = max(min_stride, lookahead_bars)
- **Gradient naming** -- return_fast/mid/slow/extended; momentum_z_fast/mid/slow; volatility_rank_z
- **ON CONFLICT for partial indexes** -- use column list + WHERE clause, not ON CONSTRAINT (TimescaleDB)
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

- Phase 168 (Cost-Hurdle-Adjusted Spread Construction, T3 Follow-On): added 2026-07-31 as a
  parallel track while the in-flight `ic_engine` recompute runs (zero compute contention --
  pure scoping/discussion work). Follow-on to Phase 167's cross-sectional long-short
  construction (both live Validation Gates PASSED); applies todo 030's cost-hurdle sweep as a
  construction-layer change (which symbols/legs survive transaction costs), no new features.
  See `docs/research/trade-construction-layer.md`.

- Phase 162 (ic_engine Corpus Pipeline Throughput): added 2026-07-18, planned 2026-07-22, executed and COMPLETE 2026-07-23.
- Phase 163 (VP/SR Structural Primitives): added 2026-07-20, planned and reviewed, executed and COMPLETE 2026-07-24.
- Phase 164 (SMC Institutional Footprint Primitives): added 2026-07-20, planned 2026-07-25 (4 plans, 4 waves, `gsd-plan-checker` verified). Deprioritized 2026-07-26 behind Phase 167, then explicit user override 2026-07-27 (Tier 0) reinstated it regardless of the evidence-gate reasoning. Plan 01 (data contract) executed 2026-07-27; Plan 02 (order blocks + stateless breaker/mitigation), Plan 03 (FVG + liquidity sweeps + liquidity pools), and Plan 04 (supply/demand zones + BOS/CHoCH + AMD cycle) all executed 2026-07-28 -- COMPLETE, 4/4 plans, see Phase Summary table. Next per Tier 0's sequencing: plan Phase 165, execute Phase 165, then one combined `backfill_feature_factory.py --compute-only --refresh` pass covering both phases' new columns.
- Phase 165 (Swing/Fib/Trend Structure Primitives): planned 2026-07-27 (5 plans, 5 waves, sequential -- every plan touches `feature_factory.py`). Plan 01 (data contract: migration 267, 41 new columns/registry rows/APR keys) executed 2026-07-28. Plan 02 (swing detection + trend structure, 13/41 columns, mutation-verified) executed 2026-07-28. Plan 03 (swing momentum + fibonacci zones, 12/41 columns, 25/41 total, mutation-verified) executed 2026-07-28. Plan 04 (session levels FeatureCache state layer, 22 new state fields, mutation-verified) executed 2026-07-28. Plan 05 (final 16-column derivation + phase-closing gate) executed 2026-07-28 -- **COMPLETE, 5/5 plans.** All 41 `feature_registry` rows (`added_phase='165'`) confirmed live in DB. Per Tier 0's sequencing, next action is the ONE combined `backfill_feature_factory.py --compute-only --refresh` pass covering both Phase 164's and Phase 165's new columns (~8h estimated, not yet started -- the user's decision when to kick off, not automatic).
- Phase 166 (Frame/Execution Recalibration): added 2026-07-23, planned and executed same day -- COMPLETE, verdict: neither candidate promoted. Direct follow-on (todo 179) found the real cause (see Current Focus).
- Phase 151 (Feature Primitives Expansion + Interaction Layer): planned 2026-07-24, cross-AI reviewed and revised same day (Codex found 3 HIGH-severity findings, all fixed as real plan changes). 9 plans, execution-ready. Deprioritized 2026-07-26 behind Phase 167 (see Current Focus) -- stays planned and ready, not the next priority.
- Phase 167 (Cross-Sectional Trade Construction, T3): added 2026-07-26 after T3 passed decisively -- the first thesis in the edge-source-thesis tree to clear its own bar. Planned (6 plans), executed, COMPLETE 2026-07-27 -- both live Validation Gates PASSED. Full detail in Current Focus above.

**Prior session history (resolved, not duplicated here per this project's "no resolved history"
convention -- full detail in git log and `.planning/todos/completed/`):** 143.1-08 shadow-mode
resolution (2026-07-21) · todos 164/165 ensemble-eligibility fixes (2026-07-21) · symbol_hmm
restoration + Phase 148 planning (2026-07-22) · Phase 148 finalized, todo 160's real corrupt-print
scope found and fixed -- 40 bars across 14 symbols, 20x the known count (2026-07-22) · Phase 148
executed, both irreversible OOS gates run, verdict DO NOT PROMOTE (2026-07-22/23) · Phase 163
executed, Gate 2's real cause found (todo 179), Layer-1 regime-coverage foundation fixed -- todo
168 closed, todo 169 shipped (2026-07-24) · Phase 167 planned and executed end-to-end (6/6 plans,
2026-07-27), both live Validation Gates PASSED, post-execution `/simplify` + code-review found and
fixed 1 critical + 5 warnings (CR-01 turnover-seed bug, WR-01 APR migration, 3 doc/glossary fixes,
WR-05 filename-collision fix), CLAUDE.md/gotchas.md corrected same session.

## Session

**Last session:** 2026-07-31T10:53:33.256Z

**Stopped at:** Phase 168 context gathered
phase-closing gate) executed: `_derive_session_levels()` derives the final 16 columns from
Plan 04's `FeatureCache` state, wired into both `compute()`/`compute_batch()`; the phase-closing
`test_phase165_all_41_fields_non_constant_batch` gate confirms all 41 Phase 165 columns now
produce real, non-constant values in both compute paths. `feature_registry` DB check confirms
41 live rows with `added_phase='165'`. A post-merge test failure (a Plan 05 comment's literal
"backward compatibility" phrase tripped the causal-safety look-ahead scanner
`test_no_smooth_or_backward_in_factory`) was caught by the post-merge gate and fixed same-session
(`ca4ef569`) -- reworded, not suppressed. Next: the user's decision on Tier 0's final step, the
combined Phase 164+165 `backfill_feature_factory.py --compute-only --refresh` pass (~8h,
covers 77 new columns + Phase 163's deferred VP/SR backfill, not yet started).

**This session's arc:** Resumed from a prior session's handoff (Plan 02 finalization, committed
as `1bc98d0f`). Continued via `/gsd-execute-phase 165`, dispatching sequential single-plan-wave
`gsd-executor` subagents in worktree isolation for Waves 3-5. Wave 3 (Plan 03: swing momentum +
fibonacci zones) merged clean, tracking committed `88eb4a2c`. Wave 4 (Plan 04: session levels
state layer) merged clean, tracking committed `d244977b`. Wave 5 (Plan 05: session levels
derivation + phase-closing gate, commits `aa7d1532`/`ddf3474f`/`41cd741c`/`76bf478a`) merged, but
the post-merge `tests/unit/` gate caught one real failure -- fixed directly (`ca4ef569`) rather
than deferred. Every one of Plans 02-05's own mutation-verification passes (commit `a748d13d`
discipline) surfaced and fixed a genuine bug in that plan's own tests, not just confirmed green:
a `math.isclose` `rel_tol` masking (Plan 03), a structurally-blind accumulator-collision test
(Plan 04), and a vacuous live/batch parity check (Plan 05) -- worth noting since it validates the
discipline itself, not just this phase's output. Marked Phase 165 COMPLETE in ROADMAP.md/STATE.md
(manual edits, not `gsd-sdk query roadmap.update-plan-progress`, which corrupted both files' text
in an earlier session per MEMORY.md's `feedback_gsd_state_frontmatter_resync` note) and updated
Tier 0's status to reflect both Phase 164 and Phase 165 now complete, with only the combined
recompute pass remaining.
