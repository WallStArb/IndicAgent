---
**Created:** 2026-06-28
**Area:** intelligence
**Type:** improvement
**Priority:** P2
**Effort:** 1-2 days
**Benefit:** Improves IC measurement accuracy by removing regime transition label noise
**Risk:** low (optional flag, can measure effect)
**Gate:** Phase 141 complete (OPEN) — do after Phase B corpus re-run to measure effect against corrected baseline. **Note (2026-07-01): also gated on todo 034 landing** — the current Phase B corpus re-run's regime labels are still contaminated by the non-causal HMM fit todo 034 describes; "corrected baseline" isn't corrected for regime-stratified purposes until 034 ships. **Re-gated 2026-07-12 (housekeeping audit):** this todo's fix targets `feature_vectors.regime` (per-symbol HMM labels), but `services/ic_engine.py`'s live measurement path runs with `alpha.regime.equity_model_enabled=true` by default, meaning `_compute_symbol_tf` stratifies on cross-sectional `market_regimes` labels, not `feature_vectors.regime` — confirmed via `.planning/todos/deferred/026-hmm-regime-audit-optimization.md`'s finding that `feature_ic_scores` has zero `regime_scope='symbol_hmm'` rows in the current corpus. This todo's transition-boundary-noise concern may still be real, but it needs to be re-scoped against `market_regimes`' own transition behavior (if any) before being actioned as written — applying a purge mask to a label sequence that isn't the one driving live IC stratification wouldn't change anything measured today.
---

# 005 — IC Engine: Regime Transition Purge Window

**Priority: Medium — correctness improvement, not a blocker**
**Gate: Phase 141 complete (OPEN) — do after Phase B corpus re-run**
**Source:** `docs/plans/2026-06-26-renaissance-optimization-roadmap.md` (IC-003)

---

## Problem

HMM regime labels switch states at discrete boundaries. Bars immediately following a
regime change (e.g., ranging → trending) are assigned the new label but still contain
residual dynamics from the old regime. This introduces label noise into regime-stratified
IC measurements — the transition period biases IC toward zero.

Per the roadmap analysis: "Your regime labels are switching faster than the underlying
dynamics. You're measuring a transition period as if it were pure regime. This biases IC
toward zero (regime misclassification dilutes signal)."

Expected effect: `ic_sharpe` increases 10-20% for regime-dependent features (momentum_z,
hmma_slope_z) after purging transition contamination.

---

## Fix

In `services/ic_engine.py`, add a regime purge window to `_compute_symbol_tf()`:

1. After aligning feature_vectors with regime labels, identify bar indices where
   `regime_label[i] != regime_label[i-1]` (regime change points).
2. Build a boolean mask excluding `±alpha.ic.regime_purge_bars` bars around each change.
3. Apply mask to `X_aligned` and `returns_aligned` before IC computation.

**APR key to add:** `alpha.ic.regime_purge_bars` (default 20) — seed in a migration.

```python
purge_bars = cfg.get_sync("alpha.ic.regime_purge_bars", 20)
regime_arr = np.array([r["regime"] for r in rows])
changes = np.where(np.diff(regime_arr) != 0)[0]
valid_mask = np.ones(len(regime_arr), dtype=bool)
for idx in changes:
    lo = max(0, idx - purge_bars + 1)
    hi = min(len(regime_arr), idx + purge_bars + 1)
    valid_mask[lo:hi] = False
X_aligned = X_aligned[valid_mask]
returns_aligned = returns_aligned[valid_mask]
```

Trade-off: reduces sample size by ~5-10% (regime changes are infrequent relative to
bar count). Acceptable given the IC purity improvement.

---

## Scope

- `services/ic_engine.py` — add purge mask before IC computation
- Migration — seed `alpha.ic.regime_purge_bars = 20` in APR
- Re-run IC pipeline after change to measure effect

Should apply to both per-symbol and cross-sectional IC computation paths.
