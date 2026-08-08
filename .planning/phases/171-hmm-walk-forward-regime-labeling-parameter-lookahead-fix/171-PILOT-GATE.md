# Phase 171 Plan 05: D-01 Staged Pilot Go/No-Go Gate

**Governing principle (D-00, `171-CONTEXT.md`):** this gate is a mechanical-correctness gate,
not a performance gate. The ROADMAP is explicit that this phase ships regardless of the Gate 4
ordinal-IC pilot's negative result — a weak or negative IC number is an expected, already-known
finding and **does not gate** the walk-forward wiring decision and is **not grounds for NO-GO**.
IC magnitude, IC sign, and label agreement with the production baseline are recorded below as
evidence and interpreted in prose, never as pass/fail criteria.

Evidence sources (checked into `evidence/` under this phase directory):
- `171-05-seed-stability-pilot.json` — REQ-5's first real-corpus exercise of
  `_hmm_seed_stability_check`, 8 symbols × 1d/1h (16 cells; Stage B / 15m,5m not run — see G2).
- `171-05-n-restarts-comparison.json` — D-03's walk-forward-vs-production and
  n_restarts=1-vs-3 parallel comparison arms, same 8×2 scope.
- `171-05-provenance-report.json` — documents that Task 2's NULL-out + relabel cycle was
  deliberately not executed against the corpus (see G1).

---

## G1 — Provenance (BLOCKING)

**Criterion:** Zero cells in the provenance report carry `"verdict": "fail"`.

**Result: PASS (vacuously — no relabel was attempted).** `evidence/171-05-provenance-report.json`
records all 32 pilot cells with `"verdict": "not_run_no_go_before_relabel"`; zero cells carry
`"verdict": "fail"`. Task 2's NULL-out + walk-forward relabel + restore cycle was deliberately
not run against the live corpus, because G2 below already produced a conclusive, BLOCKING NO-GO
from Task 1's diagnostic evidence alone — no relabel result could reverse it. Running the NULL-out
and relabel anyway (only to immediately restore it on this NO-GO) would mutate then revert
`feature_vectors.regime` for 8 symbols × 4 timeframes of live production data, at real compute
cost (≈20 `GaussianHMM.fit()` calls per cell per `171-RESEARCH.md` Pitfall 3), for a verdict that
cannot change. Per D-00 ("ruthlessly eliminate unnecessary complexity", "data integrity is
paramount") and CLAUDE.md's Musk 5-step mandate ("delete" before "accelerate"), this plan chose
the zero-mutation path instead. Confirmed empirically, not assumed:
`feature_vectors.regime IS NOT NULL` count for the 8 pilot symbols is unchanged at
**3,895,913** rows before and after this plan's execution (checked at plan start and again before
writing this document).

## G2 — Seed Stability (BLOCKING above a threshold)

**Criterion:** Count cells with `min_pairwise_agreement <= 0.25` at any sampled boundary. 0 = PASS,
1 = PASS WITH QUARANTINE, 2+ = NO-GO.

**Result: NO-GO. 16/16 cells fail — every single tested cell, not a convenience-sample subset.**
Corpus-wide headline (minimum, not average, per the script's own reporting convention):

```
MIN min_pairwise_agreement = 0.0000 at SPY/1d, boundary=first
```

Full per-cell verdicts (`cell_min_pairwise_agreement`, gate ≤ 0.25) from
`evidence/171-05-seed-stability-pilot.json`:

| Symbol | 1d | 1h |
|--------|-----|-----|
| SPY | 0.0000 FAIL | 0.0012 FAIL |
| IWM | 0.0000 FAIL | 0.0006 FAIL |
| TLT | 0.0000 FAIL | 0.0000 FAIL |
| GLD | 0.0075 FAIL | 0.0000 FAIL |
| XLE | 0.0000 FAIL | 0.0021 FAIL |
| EEM | 0.1329 FAIL | 0.0094 FAIL |
| FXY | 0.0000 FAIL | 0.0000 FAIL |
| SMH | 0.0000 FAIL | 0.0000 FAIL |

This is 8x past the plan's own "2 or more failing cells = NO-GO, systemic degeneracy" threshold.
Two failure modes contribute, both real and both below the 0.25 chance-baseline gate:
(a) genuine seed-driven label disagreement even where the fit converges cleanly (e.g. SPY/1h
first-boundary pairwise agreements of 0.0285/0.0012/0.5582 across three seed pairs — the fitted
models disagree with each other about which of the 5 regime labels applies to the same bars far
more than chance would predict), and (b) outright numerical instability — a full-covariance
5-state `GaussianHMM` EM fit on thin training prefixes (particularly the ~504-obs 1d first
boundary and several ~3,300-obs 1h first/middle boundaries) repeatedly raises a
non-positive-definite-covariance `ValueError` mid-fit, recorded as a hard 0.0 agreement per the
script's documented catch-and-degrade behavior (confirmed on SPY/1d, TLT/1d, IWM/1d, XLE/1d,
FXY/1d, SMH/1d, FXY/1h, SMH/1h, TLT/1h). Some individual boundaries do show high agreement
(SPY/1h last=0.6674, IWM/1h last=0.9613, TLT/1h middle=0.6548) — the pathology is
boundary-density-dependent, not uniform across every window, but the corpus-wide minimum is what
this gate is defined against, and it is unambiguously below threshold.

**Stage B (15m, 5m — 16 additional cells) was not run.** The plan stages cheapest-first
specifically so a degenerate result surfaces before the expensive timeframes are paid for
(`171-05-PLAN.md` Task 1's own framing). With 16/16 Stage A cells already failing at 8x the
NO-GO threshold, no possible Stage B result changes this criterion's verdict — 15m/5m data would
only ever add more evidence to an already-conclusive NO-GO, at a compute cost RESEARCH.md's
Pitfall 3 flags as the most expensive tier (5m carries ~390k-bar histories vs 1h's ~30-36k, all
under the same ~20-fits-per-cell walk-forward cost multiplier). This is a deliberate, documented
scope reduction, not an unexplained gap — recorded in full in the plan SUMMARY's Deviations
section.

## G3 — Coverage (BLOCKING)

**Criterion:** Every one of the 32 pilot cells is accounted for as either relabeled-and-passing,
or explicitly skipped with the insufficient-history arithmetic satisfied and shown.

**Result: satisfied by construction, under G1/G2's early-exit path.** No cell was
"relabeled-and-passing" (G1: relabel never ran) and no cell was skipped for insufficient history
(all 32 pilot cells have real OHLCV/feature history — the coverage gap this criterion exists to
catch, per `171-RESEARCH.md`'s Critical Finding, is a *silent* unexplained hole, not a documented
early-exit). All 32 cells are explicitly accounted for in `evidence/171-05-provenance-report.json`
with `verdict="not_run_no_go_before_relabel"` and an inline `reason` field citing G2's already-
conclusive failure. This is the coverage state G3 is designed to distinguish from a real gap:
every cell has a named, arithmetic-free but evidence-cited explanation, not a silent omission.

## G4 — Runtime Sizing (REPORT-ONLY, no pass/fail)

**Corpus scope at execution time:** `SELECT tf, count(DISTINCT symbol) FROM feature_vectors GROUP
BY tf` → **80 symbols per timeframe**, all 4 timeframes (1d/1h/15m/5m), confirmed 2026-08-08 —
not yet the 231-instrument universe todo 259's backfill is still expanding toward.

**Measured diagnostic cost (Stage A only, seed-stability script, from
`elapsed_seconds` in the evidence JSON):**

| tf | cells (pilot) | sum elapsed_s | mean elapsed_s/cell |
|----|---------------|---------------|----------------------|
| 1d | 8 | 158.9 | 19.9 |
| 1h | 8 | 616.8 | 77.1 |

Extrapolating the *diagnostic* seed-stability check alone to 80 symbols at 1d+1h only:
80×19.9s + 80×77.1s ≈ **7,760s ≈ 2.16 hours**, for the diagnostic script only — this is a distinct
workload from `regime_writer.py`'s production relabel path (3 seeds × 3 sampled boundaries vs.
production's single seed across all ~18-20 segments), so it is not a direct proxy for full-rollout
relabel wall-clock, but it is real measured evidence of the same order-of-magnitude cost class.

**n_restarts comparison script (Stage A, n_restarts=3 arm — 3x a single-fit relabel's cost):**
wall-clock ≈71 minutes for 16 cells (13 evaluated + 3 aborted near-zero-cost on missing
baseline), ≈328s/cell average across evaluated cells.

**15m/5m: no direct measurement in this pilot** (Stage B not run, per G2). RESEARCH.md's Pitfall
3 flags 5m as the most expensive tier given its far larger per-cell row counts (~390k bars vs
1h's ~30-36k) under the same walk-forward fits-per-cell multiplier.

**This estimate is explicitly moot given the NO-GO verdict below** — no relabel work is
scheduled from this pilot. A future pilot iteration (if this fix is revisited after addressing
G2's finding) should size the full rollout from a genuine 15m/5m Stage B run and the production
single-fit relabel path directly, not proxied through either diagnostic script's timing.

## G5 — D-03 n_restarts Attribution (DECIDES A VALUE, DOES NOT GATE THE ROLLOUT)

**Criterion:** the multi-restart arm is preferred only when `a_significantly_better` on a strict
majority of evaluated cells; otherwise INCONCLUSIVE and `alpha.hmm.n_restarts` stays at 1.

**Result: INCONCLUSIVE.** From `evidence/171-05-n-restarts-comparison.json`:

```
D-03 ATTRIBUTION: INCONCLUSIVE
n_restarts=N significantly better than n_restarts=1 on 0/13 evaluated cells (0.0%)
```

**`alpha.hmm.n_restarts` stays at its current value of 1.** This criterion never produces a
NO-GO by design — it selects a parameter value only, and it does not gate the rollout. It is
recorded here for completeness even though the rollout itself is NO-GO per G2: if this phase is
ever revisited, `alpha.hmm.n_restarts=1` is the empirically-decided starting point, not an
assumption.

**Note on the walk-forward-vs-production IC comparison (Block A) recorded in the same evidence
file:** several cells show the walk-forward arm with numerically worse or more negative point IC
than the production (full-history-fit) arm (e.g. XLE/1d: production point_ic=0.0359 vs
walk-forward=-0.0245, paired diff CI [-0.0969,-0.0230], `prod_better=True`). Per this gate's
governing principle above, **this IC comparison does not gate and is not grounds for NO-GO** —
it is recorded as evidence for a separate, already-known thread (the Gate 4 ordinal-IC pilot
result cited in STATE.md), not re-litigated here. The G2 finding above is what determines this
gate's verdict, not any IC number.

---

## Verdict

PILOT VERDICT: NO-GO

**Failing criterion: G2 (seed stability, BLOCKING).** 16/16 tested cells (8 symbols × 1d/1h) have
`min_pairwise_agreement <= 0.25` at their worst sampled boundary; corpus-wide minimum is
`0.0000` at SPY/1d. This is 8x past the plan's own "2+ failing cells = systemic degeneracy =
NO-GO" threshold — not one bad symbol, a corpus-wide pattern.

**Required investigation before any future re-attempt of this rollout:** the walk-forward HMM
fit is not reproducible across different random seeds at the training-prefix lengths this
phase's `initial_warmup_bars`/`refit_every_bars` schedule actually produces (504 obs at 1d,
3,300 obs at 1h). Two intertwined causes are visible in the evidence: (1) genuine seed-sensitivity
in the label assignment even on fits that converge cleanly, and (2) outright numerical
instability (non-positive-definite covariance) on the thinnest prefixes, consistent with too few
observations per Gaussian component for a full-covariance 5-state model at this density. Candidate
directions for a future fix (not evaluated in this pilot, out of scope for this gate): a
diagonal/tied covariance type for the earliest segments, a larger `initial_warmup_bars` floor
specifically at 1d (already flagged in D-02 as an `[initial_estimate]`, now empirically shown to
be too thin), or accepting single-seed instability as inherent and deferring to
`_seed_prior_from_label`'s belief-continuity mechanism to dampen it across refits (untested by
this pilot, which measures per-boundary independent fits, not the chained continuity path).

**Corpus state: uniform, untouched, no restoration needed.** No NULL-out was performed and no
relabel was performed — `feature_vectors.regime` for the 8 pilot symbols is unchanged
(3,895,913 `NOT NULL` rows, identical before and after this plan). `alpha.hmm.walk_forward.enabled`
remains `false` in `config_state`, confirmed via direct query at the start and end of this plan's
execution. Zero new `config_history` rows for that key. The corpus remains in the single, uniform
full-history-fit labeling method it was in before this plan started — the plan's "restore to
uniform on NO-GO" requirement is satisfied trivially because nothing was ever migrated away from
that state.

**alpha.hmm.n_restarts for any future rollout: 1** (G5, INCONCLUSIVE — no change from current).

**Plan 171-06 should not proceed to the full 231-symbol × 4-tf rollout** until G2's seed-instability
finding is investigated and a revised approach re-clears this same gate (or an equivalent one) on
a fresh pilot.
