# Empirical Null Calibration for the IC Inference Chain

**Date:** 2026-07-09
**Status:** Design — pending implementation
**Scope:** todo 071 / L4-2 only (`docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §7). L4-4 (IC hit-rate/magnitude decomposition) is a separate, later spec — see "Explicitly out of scope" below.
**Sequencing:** No phase dependency. Runnable now that `feature_ic_scores` holds its first trustworthy full-universe measurement (2026-07-09 corpus rebuild, see `project_corpus_pipeline_state` memory).

---

## Motivation

`_fisher_z_ci` and `_p_values_from_ic` in `src/intelligence/statistics/ic_math.py` assume the analytic
Fisher z-transform standard error, `SE = 1/sqrt(n-3)`, correctly describes the sampling distribution of
Spearman IC on this data after stride subsampling. That assumption replaced circular block bootstrap on a
documented but *theoretical* argument — `services/ic_engine.py`'s own header docstring says the bootstrap
was redundant "at our sample sizes (n > 500 everywhere; CLT fully converged)". That claim has never been
checked end-to-end against this corpus's actual autocorrelation structure.

Every downstream decision — CI gates, BH-FDR pass/fail, walk-forward validation, the E1/E2 ensemble
weighting judgment run 2026-07-09 — inherits whatever error is in that one assumption. If the analytic CI
is too narrow, the system has been passing features (and ensemble variants) that shouldn't pass, silently,
for as long as this measurement chain has existed. This is the highest-leverage cheap check available: it
either certifies the entire inference chain with evidence, or tells us precisely how much to widen it.

This is a **verification** project, not a new capability. Nothing about `ic_engine.py`'s production output
changes as a result of running it. The outcome is a decision — keep Fisher-z as-is, or reopen circular
block bootstrap — made with evidence instead of the current unverified assertion.

---

## Falsification Target

For a sampled `(feature, symbol|POOLED, tf, regime, lookahead)` cell, break the true X↔Y relationship while
preserving Y's own autocorrelation structure (a circular shift does this; an i.i.d. shuffle would not — it
would destroy the autocorrelation the whole HAC/stride-subsampling design exists to handle, producing a
strawman-easy null). Recompute IC under 200 such shifts. The resulting empirical distribution of
`arctanh(IC_null)` should be approximately `Normal(0, SE_analytic²)` if the Fisher-z assumption holds.
Compare **both** the empirical standard error (does the CI width match?) and the empirical shape (does the
normality assumption hold, not just the variance?).

---

## Architecture

Three pieces, each with one job. No schema change, no APR keys, no edit to `ic_engine.py` or any
production write path — this is read-only forensics against the existing corpus.

### 1. `_circular_shift_null(Y, rng)` — new pure function in `ic_math.py`

```
_circular_shift_null(Y: np.ndarray, rng: np.random.Generator) -> np.ndarray
```

Circularly shifts `Y` by a random offset drawn from `[1, len(Y)-1]` (uniform, excludes the
identity/zero-shift case). `np.roll` under the hood. Preserves every value and Y's own
autocorrelation/spectral structure; destroys alignment with X. Pure, no DB, no config — unit-testable in
isolation alongside the rest of `ic_math.py`.

### 2. `scripts/ops/alpha/ops_ic_null_calibration.py` — one-off diagnostic script

Same house style as `scripts/ops/alpha/ops_ensemble_ic_diagnosis.py`: asyncpg read-only connection,
imports and calls `ic_math.py`'s existing `_vectorized_ic`, `_fisher_z_ci`, `_p_values_from_ic`,
`rankdata` directly — **does not reimplement the IC computation**. If production math has a latent bug,
the diagnostic must inherit it, not accidentally route around it. Prints a Markdown report to stdout.
**Exit code always 0** — informational, never a gate, can never block a pipeline run. Docstring documents
the D-numbered decisions below in the same style `ops_ensemble_weight_compare.py` uses.

### 3. No schema change

No new columns, no new table, no new APR key. `feature_ic_scores` is read-only input (to select which
cells to sample and to know `n_independent`/gate status per cell); raw `(X, Y)` for the permutation itself
comes from `feature_vectors JOIN forward_returns` (the same tables `ic_engine.py` reads at
`services/ic_engine.py:882` and `:1244`), not from `feature_ic_scores`, which only stores summary
statistics.

---

## Cell Sampling — Stratified at the Decision Boundary

Uniform random sampling characterizes the null everywhere; it is not where a RenTech-grade check should
spend compute. The point of this diagnostic is to protect decisions that are actually being made today, so
sampling is stratified to concentrate exactly there.

Eight strata: `tf ∈ {5m, 15m, 1h, 1d}` × `is_pooled ∈ {false, true}` — verified against live data
(`SELECT tf, is_pooled, count(*) FROM feature_ic_scores GROUP BY 1,2`, 2026-07-09): all 8 combinations
have both passing and failing cells to sample from. `is_pooled=false` is the per-symbol population;
`is_pooled=true` is the `symbol='POOLED'` cross-sectional aggregate. Note:
`feature_ic_scores.regime_scope` has only two populated values today — `cross_sectional` (783,300 rows)
and `pooled` (137,349 rows); `symbol_hmm` has zero rows (todo 026 P4a is unresolved — per-symbol HMM
regime labels have never been written to this table, only the 9 `market_regimes` cross-sectional labels
have). `regime_scope` is therefore not a usable stratification axis today; `is_pooled` is the correct
proxy and is what the existing "`symbol='POOLED'` 5m/15m clear [the 60K-bar floor]; 1d structurally
cannot" gotcha already uses. Per stratum, select:

- **5 boundary cells** — smallest `|ic_ci_lower|` among cells with `passes_fdr = true AND reliable = true`
  in that stratum (the cells one bad SE estimate away from flipping a gate decision — the highest-value
  cells to check)
- **2 clearly-null cells** — `passes_fdr = false`, `ic_value` nearest zero (sanity floor: null should
  measure as null)
- **2 clearly-strong cells** — `ic_sharpe_hac` in the stratum's top decile (sanity ceiling: strong signal
  shouldn't evaporate under a correctly-calibrated null)

9 cells × 8 strata = **72 cells total**, 200 circular-shift permutations each (the source doc's own
number — resolves a >20% SE miscalibration at this rep count without being a compute-cost concern).
~14,400 total IC recomputations on already-subsampled arrays: seconds to low single-digit minutes of
compute, dominated by the 72 raw-series fetches, not the permutation loop. No `ProcessPoolExecutor` — this
is orders of magnitude below `ic_engine.py`'s own scale, and adding parallelism here would be complexity
without a corresponding need.

If a stratum has fewer than 9 qualifying cells (e.g. a thin `is_pooled=true` × `1d` combination — the
60K-bar floor gotcha already documents 1d as structurally short on independent observations), take what
exists and note the shortfall in the report rather than backfilling from a different stratum — a stratum
with too little data to sample from is itself a finding, not a gap to paper over.

---

## Mechanics — Exact Reuse of the Production Shape

For each sampled cell:

1. Fetch the same raw `(X, Y)` the corresponding `ic_engine.py` run used: same symbol (or the
   `symbol='POOLED'` cross-sectional aggregation when `is_pooled = true`), same `tf`, same `regime`, same
   `lookahead_bars`, same `training_window_end` vintage.
2. Apply the identical `scale_stride = max(subsample_min_stride, lookahead_bars)` subsampling
   `ic_engine.py` uses (read `alpha.ic.subsample_min_stride` via `ConfigService`, matching
   `ICEngineConfig.from_apr`).
3. Rank-transform once (`rankdata`), confirming `n_independent` matches what's stored in
   `feature_ic_scores` for that cell — a mismatch here means the diagnostic mis-selected the cell or the
   corpus has drifted since measurement, and the script aborts that cell with a logged warning rather than
   silently comparing against a different population.
4. Run 200 iterations of: circular-shift `Y` via `_circular_shift_null`, re-rank, compute IC via
   `_vectorized_ic`, collect.
5. Compare the 200-value empirical null distribution against the analytic prediction (next section).

This is the production path with exactly one line changed — `Y` shifted before ranking. Divergence
between the diagnostic's code path and production's would invalidate the whole exercise, so identical
function calls matter more here than performance or elegance.

---

## Verdict Criteria

Per cell, report:

- `empirical_se = std(arctanh(IC_null_200))`
- `analytic_se = 1/sqrt(n-3)` (the same formula `_fisher_z_ci` uses internally)
- `se_ratio = empirical_se / analytic_se`
- A normality check on `arctanh(IC_null_200)` (Shapiro-Wilk via `scipy.stats.shapiro`, or the QQ-correlation
  coefficient if Shapiro's n-sensitivity is a concern at 200 samples) — the CLT assumption is about *shape*,
  not only variance; a heavy-tailed null with the "right" variance still miscalibrates the tail p-values
  that BH-FDR depends on.

**Flag threshold:** `se_ratio > 1.2` → **SUSPECT** (analytic CI is >20% too narrow — the dangerous
direction, since it means more false positives than the reported gate implies). `se_ratio` below 1 is
conservative, not dangerous, but reported for completeness. This mirrors the flag idiom
`ops_ensemble_ic_diagnosis.py` already uses (`| flag |` column, human-readable verdict per row).

**Aggregate verdict:** if zero cells are SUSPECT across all 54 → Fisher-z stands, confirmed by evidence
rather than theory. If any stratum shows systematic SUSPECT clustering (not just an isolated cell) → the
CLT assumption fails specifically in that stratum (most likely candidate: `1d` tf, smallest N, per the
existing "1d structurally cannot [clear 60K-bar floor]" gotcha already on record) and block bootstrap needs
reopening at least for that stratum.

---

## Durable Record

The verdict determines the fate of the dead `alpha.ic.bootstrap_seed` / `bootstrap_resamples` /
`bootstrap_block_size.*` APR keys (migrations 161, 165, 177 — currently zero readers). Whichever way it
lands:

- **All-clear:** delete the dead keys in a follow-up migration, citing this diagnostic's run as the
  evidence (satisfies the "delete unnecessary complexity" mandate — these keys are currently kept "just in
  case," which is exactly the kind of unexamined complexity a RenTech review would remove).
- **SUSPECT found:** file a new todo scoped to the affected stratum/strata to implement circular block
  bootstrap in the kernel (giving the dead keys their first real reader), and widen the affected gates'
  interpretation in the interim.

Either outcome gets added as a new dated row in `docs/research/measurement-ic-engine.md`'s Measurement
Gaps table (verified 2026-07-09: no existing L4-2 entry there today — the L4-2 label lives only in todo
071 and `fable-2026-07-07-renaissance-layer-refinements.md` §7; this is a new addition, not an update to
a placeholder) — same inline-dated-addendum convention OQ7's resolution used elsewhere in that doc. Todo
071 gets its L4-2 half moved to `completed/` (L4-4 stays open as the separate follow-on spec).

---

## Testing

- Unit test for `_circular_shift_null` in `ic_math.py`'s existing test file: fixed-seed determinism, offset
  excludes zero-shift, output is a permutation of the same multiset of values (no value fabricated or
  dropped), shift is circular (wraps, doesn't truncate).
- The diagnostic script itself is exercised by running it against the live corpus, not by a synthetic unit
  test — consistent with `ops_ensemble_ic_diagnosis.py` having no dedicated test file (it is read-only
  forensics over live data, not logic that benefits from a mocked-DB unit test).

---

## Explicitly Out of Scope

- **L4-4 (IC hit-rate/magnitude decomposition)** — different shape of work (new persisted columns on
  `feature_ic_scores`, a production `ic_engine.py` change). Separate spec, sequenced after this one lands
  so it inherits a verified — or correctly-widened — inference chain rather than building on an unverified
  one.
- **Null-check on `ic_sharpe_hac` specifically** — a different statistic (Newey-West Bartlett-kernel
  inflation) that already has its own autocorrelation-correction mechanism by design; lower priority than
  the Fisher-z CI/p-value chain this diagnostic targets.
- **Full-corpus run** — this diagnostic answers "is the inference chain calibrated," not "characterize
  every one of ~920K cells." A full sweep is a different compute budget and a different question; revisit
  only if the stratified sample surfaces a pattern that needs corpus-wide confirmation.
