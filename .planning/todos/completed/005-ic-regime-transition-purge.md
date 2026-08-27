---
**Status:** CLOSED 2026-08-27
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

**Gate cleared 2026-07-30 (todo-priorities audit):** the 094→096→088 sequencing chain this was
waiting on is now fully closed (PRIORITIES.md: "Status 2026-07-29: the entire chain is now fully
closed" — 096 and 088 both moved to `completed/`). The "do not implement yet" instruction below
no longer applies on that basis. This todo's OWN scoping question above (rewrite against
`market_regimes` vs. fix at the source in `equity_regime_model.py`) is still open and unrelated
to the cleared gate — that decision, not the sequencing chain, is what's left before
implementing.

**Re-verified 2026-08-02 (user asked "is this still valid"):** confirmed against current live
code, not just this todo's own history. `equity_regime_model.py` is deprecated as of Phase 144
(2026-07-12), superseded by `services/cross_sectional_regime_model.py` as the actual live
`market_regimes` label source. Checked that successor directly: it has **zero hysteresis/
smoothing logic anywhere in the file** -- same transition-flicker gap this todo originally found,
carried over unchanged (Phase 144's own docstring confirms it was a pure architectural
generalization, no functional change to the label-generation algorithm itself). `docs/research/
stratification-dimension-unification.md` independently corroborates this is a known, unaddressed
gap for percentile-rank-based regime dimensions (its own line ~496-497 notes `regime_writer.py`'s
`min_hold_bars` smoothing pattern "applies to a percentile-rank series" too -- i.e. the same fix
this todo's "corrected fix target" section already proposed). **Verdict: still necessary and
valid.** Correct the stale file citation to `cross_sectional_regime_model.py` when this is
finally scoped. Recommend the "fix at the source" option over the downstream `ic_engine.py`
purge mask, consistent with both this todo's own 2026-07-19 reasoning and the unification doc's
stated remediation path.

**Sequencing note:** do NOT implement this while the in-flight `ic_engine` corpus pass
(started 2026-07-30, still running as of 2026-08-02) is active -- it's consuming today's
unsmoothed `market_regimes` labels for its cross-sectional equity/rates computation. Changing
the regime-generation algorithm mid-run would invalidate that run's results from the point of
change forward, same class of risk as todos 226/229. Sequence after that run completes.

**Measurement-first design doc written 2026-08-02:**
`docs/plans/2026-08-02-regime-label-transition-quality-measurement-design.md`. Rejects the
10-20% ic_sharpe claim above as unverified (traced to a planning doc, never measured). Specs
a read-only diagnostic (no production changes) that measures, out-of-sample, whether
combined-label hysteresis smoothing and/or a purge window actually move IC, before either
gets implemented. Went through an Opus review (5 Critical findings) and a full rewrite;
every load-bearing number in the final version independently re-verified against the live
DB. This todo's own "fix" code sample (the purge-mask sketch below) is superseded by that
spec's Component 3 (splits into `purge_back`/`purge_fwd` with per-scale widths) -- read the
spec before implementing anything here.

**Sequencing relative to todo 080/L5-1, 2026-08-02:** not a duplicate of that todo (different
consumer -- IC measurement here vs. ensemble scoring there -- different fix mechanism,
different gate criteria). But if this todo's diagnostic promotes combined-label smoothing at
the source, that independently reduces the boundary flicker feeding todo 080's L5-1 question.
**This todo runs first.** Todo 080's Phase 0 diagnostic should not be trusted as a final
materiality reading if run before this one resolves.

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

## Fixed, 2026-08-27

Fixed at the source (option 2 of the two approaches this file's own 2026-07-19 note
weighed), not via a downstream purge mask in `ic_engine.py`: `services/
cross_sectional_regime_model.py`'s `_assign_labels` now applies a causal min-hold-bars
hysteresis smoother (`_smooth_labels`, ports `regime_writer.py`'s existing
`_smooth_states` pattern to string tier labels) to each tier dimension independently
before combining into `regime_label`. New APR key
`alpha.regime.cross_sectional.min_hold_bars=3` (migration 326), same value/provenance
as `regime_writer.py`'s own `feature.hmm.min_hold_bars`.

**Verified via a real write through the production entry point** (`--tf 1h`, all 4
enabled regime groups), not just synthetic unit tests -- before/after bar-to-bar
label-churn measurement against the live DB:

| Group | Raw (pre-fix) churn | Post-fix churn |
|---|---|---|
| equity | 5.6% | 5.4% |
| rates | 18.3% | 7.0% |
| fx | 63.7% | 7.4% |
| commodity | 84.0% | 6.0% |

**This surfaced a materially more severe finding than the original filing's framing:**
commodity and fx regime labels were flipping on the majority of consecutive bars
before this fix -- not "occasional boundary noise" but near-random label assignment,
contaminating essentially every commodity/fx regime-stratified IC measurement in the
corpus's history. Post-fix, all four groups converge to a tight, sane 5.4%-7.4% band
with no group-specific tuning needed. No label vocabulary collapsed to
degenerate/unreachable states for any group (full vocabulary confirmed present
post-fix for all 4 groups).

17 new unit tests (`tests/unit/test_cross_sectional_regime_model.py`), hand-traced
against the implementation before running, all passing. Full `tests/unit/` suite
green. Blast radius: same class as an `HMM_RANDOM_STATE` change -- requires a
`market_regimes` relabel (`cross_sectional_regime_model.py`, step 4) + full
`ic_engine` recompute (step 5) to take effect corpus-wide; deliberately fixed
*before* launching the pending post-Phase-173 corpus recompute rather than after, to
avoid a second multi-day recompute cycle in the same week.
