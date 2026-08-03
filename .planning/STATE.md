---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: AlphaEngine Validation + Alpha Scoring
status: ready_to_execute
stopped_at: Phase 168 planned (5 plans, 4 waves), reviewed by Codex+Agy, revised -- ready to execute
last_updated: "2026-07-31T12:02:57.744Z"
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
must be empirically demonstrated, not assumed -- cross_sectional_relative_value below earned its place by clearing a
shuffled-ranking-null guard, not by a plausible story. Before building anything, apply Musk's
5-step mandate: question whether the requirement is real, delete before adding, simplify,
accelerate, automate -- in that order. **Corrected 2026-08-03 -- this sentence used to lump
Phase 164/165 in with Phase 151 as "deprioritized, expensive, unproven"; that's stale. Phase
164/165 were deprioritized behind Phase 167 on 2026-07-26, then the user explicitly overrode
that call the next day (Tier 0) and both executed to COMPLETE by 2026-07-28, columns already
backfilled and live in the corpus (see Phase Summary table).** Phase 151 alone remains planned
but not executed, still deliberately behind Phase 167: don't accelerate feature-expansion work
that hasn't been shown to be the actual bottleneck.

**Current focus (updated 2026-07-30):** Milestone v3.1's defining verdict stands: Phase 148
found Gate 1 (signal proof) PASS but Gate 2 (execution proof) FAIL -- do not promote the
per-symbol directional construction to live capital. Phase 167 (Cross-Sectional Trade
Construction, cross_sectional_relative_value) resolved the fork this opened -- **COMPLETE 2026-07-27, both live Validation
Gates PASSED** (`gate1_passes=true`, `gate2_passes_overall=true`), the first construction in the
tree to clear both -- though which tf it should trade at is itself an open question: `_TF="15m"`
was inherited from the original falsification script, never comparatively tested against 5m for
this specific construction (todo 235, new 2026-08-03). regime_conditional_persistence (regime-conditional persistence) is
CONFIRMED DEAD (270 cells tested, zero pass on live corrected labels). nonlinear_interaction_combiner (non-linear combiner)
now replicated at all three tfs (todo 234 CLOSED 2026-08-03 -- root-caused via
`superpowers:systematic-debugging`, the wide-DataFrame fetch pattern itself was the OOM defect,
not any single operation on it; fixed by building the training matrix directly from asyncpg rows,
matching `ensemble_trainer.py`'s existing pattern): **substantial at 1h and 15m** (the directly
actionable tf, cross-sectional-neutral `point_ic` 0.18-0.25), **small specifically at 1d**
(`point_ic`=0.0127, 1d's own `ctf_momentum` baseline separately known-degenerate, todo 189). Five
new Signal-Extraction candidates (`cointegrated_pairs_residual`, `statistical_factor_residual`,
`cross_asset_lead_lag`, `adaptive_combiner_weights`, `jump_diffusion_decomposition`) added the
same session, none tested yet. Full detail on
all theses: `docs/research/data-edge-source-thesis.md` (v1.8).
Phase 144/143.1/162/163/164/165/167 are all COMPLETE -- see Phase Summary table below, not
duplicated here.

**Current saga (2026-08-03, latest): a `ctf_momentum` mechanics question surfaced a live/batch
divergence, whose review chain surfaced a more serious, still-unmeasured integrity question
directly touching Phase 167's proof.** Todo 241 (live serving used a crude same-bar intrabar-
return proxy for `ctf_momentum` where batch used a causal Wilder RSI -- two different statistics
sharing one column name) is FIXED and committed (`8b2cf690`). Its own review chain (`/simplify`
+ an independent code-reviewer subagent) surfaced three more: **todo 243 (P0, NOT yet fixed)** --
batch's LTF-to-HTF join selects the still-forming HTF bar, not the last completed one, real
lookahead up to 55min (5m/15m) or a full day (1h) in every published `ctf_momentum` IC number at
those tfs -- and `cross_sectional_spread_tracker.py` ranks directly on `ctf_momentum`, Phase
167's sole ranking signal and **the first and only construction to pass both live Validation
Gates**. Mechanism confirmed mechanically; magnitude NOT yet measured. Per explicit user
direction: measure the impact (read-only, scoped sample) before touching the join or triggering
any corpus recompute -- this is now the single highest-value open question in the tree, ahead of
any feature-expansion or new-construction work, because it bears on whether Phase 167's already-
"proven" result needs re-litigating. Todo 242 (P3, `_CTF_HIGHER_TF` not APR-governed) and todo
244 (P3, `ctf_vwap_align`/`ctf_regime_align` never computed live -- both already-rejected
features, zero blast radius) are real but low-urgency siblings, not blocking.

Separately, the same session's rigor review of `docs/research/data-edge-source-thesis.md` found
nonlinear_interaction_combiner's own pre-registered falsification bar had never actually been
tested (compared only to `ctf_momentum` alone, not "the existing linear ensemble" the bar names)
and its walk-forward embargo was measured in pooled-panel rows, not bars (todos 240/239). **Both
FIXED and committed** (`816032e2`): a new fold-local linear-ensemble comparison arm (reusing
`ensemble_trainer.py`'s own weighting primitives) plus a corrected bar-to-row fold mapping, with
a paired-bootstrap PRIMARY VERDICT replacing the prior single-baseline comparison. An independent
review caught and fixed 2 more issues in the same pass (unstandardized features dominating
weights by raw scale, not IC; a memory footprint too close to this module's prior OOM history).
**Still open: the actual 1h/1d/15m/5m re-run under the corrected methodology** -- multi-hour,
DB-heavy, deliberately not started without checking host contention first (another session was
concurrently committing throughout this work).

Also this session: todo 172's item 2 (frame_gate_passes cluster-mean non-determinism) FIXED;
item 1 (broader path-dependent-statistics sweep) remains open, unscoped. Todo 218 (BIL thin-cell
IC instability) root-caused via direct peer comparison (SHY/IEF) and closed -- deliberately not
fixed, folded as corroborating evidence into todo 099 whenever that gets real design attention.
Todo 157 (base-class compliance mechanical check) fully closed. Full detail, all cross-refs:
`.planning/todos/PRIORITIES.md`'s 2026-08-03 status-sync entry.

**2026-07-30 thread (compressed 2026-08-03 -- reconciliation/merge detail dropped, git log has
it):** the per-tf-active-scale-set fix (migration 271) and todo 208's same-ET-session gate fix
(`complete_{scale}` now means "the forward bar exists" at every tf; migration 272;
`forward_returns` rebuilt clean) both landed, triggering the corpus pipeline relaunch whose
outcome is recorded authoritatively in Tier -1 below -- not restated here. `_SCALES`-hardcoding
cleanup: todos 209/210/211/212 CLOSED; todo 214 (the duplicated-compute-logic root cause) still
open, deliberately deferred until this chain is stable through a full cycle. Todo 146's per-tf
lookahead grid (migration 269): session-boundedness premise resolved, actual VALUES still open
pending `ops_lookahead_horizon_response.py` characterization + real measurement -- design doc:
`docs/research/2026-07-30-forward-return-horizon-grid-refactor.md`. Todo 203 (canary RNG
pseudo-replication) fixed; todo 204 status is in Tier -1 below (don't restate here).

**Next actions, priority order:**

*Tier 0.5 -- outranks Tier 1: read-only measurement, not a build.* `ctf_momentum` batch-join
lookahead bias (todos 243/245). **1h diagnostic COMPLETE 2026-08-03** (`nonlinear_interaction_combiner_ctf_leak_diagnostic_1h.py`,
full result in todo 245): tree's cross-sectional-neutral point_ic **collapsed 90.6% (0.1811 ->
0.0171)** once the three contaminated CTF columns were excluded -- confirms the published
"substantial at 1h" finding was overwhelmingly leak-driven, not genuine non-linear structure. A
small, real, statistically significant tree-vs-linear edge DOES survive (diff=0.0106,
ci_lower=0.0064) -- ~15x smaller than published, not a total null. **Next: same with/without-CTF
diagnostic at 15m and 5m (also leak-affected, NOT yet tested; 1h result doesn't auto-generalize)
-- 15m is ~4x 1h's row count (~8.8M vs ~2.2M), expect a longer run. Todo 243's actual join bug is
still unfixed regardless of these diagnostic results.**

*Tier 1 -- decision point, REDIRECTED 2026-07-27 by explicit user instruction:* Phase 156-159
(execution/sizing) is NOT the priority even though its precondition is cleared. User wants the
features/regimes/IC/ensemble signal-generation stack validated first ("real proven signals")
before any execution-layer investment. Do not resume Phase 156-159 scoping without the user
re-raising it.

*Tier 2 -- serves the redirected priority:* todo 234 CLOSED 2026-08-03 -- nonlinear_interaction_combiner's 15m result
substantial at the tf that's actually tradeable, **but see Tier 0.5/Current Saga: that read needs
re-confirming once the CTF-leak diagnostic lands (1d re-run is safe now, 1h/15m/5m wait).** todo
235 (cross_sectional_relative_value-at-5m, never comparatively tested against 15m for this
construction); the open `alpha_ensemble_ic`/`alpha_events` question (is the linear-only combiner
adequate -- confirmed `ensemble_trainer.py`'s `resolve_stratum_weights` is linear combination
only; `alpha_events` confirmed sparse/emission-gated, not a dense ranking input; not yet
investigated further). Phase 151 is the next-tier option if these don't pan out.

*Tier 2b -- concretely staged, waiting on Tier -1's pipeline to exit:* todo 167 (equity
cross-sectional-vs-symbol-HMM stratification falsifier, never tested unlike rates'). Migration
262 applied (`dual_write_symbol_hmm=true` for equity), falsifier gate script written and
verified (`scripts/analysis/equity_regime_separation_gate.py`, generalized from Phase 144's D-05
gate). **The in-flight `ic_engine` run (Tier -1) is a full, unscoped pass -- check whether it
already covers the 49 equity symbols this todo needs before assuming a second scoped run is
still required once it completes.**

*Tier 3 -- ready now, independent of the pipeline:* todo 009 Parts B/C (Parts A/D closed
2026-07-31 -- promote 4 scripts to `BaseBatch`+systemd, naming-vocab doc update, still open).
Todos 172/173 (non-blocking Phase 148 findings) also live here, lower urgency.

*Tier 4 -- deprioritized, do not resume without re-reading why:* Phase 151 (Feature Primitives
Expansion, planned and ready but not the next priority -- see Guiding lens above), Phase 145
(StratificationDimension Formalization, unblocked but not planned), todo 175 (structural
candidate Part 2 -- exists only to serve an overridden plan, see todo 179).

*Tier 0 -- CLOSED 2026-07-29:* the combined `backfill_feature_factory.py --compute-only
--refresh` pass landed Phase 164/165's 77 new columns and Phase 163's deferred VP/SR historical
backfill (todo 176). Its regime-wipe side effect (todo 205) and the resulting repair pipeline
are ALSO fully closed as of 2026-07-30 -- not the pipeline currently running (see Tier -1).

*Tier -1 -- HALTED 2026-08-02, supersedes every tier below until it clears:* the corpus
pipeline relaunched 2026-07-30 from step 3 (`forward_return_writer`) reached `ic_engine`
(step 5/8) run_complete at **2026-08-02 19:19:25 UTC** -- 81/81 symbols, 2,924,007
`feature_ic_scores` rows, zero error-level log lines, FDR backfill already complete
(`passes_fdr` non-NULL on every row), elapsed ~70.2h. Clean on its own terms. **But the
wrapper script's next gate, `ops_canary_integrity_assert.py`, FATAL-halted the pipeline
before steps 6-8 (`ic_shrinkage`/`ensemble_trainer`/`alpha_publisher`) ran.** Two findings
from that gate, both filed: **todo 204 CLOSED** (positive control `canary_acausal_placebo`
now clears correctly, 231/239 cells -- confirms the gate itself works and the prior failure
was a stale-vintage artifact) and **new todo 230** (3 negative-control canaries falsely
cleared the gate, 8/717 cell-tests ≈1.1% -- below this project's own documented ~5% naive-CI
noise baseline, root cause not diagnosed: could be the gate needing a Binomial-tolerance
check instead of zero-tolerance, or a real artifact -- do not guess-fix). **Steps 6-8 do not
run until 230 is resolved or the gate is deliberately overridden (user's call).**

**Parallel to this run, 2026-08-02 (pure code/docs, no corpus dependency):** todo 216 (BLAS
thread oversubscription across all 5 `ProcessPoolExecutor` batch services) CLOSED, migration
281 -- not yet confirmed at production scale, self-confirms on the next full pipeline run since
it landed after this run's `regime_writer` step. Reviewing that fix surfaced todo 229 (a
separate, deeper bug: hmmlearn's `monitor_.converged` is unconditionally `True` post-fit,
making `regime_writer.py`'s same-seed convergence retry structurally unreachable since it
shipped) -- design proven, implementation deferred pending this run's own convergence-iteration
log data. Todo 005 (regime-label transition IC contamination) got a measurement-first design
doc after an Opus review + rewrite corrected its own motivating statistic (measured on the
wrong population initially). See `docs/research/intelligence-lifecycle-backlog-matrix.md`'s
Operational Context section for full detail on both threads, not duplicated here.

A same-day partial-data check (safe, read-only, ran alongside the live pipeline) found
`ctf_momentum` at 15m holding up on the first 21 symbols computed under the corrected corpus:
872 cells, 91.4% positive sign, 63% passing the bootstrap CI gate, mean IC 0.0527, mean IC
Sharpe 0.4389, BIL (T-bill ETF, near-zero movement) the one sensible outlier. **Early
reinforcement of Phase 167/cross_sectional_relative_value's already-proven result, not new evidence** -- `bh_adjusted_p` is
NULL for all rows so far (FDR correction is a corpus-wide pass that only runs once at the very
end), so this is a legitimate partial read of real per-cell stats, not a final verdict. **This
15m read is exactly the number todo 243 (Tier 0.5) puts in question** -- the `ctf_momentum`
values behind it came from the batch join now confirmed to select the still-forming HTF bar at
15m, so this "reinforcement" needs re-reading once 243's magnitude measurement lands.

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
| 167 | Cross-Sectional Trade Construction (cross_sectional_relative_value) | COMPLETE (6/6 plans, 2026-07-27) -- both live Validation Gates PASSED (gate1_passes=true, gate2_passes_overall=true); Phase 156-159's stated precondition is now met. See Current Focus. |
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

- Phase 169 (Symbol State Query Layer): added 2026-07-31. Scoped through extensive same-session
  design work (rejected a predictive composite score, an independent Opus review that corrected
  several factual errors along the way, a descriptive-vs-predictive correction, and a locked
  `-1`/`+1` gradient encoding -- one number for magnitude strata like volatility, a
  direction+conviction pair for directional strata like structure). Not yet planned -- design doc
  only: `docs/research/intel-symbol-state-query-layer.md`. Independent of Phase 168 (reads
  `feature_vectors`/`market_regimes`, not `construction_spreads`).

- Phase 168 (Cost-Hurdle-Adjusted Spread Construction, cross_sectional_relative_value Follow-On): added 2026-07-31 as a
  parallel track while the in-flight `ic_engine` recompute runs (zero compute contention --
  pure scoping/discussion work). Follow-on to Phase 167's cross-sectional long-short
  construction (both live Validation Gates PASSED); applies todo 030's cost-hurdle sweep as a
  construction-layer change (which symbols/legs survive transaction costs), no new features.
  See `docs/research/trade-construction-layer.md`.

- Phase 151 (Feature Primitives Expansion + Interaction Layer): planned 2026-07-24, cross-AI reviewed and revised same day (Codex found 3 HIGH-severity findings, all fixed as real plan changes). 9 plans, execution-ready. Deprioritized 2026-07-26 behind Phase 167 (see Guiding lens above) -- stays planned and ready, not the next priority.

(Entries for Phases 162/163/164/165/166/167 removed 2026-08-03 -- all COMPLETE, already fully
described in the Phase Summary table above; this section is for phases with no table row yet.)

## Session

**Last GSD-phase-level session:** 2026-07-31T12:00:00.000Z. **Stopped at:** Phase 168 planned --
5 plans in 4 waves, plan-checker passed, reviewed by Codex + Agy/Antigravity, 9 findings
incorporated. Ready to execute: `/gsd:execute-phase 168`. (Phase 165's own execution detail --
wave-by-wave commits, mutation-verification catches -- is fully resolved and git-log-recoverable;
trimmed here 2026-08-03. See the Phase Summary table above for what it shipped.)
