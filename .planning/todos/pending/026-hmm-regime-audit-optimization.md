---
**Created:** 2026-06-28
**Updated:** 2026-06-29
**Area:** intelligence
**Type:** optimization
**Priority:** P0-P3 actionable; P4a/P4b gated (see below)
**Effort:** 3-5 days (P0-P3) + 8-12h compute (P4, if validated)
**Risk:** low
**Gate:** P0-P3 have no gate; P4a/P4b require empirical IC proof first
---

# 026 — HMM Regime Audit & Optimization

**Plan:** `docs/plans/2026-06-28-hmm-regime-audit-optimization.md`

Consolidates and supersedes:
- 007-numba-jit-hmm-inference.md
- 023-hmm-parameter-lookahead-bias.md
- 999-hmm-parameter-lookahead-validation.md

## Findings

10 gaps across per-symbol HMM (`regime_writer.py`) and cross-sectional model (`equity_regime_model.py`):

| Priority | Finding | File |
|---|---|---|
| P0 | Numba JIT forward-filter — 20+ hr → ~30 min | `regime_writer.py:234`, new `hmm_jit.py` |
| P1a | Expanding rank for cross-sectional VIX proxy (look-ahead bug) | `equity_regime_model.py:175` |
| P1b | TF-normalized windows for VIX z-score and 200MA | `equity_regime_model.py:75-76` |
| P2a | Multiple HMM restarts, pick max log-likelihood | `regime_writer.py:377` |
| P2b | Degenerate model detection (occupation fraction gate) | `regime_writer.py:439` |
| P2c | Regime churn feature (`hmm_churn` column) | `regime_writer.py` + migration |
| P3 | Empirical threshold calibration for vix/breadth cuts | `equity_regime_model.py` APR |
| P4a | Rolling HMM refit (parameter look-ahead bias) | `regime_writer.py` — **GATED** |
| P4b | Expanding StandardScaler | `regime_writer.py:375` — **GATED on P4a** |

See plan doc for full implementation notes and APR keys.

---

## P4a/P4b — Rolling Refit & Expanding Scaler (GATED)

**Status:** DEFERRED — no empirical evidence that current labels are broken.

**Background:** HMM is fit on full history (2014-2024), causally decoded via forward-filter. Forward-filter is causal (no future information in the decode step), but emission parameters and transition matrix are learned from the full window including future data. The question is whether this materially harms IC predictive power.

**2026-06-29 finding:** A rolling refit pilot was built and then killed before writing to production. When we went to measure whether improvement was needed, `feature_ic_scores` was empty (truncate script had cleared it). No baseline = no proof of a problem.

**Renaissance mandate:** Do not optimize what should be deleted. Measure first.

### Decision Gate — ALL must be true before any P4 work

1. `feature_ic_scores` is populated (IC engine has run)
2. Current regime labels show poor IC separation — e.g. trending_up IC ≈ trending_down IC (gap < 0.01)
3. Root cause analysis confirms parameter look-ahead bias is the driver (not regime irrelevance)
4. Rolling refit pilot shows ≥10% IC improvement (shadow mode, p < 0.05)

**If any gate fails → drop P4a and P4b entirely.**

### How to validate (when IC data exists)

**Step 1 — Measure baseline separation (5 min):**
```sql
SELECT regime, AVG(ic_value) as mean_ic, STDDEV(ic_value) as ic_std, COUNT(*) as n
FROM feature_ic_scores
WHERE is_pooled = false AND symbol IN ('SPY', 'TLT') AND tf IN ('5m', '1h')
GROUP BY regime
ORDER BY regime;
```
Expected if labels work: `trending_up` mean_ic > 0, `trending_down` mean_ic < 0, gap > 0.05.
If gap < 0.01 → proceed to Step 2. If gap > 0.05 → labels are fine, stop.

**Step 2 — Root cause analysis (1 hour):**
Compare IC separation across: (a) current labels (full-history fit), (b) time-truncated labels (fit 2019-2022 only, decode 2023), (c) cross-sectional regimes (`market_regimes` table). If (b) or (c) shows materially better separation → parameter bias is the issue.

**Step 3 — Rolling refit pilot (shadow mode):**
- Scope: SPY + TLT, 5m + 1h only
- Method: 3-year rolling window, annual step
- Write to `feature_vectors.regime_rolling` (migration 184 already applied — column exists)
- Compare IC scores `regime` vs `regime_rolling`
- Success: ≥10% IC improvement, p < 0.05, label disagreement ≥20%

**Step 4 — Full corpus rollout (ONLY if pilot succeeds):**
- 58 symbols × 4 TFs = ~3,480 HMM fits; 8-12h compute
- APR keys: `alpha.hmm.rolling_window_bars`, `alpha.hmm.rolling_step_bars`
- Shadow mode toggle in `regime_writer.py`; monitor 3 months before promoting to production

### Infrastructure already done
- Migration 184: `feature_vectors.regime_rolling` column exists
- `docs/experiments/2024-06-29-hmm-rolling-refit-pilot.md` — experiment doc
- Pilot code was deleted (2026-06-29) — rebuild from scratch if gates pass
