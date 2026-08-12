# Renaissance Obstacle Map — IndicAgent v3.1+

**Date:** 2026-06-28  
**Framing:** Council of senior engineers at Renaissance Technologies. Mission: find every threat that produces a silent wrong answer, slows the research loop, or blocks the path to live shadow trading. Ruthless prioritization — no hedging.

---

## North Star

Live shadow trading where:
1. Every alpha_event reflects a net-positive (after costs) IC-validated feature signal.
2. The ensemble weights are stratified by uncontaminated regime labels.
3. Promotion from shadow to live requires passing pre-defined statistical gates — not negotiation.
4. The v2.x I7 binary pipeline is retired, evidence in hand.

The current state: corpus is complete (12.47M alpha_events). But three known validity threats exist in that corpus. Until they are fixed, every downstream result is provisional.

---

## Obstacle Classification

| Class | Description | Stakes |
|---|---|---|
| **V — Validity Threat** | Produces silent wrong answers; data looks correct but isn't | **Ship nothing until fixed** |
| **G — Gate** | Phase cannot start without it | **Sequence blocker** |
| **S — Velocity** | Slows the research iteration loop | Fix before next corpus rerun |
| **D — Debt** | Accumulating cognitive overhead or latent failure mode | Fix in batch |

---

## V1 — Look-Ahead Bias in Cross-Sectional Regime Model

**Class:** V — Validity Threat  
**Severity:** Critical  
**Todo:** 026 (P1a)  
**File:** `equity_regime_model.py:175`

### Problem

`equity_regime_model.py` computes the VIX proxy using SPY realized-vol z-score **percentile rank across all historical bars simultaneously** during backfill. This is look-ahead contamination: each bar's regime label is assigned knowing all future values. In live operation the model sees only data up to the current bar.

The 9 cross-sectional regime labels in `market_regimes` drive IC stratification — they are the primary stratification source in `feature_ic_scores` (all 54,036 cross-sectional rows). The ensemble weights in `ensemble_weights` (328 rows) are computed from these stratified scores.

**Result:** Regime labels in the corpus are more stable and correctly placed than they will ever be in live operation. IC scores stratified by these labels overstate the realized IC the ensemble will achieve live. The ensemble weights are calibrated on contaminated data.

### Fix

Replace `percentile_rank(all bars)` with `expanding_rank(bars up to t)` in the VIX proxy computation (equity_regime_model.py line 175). Also fix TF-normalized windows for VIX z-score and 200MA breadth (P1b, same file, lines 75-76): windows must scale with timeframe, not be hardcoded.

After fixing: rerun `equity_regime_model` + `ic_engine` (cross-sectional only) + `ensemble_trainer` + `alpha_publisher`. Per-symbol IC scores (is_pooled=false) are unaffected.

**Estimated effort:** 4-8 hours fix + ~4-6 hour corpus rerun (steps 4b-6 only).

---

## V2 — Gross vs Net Scoring: Silent Loss at Short Horizons

**Class:** V — Validity Threat  
**Severity:** High at 5m/15m  
**Todo:** 004  
**File:** `services/alpha_publisher.py`, scoring engine

### Problem

The ensemble and alpha_publisher emit **gross expected return** — no transaction cost deduction. At 5m and 15m horizons, transaction costs (spread + slippage) are a non-trivial fraction of the observed IC-weighted edge.

The 9.37M 5m+15m alpha_events in the corpus (7.96M + 1.41M) may include a material fraction of signals that are gross-positive but net-negative. Phase 142 shadow evaluation will measure counterfactual_pnl_r against these events. If costs are not modeled, the shadow P&L distribution will look better than live P&L — and the promotion gate (mean counterfactual_pnl_r > 0 at 95% CI) becomes a false positive.

At 1h and 1d, costs are negligible relative to the expected move. The 3.10M + 2.5K events at those horizons are unaffected.

### Fix

Implement cost-aware net scoring (todo 004) before the corpus rerun triggered by V1:

- `E[R]_net = E[R]_gross - cost_model(symbol, tf)` 
- Conservative static estimate: spread + slippage from APR defaults by asset class
- Apply only at `5m`, `15m` (APR: `alpha.scoring.net_cost_tfs`)
- Emit `expected_r_gross` (diagnostic) and `expected_r_net` (ensemble input) as separate fields
- Rerun alpha_publisher on the same ensemble_weights after fix

This fix is local to the scoring/emission layer and does not require ic_engine or ensemble_trainer reruns.

**Estimated effort:** 1 day fix. Can be done in same batch as V1 corpus rerun.

---

## V3 — BaseBatch JSONB Codec: Latent Corruption Vector

**Class:** V — Validity Threat (latent)  
**Severity:** Medium (currently worked around, but ticking)  
**Todo:** 002  
**File:** `src/core/agent/base_batch.py:124`, `services/alpha_publisher.py:323`

### Problem

`BaseBatch._setup_pool()` calls `asyncpg.create_pool()` without `init=_setup_codecs`. Every BaseBatch-derived service (AlphaPublisher, EnsembleTrainer) has no JSONB codec registered. The current workaround: `alpha_publisher.py:323` manually calls `json.dumps(e["top_features"])` with an explicit `::jsonb` cast.

This works today. The trap: any future developer (or refactor) who "correctly" calls `database_manager.create_pool()` to fix this will activate the codec — but if the `json.dumps()` call sites are not simultaneously removed, every JSONB column stores a string literal (`"\"{ ... }\""`) instead of an object. Queries using `->>` will silently return wrong results.

CLAUDE.md rule: `asyncpg: JSONB → dict (no json.loads()/json.dumps())`. This is an active violation.

### Fix

Step 1 and Step 2 must land in the same commit (atomic):
1. Replace `asyncpg.create_pool(self._db_dsn, ...)` in `BaseBatch._setup_pool()` with `database_manager.create_pool(self._db_dsn, ...)`.
2. Remove `json.dumps(e["top_features"])`, `import json`, and `::jsonb` cast from `alpha_publisher.py:323`.
3. Grep all BaseBatch subclasses for other `json.dumps()` JSONB workarounds; remove them.
4. Add a unit test: BaseBatch-derived service inserts Python dict into JSONB column without manual serialization.

**Estimated effort:** 2-4 hours. Fix immediately; no gate.

---

## G1 — Phase 141 (IC Validation) Not Built

**Class:** G — Gate  
**Severity:** Blocks all downstream phases  
**Status:** Planned, unblocked after V1 corpus rerun completes

### Problem

The corpus is complete — but "we have data" is not the same as "the features predict returns." Phase 141 must prove IC > 0 with p < 0.05 (sufficient N) across the full 58-symbol corpus before any capital-risking downstream work (Phase 142 shadow trading) is justified.

Currently no Phase 141 plan exists. It was marked "planned — blocked on corpus pipeline." The corpus pipeline is now unblocked.

### What Phase 141 Delivers

- Per-feature IC Sharpe ranked table (which of the 54 features actually predict?)
- Per-regime breakdown (which regimes produce IC > 0?)
- Statistical significance report: p < 0.05 gate, bootstrapped CI, minimum N validation
- Features that fail the gate are flagged for demotion (15 — feature lifecycle, todo 015)
- Outcome documents go to `docs/analysis/ic-validation-report-58sym.md`

**Sequence:** Phase 141 must run on the V1-corrected corpus. Do not run Phase 141 on contaminated cross-sectional regime data.

**Estimated effort:** 2-3 days (analysis + report writing, minimal new code).

---

## G2 — Shadow Monitoring Protocol Undefined Before Phase 142

**Class:** G — Gate  
**Severity:** Architecture violation if Phase 142 ships without this  
**Todo:** 011  
**Note:** Must be built as part of Phase 142 launch, not deferred to Phase 143

### Problem

Phase 142 deploys alpha_events in shadow mode (`is_shadow=true`) with counterfactual_pnl_r measurement. A shadow deployment without pre-defined:

1. Monitoring panels (emission rate, P&L distribution, win rate, VaR headroom)
2. Review cadence (who, when, what criteria)
3. Promotion gate criteria defined before shadow starts

...is not scientific shadow testing. It is deployment with delayed detection and post-hoc gate negotiation. Post-hoc negotiation is forbidden: "the numbers were almost there, let's lower the threshold" invalidates the experiment.

### What Must Exist at Phase 142 Launch

**Grafana panels:** Shadow emission rate per (symbol, TF, regime) with 7-day rolling alert if drops >50% week-over-week. Counterfactual P&L histogram. Rolling 20-day win rate per (symbol, TF). VaR headroom vs limit. Alpha score distribution at emission (monitors for ensemble weight decay).

**SHADOW-REVIEW.md:** Written at Phase 142 launch, not after. Contains: promotion gate criteria (≥60 trading days, mean counterfactual_pnl_r > 0 at 95% CI, Sharpe > 0.5 annualized, max drawdown < 25%), review cadence, alert thresholds.

**Estimated effort:** 1-2 days. Must land in Phase 142 plan as non-negotiable scope.

---

## S1 — HMM Regime Writer: 20+ Hour Runs Kill Iteration

**Class:** S — Velocity  
**Severity:** High — every parameter change requires a full day wait  
**Todo:** 026 (P0)  
**File:** `regime_writer.py:234`

### Problem

Per-symbol HMM inference runs in pure Python. Full 58-symbol corpus refit = 20+ hours. This is the primary bottleneck on the research iteration loop. Every time K changes, observation vector changes, or new data arrives, we pay 20 hours to validate the result.

Numba JIT on the forward-filter pass (the innermost loop) reduces this to ~30 minutes — a 40x speedup.

### Fix

New module `src/intelligence/hmm_jit.py` implementing `@numba.njit`-decorated forward filter and Viterbi. Regime writer calls it instead of the pure Python path. Numba is already in the dependency graph (or trivially added). First call triggers JIT compile (~30s); subsequent calls hit the compiled path.

**Do not block the corpus rerun on this** — implement after V1/V2 fixes and Phase 141. But plan it before any further parameter exploration (HMM K, observation dimensions).

**Estimated effort:** 3-5 days.

---

## S2 — IC Engine Parallelism Gaps (128.9s/symbol skip cost)

**Class:** S — Velocity  
**Severity:** Medium  
**File:** `services/ic_engine.py`

### Problem

Three parallelism gaps documented:

1. **APR `infra.ic_engine.workers = 2`** — was set as conservative initial value; should be 12 (matching CPU availability confirmed during HMM improvement).
2. **Per-symbol skip guard missing** — `ic_engine` takes 128.9s per symbol even when skipping (pre-computation guard needed). With 58 symbols × 4 TFs = 232 cells, skipping all takes 7.5 hours.
3. **Cross-sectional path: 36 cells in main process** — no parallelism; should match per-symbol ProcessPoolExecutor pattern.

APR fix is a one-line change to `config_state`. The skip guard and cross-sectional parallelism are code changes. Together these reduce a full-corpus rerun from hours to tens of minutes at the ic_engine step.

**Estimated effort:** 4-8 hours (skip guard + cross-sectional parallelism); APR update is 5 minutes.

---

## S3 — Forward Return Writer: Serial 232-Cell Run

**Class:** S — Velocity  
**Severity:** Medium  
**File:** `services/forward_return_writer.py`

### Problem

Forward return writer runs 1 worker serial across 232 cells (58 symbols × 4 TFs). ProcessPoolExecutor pattern already proven in ic_engine and regime_writer. This is a direct parallelism gap: no architectural constraint prevents it.

**Estimated effort:** 4-8 hours (parallel with S2 above — same pattern).

---

## D1 — I7 Dual Pipeline: No Retirement Criteria Defined

**Class:** D — Strategic Debt  
**Severity:** High cognitive overhead  
**Todo:** 016

### Problem

Two intelligence pipelines coexist with no defined retirement date or criteria:
- v2.x I7: binary emission, hand-coded confluence rules, no IC validation
- v3.0 AlphaEngine: continuous alpha score, IC-measured features, ensemble gate

Every schema change must consider both systems. Every bug investigation starts with "which pipeline produced this?" The v2.x system embeds researcher hypotheses that have never been validated against forward returns. Running them in parallel does not make the system more robust — it makes attribution impossible.

### Fix

Phase 144 (v2.x retirement gate) requires a defined promotion/retirement plan now. The path (from todo 016):

1. Add `alpha_score` column to `signal_events` (NULL for legacy rows).
2. Convert I7 plugins from binary emitters to alpha scorers (`alpha_score = confidence × direction`); no emission decision inside the plugin.
3. The ensemble IS the emission decision.
4. After 60 trading days of shadow comparison (Phase 142), if v3.0 Sharpe > v2.x Sharpe at 95% CI: retire v2.x.

The plan must be documented before Phase 142 starts, not derived post-hoc from shadow results.

**Estimated effort:** The plan write-up is 1 day. Execution (plugin conversion) is 3-5 days gated on Phase 141 + 142 shadow stability.

---

## D2 — APR Violations in `services/` (Architecture Violations)

**Class:** D — Structural Debt  
**Severity:** Medium  
**Todo:** 012 (Part A)

### Problem

CLAUDE.md is unambiguous: "Hard-coded numeric thresholds, weights, periods, or counts in `src/` or `services/` are an architecture violation." Audit shows approximately 6 module-level numeric constants in `services/` that are not APR-backed.

**Fix:** Migrate in one batch (todo 012 Part A) after Phase 141 IC validation confirms stable IC baseline. Not blocking but accumulates with each new service added.

**Estimated effort:** 2-3 hours.

---

## Recommended Sequence

The critical path to live shadow trading, free of known validity threats:

```
TODAY
  └─ D3 (V3): Fix BaseBatch JSONB codec — no gate, 2-4 hours (latent corruption)

SPRINT 1 (~1 week)
  ├─ V1: Fix equity_regime_model expanding rank + TF-normalized windows
  ├─ V2: Implement cost-aware net scoring (E[R]_net) in alpha_publisher
  ├─ S2: APR workers=12 one-liner; add ic_engine skip guard
  └─ Rerun corpus steps 4b–6 (equity_regime_model → ic_engine cross-sectional → ensemble_trainer → alpha_publisher)
     Uses V2 net scoring; S2 makes this run fast

SPRINT 2 (~1 week)
  ├─ G1: Phase 141 — IC Validation Report on corrected 58-symbol corpus
  └─ D1: Write v2.x retirement plan (I7 transition criteria, SHADOW-REVIEW.md skeleton)

SPRINT 3 (~2 weeks)
  ├─ G2 + Phase 142: Portfolio construction + shadow mode
  │   Shadow monitoring protocol (G2) is non-negotiable Phase 142 scope
  │   SHADOW-REVIEW.md promotion gates written before shadow launch
  └─ S1: HMM Numba JIT (parallel with Phase 142 — needed before next parameter sweep)

SPRINT 4+ (gated on 60 trading days shadow data)
  ├─ D1 execution: I7 plugin conversion to alpha scorers
  ├─ 014: Feature primitives expansion (~60 candidates, re-run corpus after)
  ├─ 013: Cross-sectional rank features (momentum_rank_z, volume_rank_z)
  └─ Phase 144: v2.x retirement with evidence
```

---

## What Not to Do

1. **Do not run Phase 141 on the current corpus.** Cross-sectional IC scores are contaminated by look-ahead bias (V1). Running Phase 141 now produces a report that will be invalidated by the corpus rerun. Wait for Sprint 1 to complete.

2. **Do not build Phase 142 without shadow monitoring gates pre-defined.** Shadow mode without pre-defined promotion criteria is not a scientific experiment. It is a deployment with delayed detection.

3. **Do not expand primitives (todo 014) before Phase 141 validates the existing 54 features.** Adding 60 new features to an IC engine whose regime stratification is contaminated doubles the corpus rerun time while learning nothing reliable. Validate the foundation before expanding it.

4. **Do not defer the I7 retirement plan.** The longer the dual pipeline runs, the more attribution debt accumulates. The plan (not execution) should exist before Phase 142 starts so shadow comparison has a defined endpoint.

---

## Open Questions for Review

1. **V1 severity:** How large is the look-ahead bias in practice? Expanding rank for a percentile converges as bars accumulate — the contamination may be concentrated in early 2020-2022 bars. Should we quantify the before/after delta in regime label stability before committing to full ic_engine rerun, or accept the rerun cost as insurance?

2. **V2 sequencing:** Cost-aware net scoring requires per-symbol spread estimates. Using APR defaults (static estimates) is conservative and immediately implementable. Should Phase 1 use static defaults, or should we pull last-observed bid/ask from `market_data_ohlcv` for a per-symbol estimate? The static default is faster and sufficient for the corpus rerun; per-symbol calibration is Phase 2.

3. **S1 gate:** Numba JIT for HMM is 3-5 days of engineering. Should this block the corpus rerun in Sprint 1, or run the corrected corpus with the existing 20-hour regime_writer and implement Numba JIT in Sprint 3 (before the next parameter sweep)?

4. **Phase 141 scope:** IC Validation — analysis only (read existing feature_ic_scores, write report) or does it include any new service code? Recommendation: analysis-only; the data is there, the service is not needed. But if Phase 141 also implements the IC gate and feature demotion trigger (todo 015), it becomes a code phase.
