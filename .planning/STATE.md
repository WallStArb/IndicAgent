---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: AlphaEngine Validation + Alpha Scoring
status: milestone_complete
stopped_at: Phase 174 context gathered
last_updated: "2026-09-15T12:31:48.119Z"
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

- **22 registered futures/FX instruments (ES, NQ, CL, GC, VX, Treasury/grain complex,
  4 FX pairs) have ZERO rows in `market_data_ohlcv`/`feature_vectors`** — never
  backfilled despite existing as instrument metadata. Real instrument count is 253
  (231 active + 22 empty), not the ~350 previously assumed. Server headroom: 24
  cores, 29GB RAM + 150GB swap, 569GB disk free — compute time, not disk, is the
  constraint (full `ic_engine` recompute runs 66-77+ hours). **Not one uniform blocker
  (corrected 2026-09-13, see [377](todos/pending/377-futures-backfill-needs-continuous-contract-construction-not-just-gateway.md)):**
  the 4 FX pairs are spot (IDEALPRO, no roll/expiry) and blocked only on `ib-gateway`
  being down; the 18 futures need a continuous-contract construction methodology
  (back-adjustment choice, per-contract-month IBKR history depth, real-vs-proxy
  forward-curve data) that doesn't exist yet — `ops_roll_batch.py` only handles live
  forward rolls, not historical stitching. **Further narrowed same session: 14 of the
  22 are redundant with ETFs already in the 231-symbol universe** (ES/NQ/RTY/YM vs.
  SPY/QQQ/IWM/DIA; ZN/ZB/ZF/ZT vs. TLT/IEF/SHY; GC/SI vs. GLD/SLV; EURUSD/USDJPY vs.
  FXE/FXY — all confirmed present) — **only CL/NG/HG/ZC/ZS/ZW/VX + GBPUSD/USDCHF (9
  instruments) target exposures with no existing proxy.** Any future backfill should
  target that 9, not all 22.

- **Single-name equity IS the primary breadth-scaling lever (corrected 2026-09-13, same
  session) — reasoned via the Fundamental Law of Active Management (IR ≈ IC × √breadth):**
  measured IC is small and stable (~0.03-0.06) and effective breadth is only ~8.4, so breadth
  is the dominant term. Only single-name equity expansion has the scale (potentially hundreds
  to thousands of names) to move that number materially — ETF additions (10-20 symbols
  filling exposure gaps) move the count from 231 to ~250, noise against a breadth problem
  this severe. **`alpha_score_residual_single_security_15m`'s DEAD verdict (0/231, then 0/8
  sector-bucketed) is NOT evidence against this** — the current 128 single-names are almost
  entirely large/mega-cap (only 1 of 128 tagged `eq_small_cap`), the segment where market
  efficiency is highest and idiosyncratic signal is hardest to find. It's evidence against
  resampling more of the same large-cap population, not against real breadth-scale expansion
  into a larger, less-efficient (further down-cap) slice of the market — an untested
  population. **Real open cost question, not yet measured:** the "personal cost hurdle isn't
  binding" finding (0b) was calibrated against the current liquid, large-cap-dominated
  universe — going down-cap means wider spreads/slippage/borrow-availability questions that
  haven't been tested and shouldn't be assumed still non-binding.

- **ETF expansion stays useful for filling specific exposure blind spots, not as a breadth
  strategy** — checked `instrument_tags`/`tag_vocabulary` (39 exposure tags across 231
  symbols): commodities/international-equity/fixed-income/real-estate/crypto already
  well-covered; confirmed gaps are EM currency exposure (zero symbols tagged `fx_em`),
  standalone factor-equity ETFs (value/growth/small-cap each only 1-2 symbols, no momentum/
  quality/low-vol factor ETF at all), and vol term structure (see futures gap above).

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
- **Phase 174** (Universe Expansion — Single-Name Breadth Scaling + Targeted ETF Gap-Fill): added to roadmap 2026-09-13 (prescribed by the personal-scale program's kill criterion, 2026-09-12), not yet planned. See Strategic Plan section above for scoping inputs already gathered. Note: `gsd-sdk phase.add` initially returned a colliding number (162, already in use by a completed phase) — corrected to 174 by hand; see feedback queued this session.

## Session

Last session: 2026-09-14
Stopped at: Phase 174 context gathered
Resume file: .planning/phases/174-universe-expansion-single-name-breadth-scaling-targeted-etf-/174-CONTEXT.md

**This section has a recurring pattern of going stale the moment GSD-phase-level work pauses**
(confirmed 3 times: 2026-07-31, 2026-08-09, 2026-08-14) -- narrative left here gets superseded by
the Strategic Plan section and rots undetected. **Check the Strategic Plan section at the top of
this file first, always** -- it is the one kept live. GSD-phase-level work resumed 2026-09-14
after idling since Phase 172 (2026-08-09) -- Phase 174 (Universe Expansion) now has context
gathered, ready for `/gsd-plan-phase 174`. Resolved incident narrative belongs in memory (e.g.
`project_disk_full_incident_2026_08_13`) or git log, not here.
