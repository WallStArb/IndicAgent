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

**Re-scoped 2026-07-19 (correction, not just re-gating):** verified `services/equity_regime_model.py`
directly — `_compute_tf_regimes()` (the live `market_regimes` label source, since
`equity_model_enabled` defaults true) does **pure per-bar VIX-percentile × breadth-fraction
threshold bucketing with zero hysteresis** (`np.where(vix_np < vix_low_pct, "low", ...)`,
recomputed independently every bar). By contrast `services/regime_writer.py` (the per-symbol HMM
path this todo's code sample actually targets, `feature_vectors.regime`) already has a
`_smooth_states()` minimum-holding-period smoother — it does not need this fix. So the 2026-07-12
note was right that the fix targets the wrong table, but the underlying concern is *more* live
than that note implied: the actual live stratification source (`market_regimes`) has **no
transition guard of any kind**, not even the existing HMM path's protection. A bar right at a VIX
threshold crossing can flip `market_regimes.regime_label` on literally the next tick with nothing
smoothing it.

**Corrected fix target:** rewrite the purge-window logic below against `market_regimes` labels in
`ic_engine.py`'s `_compute_symbol_tf`/`_compute_cross_sectional_tf` (both read `mr_dict`/join
`market_regimes` when `equity_model_enabled=true`), not `feature_vectors.regime`. Equivalently,
consider adding a hysteresis/min-hold-bars smoother directly in `equity_regime_model.py`'s
`_compute_tf_regimes()` (mirroring `regime_writer.py`'s existing pattern) instead of a
downstream purge mask in `ic_engine.py` — that would fix the label quality at the source for
every consumer of `market_regimes`, not just IC measurement, and is arguably the more Renaissance-
grade fix (don't patch a symptom in the measurement layer when the generating process is the
actual defect). Worth deciding between the two approaches before implementing.

**Do not implement yet:** this todo's fix target overlaps directly with the files the active
143.1 sequencing chain (todo 094 → 096 → 088, see PRIORITIES.md P0) is currently validating
(`ic_engine.py`'s regime-stratification path). Land after that chain clears, per the same
reasoning as todo 009's Part E deferral — don't double the diff on code someone else is mid-way
through re-validating.

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
