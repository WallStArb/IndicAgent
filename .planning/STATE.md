---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: AlphaEngine Validation + Alpha Scoring
status: ready_to_execute
stopped_at: "Tier 0's --refresh recompute ran (2026-07-29), landed Phase 164/165's 77 columns, but wiped feature_vectors.regime via an upsert bug (todo 205, root-caused + fixed same day). Repair pipeline (regime_writer -> forward_return_writer -> cross_sectional_regime_model -> ic_engine) relaunched 2026-07-30 06:22 UTC, regime_writer still running as of last check (~65% of 36.8M rows repaired, up from ~45% earlier). Do not start new corpus-write work until it completes -- see todo 202."
last_updated: "2026-07-30T14:00:00.000Z"
progress:
  total_phases: 12
  completed_phases: 11
  total_plans: 51
  completed_plans: 51
  percent: 100
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

**Active saga (2026-07-29/30): Tier 0's recompute landed, then broke regime labels, now
mid-repair.** The combined Phase 164+165 `--refresh` pass (Tier 0, below) finally ran
2026-07-29, landing both phases' 77 new columns -- but its own upsert clobbered
`feature_vectors.regime` across all 36.8M rows (a generic `DO UPDATE SET` included columns
`regime_writer.py` owns, not the `--refresh` caller). Root-caused and fixed same day as
[todo 205](.planning/todos/completed/205-refresh-upsert-clobbers-regime-writer-owned-columns.md)
(`feature_vector_persistence.py` + regression test) -- this only prevents recurrence on the
*next* `--refresh`, the wipe itself still needed repairing. Repair pipeline (`regime_writer` ->
`forward_return_writer` -> `cross_sectional_regime_model` -> `ic_engine`) relaunched 2026-07-30
06:22 UTC; **regime_writer still running as of last check (~65% of 36.8M rows repaired, live
verify via `ps aux | grep regime_writer` +
`SELECT count(*) FROM feature_vectors WHERE regime IS NOT NULL`). Do not start new
corpus-write work (ic_engine runs, regime sweeps, ensemble retrains) until this completes.**
[Todo 202](.planning/todos/completed/202-per-tf-lookahead-grid-downstream-consumers-stale.md)
**CLOSED 2026-07-30 -- correcting an error this file itself carried for part of today's
session:** all of 202's items (the CRITICAL `forward_returns` truncate+rebuild, verified via
`computed_at` clustering in a single 2026-07-30 01:10-01:54 UTC window across all 4 tfs, AND
all 7 downstream script fixes) were actually already done -- landed 2026-07-29 20:16-20:37 EDT,
correctly sequenced before the rebuild, each with its own passing tests. The todo file simply
never got updated, which is why it read as open through two separate checks (this session's
initial "not done, confirmed via git log" claim -- that check's window was too narrow, only
looking at commits since the `dd49c36e` audit rather than the todo's full history -- and the
`dd49c36e` audit itself). Don't re-litigate 202; it's genuinely closed. One caveat carries
forward: the rebuild ran under the still-session-gated logic 208 disputes, so it may need a
second rebuild if 208's Step 2 lands.

**Same week, a cluster of measurement-integrity bugs surfaced and were mostly fixed:**
[todo 146](.planning/todos/pending/146-lookahead-grid-per-tf-recalibration.md)'s per-tf IC
lookahead grid **shipped to production APR** (migration 269, 2026-07-29) but is **provisional
for 5m/15m/1h** -- [todo 208](.planning/todos/pending/208-intraday-same-session-forward-return-gate-inconsistent-with-trade-construction.md)
(filed 2026-07-30) found live 1h `mid` completeness only 53.5% and disputes the
session-boundedness premise the grid was derived under; don't treat 146 as final for those 3 tfs
until 208's empirical check runs (blocked behind the regime repair above). Canary negative
controls were silently pseudo-replicated cross-sectionally (same RNG seed at a given timestamp
regardless of symbol) -- per-symbol seeding fix shipped
[todo 203](.planning/todos/pending/203-canary-rng-seed-not-per-symbol-cross-sectional-pseudo-replication.md);
a broadcast-feature audit confirmed the same exposure applies to `vix_z`/`yield_slope_z`/
`flight_quality`/session-calendar features (a real broadcast-aware significance test remains
open, not yet its own todo). A sibling anomaly, `canary_acausal_placebo` not clearing its POOLED
gate, is still undiagnosed -- [todo 204](.planning/todos/pending/204-canary-acausal-placebo-pooled-not-detected.md).
The dead K=3 HMM compute path (superseded by K=5 years ago but never deleted) is now actually
deleted, closing [todo 207](.planning/todos/completed/207-hmm-column-name-collision-k3-k5.md) and
[todo 197](.planning/todos/completed/197-hmm-forward-filter-window-reset-every-refresh.md).

**Concurrent, uncommitted work in progress (separate worktree, not yet merged):**
`.claude/worktrees/per-tf-active-scale-set` (branch `worktree-per-tf-active-scale-set`) is
implementing `docs/plans/2026-07-30-per-tf-active-scale-set.md` -- `canonicalize_active_scales`
+ per-tf active-scale fallback table for `ic_engine.py`, one commit in
(`b7ae5400`) plus uncommitted edits to `ic_engine.py` and 5 test files. Don't assume this is
stale/abandoned; check `git -C .claude/worktrees/per-tf-active-scale-set status` before touching
it.

**Todo backlog reprioritized/audited against live ground truth 2026-07-30** (commit `dd49c36e`)
-- `.planning/todos/PRIORITIES.md` is current as of that pass; don't re-derive priority from
older snapshots in this file or ROADMAP.md.

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

*Tier 2b -- concretely staged, now folded into todo 176's queued sequence, waiting on Tier -1's
pipeline to exit:* todo 167 (equity cross-sectional-vs-symbol-HMM stratification falsifier,
never tested unlike rates'). Migration 262 applied (`dual_write_symbol_hmm=true` for equity),
falsifier gate script written and verified (`scripts/analysis/equity_regime_separation_gate.py`,
generalized from Phase 144's D-05 gate). Next action: once the Tier -1 pipeline exits, run a
scoped `ic_engine.py --symbols <49 equity symbols>` pass (single-writer discipline), then re-run
the gate for the real verdict.

*Tier 3 -- ready now, independent of the above:* **corrected 2026-07-30 -- todos 182, 088, 170,
and 129 (all previously listed here) are already CLOSED, confirmed live in `completed/`; this
line was stale.** What's actually still open and pipeline-independent: **todo 202's Items 2-4**
(7-script tf-scoping fix, pure code, no live-corpus dependency -- see "Active saga" above; a
live-verified window exists to land this before the Tier -1 pipeline's `ic_engine` step starts)
· todos 172/173 (non-blocking Phase 148 findings) · todo 009 Parts A-D.

*Tier 4 -- deprioritized, do not resume without re-reading why:* Phase 151 (Feature Primitives
Expansion, planned and ready but not the next priority -- see Guiding lens above), Phase 145
(StratificationDimension Formalization, unblocked but not planned), todo 175 (structural
candidate Part 2 -- exists only to serve an overridden plan, see todo 179).

*Tier 0 -- CLOSED 2026-07-29, but its side effect is now Tier -1 (see below):* the combined
`backfill_feature_factory.py --compute-only --refresh` pass ran 2026-07-29, landing Phase
164/165's 77 new columns and Phase 163's deferred VP/SR historical backfill (todo 176). It also
wiped `feature_vectors.regime` (todo 205, fixed same day). No longer an open action item itself.

*Tier -1 -- ACTIVE, supersedes every tier below until it clears:* the regime-repair pipeline
(`regime_writer` -> `forward_return_writer` -> `cross_sectional_regime_model` -> `ic_engine`)
relaunched 2026-07-30 06:22 UTC is still running -- see "Active saga" above. Nothing that reads
`feature_vectors.regime`, `feature_ic_scores`, or `ensemble_weights` should start until it
completes. Re-verify before trusting this: `ps aux | grep -E
"regime_writer|forward_return_writer|cross_sectional_regime_model|ic_engine"`.

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

**Last session:** 2026-07-28T12:00:00.000Z

**Stopped at:** Phase 165 COMPLETE (5/5 plans). Plan 05 (session levels derivation +
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
