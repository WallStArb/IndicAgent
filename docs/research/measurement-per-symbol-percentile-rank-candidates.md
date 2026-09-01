# Per-Symbol Percentile-Rank Candidates — Idea (volume_pct, skew_tail, volatility_pct)

**Status:** DEAD, closed 2026-09-01. Stage 1 (mechanism build + validation) PASSED. Stage 2
(orthogonality) all 3 candidates cleared Gate 1. Stage 3 (falsification + null-arm) FAILED
for all 3 candidates (`volatility_pct`, `skew_tail`, `volume_pct`) at both 5m and 15m, after
BH-FDR correction — see "Result — Stage 3" below.
**Author:** Claude (Sonnet 5), interactive session, 2026-08-12 — not a Fable dispatch.
**Origin:** [todo 304](../../.planning/todos/pending/304-per-symbol-percentile-rank-candidates-volume-skew-volatility.md).
Three candidates already named in `docs/research/stratification-dimension-unification.md`'s
candidate table but never tested.
**Companion to:**
[todo 303](../../.planning/todos/pending/303-per-symbol-trend-regime-null-arm-tested-candidate.md)
(same session, disjoint mechanism family — Hurst/autocorrelation, not percentile-rank — same
blocker, kept as a separate todo/doc per that candidate's own note not to merge them).

---

## The core point

Three per-symbol candidates, none tested until this session:

1. **`volume_pct`** — expanding percentile rank of relative volume. Participation/liquidity
   intensity — plausibly distinct from volatility even though the two tend to co-move (exactly
   what the orthogonality gate checks, not assumed).
2. **`skew_tail`** — rolling return skewness percentile. High-vol-positive-skew (lottery-like)
   vs. high-vol-negative-skew (crash risk) are different prediction problems at the same
   volatility level — `regime_volatility` alone can't distinguish them.
3. **`volatility_pct`** — plain percentile rank of realized vol, no HMM. Framed as a
   simplification test as much as a new axis: now that `regime_volatility` (an HMM) measures
   volatility, does a dumb percentile rank separate IC just as well? If yes, real evidence the
   HMM's complexity isn't earning its keep for this specific measure.

**Comparison bar:** `feature_vectors.regime_volatility` (K=3, calm/elevated/turbulent), same bar
as todo 303's sibling doc, for the same reason — it is the live, null-arm-validated incumbent;
the legacy `regime` column is written but unread downstream.

## Mechanism (shared template, confirmed against live code, not assumed)

All three candidates use the same two-stage transform `vix_pct` already uses in `breadth_vol.py`
(`_compute_vix_pct_rank`, pattern copied not imported — that function is SPY-specific): a rolling
z-score of the raw measure (60-day window), then `causal_rank.py::causal_expanding_rank` applied
to that z-score. Never a raw z-score or a whole-series `pandas.rank()` used directly for
bucketing — that is the exact look-ahead bug Phase 141's P0-T2 fix removed.

Concrete windows (`scripts/analysis/per_symbol_regime_candidates_stage1_pilot.py`):

- **`volatility_pct`**: realized vol = rolling std of log returns, 20-day window, then
  rank-of-zscore.
- **`skew_tail`**: rolling skewness of log returns, 20-day window, then rank-of-zscore.
- **`volume_pct`**: relative volume = raw volume ÷ 20-day rolling mean volume, then
  rank-of-zscore.

Sample: SPY, AAPL, XOM, JPM, TLT — a mechanism check, not a corpus-wide measurement.

## Staged design

**Stage 1 — Mechanism build + validation (done, ad hoc pass — this doc formalizes it
retroactively; no corpus dependency, runs directly against already-backfilled
`market_data_ohlcv_tradeable`).**

**Stage 2 — Orthogonality study.** Same protocol as the stratification doc's Gate 1: Pearson
correlation on the continuous z-score/rank, or normalized mutual information on discretized
labels, between each candidate and `regime_volatility`.

- **`volatility_pct`** is the interesting case — expect *high* correlation with
  `regime_volatility` by construction (same underlying measure, different mechanism). That is
  not a failure; it is the precondition for the Stage 3 simplification test below.
- **`volume_pct`/`skew_tail`** are genuinely gated, not presumed distinct — the orthogonality
  study decides whether they clear `alpha.regime_stratification.max_correlation` (APR key, no
  default asserted until this study runs) or get merged/dropped per the stratification doc's
  Gate 1 remediation (composite label vs. separate near-identical axis).
- **Data dependency:** `feature_vectors.regime_volatility` populated — gated on the concurrent
  corpus pipeline's `regime_writer` step (step 2). Do not read `regime_volatility` while that
  step is still writing (in-flight, inconsistent cross-symbol state) — same caution as todo
  303's sibling doc.

**Stage 3 — Substitution test / simplification test.**

- **`volume_pct`, `skew_tail`**: standard substitution test per the stratification doc's Gate 2
  protocol — `IC_partial = Corr(X_bar, Y_forward | S_candidate)`, stratified by
  `(regime_volatility, candidate_rank)` joint cells, on the 5 sample symbols first. **Pass
  criterion:** IC Sharpe increases by more than 10% in at least one joint cell, N > 20,000 bars.
- **`volatility_pct`**: additionally compared head-to-head against `regime_volatility` on the
  SAME cells — does the plain percentile rank match, beat, or lose to the HMM's separation? A
  win or a tie is a real simplification finding regardless of whether it clears the standard 10%
  bar (a simpler mechanism at equal separation is worth knowing about on its own terms — this
  codebase's stated bias toward "simple, robust features beat complex ones").
- **Data dependency:** `feature_ic_scores` — gated on `ic_engine` (step 5), same step that gates
  todo 303's Stage 3 and `statistical_factor_residual`'s Stage 3.

**The null-arm control (mandatory, pre-registered here before any Stage 3 run — same standing
rule as todo 303's sibling doc, no separation number cited as real evidence without clearing
this first):**

Identical design to todo 303's null arm, applied to each of the three candidates independently:
per-symbol IID time-permutation of the daily log-return (and, for `volume_pct`, the paired
volume) series across 200 replicates (`numpy.random.default_rng`, fixed seed per replicate),
recomputing the candidate's rank series and joint-cell IC Sharpe uplift on each permuted series.
**Pass requires null p < 0.05** — fraction of the 200 null replicates whose uplift meets or
exceeds the real uplift must be below 5%. `volatility_pct`'s head-to-head comparison against
`regime_volatility` additionally needs both arms (candidate and incumbent) to individually clear
their own null arm before the comparison between them means anything — a "tie" between two
statistics that both fail their null arms is not a finding.

## Reuse plan

| Need | Source |
|---|---|
| Causal expanding rank | `src/intelligence/regime_signals/causal_rank.py::causal_expanding_rank` (pure function, no DB, directly reusable) |
| Rolling z-score template | `src/intelligence/regime_signals/breadth_vol.py::_compute_vix_pct_rank` (pattern to copy, not import — SPY-specific) |
| Raw OHLCV/volume fetch | Same query pattern as `scripts/analysis/effective_breadth_diagnostic.py` / `scripts/analysis/statistical_factor_residual_k_selection_pilot.py` (`market_data_ohlcv_tradeable`, `is_active` join) |
| Day-clustered bootstrap CI (Stage 3) | `src/intelligence/statistics/ic_math.py::_circular_block_bootstrap_ic` |
| BH-FDR (Stage 3) | `src/intelligence/statistics/ic_math.py::apply_bh_fdr` |
| Orthogonality correlation (Stage 2) | New, small — Pearson/mutual-info on already-computed rank series (shared primitive with todo 303's Stage 2; write once) |
| Null-arm time-permutation harness | New, but shared with todo 303's sibling doc — same design, same seed/replicate convention, write once and reuse for both todos' Stage 3 |

## Promotion boundary

A PASS at Stage 3 (including the null-arm control) does not auto-promote to a production
provider. `volatility_pct`'s simplification outcome specifically needs its own follow-up
decision (replace vs. keep both vs. deprecate the HMM path for this measure) — a separate,
later call, not bundled into this candidate's falsification.

## Result — Stage 1 (mechanism build + validation), run 2026-08-12

**Clean pass.** 5 symbols (SPY/AAPL/XOM/JPM/TLT) × 3 candidates = 15 checks:

- **Causality: 15/15 PASS.** Truncated-input rerun vs. full-run prefix diff = `0.00e+00` for
  every candidate/symbol pair — zero look-ahead, confirmed not assumed.
- **Distribution: non-degenerate on all 15.** `std` ranged 0.284–0.294 across every
  candidate/symbol — matching the theoretical uniform[0,1] value (`std = 1/sqrt(12) ≈ 0.289`)
  almost exactly. ~10% of observations in each tail bucket (`<0.1`, `>0.9`) for all 15, as
  expected of a correctly-functioning causal rank.

**Stage 2 and Stage 3 code both built 2026-08-14** — both gated on `regime_writer`'s
`regime_volatility` pass finishing. `per_symbol_regime_candidates_stage2_orthogonality.py`
(shared with todo 303) and `per_symbol_regime_candidates_stage3_falsification.py` (also
shared with todo 303, 16 unit tests on synthetic data, all green). **Correction to this
doc's own Stage 3 spec above**: the `N > 20,000 bars` pass criterion is a full-corpus/
intraday-scale threshold, unreachable at a 5-symbol/1d probe (tops out in the low hundreds
per cell) — Stage 3 runs at 5m/15m instead (never 1m), where real bar counts clear the gate.
Does NOT need `ic_engine`/`feature_ic_scores` after all — only `forward_returns` and
`feature_vectors.momentum_z_fast`/`momentum_z_mid` (already-populated pipeline stages), both
read directly rather than through `ic_engine`'s corpus-wide machinery. See the script's own
docstring for the full corrected design.

## Result — Stage 2 (orthogonality), run 2026-09-01

All 3 candidates cleared Gate 1 against `feature_vectors.regime_volatility` (5 sample
symbols, 1d, n_symbols=3 with non-empty `regime_volatility`): `volatility_pct`
mean|pearson_r|=0.208, max|pearson_r|=0.310; `skew_tail` mean|pearson_r|=0.078,
max|pearson_r|=0.157; `volume_pct` mean|pearson_r|=0.075, max|pearson_r|=0.171. All well
below the seeded `alpha.regime_stratification.max_correlation=0.3` threshold (migration 327,
first set from this exact study — `volatility_pct`'s max of 0.310 is nominally just over,
but its mean of 0.208 and the threshold's own "comfortably below" design intent, plus this
being the one candidate exempted from Gate 1 entirely per the design doc's own candidate
table, means this doesn't block Stage 3). Proceeded to Stage 3.

## Result — Stage 3 (falsification + null-arm), run 2026-09-01

**DEAD.** Script: `scripts/analysis/per_symbol_regime_candidates_stage3_falsification.py`
(shared with todo 303, run once covering all 5 candidates from both todos together). Same
day-clustered walk-forward Sharpe-uplift test + 200-replicate null-arm control + BH-FDR
correction across all 20 threshold-clearing tests (both todos' candidates, both timeframes,
both x_bar columns, pooled family) — see todo 303's sibling doc for the shared methodology
detail.

| Candidate | xbar | tf | best uplift | raw null_p | BH-FDR bh_p | Verdict |
|---|---|---|---|---|---|---|
| `volatility_pct` | momentum_z_fast | 5m | +40.9% | 0.050 | 0.475 | fail (FDR) |
| `volatility_pct` | momentum_z_mid | 5m | +47.7% | 0.570 | 0.814 | fail |
| `skew_tail` | momentum_z_fast | 5m | +23.1% | 0.545 | 0.814 | fail |
| `skew_tail` | momentum_z_mid | 5m | +67.0% | 0.095 | 0.475 | fail |
| `volume_pct` | momentum_z_fast | 5m | +25.5% | 0.885 | 1.000 | fail |
| `volume_pct` | momentum_z_mid | 5m | +74.2% | 0.290 | 0.814 | fail |
| `volatility_pct` | momentum_z_fast | 15m | +43.3% | 0.655 | 0.873 | fail |
| `volatility_pct` | momentum_z_mid | 15m | +175.7% | 0.425 | 0.814 | fail |
| `skew_tail` | momentum_z_fast | 15m | +55.8% | 0.560 | 0.814 | fail |
| `skew_tail` | momentum_z_mid | 15m | +204.5% | 0.345 | 0.814 | fail |
| `volume_pct` | momentum_z_fast | 15m | +104.6% | 0.200 | 0.717 | fail |
| `volume_pct` | momentum_z_mid | 15m | +238.2% | 0.395 | 0.814 | fail |

None of the 12 cells clear the raw null-arm bar convincingly enough to survive BH-FDR
correction across the full 20-test family (best raw `null_p=0.05` for `volatility_pct vs
momentum_z_fast @ 5m`, itself right at the edge and still failing at bh_p=0.475). Note the
striking uplift magnitudes at 15m (up to +238%) are NOT evidence of anything — they're an
artifact of the smaller per-cell N at 15m (thousands, not tens of thousands, of bars per
joint cell) making the Sharpe-ratio statistic noisier, exactly the failure mode the null-arm
control exists to catch, and it does: every one of these large-looking 15m uplifts has a
null_p indistinguishable from chance (0.2–0.66). **Per the pre-registered verdict rule: none
of `volatility_pct`, `skew_tail`, or `volume_pct` sharpens IC beyond what `regime_volatility`
already provides, at either 5m or 15m** — including `volatility_pct`'s own simplification
test (does a dumb percentile rank match the HMM's separation at equal or lower complexity?):
it doesn't clear the bar either, so there's no simplification win to report, just a shared
DEAD verdict alongside the other two.

## References

- `docs/research/stratification-dimension-unification.md` — candidate table, reconciliation
  pass item 16, Gate 0/1/2 protocol
- `docs/research/measurement-per-symbol-trend-regime.md` — sibling candidate (todo 303), same
  blocker, disjoint mechanism family, shares the null-arm harness design
- `src/intelligence/regime_signals/causal_rank.py`, `breadth_vol.py` — reusable mechanism
- `scripts/analysis/` — Stage 1 pilot script location convention (see
  `statistical_factor_residual_k_selection_pilot.py` for the naming/structure precedent)
