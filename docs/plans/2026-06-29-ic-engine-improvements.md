# IC Engine Improvements Plan

Date: 2026-06-29
Status: OPEN — prioritized backlog; P0/P1 are correctness issues, P2+ are quality improvements

Renaissance Council audit of `services/ic_engine.py`. The engine's foundation is sound
(executable-only returns, Fisher z-transform CI, per-scale stride, HAC Sharpe, BH-FDR,
cluster redundancy reduction, serial writes). These findings are the gaps on top of that.

---

## P0 — Walk-forward is cross-validation, not walk-forward (correctness bug)

**File:** `services/ic_engine.py:882-885`

**Issue:** The current fold construction:
```python
train_end = int(n_valid * (k+1) / (walk_forward_folds+1))
test_start = train_end + embargo_bars
test_end = int(n_valid * (k+2) / (walk_forward_folds+1))
```
This partitions the full observation window into equal segments and tests each middle
segment. That is cross-validation with an embargo, not walk-forward. The contamination:
fold k's test window is validated against a training set that contains bars from *after*
the test period (the later folds' training data). True walk-forward trains on [0..T] and
tests on [T+embargo..T+window], advancing T monotonically. The middle fold currently sees
future training data.

**Fix:** Replace the symmetric partition with expanding-window walk-forward:
```python
for k in range(walk_forward_folds):
    train_end = int(n_valid * (k + 1) / (walk_forward_folds + 1))
    test_start = train_end + embargo_bars
    test_end = int(n_valid * (k + 2) / (walk_forward_folds + 1))
    # ONLY use X[0:train_end] as training context -- never rank against future bars.
    # Currently ranking is done on X[test_start:test_end] in isolation, so the
    # contamination is in the *training set definition*, not the rank computation.
    # The fix: add an assertion that test_end <= n_valid and that no test bar
    # precedes any training bar.
```
The simplest correct formulation: each fold's test window must be strictly after all
training bars. Folds advance forward in time; none looks back at future data.

**Note:** The actual Spearman rank is computed on the test window slice only (no training
data used in the rank). The contamination is conceptual -- the "walk-forward" label is
incorrect and the fold boundaries don't guarantee temporal ordering. In practice the
current implementation may be approximately correct (no explicit future leakage in the
rank computation), but the methodology claim in the docstring is wrong and should be fixed
for rigor.

---

## P1 — No trailing IC series: ensemble weighter is flying blind on recency

**Files:** `services/ic_engine.py`, `feature_ic_scores` schema

**Issue:** The engine produces a single IC number per `(feature, symbol, tf, regime,
lookahead)` from the full training window. That number is written once and treated as
static by the ensemble weighter. IC is non-stationary -- a feature with IC=0.08 over 5
years could have IC=0.15 in the last 6 months and IC=-0.02 in the last 3 months. The
ensemble weighter has no visibility into which of those is true *now*.

**What Renaissance does:** Signals are re-scored daily on recent data. The static
historical estimate is a prior; the recent trailing estimate is the signal quality input
to position sizing.

**Proposed design:**
- Add `ic_trailing_series` table: one row per `(feature, symbol, tf, regime, lookahead,
  window_end_date)` -- same schema as `feature_ic_scores` but keyed by time.
- IC engine adds a `--trailing-mode` flag: runs IC on a rolling window (e.g. trailing 60
  trading days of bars, stepping forward 1 TF bar at a time or N bars for efficiency).
- Ensemble weighter reads `ic_trailing_series` WHERE `window_end_date >= now() - interval
  '30 days'` instead of the static `feature_ic_scores`.
- Staleness: if trailing IC is unavailable (ic_engine hasn't run recently), fall back to
  static `feature_ic_scores` with a staleness penalty.

**The "60-day rolling IC"** referenced in earlier discussions is this: a 60-trading-day
trailing window, slid forward 1 bar (or N bars for compute budget), producing a time
series of IC estimates per cell. This answers "is this feature still working *now*?" vs
"did this feature work on average over the last 5 years?"

**Gate:** Requires static IC corpus to be complete and validated first (corpus pipeline
done as of 2026-06-29). Trailing mode is a second pass on top of the existing corpus.

**Compute cost:** ~60x the static run (one pass per trailing window position). Numba JIT
on the regime_writer (todo 026 P0) is not a prerequisite, but the trailing IC run will
benefit from any performance improvements made to the underlying compute path.

**APR keys:** `alpha.ic.trailing_window_bars`, `alpha.ic.trailing_step_bars`

---

## P2 — BH-FDR family is per-cell, not corpus-wide (inflated false discovery rate)

**File:** `services/ic_engine.py` — BH-FDR applied inside `_compute_symbol_tf`

**Issue:** The engine collects p-values across all features × regimes × scales for one
`(symbol, tf)` cell and applies BH-FDR to that batch. But the correct multiple-testing
family is all features × symbols × TFs × regimes × scales -- the full corpus. Running
BH-FDR per `(symbol, tf)` means the effective FDR is not 5% across the corpus. With 58
symbols × 4 TFs = 232 cells each doing independent FDR correction, the expected number
of false discoveries across the corpus is 232x what the 5% threshold implies.

**Fix:** Two options:
1. **Corpus-level BH-FDR (correct):** Collect all p-values from all cells in memory,
   apply BH-FDR once, then write. Requires all workers to return raw p-values before any
   FDR correction. Already partially supported (workers return `all_results` with
   `p_value` fields; main process could apply FDR). Memory cost: 54 features × 58
   symbols × 4 TFs × 9 regimes × 4 lookaheads ≈ 450K p-values -- trivial.
2. **Bonferroni-corrected alpha (conservative):** Apply `fdr_alpha / n_total_cells` per
   cell. Simple, no architecture change, conservative.

**Recommendation:** Option 1 -- the infrastructure is already there. Workers return rows;
main process applies one BH-FDR pass before writing.

---

## P3 — Embargo should be scale-specific, not max(lookaheads) for all scales

**File:** `services/ic_engine.py:789-791`

```python
# embargo_bars for walk-forward: max lookahead across all scales.
embargo_bars = max(lookaheads.values())  # = 60 for the [1,5,20,60] set
```

**Issue:** The 60-bar embargo is applied to *all* scales including fast (1-bar lookahead).
For the fast scale, the correct embargo is 1 bar, not 60. The current approach discards
59 valid observations at each fold boundary for fast-scale measurements. For 5m bars:
59 bars × 3 folds = ~15 hours of discarded observations per regime per symbol. Across
58 symbols × 9 regimes this is meaningful data loss.

**Fix:** Move `embargo_bars = lookahead_bars` inside the scale loop (one line change).
The purpose of the embargo is to prevent overlapping forward-return labels from leaking
across the fold boundary. For a 1-bar lookahead, only 1 bar of embargo is needed.

---

## P4 — Clustering uses transitive linkage, can silently merge uncorrelated features

**File:** `services/ic_engine.py:438-460` (`_cluster_features`)

**Issue:** The code itself comments: *"transitive linkage can merge features whose direct
pairwise correlation is below cluster_max_corr."* At `cluster_max_corr=0.70`, two
features with direct pairwise correlation 0.55 can be merged if a third feature bridges
them at 0.68 each. The representative selected for a transitive cluster may not represent
the actual IC of features merged by transitive bridges.

**Fix:** Switch from average/complete linkage to **single linkage** (`method='single'` in
`scipy.cluster.hierarchy.linkage`). Single linkage merges clusters only when the closest
pair across the two clusters meets the threshold -- it is the conservative, correct choice
for redundancy elimination. Two features that are not directly correlated above the
threshold will never be merged via single linkage.

**Effort:** One-line change. Low risk.

---

## P5 — IC vintage / staleness model

**File:** `feature_ic_scores` schema, ensemble weighter

**Issue:** `feature_ic_scores` has no expiry or staleness flag. A score computed from
2019-2023 data is equally valid (from the schema's perspective) as one computed from
2023-2026 data. `ON CONFLICT DO NOTHING` means the *old* score silently wins on re-run.
The ensemble weighter has no concept of IC vintage.

**Fix:**
- Add `training_window_start` to `feature_ic_scores` (currently only `training_window_end`
  exists -- check schema). The tuple `(start, end)` defines the IC estimate's vintage.
- Ensemble weighter selects the most recent `training_window_end` per cell when multiple
  estimates exist.
- Optional: `ON CONFLICT DO UPDATE` with a condition that newer `training_window_end`
  wins, replacing the old estimate rather than silently keeping it.
- Long-term: see P1 (trailing IC series) which supersedes this for recency-sensitive use.

---

## P6 — Cross-sectional effective N assumes independence across symbols (overconfident CI)

**File:** `services/ic_engine.py:1264` (`_compute_cross_sectional_tf`)

**Issue:** Each `(bar_ts, symbol)` pair is treated as an independent observation. For a
given bar_ts, all 58 symbols share the same cross-sectional regime label, the same macro
environment, and correlated factor exposures. These are not 58 independent observations.
The Fisher z-transform CI (which assumes independence) will be overconfident -- CIs are
too narrow, more features appear to pass the `ic_ci_lower > 0` gate than should.

**Fix:** Apply an effective-N correction for intra-cross-section correlation. The
simplest approach: `N_eff = N_raw / (1 + (n_symbols - 1) * rho_bar)` where `rho_bar` is
the mean pairwise feature-IC correlation across symbols. This is the standard correction
for clustered observations. Alternatively, cluster-robust standard errors.

**Note:** This only affects cross-sectional IC (`_compute_cross_sectional_tf`, symbol=
'POOLED'). Per-symbol IC in `_compute_symbol_tf` is unaffected.

---

## Implementation Order

```
P0: Walk-forward correctness fix        -- methodology integrity, one session
P2: Corpus-level BH-FDR                -- one session, architecture already supports it
P3: Scale-specific embargo              -- one line, zero risk
P4: Single linkage clustering           -- one line, zero risk
P5: IC vintage / staleness model        -- schema + ensemble weighter change
P1: Trailing IC series (60d rolling)    -- major new capability, own phase
P6: Cross-sectional effective N         -- lower priority, affects POOLED rows only
```

P0, P2, P3, P4 can ship together in one session (all small, all correctness-class fixes).
P5 is a schema change that requires coordination with the ensemble weighter.
P1 is a major new capability -- own phase, gated on corpus pipeline being stable.

---

## References

- `services/ic_engine.py` -- full implementation
- `docs/plans/2026-06-20-alphaengine-architecture.md` -- IC methodology spec
- `docs/plans/2026-06-28-hmm-regime-audit-optimization.md` -- parallel audit (regime labels)
- Todo: `028-ic-engine-improvements.md`
