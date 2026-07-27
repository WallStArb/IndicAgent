---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: AlphaEngine Validation + Alpha Scoring
status: ready_to_execute
stopped_at: "Phase 167 context gathered (--auto mode). T3's cost-hurdle treatment formalized into the analysis script and confirmed: net spread survives at every tested round-trip cost floor (1-10bp) at both lookahead scales. Ready for /gsd-plan-phase 167."
last_updated: "2026-07-27T04:14:11.585Z"
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
must be empirically demonstrated, not assumed — T3 below earned its place by clearing a
shuffled-ranking-null guard, not by a plausible story. Before building anything, apply Musk's
5-step mandate: question whether the requirement is real, delete before adding, simplify,
accelerate, automate — in that order. This is why Phase 167 (cheap, already-proven) is
sequenced ahead of Phase 151/164/165 (expensive, unproven): don't accelerate feature-expansion
work that hasn't been shown to be the actual bottleneck.

**Current focus (updated 2026-07-26):** Milestone v3.1's defining verdict stands: Phase 148
found Gate 1 (signal proof) PASS but Gate 2 (execution proof) FAIL — do not promote the
existing per-symbol directional construction to live capital. Phase 166's frame/execution
recalibration couldn't fix it; todo 179's investigation found why — `mid_bull`'s raw
un-barriered forward return is negative at every horizon, a genuine market-data finding no
stop/target/hold tuning can fix.

**That closed the fork to three options: more features (Phase 151/164/165), a different
construction/model over the *existing* features (Edge Source Thesis T2/T3/T5), or accept no
edge on this branch. Resolved 2026-07-26: T3 (cross-sectional long-short decile spread) passed
decisively** at both lookahead scales, clearing a shuffled-ranking-null guard —
`scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py`. First thesis in the
whole tree to clear its own bar. **Registered as Phase 167 (Cross-Sectional Trade
Construction)** — the current probable path, sequenced ahead of Phase 156-159 (would produce
the signal those size/execute) and ahead of Phase 151/164/165 (proven and cheap beats
unproven and expensive). First open item before scoping plans: apply the todo 030 cost-hurdle
treatment to the spread construction (today's result is gross-only).

T5 (non-linear combiner) cleared its canary-leakage check 2026-07-26 (todo 184, CLOSED) — the
0.30 OOS IC (~3x anything else measured) is NOT explained by look-ahead leakage (all 4 negative
controls clean by standalone IC; the positive control's presence doesn't move aggregate IC,
Δ=+0.0007). Genuinely interesting lead, still not a confirmed pass — independent replication
(different tf/OOS window) is the next legitimate step, not more leakage investigation on this
same result. Full detail: `docs/research/data-edge-source-thesis.md`'s T5 section. **T2
(regime-conditional persistence, the thing that motivated testing T3/T5) was
tested and found dead by todo 179's exhaustive sweep — but that sweep ran under OLD, pre-todo-092
regime labels, later found miscalibrated and fixed the same day.** A full corpus recompute
under the corrected labels is in progress (todo 183 — hit and fixed a `max_cell_rows` ceiling
issue 2026-07-26, see `.planning/todos/pending/183-ic-engine-max-cell-rows-breached-by-todo092-rebalance.md`).
T2's "dead" verdict is provisional until that completes and todo 179's sweep is re-run — doesn't
affect T3's own result, which has no regime dependency.

Phase 144/143.1/162/163 are all COMPLETE — see Phase Summary table below for detail, not
duplicated here.

**Next actions, priority order:**

*Tier 1 — the probable path:* Scope Phase 167 (`/gsd-plan-phase 167` once the cost-hurdle
treatment below is applied). First step: apply todo 030's cost-hurdle treatment to T3's spread
construction specifically (today's result is gross-only) — a long-short spread's cost dynamics
differ from a directional trade's.

*Tier 1b — concurrent, don't block Tier 1 on this:* todo 183's corpus recompute completing →
re-run todo 179's regime sweep under corrected labels → final T2 verdict, one way or the other.

*Tier 2 — cheap, resolves an open question:* todo 184 (T5 canary-leakage check).

*Tier 3 — ready now, independent of the above:* todo 182 (15m cross-sectional bootstrap
threads stale) · todo 088 (`hold_max_bars` type safety) · todo 170 (`volatility_pct`
substitution probe for rates) · todo 129 (revived cross-service short-lived-conn helper) ·
todos 172/173 (non-blocking Phase 148 findings) · todo 009 Parts A-D · todo 167 (equity
cross-sectional-vs-symbol-HMM stratification falsifier, never tested unlike rates').

*Tier 4 — deprioritized, do not resume without re-reading why:* Phase 151 (Feature Primitives
Expansion, planned and ready but not the next priority — see Guiding lens above), Phase
164/165 (feature-expansion track, same reasoning), Phase 145 (StratificationDimension
Formalization, unblocked but not planned), todo 176 (historical VP/SR backfill) and todo 175
(structural candidate Part 2 — both exist only to serve an overridden plan, see todo 179).

*Tier 5 — explicitly gated:* Phase 156-159 (Portfolio State/Sizing/Execution/Cost) — building
execution infrastructure ahead of a *proven* signal would be building on an unproven
foundation. Phase 167 is what could clear this gate. Phase 149/150/155 (PrecedentEngine, Alt
Data) — v4.0-adjacent, no case made yet. Phase 147 (I7 due diligence) — cheap, gates nothing.

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
| 142A | Ensemble IC Measurement | COMPLETE (2/2 plans) — EIC-04 current verdict PASS 54/1425=3.79%, see [Corpus pipeline state](project_corpus_pipeline_state.md) for the live number |
| 142B.1 | Ensemble Weighting Methodology | COMPLETE (5/5 plans) — E1 (shrunk-IC) is champion; E2 (mean-variance) rejected |
| 142.5 | Renaissance Primitives | COMPLETE (8/8 plans) — 89 primitives live in Feature Factory, 150 total `FeatureVector` fields |
| 142B | Frame Simulation + Counterfactual Tracking | COMPLETE (2/2 plans) — `alpha_frames` hypertable + `AlphaFrameWriter` + `CounterfactualTracker` live |
| 143 | Feature Lifecycle Routing (merged with 149B) | COMPLETE (3/3 plans) — `feature_registry` evidence-based promotion/demotion + `integrity_monitor` table live |
| 143.1 | Measurement and Eligibility Integrity | COMPLETE (8/8 plans, 2026-07-21) — 143.1-08 shadow-mode validation VERDICT: HOLD (`alpha.ensemble.sign_symmetric` stays false) |
| 144 | Cross-Sectional Regime Model (`regime_group`) | COMPLETE (6/6 plans, 2026-07-22) — D-05 verdict: F1 not triggered (TLT HMM stays deficient, demotion holds), F2 triggered for 15m/5m (rates cross-sectional also deficient there) |
| 146 | Empirical Instrument Tag Calibrator | COMPLETE (5/5 plans, 2026-07-17) — `TagCalibrator` live-verified: 11/12 measurable tags carry real `source='empirical'` rows |
| 160 | Concept Registry MVP | COMPLETE (4/4 plans) — 4-table schema + `ConceptRegistryService`/`ConceptRegistryAPI`/`ConceptRegistryDashboard` live |
| 161 | Controlled Vocabulary System | COMPLETE (4/4 plans, 2026-07-18) — schema + `VocabularyService` + `vocabulary_drift` audit + `/api/vocabulary/{namespace}` route, live-verified (VERIFICATION.md: passed, 23/24 truths, 1 accepted YAGNI override) |
| 148 | Alpha Scoring System (OOS Proof Gates) | COMPLETE (5/5 plans, 2026-07-22) — the actual proof-of-alpha milestone: Gate 1 PASS, Gate 2 FAIL, VERDICT do not promote to live capital; see ROADMAP.md's Phase 148 section and `docs/plans/2026-07-22-phase148-promotion-decision.md` for full evidence |
| 162 | ic_engine Corpus Pipeline Throughput | COMPLETE (4/4 plans, 2026-07-23) — whole-cell fingerprint mechanism, equivalence-proven |
| 166 | Frame/Execution Recalibration | COMPLETE (6/6 plans, 4 waves, 2026-07-23) — baseline and scalar candidates FAIL gate166 decisively; structural candidate halted pending Phase 163. Part 2 (todos 175/176) deprioritized by todo 179's finding. |
| 163 | VP/SR Structural Primitives | COMPLETE (3/3 plans, 2026-07-24, verification 15/15 must-haves) — closes todo 153. Historical backfill still open (todo 176, deprioritized) |
| 167 | Cross-Sectional Trade Construction (T3) | REGISTERED 2026-07-26, not planned — see Current Focus. The current probable path. |

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

- Phase 162 (ic_engine Corpus Pipeline Throughput): added 2026-07-18, planned 2026-07-22, executed and COMPLETE 2026-07-23.
- Phase 163 (VP/SR Structural Primitives): added 2026-07-20, planned and reviewed, executed and COMPLETE 2026-07-24.
- Phase 164 (SMC Institutional Footprint Primitives): added 2026-07-20, registered not planned. Deprioritized 2026-07-26 behind Phase 167.
- Phase 166 (Frame/Execution Recalibration): added 2026-07-23, planned and executed same day — COMPLETE, verdict: neither candidate promoted. Direct follow-on (todo 179) found the real cause (see Current Focus).
- Phase 151 (Feature Primitives Expansion + Interaction Layer): planned 2026-07-24, cross-AI reviewed and revised same day (Codex found 3 HIGH-severity findings, all fixed as real plan changes). 9 plans, execution-ready. Deprioritized 2026-07-26 behind Phase 167 (see Current Focus) — stays planned and ready, not the next priority.
- Phase 167 (Cross-Sectional Trade Construction, T3): added 2026-07-26 after T3 passed decisively — the first thesis in the edge-source-thesis tree to clear its own bar. Registered, not planned. Full detail in Current Focus above.

**Prior session history (resolved, not duplicated here per this project's "no resolved history"
convention — full detail in git log and `.planning/todos/completed/`):** 143.1-08 shadow-mode
resolution (2026-07-21) · todos 164/165 ensemble-eligibility fixes (2026-07-21) · symbol_hmm
restoration + Phase 148 planning (2026-07-22) · Phase 148 finalized, todo 160's real corrupt-print
scope found and fixed — 40 bars across 14 symbols, 20x the known count (2026-07-22) · Phase 148
executed, both irreversible OOS gates run, verdict DO NOT PROMOTE (2026-07-22/23) · Phase 163
executed, Gate 2's real cause found (todo 179), Layer-1 regime-coverage foundation fixed — todo
168 closed, todo 169 shipped (2026-07-24).

## Session

**Last session:** 2026-07-26T22:17:13.014Z

**Stopped at:** Phase 167 context gathered (--auto mode). T3's cost-hurdle treatment formalized into the analysis script and confirmed: net spread survives at every tested round-trip cost floor (1-10bp) at both lookahead scales. Ready for /gsd-plan-phase 167.
`bash scripts/ops/corpus/ops_corpus_pipeline_run.sh --from-step 5`, same `WEIGHT_EPOCH`/
`TRAINING_WINDOW_END` as the original halted run) — re-verify via `ps aux | grep ic_engine`
and `logs/ic_engine.log` before trusting this as still-running in a future session. Phase 167
registered but not planned; `/gsd-plan-phase 167` is the next concrete step once the todo
030 cost-hurdle treatment has been applied to T3's construction (not yet done). Todo 184 (T5
canary-leakage check) and todo 182 (15m bootstrap-threads benchmark) are both ready,
independent, unstarted.

**This session's arc:** Started from a status check on todo 092's corpus recompute → found it
halted on a `CellTooLargeError` → root-caused as two compounding issues (stale `market_regimes`
rows from the retired `equity_regime_model.py`, and a memory ceiling extrapolated from a
pre-Phase-162-fix incident) rather than accepting either at face value → fixed both (real
`cross_sectional_regime_model.py` re-run, migration 259 recalibrating `max_cell_rows` off an
actual empirical measurement) → resumed the recompute. Concurrently ran the two cheap Edge
Source Thesis falsification scripts (T3, T5) the 2026-07-25 session had recommended before
committing to Phase 164/165 — T3 passed decisively, T5 came back suspicious pending a leak
check (todo 184) — and registered T3's result as Phase 167. Caught a real methodology gap in
T2's earlier "falsified" verdict (ran under regime labels later found miscalibrated) and
recorded it as a caveat rather than letting it stand unqualified. Closed a migration-number
collision with Phase 164's plan (self-healing, no action needed, documented for the record).
This file, `docs/research/intelligence-lifecycle-backlog-matrix.md`, and
`.planning/todos/PRIORITIES.md` were all refreshed to reflect current state and cut resolved
historical narrative.
