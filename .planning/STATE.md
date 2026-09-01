---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: AlphaEngine Validation + Alpha Scoring
status: milestone_complete
last_updated: "2026-08-28T23:44:19.471Z"
progress:
  total_phases: 14
  completed_phases: 9
  total_plans: 45
  completed_plans: 44
  percent: 64
---

# Project State

## Strategic Plan (read this first)

**Resolved 2026-08-07: Phase 167's cross-sectional construction (`cross_sectional_relative_value`)
does NOT survive re-measurement under the corrected `ctf_momentum` join. Both Validation Gates
FAIL at authoritative tier, real production path, OOS window (3,803 bars / 147 day-clusters).**
Gate 1: `ci_lower` doesn't clear zero at either scale, `null_p` 0.65-0.99 (observed spread beaten
by up to 98.6% of random-ranking draws). Gate 2: no residual survives at 95% CI after removing
the static-tilt benchmark. This retracts Phase 167's original "COMPLETE, both gates PASSED"
verdict and `nonlinear_interaction_combiner`'s original "substantial edge" claim — the small
residual `nonlinear_interaction_combiner` still shows is a separate, already-tracked thread
(`docs/research/measurement-nonlinear-interaction-combiner.md`), not resurrected by this result.
Full numbers: `logs/construction_verdicts/gate1_latest.json` / `gate2_latest.json`.

**Fork resolution (decided in advance, not re-litigated): back to discovery, not construction.**
Phase 168 (cost-hurdle spread refinement) and Phase 156-159 (execution/sizing) stay blocked —
not "unverified," actually FAILED; do not start either without an independently-proven
construction first. Priority is the untested Signal-Extraction candidates below.
**Expectation to hold, not a consolation-prize framing:** every "large" edge found in this corpus
has collapsed 44-91% once a leak was corrected, with a small real residual surviving each time —
consistent with Renaissance's own actual history. The win condition is a confirmed small edge
with a clean gate record, not a big trade.

**Discovery track: 5/5 candidates run to a definitive verdict now DEAD, closed 2026-09-01.**
4 cheap Signal-Extraction candidates (`jump_diffusion_decomposition`, `cointegrated_pairs_
residual`, 2 Trade Construction theses) came back DEAD earlier —
`project_discovery_track_pilot_results_2026_08_07` memory. **`statistical_factor_residual`**
(the harder, K-selection-gated candidate picked next) also now DEAD: Stage 3 (IC
falsification vs. `ctf_momentum`, 3 measurement axes, run 2026-09-01) found residualizing
away the top-K statistical factors did not improve IC on any axis — if anything pulled it
toward zero. Full detail: `docs/research/measurement-statistical-factor-residual.md`. Per
that memory's own standing instruction, this is the point to surface the pattern before
starting a 6th candidate, not mechanically continue down the list. Two more per-symbol
regime candidates (todo 303 trend, todo 304 percentile-rank) passed Stage-1 mechanism
validation the same window and remain open, unaffected by this closure — `todo 364` (N1
fresh re-run) also still open.

**Live ingestion gap found closing this thread, filed as todo 366 (P2), explicitly NOT
urgent per user direction 2026-09-01:** the corpus has decades of history and no proven edge
yet to protect, so live-ingestion freshness doesn't gate research value — corrects the
"RESOLVED 2026-08-31" framing in `project_ibkr_live_ingestion_stalled_2fa` memory (the
gateway libgtk3 fix was real, but the 5 consumer services that write bars were never
restarted; most of the universe has had zero new bars since 2026-08-12). A backfill to
bring OHLCV current is optional/later, not blocking. Todo 366 itself was routed around, not
fixed, for Stage 3: `_fetch_universe`'s "zero tolerance for any gap date" rule was tripping
on the resulting gap dates, fixed by excluding those specific dates (not interpolating) —
see the research doc's Stage 3 section for the corrected universe/K.

**HMM per-symbol lookahead bug (todo 248): fix built + TDD-tested, NOT deployed.**
`regime_writer.py`'s `_compute_symbol_tf` fits `GaussianHMM` parameters once on the entire
(symbol, tf) history before causally decoding — a real causal-law violation, confirmed large at
3 symbol/tfs (24.9-56.8% label agreement vs. an expanding-window-refit baseline, vs. 20-22%
chance). The walk-forward fix (`_walk_forward_hmm_labels`/`_seed_prior_from_label`/
`_hmm_seed_stability_check`) is built and tested but not wired into the live path. **User
directive: deploy regardless of Gate 4's own negative ordinal-IC result** — this is a confirmed
causal-law violation in an existing mechanism, not a new/unproven signal subject to "prove before
promoting." Blast radius matches an `HMM_RANDOM_STATE` change (full regime + downstream `ic_engine`
recompute); was queued behind the CTF-leak work, which has since cleared — re-evaluate scoping
this as its own phase via `/gsd-discuss-phase`. Full detail: `.planning/todos/pending/
248-hmm-full-history-fit-regime-label-instability-gate4-pilot.md`,
`docs/analysis/hmm-parameter-lookahead-pilot-spy-1h.md`.

**Corpus pipeline: the post-Phase-173 recompute (all 8 steps) COMPLETE as of 2026-08-31 —
see [Corpus pipeline state](project_corpus_pipeline_state.md) for full detail, not
duplicated here.** All three discovery-track threads above were blocked on this recompute
finishing; re-verify each one's specific prerequisite directly before assuming unblocked
rather than inferring it from the pipeline's completion alone.

**Priority ordering for the rest of the backlog: `.planning/todos/PRIORITIES.md` is the sole
authoritative source, not duplicated here.** A tiered-priority snapshot pasted into this file
went stale every single time it was tried (confirmed repeatedly through 2026-08-08) — don't
recreate that pattern. Idea-level scoring: `docs/research/intelligence-lifecycle-backlog-matrix.md`.

**Current focus: Phase 173 (broadcast-feature-significance-correction) SHIPPED COMPLETE
(2026-08-26), full corpus recompute COMPLETE (2026-08-31 12:16 UTC).** 4 plans/3 waves
executed, merged, live-smoke-tested, independently re-reviewed (codex+agy, no blocking
findings), `/simplify` pass done. The full corpus recompute Phase 173's own fingerprint
change required (`ops_corpus_pipeline_run.sh --from-step 4`, launched 2026-08-27) ran all 8
steps end to end — `alpha_events` now carries Phase-173-corrected numbers for all 38
broadcast features, including `hyg_lqd_ret_z`/`tip_tlt_ret_z`. A real self-deadlock bug in
`alpha_publisher.py` (todo 351) was found and fixed along the way. Full detail:
`project_phase173_broadcast_significance_complete` and `project_corpus_pipeline_state`
memories. Exit-cluster todos 227/285/287/335/351/306 all individually verified and closed
2026-08-31; 292 was NOT touched by this recompute (started at step 4, not `regime_writer`)
and remains open.
Separately that session: the `ic_engine --cross-sectional-only` run completed 2026-08-25
(144,232 rows, covers the corrected commodity/fx labels from todo 335); N1
(`nonlinear_interaction_combiner`'s residual-form test) ran and came back genuinely
inconclusive (result flips sign of significance between adjacent parameter choices at 1h) —
don't cite as pass or fail either way, see
`project_n1_nonlinear_combiner_and_feature_phase_audit_2026_08_25` memory.

**Checked 2026-09-01: neither the Phase 173 recompute nor todo 335's fix reopens any
previously DEAD/inconclusive discovery-track verdict.** Verified in code, not assumed: the 4
DEAD discovery pilots and T2 (`regime_conditional_persistence`) have zero dependency on any
broadcast column or `regime_group`; Phase 167's construction trains on `ctf_momentum` alone
(already re-verified post-fix); N1 trains on ~248 columns including the broadcast set but
never touches `ic_engine.py`'s significance test (the only thing Phase 173 changed) and is
equity-only (todo-335-irrelevant). N1's own "inconclusive" verdict is still worth a fresh
re-run given ~3 weeks of real corpus churn since it ran — filed as todo 364, not a blanket
re-run-everything pass. Phase 151's Waves 6-7 (interaction IC sweep, paused behind this same
corpus pipeline) are also now unblocked — see ROADMAP.md's Phase 151 entry.

**Phase 148's Gate 1 (signal proof) PASS but Gate 2 (execution proof) FAIL** — do not promote the per-symbol directional
construction to live capital. A refinement plan using Phase 163-165's features has its 3 gating
items resolved: [276](../todos/completed/276-phase163-165-lookahead-causal-safety-audit.md)
lookahead/causal-safety audit CLEAN; [277](../todos/completed/277-alpha-score-concentration-cofiring-degeneracy-diagnosis.md)
`alpha_score` is substantially a disguised common cross-sectional factor, not real per-symbol
breadth (100% same-direction at 15m/1h/1d), though the demeaned residual carries real small
signal where the raw score has ~zero; [278](../todos/completed/278-oos-protocol-gate-relook-decision-phase163-165-features.md)
a residual-stripping construction is materially different from Phase 148's original verdict and
earns its own new `gate_id`, conditional on first clearing a diagnostic-tier test (day-clustered
bootstrap/shuffled-null/BH-FDR at 15m) — that test is the next real action if this plan proceeds,
not yet filed as its own todo.

`regime_conditional_persistence` is CONFIRMED DEAD (270 cells tested, zero pass on corrected
labels). `nonlinear_interaction_combiner` has a small real residual surviving the CTF-leak
correction at all three affected tfs (collapse 90.6%/79.1%/43.8% at 1h/15m/5m, residual growing
finer as tf gets finer) — full numbers in the CTF memory cited above. This line previously
(stale, corrected 2026-09-01) listed `cointegrated_pairs_residual`/`jump_diffusion_
decomposition`/`statistical_factor_residual` as "remaining untested" — all 3 are now DEAD (see
discovery-track paragraph above). The two genuinely still-untested Signal-Extraction
candidates are `cross_asset_lead_lag` (waits on `stale_reference_price_adjustment` running
first) and `adaptive_combiner_weights` (gated on a data-availability trigger) — full theses:
`docs/research/data-edge-source-thesis.md`. Phase 144/143.1/162/163/164/165/167 are all
COMPLETE — see Phase Summary table below.

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
| 143 | Feature Lifecycle Routing (merged with 149B) | COMPLETE (3/3 plans) -- `feature_registry` evidence-based promotion/demotion + `integrity_monitor` table live (retired into `concept_registry` by Phase 170) |
| 143.1 | Measurement and Eligibility Integrity | COMPLETE (8/8 plans, 2026-07-21) -- 143.1-08 shadow-mode validation VERDICT: HOLD (`alpha.ensemble.sign_symmetric` stays false) |
| 144 | Cross-Sectional Regime Model (`regime_group`) | COMPLETE (6/6 plans, 2026-07-22) -- D-05 verdict: F1 not triggered (TLT HMM stays deficient, demotion holds), F2 triggered for 15m/5m (rates cross-sectional also deficient there) |
| 146 | Empirical Instrument Tag Calibrator | COMPLETE (5/5 plans, 2026-07-17) -- `TagCalibrator` live-verified: 11/12 measurable tags carry real `source='empirical'` rows |
| 160 | Concept Registry MVP | COMPLETE (4/4 plans) -- 4-table schema + `ConceptRegistryService`/`ConceptRegistryAPI`/`ConceptRegistryDashboard` live |
| 161 | Controlled Vocabulary System | COMPLETE (4/4 plans, 2026-07-18) -- schema + `VocabularyService` + `vocabulary_drift` audit + `/api/vocabulary/{namespace}` route, live-verified |
| 148 | Alpha Scoring System (OOS Proof Gates) | COMPLETE (5/5 plans, 2026-07-22) -- the proof-of-alpha milestone: Gate 1 PASS, Gate 2 FAIL, VERDICT do not promote to live capital; `docs/plans/archive/2026-07-22-phase148-promotion-decision.md` |
| 162 | ic_engine Corpus Pipeline Throughput | COMPLETE (4/4 plans, 2026-07-23) -- whole-cell fingerprint mechanism, equivalence-proven |
| 166 | Frame/Execution Recalibration | COMPLETE (6/6 plans, 4 waves, 2026-07-23) -- baseline and scalar candidates FAIL gate166 decisively; structural candidate halted pending Phase 163 |
| 163 | VP/SR Structural Primitives | COMPLETE (3/3 plans, 2026-07-24, verification 15/15 must-haves) -- closes todo 153 |
| 167 | Cross-Sectional Trade Construction (cross_sectional_relative_value) | COMPLETE (6/6 plans, 2026-07-27) -- **original verdict RETRACTED, re-verified 2026-08-07: both Validation Gates FAIL** (todo 243's lookahead-leaked join). No live construction. See Strategic Plan section. |
| 168 | Cost-Hurdle-Adjusted Spread Construction (Phase 167 follow-on) | BLOCKED, not executed -- plans execution-ready but no live construction left to refine. `docs/research/trade-construction-layer.md` |
| 169 | Symbol State Query Layer | NOT PLANNED -- design doc only (`docs/research/intel-symbol-state-query-layer.md`), needs a fresh live-verification pass before planning (its "What Exists" section is a dated 2026-07-31 snapshot, now stale on row counts). |
| 170 | Concept Registry Feature-Domain Migration (`feature_registry` retirement) | COMPLETE 2026-08-10 (migration 311) -- `feature_registry`/`feature_transition_log` DROPped, `concept_registry` sole feature-lifecycle system. |
| 171 | HMM Walk-Forward Regime Labeling, Parameter-Lookahead Fix | COMPLETE 2026-08-08 -- walk-forward fitting procedure wired; root-cause investigation found production's `regime` label is a volatility partition mislabeled as trend (non-identifiability). Composite-label rollout WITHDRAWN. `171-FINAL-VERDICT.md`. |
| 172 | HMM Regime -- Volatility-Only Redesign | COMPLETE 2026-08-09 (v3.1's final phase) -- `regime_volatility` column live (migration 307), K=3, calm/elevated/turbulent vocab, replaces the trend-mislabeled `regime` column for stratification. |
| 164 | SMC Institutional Footprint Primitives | COMPLETE (4/4 plans, 2026-07-28) -- all 36 SMC `FeatureVector` fields real in both `compute()`/`compute_batch()`. |
| 165 | Swing/Fib/Trend/Session Structure Primitives | COMPLETE (5/5 plans, 2026-07-28) -- 41 new columns (swing/trend/momentum/fib/session), all float\|None, zero raw price levels. |

Current row counts and every downstream measurement number live in
[Corpus pipeline state](project_corpus_pipeline_state.md) -- that file is the single source of
truth; don't duplicate counts here.

**Dual regime system (both live):**

- `feature_vectors.regime` -- 5 per-symbol HMM labels (trending_down/transition_down/ranging/transition_up/trending_up), written by `regime_writer.py` (K=5, causal forward-filter). **Confirmed a volatility partition mislabeled as trend, not a genuine trend signal (Phase 171 verdict) — `regime_volatility` is the corrected replacement for stratification.**
- `market_regimes` -- cross-sectional labels keyed by `regime_group` (a named peer group with a pluggable regime signal: `breadth_vol` for equity, `curve_credit` for rates; commodity/fx modules ship enabled since migration 306). `cross_sectional_regime_model.py` (Phase 144) is the writer; `ic_engine` stratifies on these.

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

Phase-by-phase planning narrative (wave breakdowns, cross-AI review findings, plan-count
history) has been compressed out of this section — each phase's authoritative verdict lives in
the Phase Summary table above, and the full planning/execution record for any COMPLETE phase is
in its own `.planning/phases/<N>-*/` directory and `docs/foundation/`/`docs/research/` docs, not
duplicated here. Currently open/not-yet-planned phases, compressed to current status only:

- **Phase 169** (Symbol State Query Layer): design doc only, `docs/research/intel-symbol-state-query-layer.md`. Not planned. Needs its own live-verification refresh before planning (flagged stale 2026-08-21 -- its "What Exists" section's row/symbol counts predate the universe expansion to 231 symbols).
- **Phase 168** (Cost-Hurdle-Adjusted Spread Construction): plans execution-ready but blocked indefinitely -- Phase 167 has no live construction left to refine (see Strategic Plan section). `docs/research/trade-construction-layer.md`.
- **Phase 151** (Feature Primitives Expansion + Interaction Layer): waves 1-5 (7/9 plans) executed 2026-08-05, `FeatureVector` 249→292 fields. Waves 6-7 (corpus recompute + interaction IC sweep) intentionally paused, sequenced behind the corpus pipeline finishing rather than run twice.
- **Phase 145** (StratificationDimension Formalization): unblocked but not planned, not currently prioritized.

## Session

**This section has a recurring pattern of going stale the moment GSD-phase-level work pauses**
(confirmed 3 times: 2026-07-31, 2026-08-09, 2026-08-14) -- narrative left here gets superseded by
the Strategic Plan section and rots undetected. **Check the Strategic Plan section at the top of
this file first, always** -- it is the one kept live. GSD-phase-level work has been idle since
Phase 172 (2026-08-09); activity since then has been discovery-track research and ops/incident
work, which doesn't flow through the phase-execution loop this section exists to track. Resolved
incident narrative belongs in memory (e.g. `project_disk_full_incident_2026_08_13`) or git log,
not here.
