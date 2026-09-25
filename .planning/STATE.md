---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: AlphaEngine Validation + Alpha Scoring
status: ready_to_plan
stopped_at: context exhaustion at 77% (2026-09-23)
last_updated: "2026-09-23T16:16:43.148Z"
progress:
  total_phases: 14
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Strategic Plan (read this first)

**v3.4 Edge Proof, 2026-09-24.** 179: harness S0-S4 on main
(`scripts/analysis/sleeve_walk_forward/`); V2 (6.0% false-pass), V3 (81% power at excess 0.85)
and V4b (D7 null) PASS; V4 found a fidelity gap (todo 418) that blocks the freeze. N_tested for
179 is 17. 181: H-A and H-B both FAIL Track 1 (ledger 16); next is the cross-TF divergence
pre-registration. 178: recompute and trainer done (other session). Open data gaps: 411
(features stale since 08-10), 412 (watermark), 413 (integration suite).

**Personal-scale edge determination program: CLOSED 2026-09-12, kill criterion fired
(rule 3), reconfirmed under adversarial review 2026-09-13.** 14 constructions run to a
definitive verdict, zero PASS, across three structurally distinct paradigms (pooled
cross-sectional, single-name-only cross-sectional, per-symbol time-series). Verdict:
"this corpus, at breadth ~8 and this TF stack, cannot carry the endgame" — universe
expansion is primary, not yet scoped as a phase. Full record: `docs/plans/2026-09-02-
personal-scale-edge-determination-plan.md` (design + every pre-registration);
`docs/research/construction-verdict-ledger.md` (every individual verdict — check there
before recommending a new candidate, don't re-derive the track record from memory);
`docs/plans/methodology-change-ledger.md` E12 (a real 10x cost-model bug found and
fixed during the 2026-09-13 review — verdict unaffected, but treat every number in
this program's record as provisional until independently re-derived, not cited).
Survivorship bias (100% of the 231-symbol universe is `is_active=true`, zero delisted
names) is the one genuinely unresolved integrity gap — no owner, flag it before citing
any IC number here as a hard ceiling.

**Universe expansion — consolidated state 2026-09-23 (Phase 174 closed 2026-09-16; gates and
diagnostic run 2026-09-17 through 2026-09-22; next-step chain at the end of this list):**

- **Single-name equity breadth scaling is not the lever (Phase 174 CLOSED, D-10 FAILED).**
  The pre-registered pilot gate (avg pairwise correlation ≤0.10 unconditional / ≤0.30
  `high_bear`) failed decisively on the 40-name unbiased down-cap draw (0.30 / 0.43). Root
  cause: shared market beta dominates raw correlation in any unhedged long-only U.S. equity
  population — no regime-conditioned cell, in the pilot or the 117-name baseline, clears even
  0.14. Plans 174-11/174-12 stay blocked-by-verdict; the pilot's 40 symbols are retained as a
  1d-only measurement asset. Full record: `docs/plans/methodology-change-ledger.md` E13.

- **Cross-asset diversification is the surviving lever, validated end-to-end.** The
  pre-registered 13-symbol basket (GLD/DBA/DBB/DBC/URA/TLT/UUP/VIXY/EMLC/HYG/XOM/DHI/PGR;
  mechanical selection with within-group de-duplication, no pair >0.60) passed Gate A
  (correlation structure: 0.0879 unconditional avg pairwise, `high_bear` 0.1309, n_eff 6.33
  unconditional, 5.06-8.07 across regime slices) and Gate B (real per-instrument IC via
  `ic_engine`, todo 378 closed 2026-09-22). The covariance-aware portfolio diagnostic then
  measured a genuine positive result: `vol_normalized`/`ic_proportional` weighting both
  significantly beat `equal_weight` (ann. Sharpe ~1.19/~0.95 vs ~0.18). Shadow-mode only;
  caveats on record (selection effect, naive t-stats, zero costs modeled -- the cost caveat
  root-caused 2026-09-23 to a semantically wrong cost proxy, todo 393: `alpha_events.cost_hurdle`
  is an emission-gate threshold in alpha_score units, user-preference 0.0 at 1d, so the
  diagnostic's `net_realized_return` is structurally gross; turnover reporting itself shipped
  with the diagnostic, todo 388 closed stale). No promotion decision made. Full record:
  `docs/research/phase174-cross-asset-diversification-prereg-2026-09-16.md`.

- **Universe today: 273 active instruments, live-verified 2026-09-23** — 40 down-cap pilot
  names at 1d only (onboarded, backfilled, but absent from every ic_engine run — not yet
  producing measurements), 0 live-tradeable (live streaming dormant, todo 366). Flag drift
  noted 2026-09-23: `compute_eligible` now flags 255 instruments vs the 233 the 2026-09-17
  run processed (likely nightly-backfill self-healing completing 4-TF history for more
  names) — reconcile with one idle-DB query before citing either count. Commodities/rates/credit/vol/
  EM-currency ETFs are well represented (GLD/SLV/PPLT/DBA/DBB/DBC, TLT/IEF/SHY, HYG/LQD/EMB,
  UUP, VIXY, EMLC). Remaining real gaps: standalone factor-equity ETFs (value/growth/
  small-cap only 1-2 symbols each; MTUM/QUAL/USMV exist per migration 338 but correlate
  0.86-0.98 with SPY per `factor_series_correlation`, unverified as differentiated
  exposures) and vol term structure beyond spot VIX.

- **TF stack: keep all four tiers (5m/15m/1h/1d).** Holding period, not TF granularity, is
  what's uneconomical: every tier clears its own turnover-adjusted hurdle given a long-enough
  hold (5m @ ~half day, 15m @ ~2.5hr, 1h @ 3-10 days) while 1-bar holds fail at every tier
  (`scripts/analysis/personal_cost_hurdle_by_tf.py`). Stop measuring the structurally doomed
  short-horizon cells: pre-registered 2026-09-23 with a decision rule (uniform >=5x hurdle
  fail deletes, mixed keeps; expected ~31% of per-symbol scale-cells, APR-only) at
  `docs/research/ic-engine-short-horizon-cell-deletion-prereg.md`, execution captured as
  todo 389, gated on the post-176-08 bundled landing.

- **Cross-TF signal fusion: a separate, competing, not-yet-run thread.** Momentum decorrelates
  across TFs (1d-vs-15m/5m rho near zero), real and distinct from Phase 148's co-firing
  redundancy; `ctf_momentum` is already an HTF-broadcast feature, so feature-level fusion
  exists but ensemble-level does not. If pursued, pre-register on the DIVERGENCE framing; it
  competes for priority against universe expansion, does not precede it
  (`scripts/analysis/cross_tf_signal_correlation_screen.py`).

- **Compute cost bounds universe scale — re-derived 2026-09-23, citable (todo 385).** The
  2026-09-17/22 run reached success through three process legs; `elapsed_s: 41391` measured
  only the last one. Corrected numbers: per-symbol pass ~2.7 worker-hr/symbol (the 2.4
  estimate confirmed; per-symbol threading=2 was already active), cross-sectional ~9-11.5h
  post-migration-348, clean full recompute ~3.1-3.5 days at 233 symbols, ~11-12 days at 1000.
  Benchmark arms measured 2026-09-23 on an idle box: numba `prange` 10.77-13.12x vs scipy
  serial, byte-identical (0.0e+00 diff); scipy threads=2 (production setting) 1.75-1.88x and
  already included in the 2.7 figure. Scope expansion by measured recompute cost, not a
  target count
  ([385](todos/pending/385-ic-engine-recompute-cost-bounds-universe-scale-threading-measurement-first.md)).

- **Nautilus Trader (OSS, event-driven backtest/live-execution engine, Rust core + Python)
  flagged 2026-09-13 as a forward-looking candidate for a future execution-layer phase** —
  IndicAgent's pipeline currently stops at `alpha_events`/"killed on paper," with no order-
  execution simulator anywhere in the DAG and no live-execution path sharing code with
  backtest. Nautilus's backtest/live parity is philosophically aligned with this project's
  existing causal-construction discipline. Not actionable now (no proven edge to execute
  yet) — revisit once a construction actually passes gate, not before. Qlib and Vectorbt
  (also raised same session) don't fit: Qlib overlaps almost entirely with the
  already-built, already-correctness-proven feature-factory/IC-engine/ensemble pipeline;
  Vectorbt's grid-sweep speed would duplicate existing custom bootstrap/FDR machinery
  built for this project's exact methodology. Evaluate any future tool this way — gap-fit
  against already-built work, not a build-vs-buy default in either direction.

**Current position (2026-09-24): milestone v3.4 Edge Proof set, phases 177-181.** Sequence and
rationale live only in `docs/plans/2026-09-24-edge-proof-program.md` (ROADMAP's "Planned Phases"
table mirrors it). Phase 176 closed (both primitives FAIL). Phase 178: todo 410 fixed, bundled
recompute rerunning on the fix (~8-9h from ~11:3x UTC), then lifecycle, shrinkage, trainer,
publisher. Phase 179: pre-registration DRAFT
(`docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md`, AGY-reviewed, not frozen); build
steps 1-3 done (stratum_fit.py shared with the trainer, 408/409 fixed, migration 360;
portfolio/weighting.py with the covariance coverage fix); next is step 4, `panel_null.py`. Phase 177
not started. The cross-asset diagnostic's Sharpe ~1.19 is mostly in-sample for the ensemble
weights and was compared against a long-only, signal-free arm; don't cite it as edge evidence
until 179 lands.

**Open items, not construction verdicts:**

- **Todo 372** (`Panel.sync_shift_null_p` panel-synchronicity bug): finding 1 fixed in
  code, TDD-verified, still lacks independent adversarial review (AGY/Codex rate-
  limited when the fix landed). Finding 2 (`volume_z` diurnal detrending) untouched.

- **Todo 248** (HMM per-symbol lookahead bug): walk-forward fix built + tested, not
  deployed. User directive: deploy regardless of its own Gate 4 result (confirmed
  causal-law violation, not a new/unproven signal) — pure deployment decision now,
  re-evaluate scoping via `/gsd-discuss-phase`.

- **N1** (`nonlinear_interaction_combiner` residual form): structurally inconclusive,
  confirmed not a staleness artifact (todo 364). Don't cite as pass or fail.

- **`cross_asset_lead_lag`** and **`adaptive_combiner_weights`**: the two remaining
  untested Signal-Extraction candidates from the pre-personal-scale-program backlog,
  gated on other work (`stale_reference_price_adjustment`, a data-availability
  trigger). `docs/research/data-edge-source-thesis.md`.

**Process pointers:** `.planning/todos/PRIORITIES.md` is the sole priority source —
don't duplicate a snapshot here, it always goes stale. [Corpus pipeline state](project_corpus_pipeline_state.md)
is the sole row-count/pipeline-status source. `docs/research/construction-verdict-ledger.md`
is the sole construction-verdict source.

## v3.0 Phase Summary (SHIPPED 2026-06-25)

| Phase | Name | Status |
|-------|------|--------|
| 137 | Feature Factory | COMPLETE (7/7 plans, 2026-06-21) |
| 138 | IC Engine + Forward Returns | COMPLETE (9/9 plans, 2026-06-23) |
| 139 | Ensemble + Alpha Emission | COMPLETE (3/3 plans, 2026-06-24; 14/14 verification truths) |
| 140 | IC Engine Correctness | COMPLETE (4/4 plans, 2026-06-25) |

## v3.1 Phase Summary (SHIPPED 2026-09-02)

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
| 148 | Alpha Scoring System (OOS Proof Gates) | COMPLETE (5/5 plans, 2026-07-22) -- the proof-of-alpha milestone: Gate 1 PASS, Gate 2 FAIL, VERDICT do not promote to live capital; `docs/plans/archive/2026-07-22-phase148-promotion-decision.md`. Killed on paper for personal-scale use too, 2026-09-02 -- see construction-verdict-ledger.md. |
| 162 | ic_engine Corpus Pipeline Throughput | COMPLETE (4/4 plans, 2026-07-23) -- whole-cell fingerprint mechanism, equivalence-proven |
| 166 | Frame/Execution Recalibration | COMPLETE (6/6 plans, 4 waves, 2026-07-23) -- baseline and scalar candidates FAIL gate166 decisively; structural candidate halted pending Phase 163 |
| 163 | VP/SR Structural Primitives | COMPLETE (3/3 plans, 2026-07-24, verification 15/15 must-haves) -- closes todo 153 |
| 167 | Cross-Sectional Trade Construction (cross_sectional_relative_value) | COMPLETE (6/6 plans, 2026-07-27) -- **original verdict RETRACTED, re-verified 2026-08-07: both Validation Gates FAIL** (todo 243's lookahead-leaked join). No live construction. |
| 168 | Cost-Hurdle-Adjusted Spread Construction (Phase 167 follow-on) | BLOCKED, not executed -- plans execution-ready but no live construction left to refine. `docs/research/trade-construction-layer.md` |
| 169 | Symbol State Query Layer | NOT PLANNED -- design doc only (`docs/research/intel-symbol-state-query-layer.md`), needs a fresh live-verification pass before planning (its "What Exists" section is a dated 2026-07-31 snapshot, now stale on row counts). |
| 170 | Concept Registry Feature-Domain Migration (`feature_registry` retirement) | COMPLETE 2026-08-10 (migration 311) -- `feature_registry`/`feature_transition_log` DROPped, `concept_registry` sole feature-lifecycle system. |
| 171 | HMM Walk-Forward Regime Labeling, Parameter-Lookahead Fix | COMPLETE 2026-08-08 -- walk-forward fitting procedure wired; root-cause investigation found production's `regime` label is a volatility partition mislabeled as trend (non-identifiability). Composite-label rollout WITHDRAWN. `171-FINAL-VERDICT.md`. |
| 172 | HMM Regime -- Volatility-Only Redesign | COMPLETE 2026-08-09 (v3.1's final phase) -- `regime_volatility` column live (migration 307), K=3, calm/elevated/turbulent vocab, replaces the trend-mislabeled `regime` column for stratification. |
| 164 | SMC Institutional Footprint Primitives | COMPLETE (4/4 plans, 2026-07-28) -- all 36 SMC `FeatureVector` fields real in both `compute()`/`compute_batch()`. |
| 165 | Swing/Fib/Trend/Session Structure Primitives | COMPLETE (5/5 plans, 2026-07-28) -- 41 new columns (swing/trend/momentum/fib/session), all float\|None, zero raw price levels. |
| 173 | Broadcast Feature Significance Correction | COMPLETE 2026-08-26, full corpus recompute COMPLETE 2026-08-31 -- `alpha_events` carries corrected numbers for all 38 broadcast features. A self-deadlock bug in `alpha_publisher.py` (todo 351) found and fixed along the way. |

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
in its own `.planning/milestones/v3.1-phases/<N>-*/` directory (archived at milestone close 2026-09-02; future phases create fresh dirs under `.planning/phases/`) and `docs/foundation/`/`docs/research/` docs, not
duplicated here. Currently open/not-yet-planned phases, compressed to current status only:

- **Phase 183** (Research layer: runner, ledger, combiner, book test): added 2026-09-25; not planned. Gates family 1's first real-data run.
- **Phase 182** (Security classification hierarchy, todo 384): added 2026-09-25 on owner decision to build; not planned. Off the research critical path.
- **Phase 169** (Symbol State Query Layer): design doc only, `docs/research/intel-symbol-state-query-layer.md`. Not planned. Needs its own live-verification refresh before planning (flagged stale 2026-08-21 -- its "What Exists" section's row/symbol counts predate the universe expansion to 231 symbols).
- **Phase 168** (Cost-Hurdle-Adjusted Spread Construction): plans execution-ready but blocked indefinitely -- Phase 167 has no live construction left to refine. `docs/research/trade-construction-layer.md`.
- **Phase 151** (Feature Primitives Expansion + Interaction Layer): waves 1-5 (7/9 plans) executed 2026-08-05, `FeatureVector` 249→292 fields. Waves 6-7 (corpus recompute + interaction IC sweep) intentionally paused, sequenced behind the corpus pipeline finishing rather than run twice.
- **Phase 145** (StratificationDimension Formalization): unblocked but not planned, not currently prioritized.
- **Phase 174** (Universe Expansion — Single-Name Breadth Scaling + Targeted ETF Gap-Fill): executed and CLOSED 2026-09-16 — D-10 correlation gate FAILED for single-name expansion, pivoted to cross-asset ETFs (see Strategic Plan section above for the full verdict and the follow-on pre-registration it produced). Plans 174-11/174-12 blocked-by-verdict, not executed.
- **Phase 175** (ITR materiality-filtered empirical tags for breadth/peer-grouping, todo 380):
  COMPLETE 2026-09-23 (5/5 plans; verification clean, no gaps; shadow-mode scope verified —
  both consumers still read `source='human'` only). `TagCalibrator` Pass 4 is live (migration
  346, eleven APR keys, `instrument_tags_active` view). The consumer-cutover decision is a
  separate later phase gated on the shadow report plus D-07 cross-AI review (todo 380, open);
  seeded thresholds currently admit 0 symbols.

- **Phase 176 (Earnings-Season Calendar Primitive, todo 353): EXECUTED 2026-09-24, 8/8 plans.**
  Proxy evidence on the corrected 14-42-day window (D-04): 1.90x in-season, Welch p=5.05e-05,
  67% of symbols (155/233). Real ic_engine gate
  ([176-GATE-VERDICT.md](phases/176-earnings-season-calendar-primitive-todo-353/176-GATE-VERDICT.md)):
  `GATE_VERDICT_EARNINGS_SEASON_FLAG=FAIL`, `GATE_VERDICT_DAYS_SINCE_QUARTER_END=FAIL` (reliable
  everywhere, zero FDR passes, subsumed by `quarter_cycle_sin`/`quarter_position`),
  `CONDITIONING_VERDICT=SHARPENS` on thin support, so `alpha.ic.earnings_season_conditioned`
  stays `true` pending todo 403. Lifecycle hook skipped at the pinned window (todo 402).

## Session

Last session: 2026-09-24 (ended late UTC). Built 179 steps 4-5 and most of 6; ran V2,
V3, V4b, V4 and the H-A/H-B Track 1 run. Resume at todo 418 (V4 row-set diff), then V5 and the
freeze.
