# AlphaEngine V1 — Work Plan

**Created:** 2026-06-30
**Status:** Phase A in progress
**Principle:** Correctness before scale. Empirical before theoretical. Never build signal path on top of a measurement you know is wrong.

---

## Current State

- Corpus pipeline: MID-RERUN — regime_writer --refit running (PID 2496291, 2026-06-30); forward_returns/feature_ic_scores empty until complete
- Phase 141 gate: **WAS FAIL** — gate definition was wrong (see A1/A5 findings below); redesigned gate will qualify 5m features
- Phase 142 (shadow mode): BLOCKED pending corpus re-run on corrected ic_engine + gate redesign
- 7 zero-IC features identified for demotion: momentum_rank_z, poc_dist_atr, sr_resist_dist, sr_support_dist, va_position, volatility_rank_z, volume_rank_z
- Known ic_engine methodology issues: 028 P0 (walk-forward is CV), P2 (BH-FDR per-cell), P3 (embargo), P4 (clustering)
- IC validation report: `docs/analysis/ic-validation-report-58sym.md`

**A1 root cause finding (2026-06-30):** 5m had 721/2196 cells with `ic_ci_lower > 0` — genuine positive IC at 95% CI exists. Zero passed `passes_walkforward = true` because all 3 WF folds must be positive (too strict for noisy 5m data). The `ic_sharpe_hac > 0.5` threshold used in the Phase 141 report was an analysis artifact, not the production gate. The ensemble_trainer gate `passes_walkforward = true` is the real filter discarding 5m. This is a gate design bug, not a signal absence.

**The diagnostic question Phase B must answer:**
After the gate redesign and ic_engine fixes, how many features have `ic_ci_lower > 0` per TF and regime? What weights do they receive? This determines ensemble coverage and whether shadow mode has sufficient signal breadth.

---

## Phase A — IC Foundation Correctness + Gate Redesign

**Goal:** Fix all known ic_engine methodology issues and the ensemble gate design before the next corpus run. Every downstream artifact is built on these measurements.

**Gate to Phase B:** Full corpus re-run required after A2 + A5 changes.

### A1 — 5m IC Failure Investigation — COMPLETE (2026-06-30)

**Findings:**
- [x] **A1a** — `return_type = 'executable_open_to_open'` filter enforced at ic_engine.py:689. Clean.
- [x] **A1b** — Lookahead formula correct: `ln(open[T+N+1] / open[T+1])` in forward_return_writer. Clean.
- [x] **A1c** — Subsampling not the issue: cross-sectional path has ~1.39M subsampled obs → 3,480 IC windows >> sharpe_min_windows=30. Clean.
- [x] **A1d** — Root cause: 5m has 721 cells with `ic_ci_lower > 0` (real positive IC) but 0 pass `passes_walkforward = true` (all 3 folds must be positive — too strict for noisy 5m data). The gate is wrong, not the signal.

**Outcome:** No ic_engine bug causes the 5m failure. The problem is `passes_walkforward = true` as a hard gate in ensemble_trainer. Fix is in A5.

### A2 — IC Engine Methodology Fixes (todo 028 P0+P2+P3+P4)

Small fixes, 1 session. Require full corpus re-run after.

- [ ] **A2a P0** — Fix walk-forward fold construction: expanding window (train on `[0..T]`, test on `[T+embargo..T+window]`, advance T monotonically). Current symmetric partition is CV, not WF.
- [ ] **A2b P2** — Move BH-FDR to corpus-level: collect all p-values from all `(symbol, tf)` workers, apply one BH-FDR pass in the main process before writing. Eliminates 232x per-cell FDR inflation.
- [ ] **A2c P3** — Scale-specific embargo: each scale uses `max(lookahead_bars_for_that_scale, min_embargo)` not `max(all_lookaheads)`. Recovers discarded fast-scale observations.
- [ ] **A2d P4** — Clustering: replace transitive linkage with direct threshold (`|corr| >= cluster_max_corr` for any pair in the cluster). Prevents silently merging uncorrelated features.

Reference: `docs/plans/2026-06-29-ic-engine-improvements.md`

### A3 — APR Compile-Time Binding (todo 008)

- [ ] **A3** — Define frozen config dataclasses for ic_engine, ensemble_trainer, regime_writer. Bind once in `execute()` before worker dispatch. Config is immutable for the entire run — eliminates non-determinism from mid-run config updates.

Reference: `.planning/todos/pending/008-apr-compile-time-binding.md`

### A4 — CANCELLED

Hard-deleting zero-IC features violates Renaissance principle: never remove signal candidates; use shadow/demote/promote. The zero-IC finding came from the pre-fix corpus (buggy walk-forward, inflated FDR, wrong embargo, bad clustering) and is unreliable. Features with low IC after the corrected Phase B re-run will be demoted to shadow weight, not deleted.

### A5 — Renaissance IC Gate Redesign (todo 031)

**Context:** The binary `passes_walkforward = true` gate requires all 3 WF folds to show positive IC. For noisy 5m data this almost never fires — discarding 721 cells with statistically significant positive IC. Jim Simons would not build this. Renaissance aggregates many weak signals; a feature with IC=0.04 and Sharpe=0.15 belongs in the ensemble at low weight.

- [ ] **A5a** — Replace `passes_walkforward = true` gate in `ensemble_trainer.py` (startup gate + `_process_stratum` WHERE clause + stratum discovery query) with `ic_ci_lower > 0 AND passes_fdr = true`.
- [ ] **A5b** — Replace best-lookahead selection in `feature_selector.py` (`select_features_per_stratum`) from max `ic_sharpe_hac` to max `quality_weight = ic_ci_lower * max(sharpe_floor, ic_sharpe_hac)`.
- [ ] **A5c** — Pass `quality_weight` into `derive_weights` as the raw weight input (replacing raw `ic_sharpe_hac`). Ledoit-Wolf deflation, max_feature_weight, and max_cluster_weight caps remain unchanged.
- [ ] **A5d** — Add APR seeds: `alpha.ensemble.sharpe_floor = 0.05` (weight floor for low-Sharpe features), migration required.

Reference: `.planning/todos/pending/031-renaissance-ic-gate-redesign.md`

**Expected outcome:** 5m features with `ic_ci_lower > 0` enter the ensemble at small weights. Broader, more diversified ensemble. Phase B gate becomes "features present with positive ci_lower" rather than "N features pass Sharpe threshold."

---

## Phase B — Corpus Re-run + Empirical Ground Truth

**Goal:** Re-run the full pipeline on the corrected ic_engine. Analyze the results. Determine whether the foundation is ready for shadow deployment.

**Gate to Phase C:** Each active TF (5m, 15m, 1h) has >=5 features with `ic_ci_lower > 0 AND passes_fdr = true` in at least 3 regimes. Low weight is acceptable — the ensemble aggregates many weak signals. If a TF has zero qualifying features even after the gate redesign, that TF needs feature expansion (todos 013/014) before shadow.

### B1 — Full Corpus Re-run

- [ ] **B1** — Run: `regime_writer → forward_return_writer → ic_engine → ensemble_trainer → alpha_publisher` via `production/scripts/corpus_pipeline_run.sh`

### B2 — Empirical Calibration (todo 030)

- [ ] **B2a** — Cost hurdle calibration: query `alpha_ci_lower` distribution from `alpha_events` by tf; set `alpha.quant.cost_hurdle.5m` and `.15m` to empirical P10/P25
- [ ] **B2b** — Threshold validation: query `abs(alpha_score)` distribution by tf; confirm current seeds (5m=1.5, 15m=1.2, 1h=1.0, 1d=0.8) are not over-filtering
- [ ] **B2c** — Gap contamination check: query `forward_returns` split by `has_gap_before_entry`; if IC difference >= 0.01 add `WHERE has_gap_before_entry = false` to ic_engine join

Reference: `.planning/todos/pending/030-cost-hurdle-apr-calibration.md`

### B3 — IC Validation Analysis

- [ ] **B3a** — Re-run Phase 141 P1 gate assessment on new corpus: how many features qualify per TF?
- [ ] **B3b** — CORPUS-03 null model baseline: equal-weight vs IC-weighted ensemble on OOS subset. Advantage must be > 0.1 before proceeding.
- [ ] **B3c** — Regime transition purge (todo 005): apply ±20-bar purge window around regime changes; compare IC Sharpe before/after. If improvement >= 5%, include in production ic_engine.

---

## Phase C — Shadow Readiness

**Goal:** Build the monitoring infrastructure that makes shadow mode scientific rather than a log sink. Must exist before a single shadow emission goes out.

**Gate to Phase D:** SHADOW-REVIEW.md written with promotion criteria defined upfront. Grafana panels live.

### C1 — Shadow Monitoring Protocol (todo 011)

- [ ] **C1a** — `SHADOW-REVIEW.md`: promotion gate criteria written before shadow starts (not negotiated from data after)
  - ≥ 60 trading days of shadow emissions
  - Mean counterfactual_pnl_r > 0 at 95% CI (bootstrap, one-tailed)
  - Sharpe of counterfactual_pnl_r > 0.5 annualized
  - Max drawdown of cumulative counterfactual_pnl_r < 25%
  - IC Sharpe stable across shadow period (no cliff in last 20 days)
- [ ] **C1b** — Grafana "Shadow AlphaEngine" row: emission rate, counterfactual P&L distribution, rolling win rate (20-day), rejection reason breakdown, alpha score distribution drift
- [ ] **C1c** — Weekly alert (Telegram): emission count, win rate, cumulative P&L. Automated.

Reference: `.planning/todos/pending/011-shadow-alpha-events-monitoring.md`

### C2 — Feature Decay Observatory (todo 024)

- [ ] **C2** — Grafana panel tracking IC trend per feature over time as ic_engine re-runs accumulate. This is the empirical observation layer for the IC decay hypothesis — data accumulates here before any automation is built.

Reference: `.planning/todos/pending/024-feature-decay-observatory.md`

---

## Phase D — Signal Path (Shadow)

**Goal:** Transition from binary I7 emission to continuous ensemble alpha scores. Deploy in shadow with monitoring active.

**Gate to promotion:** 60 trading days, all SHADOW-REVIEW.md criteria met. No post-hoc gate negotiation.

### D1 — I7 → Ensemble Transition (todo 016)

- [ ] **D1** — Replace binary I7 emission with continuous alpha scores from the ensemble. Deploy in shadow mode (`is_shadow=true`). Shadow period begins; Phase C monitoring activates.

Reference: `.planning/todos/pending/016-i7-alpha-scorer-transition.md`

---

## Backlog (after Phase D, data-driven)

These are unblocked after the foundation is correct and shadow data is accumulating:

| Item | When to start |
|------|---------------|
| 028 P1 — Trailing IC series (60-day rolling IC) | Own phase, after static corpus trusted |
| 028 P5 — IC vintage model | After trailing IC exists |
| 013 — Cross-sectional rank features | If Phase B shows coverage gaps |
| 014 — Primitives expansion | After 58-symbol analysis shows where gaps are |
| 029 — Feature scoring beyond IC | After static IC foundation solid |
| 005 — Regime transition purge | Evaluate in Phase B3c |
| 009 — Service utils cleanup | Phase B cleanup sprint (after corpus re-run) |
| 012 — Structural compliance | Phase B cleanup sprint (after corpus re-run) |
| 032 — ic_engine pure function extraction | Phase B cleanup sprint (after corpus re-run validates Phase A fixes) |
| 022 — BI Superset | After Phase D is live |

---

## Hypothesis Register

Three theoretical claims deferred until empirical validation:
- **H1 Gap contamination** — validate in B2c; act only if IC difference >= 0.01
- **H2 Threshold mis-calibration** — validate in B2b; manual APR write if needed
- **H3 IC decay velocity** — observe via C2 over 3+ months before building automation

Full context: `docs/plans/2026-06-30-alphaengine-methodology-hypotheses.md`
