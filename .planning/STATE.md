---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: AlphaEngine Validation + Alpha Scoring
status: ready_to_execute
stopped_at: "Phase 165 IN PROGRESS (1/5 plans) -- Plan 01 (data contract: migration 267, 41 new swing/fib/trend/session FeatureVector fields + registry rows + 17 APR keys) executed, ready for Plan 02 (swing detection + trend structure)"
last_updated: "2026-07-28T07:39:43.789Z"
progress:
  total_phases: 12
  completed_phases: 10
  total_plans: 51
  completed_plans: 47
  percent: 92
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

**Current focus (updated 2026-07-26):** Milestone v3.1's defining verdict stands: Phase 148
found Gate 1 (signal proof) PASS but Gate 2 (execution proof) FAIL -- do not promote the
existing per-symbol directional construction to live capital. Phase 166's frame/execution
recalibration couldn't fix it; todo 179's investigation found why -- `mid_bull`'s raw
un-barriered forward return is negative at every horizon, a genuine market-data finding no
stop/target/hold tuning can fix.

**That closed the fork to three options: more features (Phase 151/164/165), a different
construction/model over the *existing* features (Edge Source Thesis T2/T3/T5), or accept no
edge on this branch. Resolved 2026-07-26: T3 (cross-sectional long-short decile spread) passed
decisively** at both lookahead scales, clearing a shuffled-ranking-null guard —
`scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py`. First thesis in the
whole tree to clear its own bar. **Registered as Phase 167 (Cross-Sectional Trade
Construction)** -- sequenced ahead of Phase 156-159 (would produce the signal those size/execute)
and ahead of Phase 151/164/165 (proven and cheap beats unproven and expensive).

**Phase 167 is now COMPLETE (2026-07-27, 6/6 plans).** `services/cross_sectional_spread_tracker.py`
productionized T3's script, applied the todo 030 cost-hurdle sweep, backfilled the full
2006-2026 corpus into `construction_spreads` (24,924 bars), and ran both live Validation Gates
against the real OOS population: Gate 1 (shadow spread Sharpe) `gate1_passes=true`, Gate 2
(attribution honesty) `gate2_passes_overall=true`. **Both PASSED** -- unlike Phase 148's
per-symbol directional construction, which passed Gate 1 but failed Gate 2. Per
`docs/research/trade-construction-layer.md`'s Sequencing section, this means the Phase 156-159
execution/sizing chain's stated precondition (a proven, attribution-honest signal) is now met
for this construction. Full verdict detail, the binding pass rule, and the retrospective-caveat
text: `docs/research/trade-construction-layer.md`'s Validation Gates section, transcribed from
`logs/construction_verdicts/gate1_20260727T112626Z.json`/`gate2_20260727T112642Z.json`. **The
decision whether and how to proceed toward Phase 156-159 with this construction as the signal
source is the user's** -- not made by this phase.

T5 (non-linear combiner) cleared its canary-leakage check 2026-07-26 (todo 184, CLOSED) -- the
0.30 OOS IC (~3x anything else measured) is NOT explained by look-ahead leakage (all 4 negative
controls clean by standalone IC; the positive control's presence doesn't move aggregate IC,
Δ=+0.0007). **Independent replication at equity/1d ran 2026-07-27
(`scripts/analysis/t5_nonlinear_combiner_replication_1d.py`): PARTIAL replication, NOT the same
finding.** Tree combiner clears its own bootstrap CI in the cross-sectional-neutral rigor pass
(`point_ic`=0.0164, `ci_lower`=0.0081) -- real, not dead -- but the magnitude collapsed ~16x
from the original 1h result (0.258 -> 0.0164). **Revised read: T5 is confirmed SMALL, not
confirmed LARGE.** Separately surfaced: `ctf_momentum` shows NEGATIVE mean IC at 1d
(`point_ic`=-0.0244, does not clear zero), the opposite of its validated positive 15m behavior
that Phase 167's live gates both passed on. **Resolved 2026-07-27 (todo 189): this is a
measurement artifact, not real timeframe instability** -- `_CTF_HIGHER_TF` maps `1d -> 1d`
(self-referential, no timeframe above 1d exists in the corpus), so `ctf_momentum` silently
degenerates from a genuine cross-timeframe RSI at every other tf into a plain same-tf RSI
oscillator at 1d -- a classic mean-reversion signal, comparing two different features under one
name. The 15m feature Phase 167 trades is unaffected. Doc corrected in
`docs/research/data-edge-source-thesis.md`'s T5 section. Also added a genuine methodological fix during this replication: BH-FDR
correction (sign-gated) across the ~80 per-symbol tests, which neither the original 1h script
nor its leak-check ever applied despite the research doc's own stated bar requiring it. 15m
replication (the tf Phase 167's live construction actually trades on, directly actionable)
deliberately deferred -- ~8.1M rows vs 1d's ~330K, unsafe to load given concurrent memory
contention from todo 183's `ic_engine` recompute; see
[todo 188](.planning/todos/pending/188-t5-replication-15m-deferred-memory-contention.md).
Full detail: `docs/research/data-edge-source-thesis.md`'s T5 section (v1.4), full per-symbol
table: `docs/analysis/t5-replication-1d-per-symbol.csv`. **T2
(regime-conditional persistence, the thing that motivated testing T3/T5) is CONFIRMED DEAD,
no longer provisional.** Todo 183's corpus recompute completed 2026-07-27T21:55 UTC
(`ic_engine.run_complete`, both `equity`/`rates` groups, zero errors, ~27.6h). Todo 179's sweep
was re-run the same day directly against live `market_regimes.regime_label` (genuinely
corrected, not the offline proxy the 2026-07-24 sweep used) --
`scripts/analysis/live_recalibrated_regime_sweep_check.py`: 270 cells tested, 108 adequately
covered, zero pass. The previously-interesting `high_bear` lead (5/8 passes in the OLD-label
offline sweep) has all 36 of its live cells stuck at 12-13 day-clusters, below the 20-cluster
floor -- genuinely untestable in the current OOS window, not a new negative finding, confirming
what todo 092's offline analysis already suspected. Full detail appended to
`.planning/todos/pending/179-gate166-concurrent-exposure-diagnostic.md`. Doesn't affect T3's own
result, which has no regime dependency.

Phase 144/143.1/162/163 are all COMPLETE -- see Phase Summary table below for detail, not
duplicated here.

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

*Tier 2b -- concretely staged 2026-07-27, waiting only on todo 183's process to exit:* todo 167
(equity cross-sectional-vs-symbol-HMM stratification falsifier, never tested unlike rates').
Migration 262 applied (`dual_write_symbol_hmm=true` for equity), falsifier gate script written
and verified (`scripts/analysis/equity_regime_separation_gate.py`, generalized from Phase 144's
D-05 gate) -- correctly reports BLOCKED (zero `symbol_hmm` rows for the real 49-symbol
equity-routed universe, confirmed via `instrument_tags`, not the naive `asset_class` filter
which returns the wrong symbols entirely). Next action: once todo 183 exits, run a scoped
`ic_engine.py --symbols <49 equity symbols>` pass (single-writer discipline -- do not run
concurrently with 183), then re-run the gate for the real verdict. Bumped P2→P1.

*Tier 3 -- ready now, independent of the above:* todo 182 (15m cross-sectional bootstrap
threads stale) · todo 088 (`hold_max_bars` type safety) · todo 170 (`volatility_pct`
substitution probe for rates) · todo 129 (revived cross-service short-lived-conn helper) ·
todos 172/173 (non-blocking Phase 148 findings) · todo 009 Parts A-D.

*Tier 4 -- deprioritized, do not resume without re-reading why:* Phase 151 (Feature Primitives
Expansion, planned and ready but not the next priority -- see Guiding lens above), Phase 145
(StratificationDimension Formalization, unblocked but not planned), todo 175 (structural
candidate Part 2 -- exists only to serve an overridden plan, see todo 179).

*Tier 0 -- EXPLICIT USER OVERRIDE 2026-07-27, supersedes Tier 4's Phase 164/165 deprioritization
below:* user wants Phase 164 (SMC, already planned, 4 waves ready) and Phase 165 (Swing/Fib/
Trend, not yet planned) built regardless of the evidence-gate reasoning that deprioritized them
-- explicit "build out the features regardless" instruction, not evidence-triggered. Sequencing
decided the same session: **plan Phase 165 (`/gsd-plan-phase 165`) -> execute Phase 164 ->
execute Phase 165 -> ONE combined `backfill_feature_factory.py --compute-only --refresh` pass**
covering the current 20-day staleness gap, Phase 163's VP/SR historical NULLs (todo 176), and
both phases' new columns in a single recompute, not three separate ones. Rationale for the
single-pass batching (not the feature-expansion decision itself, which is the user's call): the
`--refresh` recompute is cheap/unattended background compute; phase execution is expensive/
attended engineering time -- batching avoids paying the ~8h recompute cost twice for 164 and a
third time for 165. Both 164 and 165 edit `feature_factory.py` -- execute sequentially, not
concurrently, to avoid the same file being touched by two waves at once. Todo 197 (HMM
forward-filter perf fix, ~30% of compute cost) is unrelated to this and NOT a prerequisite --
it's a separate, correctness-sensitive change still gated on its own review.

*Tier 5 -- gate status changed 2026-07-27:* Phase 156-159 (Portfolio State/Sizing/Execution/Cost)
was gated on Phase 167 producing a proven signal -- **that gate cleared: Phase 167's both
Validation Gates PASSED.** Whether to actually begin Phase 156-159 is still the user's decision,
not automatic. Phase 149/150/155 (PrecedentEngine, Alt Data) -- v4.0-adjacent, no case made yet.
Phase 147 (I7 due diligence) -- cheap, gates nothing.

Full P2/P3 todo backlog: `.planning/todos/PRIORITIES.md`. Idea-level scoring:
`docs/research/intelligence-lifecycle-backlog-matrix.md`.

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
| 165 | Swing/Fib/Trend/Session Structure Primitives | IN PROGRESS (1/5 plans, started 2026-07-28) -- Plan 01 (data contract) executed: migration 267 adds 41 new feature_vectors columns + registry rows (group_name='session') for swing detection (7), trend structure (6), swing momentum (8), fibonacci zones (4), session levels (16); zero raw price levels or raw bar indices (D-02/D-04). D-01 nullable-field fix: all 41 fields are float \| None with NO default (unlike Phase 164's SMC block, which is defaulted) -- placed immediately before the canary block since dataclass ordering forbids a non-defaulted field after a defaulted one (208->249 total FeatureVector fields). 17 feature.swing.*/feature.trend_structure.*/feature.swing_momentum.*/feature.fib.*/feature.session_levels.* APR keys wired into both live and batch FeatureFactoryConfig sites. Plans 02-04 wire real compute logic in against this fixed contract. |

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
- Phase 165 (Swing/Fib/Trend Structure Primitives): planned 2026-07-27 (5 plans, 5 waves, sequential -- every plan touches `feature_factory.py`). Plan 01 (data contract: migration 267, 41 new columns/registry rows/APR keys) executed 2026-07-28 -- IN PROGRESS, 1/5 plans, see Phase Summary table. Next: Plan 02 (swing detection + trend structure).
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

**Last session:** 2026-07-28T07:39:43.789Z

**Stopped at:** Phase 165 Plan 01 (data contract) executed -- migration 267 adds 41 new
`feature_vectors` columns (swing detection 7, trend structure 6, swing momentum 8, fibonacci
zones 4, session levels 16) + 41 matching `feature_registry` rows (`group_name='session'`) +
17 `feature.swing.*`/`feature.trend_structure.*`/`feature.swing_momentum.*`/`feature.fib.*`/
`feature.session_levels.*` APR keys. All 41 `FeatureVector` fields are `float | None` with NO
default (D-01's nullable-field fix -- the archived plugins' fake-numeric placeholders like
`trend_direction=0.0`/`price_position=0.5` are the exact todo-153 failure mode), placed
immediately before the defaulted canary block (opposite placement from Phase 164's SMC block,
which is defaulted and placed after canary) -- Python dataclass ordering forces this since a
non-defaulted field cannot follow a defaulted one. Threaded through `_build_feature_vector`,
both `compute()`/`compute_batch()` call sites, and `_cold_start_vector` as `None` placeholders.
`_SWING_FIB_TREND_FIELD_NAMES` persistence slice wired through the INSERT column list,
placeholder generator, `_TOTAL_COLUMNS`, and params tuple (217->258 total columns). Every
hardcoded field/param count assertion bumped by 41 across 6 test files. Full `tests/unit/`
suite green (0 failures), ruff/black clean, ic_engine drift gate verified live against the DB.
Next: Plan 02 (swing detection + trend structure).

**This session's arc:** Read the plan, PROJECT.md, STATE.md, CLAUDE.md, 165-RESEARCH.md,
165-PATTERNS.md, and 164-01-SUMMARY.md (closest analog). Verified migration number 267 was
free (`ls production/migrations/ | sort -V | tail -5`, 266 was the prior max, no renumbering
collision this time). Wrote migration 267 in one continuous pass (all 3 sections), applied and
verified against the live DB, then split the file back into a sections-1-2-only version for
Task 1's commit (verified idempotent re-apply) before restoring the full file for Task 2. Wired
the 17 APR keys into `FeatureFactoryConfig` and both config-build entrypoints. Added the 41
`FeatureVector` fields, `FEATURE_VECTOR_DOMAIN` entries, `_build_feature_vector`/`_cold_start_vector`
threading, and the persistence slice; fixed two pre-existing stale column-count comments in
`feature_vector_persistence.py` left un-updated by Phase 164 (said "181" when the live count was
already 217) while editing the same lines. Fixed 6 test files' blast radius (3 direct
`FeatureVector(...)` constructions needed the 41 new required kwargs; 6 hardcoded count
assertions bumped by 41; added a new `gap_filled`-at-index-257 last-element test while keeping
`sr_level_count`/`manip_strength`'s boundary-pinning tests intact). Full suite green on first
attempt after the blast-radius fixes. `gsd-sdk query roadmap.update-plan-progress 165` corrupted
a sentence in ROADMAP.md's Phase 165 section (replaced "5 plans, 5 waves (sequential..." with an
orphaned "1/5 plans executed" mid-paragraph) and separately decremented STATE.md's frontmatter
(`completed_phases` 10->9, `total_plans` 46->45, `completed_plans` 46->44, `stopped_at`
truncated mid-sentence) -- same known frontmatter-resync friction MEMORY.md's
`feedback_gsd_state_frontmatter_resync` note describes, now also observed corrupting ROADMAP.md
body text, not just STATE.md frontmatter. Both corrected manually in this edit.
