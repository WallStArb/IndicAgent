---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: AlphaEngine Validation + Alpha Scoring
status: ready_to_execute
stopped_at: "Phase 167 COMPLETE (6/6 plans): full 2006-2026 corpus backfilled into construction_spreads, both live Validation Gates PASSED against the real OOS population. Post-execution /simplify + /gsd:code-review 167 ran same session -- found and fixed 1 critical bug (CR-01, --backfill turnover-seed fix, live verdict unaffected) + 5 warnings. CLAUDE.md/gotchas.md updated with a corrected asyncpg JSONB codec claim and 3 new worktree/test gotchas. Pushed to origin/main (b7f1ed4b). Phase 156-159's stated precondition is now met; next decision is the user's."
last_updated: "2026-07-27T13:46:36.000Z"
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
Δ=+0.0007). Genuinely interesting lead, still not a confirmed pass -- independent replication
(different tf/OOS window) is the next legitimate step, not more leakage investigation on this
same result. Full detail: `docs/research/data-edge-source-thesis.md`'s T5 section. **T2
(regime-conditional persistence, the thing that motivated testing T3/T5) was
tested and found dead by todo 179's exhaustive sweep -- but that sweep ran under OLD, pre-todo-092
regime labels, later found miscalibrated and fixed the same day.** A full corpus recompute
under the corrected labels is in progress (todo 183 -- hit and fixed a `max_cell_rows` ceiling
issue 2026-07-26, see `.planning/todos/pending/183-ic-engine-max-cell-rows-breached-by-todo092-rebalance.md`).
T2's "dead" verdict is provisional until that completes and todo 179's sweep is re-run -- doesn't
affect T3's own result, which has no regime dependency.

Phase 144/143.1/162/163 are all COMPLETE -- see Phase Summary table below for detail, not
duplicated here.

**Next actions, priority order:**

*Tier 1 -- decision point:* Phase 167 is COMPLETE and both gates PASSED. The next decision
(whether and how to proceed toward Phase 156-159 with this construction as the live-capital
signal source) is the user's -- not a next-plan-to-scope item.

*Tier 1b -- concurrent, don't block Tier 1 on this:* todo 183's corpus recompute completing →
re-run todo 179's regime sweep under corrected labels → final T2 verdict, one way or the other.

*Tier 2 -- cheap, resolves an open question:* todo 184 (T5 canary-leakage check).

*Tier 3 -- ready now, independent of the above:* todo 182 (15m cross-sectional bootstrap
threads stale) · todo 088 (`hold_max_bars` type safety) · todo 170 (`volatility_pct`
substitution probe for rates) · todo 129 (revived cross-service short-lived-conn helper) ·
todos 172/173 (non-blocking Phase 148 findings) · todo 009 Parts A-D · todo 167 (equity
cross-sectional-vs-symbol-HMM stratification falsifier, never tested unlike rates').

*Tier 4 -- deprioritized, do not resume without re-reading why:* Phase 151 (Feature Primitives
Expansion, planned and ready but not the next priority -- see Guiding lens above), Phase
164/165 (feature-expansion track, same reasoning), Phase 145 (StratificationDimension
Formalization, unblocked but not planned), todo 176 (historical VP/SR backfill) and todo 175
(structural candidate Part 2 -- both exist only to serve an overridden plan, see todo 179).

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
- Phase 164 (SMC Institutional Footprint Primitives): added 2026-07-20, registered not planned. Deprioritized 2026-07-26 behind Phase 167.
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
168 closed, todo 169 shipped (2026-07-24).

## Session

**Last session:** 2026-07-27T11:44:00.000Z

**Stopped at:** Phase 167 Plan 06 (final plan) executed. Full 2006-2026 corpus backfilled into
`construction_spreads`; both live Validation Gates ran against the real OOS population and
BOTH PASSED (`gate1_passes=true`, `gate2_passes_overall=true`). Phase 167 is COMPLETE (6/6
plans). `docs/research/trade-construction-layer.md`, `docs/research/data-edge-source-thesis.md`,
`docs/operations/operations-infrastructure.md`, and `docs/reference/cheatsheet.md` all updated
with the live verdict and runbook detail. The Phase 156-159 execution/sizing chain's stated
precondition is now met; the decision whether to proceed is the user's. Todo 183's `ic_engine`
corpus recompute was still running concurrently throughout this plan's execution (confirmed via
`ps aux`) -- re-verify its status before trusting it as still-running in a future session, since
it touches unrelated tables (`feature_ic_scores`/`alpha_ensemble_ic`) with no overlap with
`construction_spreads`. Todo 184 (T5 canary-leakage check, CLOSED) and todo 182 (15m
bootstrap-threads benchmark) remain ready/independent, unstarted.

**This session's arc:** Continued from a prior session that planned Phase 167's 6 plans (schema,
pure construction primitives, write-path service, Gate 1 core, Gate 2 core) and executed Plans
01-05. This session executed Plan 06, the plan whose entire purpose is running the construction
for real rather than proving the code correct: pre-registered four equivalence tolerance bands
before backfilling, ran the full corpus backfill, verified equivalence to the original T3
falsification script (all four bands PASS, `n_bars` matches T3's own published value almost
exactly), caught and fixed a genuine bug during the first live Gate 1 run (a missing JSONB type
codec on a bare `asyncpg` connection), ran both gates live, and transcribed the actual verdicts
(both PASS) into the four governing docs with the same fidelity Phase 148 recorded its DO NOT
PROMOTE verdict.

**Post-execution gates run 2026-07-27 (same session, after Plan 06):** `/simplify` deduped ~60
lines of repeated setup logic between `_run_evaluate_gate`/`_run_evaluate_attribution` and fixed
an inaccurate docstring claim about shared permutation draws (no behavior change). `/gsd:code-review
167` found 1 critical + 5 warnings, all fixed same session:
- **CR-01 (real bug, fixed):** `--backfill` mode seeded prior-leg turnover from the table's
  globally latest row regardless of mode -- correct only when the table starts empty. A
  re-backfill against a non-empty table (e.g. picking up a newly-onboarded symbol's earlier
  history) would have fabricated a non-null `one_way_turnover` for the true first bar instead of
  the required NULL. Confirmed the ALREADY-RECORDED live verdict above is unaffected (table was
  genuinely empty at backfill time). Fixed with a regression test that reproduces the corruption
  against the pre-fix code.
- **WR-01:** hardcoded `0.05` Gate-1 null-p significance threshold migrated to APR
  (`alpha.construction.null_p_threshold`, migration 261).
- **WR-02/03/04:** 5 broken doc cross-references, one numeric transcription error
  (`0.0006`->`0.0005` in an in-sample diagnostic cell), one stale glossary status line -- all
  fixed.
- **WR-05:** `write_verdict_artifact`'s timestamped filename had only second-level resolution;
  two same-second calls would silently clobber each other. Fixed with a numeric-suffix
  disambiguation + regression test.
- Two structural findings (shared JSONB-codec connection helper across services; `cfg()`'s
  list-default cast bug) deliberately deferred -- out of this diff's scope, filed as
  [todo 187](.planning/todos/pending/187-cross-sectional-spread-tracker-altitude-cleanup.md), P3.

**CLAUDE.md maintenance (same session):** corrected an existing CLAUDE.md line that stated
asyncpg JSONB decoding as unconditional -- it's only true on a pooled `BaseBatch.create_pool()`
connection; a bare `asyncpg.connect()` (exactly what CR-01's sibling bug hit) has no codec.
`docs/reference/gotchas.md` gained 3 entries: worktree `.venv` not inherited (breaks pre-commit
hooks), worktree isolation unsafe for plans whose deliverable is gitignored
(`logs/`/`corpus_manifests/*.json`), integration tests overwrite committed corpus manifests.

**Pushed to `origin/main` 2026-07-27** (`b7f1ed4b`) -- 57 commits, spanning this session's Phase
167 work plus prior unpushed session history. No feature branch existed (Phase 167's
`branching_strategy` was `none`); all work landed directly on `main`.
