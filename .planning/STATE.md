---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: AlphaEngine Validation + Alpha Scoring
status: milestone_complete
stopped_at: Todo 378's full chain closed 2026-09-22 (ic_engine/ensemble_trainer/alpha_publisher/Gate B/portfolio diagnostic, real positive result). Todo 340 (feature-compute data-completeness bug, 8 symbols) sequenced next, then Phase 175 (fully planned, D-07 gate cleared, ready for /gsd-execute-phase).
last_updated: "2026-09-22T18:00:00.000Z"
progress:
  total_phases: 12
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Strategic Plan (read this first)

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

**Universe-expansion scoping inputs, gathered 2026-09-13, not yet acted on:**

- **TF stack: keep all four tiers (5m/15m/1h/1d).** Holding period, not TF
  granularity, is what's economically dead — every tier clears its own turnover-
  adjusted hurdle given a long-enough hold (5m @ ~half day, 15m @ ~2.5hr, 1h @ 3-10
  days), while 1-bar holds fail at every tier. `scripts/analysis/personal_cost_hurdle_by_tf.py`.

- **Cross-TF signal correlation: momentum decorrelates across TFs (1d-vs-15m/5m rho
  near zero, coin-flip sign agreement) — real, not Phase 148's 100%-co-firing
  redundancy pattern.** Necessary but not sufficient for a fusion construction to add
  tradeable value. Also found: `ctf_momentum` is a higher-TF value broadcast down via
  `ctf_higher_tf_map`, not TF-native — the codebase already fuses HTF context into
  LTF feature rows at the feature level (not at the `alpha_score`/`ensemble_trainer`
  level, which has no fusion). `scripts/analysis/cross_tf_signal_correlation_screen.py`.
  Next step if pursued: a real pre-registration on the DIVERGENCE framing specifically
  (betting when coarse/fine reads disagree) — competes for priority against universe
  expansion, doesn't precede it by default.

- **CORRECTED 2026-09-16 (superseding the 2026-09-13 entry below the strikethrough
  reasoning was never actually struck, so stating it plainly): single-name equity is NOT
  the primary breadth-scaling lever.** Phase 174 executed on the 2026-09-13 framing — drew
  a 40-name unbiased down-cap pilot (174-15), ran it through the pre-registered D-10
  correlation gate, and it FAILED decisively (unconditional 0.30 vs. ≤0.10, `high_bear`
  0.43 vs. ≤0.30). Root-cause investigation found the constraint isn't down-cap names
  specifically — it's that raw correlation among *any* unhedged long-only U.S. equity
  population is dominated by shared market beta: not one of 18 regime-conditioned
  correlation cells, across the pilot AND the existing 117-name baseline, clears even
  0.14. An 11-instrument cross-asset-class basket (already active/compute_eligible, zero
  onboarding cost) passed the identical gate cleanly (0.0947 / 0.1180) with n_eff
  5.05-7.20 in every regime, beating the entire existing equity book's best case (~3.25)
  with 11 instruments. Full record: `docs/plans/methodology-change-ledger.md` E13;
  pre-registered follow-on (mechanical candidate selection, not hand-picked):
  `docs/research/phase174-cross-asset-diversification-prereg-2026-09-16.md`. The
  down-cap pilot's 40 symbols stay in the corpus as a retained measurement asset
  (`compute_eligible=false`); Phase 174 plans 174-11/174-12 are blocked-by-verdict, not
  executed — see ROADMAP.md.

- **ETF/cross-asset expansion is now the stronger lever, not a secondary exposure-gap-fill
  task.** The 2026-09-13 framing deprioritized it on a raw-count argument (few possible new
  ETFs vs. hundreds of possible new equities) that was never checked against decorrelation
  quality — corrected above. Commodities/rates/credit/vol/EM-currency ETFs are already
  well-represented in the compute-eligible book (GLD/SLV/PPLT/DBA/DBB/DBC, TLT/IEF/SHY,
  HYG/LQD/EMB, UUP, VIXY, EMLC — all confirmed 2026-09-16). Remaining real gaps: standalone
  factor-equity ETFs (value/growth/small-cap each only 1-2 symbols; momentum/quality/low-vol
  factor ETFs — MTUM/QUAL/USMV — exist as of migration 338, correcting an earlier "zero
  representation" claim) and vol term structure beyond spot VIX (see futures gap above).

- **Gate A + Gate B both PASSED against the pre-registered 13-symbol cross-asset list**
  (GLD/DBA/DBB/DBC/URA/TLT/UUP/VIXY/EMLC/HYG/XOM/DHI/PGR) — the cross-instrument
  covariance-aware portfolio diagnostic (`scripts/analysis/portfolio_covariance_weighting_diagnostic.py`)
  then ran for real and found a genuine positive result: `vol_normalized`/`ic_proportional`
  weighting both significantly beat naive `equal_weight` (ann. Sharpe ~1.19/~0.95 vs. ~0.18).
  Shadow-mode measurement only, caveats apply (selection effect, naive significance test, zero
  costs modeled) — no promotion decision made. Full record, including the corpus-wide
  `ic_engine.py` regime-routing bug found+fixed along the way (commit `b8af2b749`):
  [378](todos/completed/378-vixy-emlc-feature-backfill-then-gate-b-and-portfolio-diagnostic.md).
  Sibling bug fixed same day (`source='human'`-only tag-routing stopgap, commit `d1ce8d6bb`):
  [379](todos/completed/379-empirical-tags-contaminate-equity-breadth-and-peer-grouping.md).
  One follow-up still open,
  [380](todos/pending/380-itr-materiality-filtered-empirical-tags-and-eq-prefix-naming-collision.md)
  (deferred materiality-filter design, feeds Phase 175); the other
  ([381](todos/completed/381-equity-regime-model-dead-code-broken-insert.md), dead-code deletion) closed.

- **Compute cost bounds universe scale — estimate STALE as of 2026-09-22, needs re-measuring.**
  The 2026-09-19 measurement (2.4 worker-hours/symbol, projecting 10-20 day recomputes at
  1000-2000 symbols) was taken mid-flight from the same run that went on to finish 2026-09-22
  in ~11.5 hours total, after the `b8af2b749` routing fix and migration 348's chunk-size
  reduction landed. Don't cite either number until re-derived from the completed run's logs.
  Scope expansion by re-measured recompute cost, not a target count. Detail:
  [385](todos/pending/385-ic-engine-recompute-cost-bounds-universe-scale-threading-measurement-first.md).

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

- **Phase 169** (Symbol State Query Layer): design doc only, `docs/research/intel-symbol-state-query-layer.md`. Not planned. Needs its own live-verification refresh before planning (flagged stale 2026-08-21 -- its "What Exists" section's row/symbol counts predate the universe expansion to 231 symbols).
- **Phase 168** (Cost-Hurdle-Adjusted Spread Construction): plans execution-ready but blocked indefinitely -- Phase 167 has no live construction left to refine. `docs/research/trade-construction-layer.md`.
- **Phase 151** (Feature Primitives Expansion + Interaction Layer): waves 1-5 (7/9 plans) executed 2026-08-05, `FeatureVector` 249→292 fields. Waves 6-7 (corpus recompute + interaction IC sweep) intentionally paused, sequenced behind the corpus pipeline finishing rather than run twice.
- **Phase 145** (StratificationDimension Formalization): unblocked but not planned, not currently prioritized.
- **Phase 174** (Universe Expansion — Single-Name Breadth Scaling + Targeted ETF Gap-Fill): executed and CLOSED 2026-09-16 — D-10 correlation gate FAILED for single-name expansion, pivoted to cross-asset ETFs (see Strategic Plan section above for the full verdict and the follow-on pre-registration it produced). Plans 174-11/174-12 blocked-by-verdict, not executed.
- **Phase 175** (ITR materiality-filtered empirical tags for breadth/peer-grouping, todo 380):
  fully planned 2026-09-18 (5 plans, 4 waves, shadow-mode). D-07 gate cleared by all three
  required reviewers (Codex, AGY, Fable — full review record: `175-REVIEWS.md`), ready for
  `/gsd-execute-phase 175`. **Sequencing decision 2026-09-22: run todo 340 first** (a feature-
  compute data-completeness bug affecting 8 symbols, orthogonal to Phase 175 but touches the
  same `feature_vectors` hypertable Phase 175's eventual `ic_engine` recompute will read) —
  avoids the exact write/read lock contention hit today (see gotchas.md), and lands complete
  feature data before the next expensive corpus-wide recompute rather than after.

## Session

Last session: 2026-09-22
Stopped at: see Strategic Plan section above (kept live; this section is a known staleness trap
— its tool-sync bug is root-caused in todo 383, don't re-investigate it).
