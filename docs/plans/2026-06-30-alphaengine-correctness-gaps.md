# AlphaEngine V1 — Correctness Gaps

**Date:** 2026-06-30
**Status:** Active — three gaps from the binding methodology spec
**Methodology reference:** `docs/intelligence/intelligence-alphaengine-methodology.md`
**Tracking:** todo 031 (gap IC) · todo 032 (empirical thresholds) · todo 033 (decay monitor)

These are not aspirational enhancements. They are correctness gaps in a system whose
invariants demand them. Each was designed in the original spec; implementation was deferred
while the pipeline was built.

---

## Execution Order

The gaps are causally ordered. Implementing them out of sequence produces a system that
is worse than the status quo:

```
[031] Gap-Stratified IC          →  cleaner measurement corpus
          ↓
[032] Empirical Thresholds        →  requires clean IC + todo 030 (cost calibration)
          ↓
[033] Alpha Decay Monitor         →  wraps the re-solve cycle; meaningful only after
                                     weights are trustworthy and thresholds are empirical
```

Gap 1 (decay monitor) listed first in the original draft was wrong — implementing it
on top of contaminated IC and researcher-set thresholds would trigger re-solves of a
corrupt ensemble.

---

## Gap 1 — Gap-Stratified IC Measurement (todo 031)

**What:** In `ic_engine.py`, separate IC measurement for bars where
`forward_returns.has_gap_before_entry = true` vs `false`. If gap IC differs significantly
from non-gap IC, exclude gap observations from the production ensemble.

**Why this is a correctness gap:** Overnight and holiday gaps are a structurally different
return distribution from intraday IC. A feature may have positive intraday IC (e.g.,
momentum at market open) but negative gap IC (mean-reversion after overnight news). Mixing
them produces a weighted average that understates IC for both populations and may produce a
net-zero IC for a genuinely predictive feature. This is exactly the kind of hidden bias the
methodology is designed to prevent.

**`has_gap_before_entry` is already populated** in `forward_returns`. The ic_engine
currently ignores it.

**Design:**

In `_compute_symbol_tf()` and `_compute_pooled_cross_sectional()`, after aligning
feature_vectors with forward_returns:

```python
gap_mask = np.array([r["has_gap_before_entry"] for r in aligned_rows])
non_gap_mask = ~gap_mask

# Measure IC on non-gap observations (primary)
ic_non_gap = compute_spearman_ic(X[non_gap_mask], returns[non_gap_mask])

# Measure IC on gap observations (diagnostic)
if gap_mask.sum() >= min_n:
    ic_gap = compute_spearman_ic(X[gap_mask], returns[gap_mask])
    # Write both to feature_ic_scores with has_gap_before_entry flag

# Production ensemble uses ic_non_gap by default
# If |ic_gap - ic_non_gap| > threshold: log warning, flag for review
```

Gate behind `alpha.ic.gap_stratified = false` initially. Measure the effect on IC before
making it the default. The corpus re-run cost is non-trivial.

**APR keys to add:**

| Key | Default | Description |
|-----|---------|-------------|
| `alpha.ic.gap_stratified` | `false` | Enable gap-stratified IC measurement `[user_preference]` |
| `alpha.ic.gap_ic_divergence_threshold` | 0.02 | Flag for review when gap/non-gap IC differ by this much `[initial_estimate]` |

**Schema change:** Add `has_gap_before_entry boolean` to `feature_ic_scores` to record
which population each row was measured on. Requires a migration.

**Files:**
- `services/ic_engine.py` — add gap stratification in `_compute_symbol_tf()` and cross-sectional path
- Migration — add `has_gap_before_entry` column to `feature_ic_scores`, add APR keys

---

## Gap 2 — Empirical Emission Threshold Derivation (todo 032)

**What:** Derive `alpha.quant.threshold.{tf}` empirically from ensemble IC and estimated
transaction costs, rather than leaving them as researcher-set seeds.

**Why this is a correctness gap:** The current thresholds (5m=1.5, 15m=1.2, 1h=1.0,
1d=0.8) are researcher estimates with no empirical grounding in the actual ensemble IC. The
methodology specifies that the threshold should be the lowest alpha_score where expected
return exceeds estimated transaction cost. A researcher-set threshold is exactly the kind of
human judgment the AlphaEngine architecture is designed to eliminate.

**Dependencies:** Requires Gap 1 complete (clean non-gap IC corpus) and todo 030 complete
(empirical cost hurdles). Both must reflect the same corpus state before the threshold
sweep is meaningful.

**Design:**

After each `EnsembleBuilder` run that produces a new `weight_version`, run a threshold
sweep on the training corpus:

```python
ensemble_ic = compute_spearman_ic(ensemble_alpha.alpha_score, forward_returns.return_fast)

for tf in ["5m", "15m", "1h", "1d"]:
    cost_estimate = cfg.get("alpha.scoring.equity_spread_default_r") + \
                    cfg.get("alpha.scoring.slippage_default_r")

    for theta in np.linspace(0.1, 3.0, 100):
        subset = ensemble_alpha[ensemble_alpha.tf == tf]
        subset = subset[subset.alpha_score.abs() >= theta]
        if len(subset) < min_n:
            continue
        expected_return = subset.alpha_score.abs().mean() * ensemble_ic
        if expected_return > cost_estimate:
            new_threshold = theta
            break

    config_service.set(f"alpha.quant.threshold.{tf}", new_threshold,
                       changed_by="ensemble_builder",
                       reason=f"empirical sweep: IC={ensemble_ic:.4f}, cost={cost_estimate:.4f}")
```

**When to run:** After every `EnsembleBuilder` re-solve where ensemble IC changes by >=
`alpha.ic.threshold_update_min_ic_change` (default 0.15). Record in `config_history`.

**APR keys to add:**

| Key | Default | Description |
|-----|---------|-------------|
| `alpha.ic.threshold_update_min_ic_change` | 0.15 | Minimum IC change to trigger threshold re-derivation `[initial_estimate]` |
| `alpha.ic.threshold_sweep_min_n` | 100 | Minimum bars above threshold candidate to evaluate `[initial_estimate]` |

**Files:**
- `services/ensemble_trainer.py` — add `_derive_emission_thresholds()` method, call after weight write
- Migration — add two APR keys above

---

## Gap 3 — Alpha Decay Monitor (todo 033)

**What:** A daily service (`services/alpha_decay_monitor.py`) that runs rolling IC on the
last W=2,000 independent observations per (feature, symbol, tf, regime) cell and triggers
an `EnsembleBuilder` re-solve when IC decays below threshold.

**Why this is a correctness gap:** Without it, ensemble weights are permanently frozen at
the values computed from the initial corpus run. Features that have lost edge stay in the
ensemble at full weight. The system has no self-correction mechanism. This is not a
monitoring gap — it is a fundamental violation of the architecture invariant that weights
must track IC over time.

**Dependencies:** Requires Gaps 1 and 2 complete. A decay monitor that triggers re-solves
of an ensemble built on contaminated IC and researcher-set thresholds propagates corruption
rather than correcting it.

**Schema is ready:** `feature_ic_scores` already has `is_decaying`, `decay_detected_at`,
`recovery_eligible_at` columns. `ensemble_weights` has `decay_triggered_at`,
`recovery_confirmed_at`. Nothing blocks implementation once upstream gaps are closed.

**Design:**

```
Daily at 06:00 UTC:
1. For each active (feature, symbol, tf, regime) cell in current weight_version:
   a. Pull last 2,000 independent observations from feature_vectors × forward_returns
      (same N-bar sub-sampling as IC Engine, non-gap observations only)
   b. Compute Spearman IC + 2,000-resample bootstrap CI
   c. Write new feature_ic_scores row (training_window_end = today)

2. Decay check:
   if ic_ci_lower <= alpha.decay.ci_lower_threshold
   AND weight × |ic_ci_lower| > alpha.decay.materiality_threshold:
       → set is_decaying = true
       → trigger EnsembleBuilder oneshot (full Ledoit-Wolf re-solve, exclude decayed cells)
       → log to config_history

3. Regime-shift detection:
   if fraction of decaying cells >= alpha.decay.regime_shift_fraction:
       → classify as regime shift (NOT individual decay)
       → log to config_history with reason='suspected_regime_shift'
       → do NOT zero weights; do NOT trigger re-solve

4. Recovery check (only for cells where now() >= recovery_eligible_at):
   if ic_ci_lower > 0 on non-overlapping window:
       → mark recovered, trigger EnsembleBuilder re-solve
```

**APR keys to add:**

| Key | Default | Description |
|-----|---------|-------------|
| `alpha.decay.ci_lower_threshold` | 0.0 | IC CI lower bound below which decay is flagged `[conventional]` |
| `alpha.decay.materiality_threshold` | 0.001 | weight × \|ic_ci_lower\| must exceed this to trigger re-solve `[initial_estimate]` |
| `alpha.decay.regime_shift_fraction` | 0.60 | Fraction of cells decaying simultaneously → regime shift `[initial_estimate]` |
| `alpha.decay.rolling_window_obs` | 2000 | Independent observations in rolling IC window `[conventional]` |

**Files:**
- `services/alpha_decay_monitor.py` (new — extends `BaseBatch`)
- New migration for APR keys above
