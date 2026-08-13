# 304 - Per-symbol percentile-rank candidates: volume_pct, skew_tail, volatility_pct

**Filed:** 2026-08-12
**Source:** Interactive session, follow-on from todo 303 (trend regime). Same conversation
surfaced three more security-level candidates already named in
`docs/research/stratification-dimension-unification.md`'s candidate table but never tested.
**Companion to:** [todo 303](303-per-symbol-trend-regime-null-arm-tested-candidate.md) (trend,
different mechanism family — Hurst/autocorrelation, not percentile-rank). Keep these separate;
don't merge into one todo, they have different reuse plans.
**Status:** pending. Mechanism build + mechanism validation can run now (no corpus dependency —
see Stage 1 below); the full IC substitution test is gated on the corpus pipeline currently
running in a separate session finishing. **Update 2026-08-13: that corpus pipeline run FAILED at
step 2** (768GB disk-full incident — see `project_disk_full_incident_2026_08_13` memory).
`regime_volatility` is still 0-populated across all 69.9M `feature_vectors` rows. **Stage 2/3
never ran — this candidate has never been built past Stage 1.** Re-query before assuming the
gate cleared.

**Pre-registered design doc written 2026-08-12**: `docs/research/measurement-per-symbol-percentile-rank-candidates.md`
— full Stage 2/3 design including the mandatory null-arm control (shared harness design with
todo 303's sibling doc: per-symbol IID time-permutation, 200 replicates, null p < 0.05), written
before either stage runs. Read that doc for the actual falsification protocol instead of
re-deriving it from this file.

## What

Three per-symbol candidates from the stratification doc, none tested yet:

1. **`volume_pct`** — expanding percentile rank of `rel_volume`. Participation/liquidity
   intensity, plausibly distinct from volatility even though the two tend to co-move (that's
   exactly what the orthogonality gate checks, not assumed).
2. **`skew_tail`** — rolling return skewness percentile. High-vol-positive-skew (lottery-like)
   vs. high-vol-negative-skew (crash risk) are different prediction problems at the same
   volatility level — `regime_volatility` alone can't distinguish them.
3. **`volatility_pct`** — plain percentile rank of realized vol, no HMM. Framed this session as
   a simplification test as much as a new axis: now that `regime_volatility` (an HMM) measures
   volatility, does a dumb percentile rank separate IC just as well? If yes, real evidence the
   HMM's complexity isn't earning its keep for this specific measure.

All three share one mechanism template, confirmed by reading the live code this session (not
assumed): the same two-stage transform `vix_pct` already uses in `breadth_vol.py` — a rolling
z-score of the raw measure, then `causal_rank.py::causal_expanding_rank` applied to that
z-score. Never a raw z-score or a whole-series `pandas.rank()` used directly (the latter is the
exact look-ahead bug Phase 141's P0-T2 fix removed).

## Staged design (same discipline as every other candidate this session)

**Stage 1 — Mechanism build + validation (no corpus dependency, runnable now).** Compute all
three directly from `market_data_ohlcv_tradeable` (raw OHLCV + volume, already fully backfilled
— client-48/49 finished) — zero dependency on `feature_vectors`/`regime_volatility`/the
in-flight corpus pipeline. Confirms: causal (no look-ahead), reasonable/non-degenerate rank
distribution, no schema change. This is a mechanism check, not the falsification test — no IC
comparison happens here.

**Stage 2 — Orthogonality study.** Correlation (Pearson on the continuous z-score/rank, or
normalized mutual information on discretized labels) between each candidate and
`regime_volatility`, per the stratification doc's Gate 1. `volatility_pct` is the interesting
case — expect high correlation with `regime_volatility` by construction (same underlying
measure, different mechanism); that's not a failure, it's the point of the simplification test
in Stage 3. `volume_pct`/`skew_tail` are less certain — genuinely gated, not presumed distinct.

**Stage 3 — Substitution test / simplification test.**
- `volume_pct`, `skew_tail`: standard substitution test per the stratification doc's protocol
  (IC Sharpe increase >10% in at least one joint cell, N>20,000 bars).
- `volatility_pct`: additionally compared head-to-head against `regime_volatility` on the SAME
  cells — does the percentile rank match, beat, or lose to the HMM's separation? A win or tie
  is a real simplification finding regardless of whether it clears the standard 10% bar (a
  simpler mechanism at equal separation is still worth knowing about).

**Null-arm control, same standing rule as todo 303**: no separation number from Stage 3 gets
cited as real evidence unless it clears a scrambled-data null run first — this project has
already paid for skipping this once (Phase 171/172's mislabeled regime) and once more with a
different failure shape (`ctf_momentum`'s lookahead leak, todo 243). Pre-register the null
design before running Stage 3, not after seeing a promising number.

## Reuse plan

| Need | Source |
|---|---|
| Causal expanding rank | `src/intelligence/regime_signals/causal_rank.py::causal_expanding_rank` (pure function, no DB, directly reusable) |
| Rolling z-score template | `src/intelligence/regime_signals/breadth_vol.py::_compute_vix_pct_rank` (pattern to copy, not import — that function is SPY-specific) |
| Raw OHLCV/volume fetch | Same query pattern as `scripts/analysis/effective_breadth_diagnostic.py` / `scripts/analysis/statistical_factor_residual_k_selection_pilot.py` (`market_data_ohlcv_tradeable`, `is_active` join) |
| Day-clustered bootstrap CI (Stage 3) | `src/intelligence/statistics/ic_math.py::_circular_block_bootstrap_ic` |
| BH-FDR (Stage 3) | `src/intelligence/statistics/ic_math.py::apply_bh_fdr` |
| Orthogonality correlation (Stage 2) | **New**, small — Pearson/mutual-info on already-computed rank series |

## Data dependency by stage

Stage 1: none beyond already-backfilled OHLCV — runnable immediately, including while the
concurrent corpus pipeline is in flight (different tables, no write contention — this is
read-only against `market_data_ohlcv_tradeable`).
Stage 2/3: need `feature_ic_scores`/`feature_vectors.regime_volatility` populated — gated on
the concurrent corpus pipeline (`ops_corpus_pipeline_run.sh`) finishing. **Do not run Stage 2/3
or touch `ic_engine`/`regime_writer` while that run is active** — see memory
`MEMORY.md`'s 2026-08-12 concurrent-session-boundary note.

## Result — Stage 1 (mechanism build + validation), run 2026-08-12

**Clean pass. Script: `scripts/analysis/per_symbol_regime_candidates_stage1_pilot.py`.**
5 representative symbols (SPY/AAPL/XOM/JPM/TLT — index, tech, energy, financial, bonds), 3
candidates each = 15 checks:

- **Causality: 15/15 PASS.** Truncated-input rerun vs. full-run prefix diff = `0.00e+00` for
  every candidate/symbol pair — zero look-ahead, confirmed not assumed.
- **Distribution: non-degenerate on all 15.** `std` ranged 0.284-0.294 across every
  candidate/symbol — a true uniform[0,1] has `std=1/sqrt(12)≈0.289`, so every one lands almost
  exactly on the theoretical value expected of a correctly-functioning causal rank. ~10% of
  observations in each tail bucket (`<0.1`, `>0.9`) for all 15, as expected.

**No IC comparison happened in this run** — this only confirms the mechanism works, not that
any candidate has predictive value. Stage 2 (orthogonality vs. `regime_volatility`) and Stage 3
(substitution test / simplification test) remain gated on the concurrent corpus pipeline
finishing (`feature_vectors.regime_volatility` still 0-populated as of this run).

## Where

- `docs/research/stratification-dimension-unification.md` — candidate table, reconciliation
  pass item 16 (2026-08-12)
- `src/intelligence/regime_signals/causal_rank.py`, `breadth_vol.py` — reusable mechanism
- `scripts/analysis/` — where the Stage 1 pilot script belongs (see companion `statistical_factor_residual_k_selection_pilot.py` for the naming/structure convention)
