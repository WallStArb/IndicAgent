# AlphaEngine V1 — Work Plan

**Created:** 2026-06-30
**Status:** Phase A in progress
**Principle:** Correctness before scale. Empirical before theoretical. Never build signal path on top of a measurement you know is wrong.

---

## Current State

- Corpus pipeline: COMPLETE (402K IC scores, 12.5M alpha_events, 328 ensemble weights)
- Phase 141 gate: **FAIL** — 5m has 0 qualifying features; 1h has 23
- Phase 142 (shadow mode): BLOCKED until gate PASS on both 5m and 1h
- 7 zero-IC features identified for demotion: momentum_rank_z, poc_dist_atr, sr_resist_dist, sr_support_dist, va_position, volatility_rank_z, volume_rank_z
- Known ic_engine methodology issues: 028 P0 (walk-forward is CV), P2 (BH-FDR per-cell), P3 (embargo), P4 (clustering)
- IC validation report: `docs/analysis/ic-validation-report-58sym.md`

**The diagnostic question Phase B must answer:**
After correcting the FDR methodology and fixing the 5m root cause, how many features have genuine positive IC at 95% CI — and in which regimes and timeframes? This determines whether the foundation is ready for shadow deployment or needs feature expansion first.

---

## Phase A — 5m Root Cause + IC Foundation Correctness

**Goal:** Understand why 5m has zero qualifying features and fix all known ic_engine methodology issues before the next corpus run. Every downstream artifact is built on this measurement.

**Gate to Phase B:** Full corpus re-run required after these changes.

### A1 — 5m IC Failure Investigation

The Phase 141 report ruled out the per-regime observation floor (all 5m cells are above 3000 obs). Root causes to investigate in order:

- [ ] **A1a** — Verify `return_type = 'executable_open_to_open'` filter is enforced in ic_engine for 5m specifically (not silently falling back to all rows)
- [ ] **A1b** — Verify lookahead alignment: 5m lookahead=1 means `ln(open[T+2] / open[T+1])` — confirm the forward_returns rows for 5m encode this correctly
- [ ] **A1c** — Review subsampling minimum: `alpha.ic.subsample_min_stride` floor vs actual 5m stride — confirm stride is not discarding all 5m observations
- [ ] **A1d** — Query the actual 5m IC Sharpe distribution (not just the gate pass/fail count): `SELECT feature_name, regime, ic_sharpe_hac, ic_ci_lower FROM feature_ic_scores WHERE tf = '5m' AND is_pooled = false ORDER BY ic_sharpe_hac DESC LIMIT 30` — are features close to the gate or universally negative?

**Outcome A1:** Root cause identified and documented. Fix applied or explained.

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

### A4 — 7 Zero-IC Feature Demotion (Phase 143)

- [ ] **A4** — Remove the 7 zero-IC features from `ensemble_weights`. Update `feature_factory.py` if any are computed unnecessarily. Features: momentum_rank_z, poc_dist_atr, sr_resist_dist, sr_support_dist, va_position, volatility_rank_z, volume_rank_z.

---

## Phase B — Corpus Re-run + Empirical Ground Truth

**Goal:** Re-run the full pipeline on the corrected ic_engine. Analyze the results. Determine whether the foundation is ready for shadow deployment.

**Gate to Phase C:** Gate PASS on both 5m and 1h (>=5 qualifying features per TF). If 5m still fails after the methodology fixes, the answer is feature expansion (todos 013/014) before shadow — not proceeding to Phase C.

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
| 009 — Service utils cleanup | Anytime, low priority |
| 012 — Structural compliance | Anytime, medium priority |
| 022 — BI Superset | After Phase D is live |

---

## Hypothesis Register

Three theoretical claims deferred until empirical validation:
- **H1 Gap contamination** — validate in B2c; act only if IC difference >= 0.01
- **H2 Threshold mis-calibration** — validate in B2b; manual APR write if needed
- **H3 IC decay velocity** — observe via C2 over 3+ months before building automation

Full context: `docs/plans/2026-06-30-alphaengine-methodology-hypotheses.md`
