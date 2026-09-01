# Statistical Factor Residual — Idea (Edge Source Thesis statistical_factor_residual)

**Status:** DEAD, closed 2026-09-01. All 3 stages complete (K-selection, causal factor fit,
IC falsification) — residualizing away the top-K statistical factors did not improve
`ctf_momentum`'s IC on any of 3 measurement axes; see Stage 3 result below.
**Author:** Claude (Sonnet 5), interactive session, 2026-08-11 — not a Fable dispatch.
**Origin:** Post-mortem of Phase 167's retraction (`ctf_momentum`'s batch-join lookahead leak,
todo 243). Part of the fork-resolution discovery track: back to Signal-Extraction candidates,
not construction, until one independently proves edge. `cointegrated_pairs_residual` and
`jump_diffusion_decomposition` (this track's two other cheap candidates) both already ran and
came back DEAD 2026-08-07 — see their own docs. `statistical_factor_residual` was the one
candidate left with real, named methodology debt blocking it (K-selection), not ready to
execute alongside those two.
**Companion to:** `docs/research/data-edge-source-thesis.md` (this is candidate thesis
**statistical_factor_residual**, one of five Signal-Extraction candidates added 2026-08-03).

---

## The core point

Decompose the cross-sectional return matrix into its top-K statistical factors (PCA over the
correlated instrument universe) and test whether the idiosyncratic residual — what's left after
removing the common factors — is more predictable than the raw or simply-demeaned return. The
classical Avellaneda-Lee stat-arb structure: instead of ranking by a feature
(`cross_sectional_relative_value`) or conditioning on a discrete regime
(`regime_conditional_persistence`), this asks whether orthogonalizing away the shared
market/sector factors first reveals structure invisible in the raw cross-section.

**Comparison bar** (corrected 2026-08-07 in the hub doc, restated here): the bar is raw
per-symbol IC and the existing pooled/cross-sectional IC already in `feature_ic_scores` — not
"beat `cross_sectional_relative_value`," since Phase 167 is confirmed FAIL at authoritative tier
and is not a proven champion to clear. If residualizing beats those existing baselines, that is
real evidence a K-factor decomposition adds something the current pooled measurement misses.

## Why K-selection is a hard gate, not an execution detail

With effective breadth measured ~4.5-8.4 (`scripts/analysis/effective_breadth_diagnostic.py`,
2026-08-07), a PCA over this universe may only have a handful of meaningful factors before
hitting noise. Picking K by eyeballing a scree plot, or worse, by trying a few K values and
reporting whichever gives the best downstream IC, is the same p-hacking shape
`adaptive_combiner_weights`' pre-registered halflife-grid discipline exists to prevent. K must
be fixed by a method that never looks at the IC target, **before** Stage 2 runs at all.

## Staged design

**Stage 1 — K-selection (this doc's script, no IC target touched).**
`scripts/analysis/statistical_factor_residual_k_selection_pilot.py`. Two independent,
unsupervised criteria on the daily log-return correlation matrix:

1. **Marchenko-Pastur (MP) threshold** — Random Matrix Theory: for an N-asset, T-observation
   correlation matrix with no true common structure, eigenvalues are bounded above by
   `lambda_max = (1 + sqrt(N/T))^2`. Any real eigenvalue exceeding this analytical bound signals
   a genuine common factor, not noise. Closed-form, no simulation, no lookahead (computed once
   on a fixed trailing window).
2. **Parallel Analysis (Horn's method)** — permute each symbol's return series independently
   (destroys cross-sectional correlation, preserves each symbol's own marginal distribution),
   recompute the eigenvalue spectrum 200 times, take the 95th percentile of the permuted
   top-eigenvalue distribution as an empirical noise ceiling. Corroborates MP with a
   resampling-based check, matching this project's existing bootstrap/shuffle-null culture
   (`ic_math.py`'s circular block bootstrap, `canary_acausal_placebo`) rather than trusting a
   single analytical formula alone.

**Pre-registered decision rule** (written before running): if MP's and PA's implied K agree
within 1, use MP's K (analytically cleaner, no simulation noise). If they disagree by more than
1, use the **smaller** (more conservative) K and flag the disagreement explicitly — never pick
whichever is larger because it gives the residual construction more room to show an effect.

Run at two window scopes, matching `effective_breadth_diagnostic.py`'s precedent for direct
comparability against the already-measured breadth numbers: the full current active universe,
and the pre-2026-08-05-expansion universe alone (same window), to see whether the expansion
changed the factor count, not just the breadth number.

**Stage 2 — Causal factor fit.** Fit PCA with Stage 1's fixed K=10, strictly causally — no
look-ahead in the factor loadings. Design, pre-registered 2026-08-12 before writing code:

**Walk-forward refit, mirroring `regime_writer.py`'s existing HMM walk-forward pattern
(`_compute_symbol_tf_walk_forward`) rather than inventing a new causal-fit shape** — same
project, same problem class (a fitted model whose parameters must never see data past the bar
being labeled), reuse the proven mechanism:

- **Window: expanding prefix**, matching the HMM precedent exactly (`train_slice =
  returns[:boundary]`, not a fixed rolling lookback) — each refit sees strictly more history
  than the last, never less.
- **`initial_warmup_bars = 252`** (~1 trading year) — standard trailing window for this class of
  factor decomposition industry-wide, and enough for a stable initial covariance estimate.
- **`refit_every_bars = 21`** (~1 trading month) — balances staleness (loadings computed once on
  years-old data misrepresent current factor structure) against noise (refitting too often on
  small increments makes loadings jumpy).
- **`StandardScaler` refit per segment**, fit only on that segment's own training prefix, never
  globally — same leak-in-miniature warning `regime_writer.py`'s docstring already states for
  its own scaler.
- **PCA-specific problem the HMM precedent doesn't have: sign ambiguity.** Eigenvectors have no
  canonical sign — a component can flip sign between consecutive refits with zero change in
  what it explains, which would make the resulting "factor 3" incoherent across time if not
  corrected. Fix: after each refit (except the first), align each of the K components to the
  *previous* refit's corresponding component by sign (flip if the dot product is negative)
  before using it. Needs an explicit test, not just a design note — see Stage 2 result below.
- **Universe scope**: symbols with complete history back through `initial_warmup_bars` before
  the first refit boundary only (same choice Stage 1's "OLD universe, same window" cross-check
  already made, for the same reason — PCA needs a consistent column set, and silently
  interpolating/dropping mid-series for newer symbols would itself be a data-integrity
  compromise, not a neutral simplification). **Known limitation, not silently accepted**: this
  under-covers the 2026-08-05/06 universe expansion's newest names for early segments of the
  fit. Acceptable for a Stage 2 mechanism build; would need real handling (e.g., admitting new
  symbols mid-series once they clear their own warmup) before any production use.

Compute the idiosyncratic residual return series per symbol per bar:
`residual_t = actual_return_t - loadings_boundary @ factor_scores_t`, using only the loadings
from the most recent refit boundary <= t — the same "at any bar t, only data through the most
recent refit boundary labeled it" invariant the HMM precedent states explicitly.

**K re-measured for Stage 2's actual universe, 2026-08-12 — do not reuse Stage 1's K=10.**
Stage 1's K=10 was measured on the full 231-symbol universe over a 349-day common window
(bounded by the newest 2026-08-05/06 additions). Stage 2's "complete history back through
warmup" scoping rule (above) can only use symbols with much deeper clean history — checked
live: 349 days gives 109 symbols, but a window long enough for a real walk-forward (many
refit segments past the 252-day warmup) needs far more. **96 symbols have zero gaps over the
trailing 2000 trading days (~8 years)** — re-ran the identical MP/PA K-selection method on
exactly this universe/window: **MP and PA agree again, K=9.** Using K=10 (measured on a
different, larger, much-shorter-window universe) against this data would have been a real
mismatch, not just an approximation — re-measuring on the actual data a stage will consume,
every time, rather than carrying a number across a scope change, is the same discipline this
project's `HMM_RANDOM_STATE`/BIC-K precedent already established.

**Stage 3 — Falsification bar (not started).** Does `ctf_momentum` (or the
`nonlinear_interaction_combiner` tree score) computed on the residual return series show a
materially higher IC than on raw returns, against the bar defined above (raw per-symbol IC +
existing `feature_ic_scores` pooled/cross-sectional IC)? Day-clustered bootstrap CI
(`ic_math.py::_circular_block_bootstrap_ic`), BH-FDR across cells, same harness as every other
candidate in this track. If residualizing doesn't change the IC picture, `statistical_factor_residual`
is dead.

## Reuse plan — what's new code vs. existing primitives

| Need | Source |
|---|---|
| Daily close fetch, correlation matrix, windowing | `scripts/analysis/effective_breadth_diagnostic.py` (query + window pattern reused directly) |
| Eigenvalue decomposition | `numpy.linalg.eigvalsh` (already used by the breadth script) |
| Day-clustered bootstrap CI (Stage 3) | `src/intelligence/statistics/ic_math.py::_circular_block_bootstrap_ic` |
| BH-FDR (Stage 3) | `src/intelligence/statistics/ic_math.py::apply_bh_fdr` |
| MP threshold, Parallel Analysis, K-decision rule | **New** — `statistical_factor_residual_k_selection_pilot.py`, ~90 lines, no new external dependencies (pure numpy/pandas) |
| PCA factor fit + residual construction (Stage 2) | **New**, not yet written — gated on this doc's Stage 1 result |

## Data verified live, 2026-08-11

Reuses `effective_breadth_diagnostic.py`'s exact query (`market_data_ohlcv_tradeable`, `1d`,
`is_active = true` join to `instruments`) — that script already confirmed this query returns a
usable multi-year common window across the current active universe as of 2026-08-07; re-verified
current as of this doc via the same query path in Stage 1's run below.

## Promotion boundary

A PASS at Stage 3 does not auto-promote to a live construction — that is a separate, later
decision. If it does promote, the residual series would need its own persistence path (not yet
designed) distinct from the raw-return-based `feature_vectors` columns it would sit alongside.

## Result — Stage 1 (K-selection), run 2026-08-11

**Marchenko-Pastur and Parallel Analysis agree exactly on both windows — no disagreement to
arbitrate, the cleanest possible outcome for this design.**

| Window | N | T | MP K | PA K | Decision |
|---|---|---|---|---|---|
| Full active universe (231 symbols) | 231 | 349 days | 10 | 10 | **K=10** |
| Pre-expansion universe only, same window (80 symbols) | 80 | 349 days | 5 | 5 | K=5 |

Top eigenvalues, full universe: `[73.0, 20.4, 12.5, 10.0, 7.1, 6.3, 5.1, 4.3, 3.5, 3.3, ...]` vs.
MP noise ceiling `3.29` — a clear, well-separated drop-off, not a borderline call (the 10th real
eigenvalue at 3.32 barely clears 3.29, but eigenvalues 11+ presumably fall well below it; worth
spot-checking the immediate next few if Stage 2's result is sensitive to K=10 vs K=9).

**Decision for Stage 2: K=10**, using the full active universe (231 symbols) — that's the actual
corpus any promoted construction would run against, not the pre-expansion subset. The old-universe
K=5 result is a useful cross-check (roughly doubling the universe size added roughly double the
factor count, consistent with more sector/theme diversity rather than pure noise inflation — a
mild positive signal that the 2026-08-05/06 expansion added real structure, not just correlated
padding, though this is a side observation, not this doc's falsification target).

**One caveat, not yet resolved:** `T=349` trading days (~1.4 years) is the common window bounded
by the shortest-history symbol in the full-universe case — some 2026-08-05/06 additions have
limited history. Before Stage 2 runs, worth a robustness check with a longer window restricted to
symbols with deeper history (same pattern as `effective_breadth_diagnostic.py`'s "Window 3"), to
confirm K=10 isn't an artifact of the short common window. Not done in this run — flagging rather
than blocking, since MP/PA's exact agreement on the available window is already a good sign.

## Result — Stage 2 (causal factor fit), run 2026-08-12

**Clean pass. Script: `scripts/analysis/statistical_factor_residual_stage2_causal_fit.py`.**
96-symbol long-history universe (2000 trading days, ~8yr), K=9 (re-measured for this exact
universe/window — see above, not Stage 1's K=10), walk-forward: `initial_warmup_bars=252`,
`refit_every_bars=21`.

- **84 refit segments** over the 2000-day window — a real walk-forward test, not a toy sample.
- **Causality: PASS**, `0.00e+00` max diff on the truncated-vs-full early-segment check — no
  look-ahead in the factor loadings, confirmed not assumed, same rigor as every other stage.
- **51.1% mean variance removed** by the 9 factors (raw return variance 5.74e-4 -> residual
  variance 2.80e-4) — a plausible number for equity factor decomposition (broad market/sector
  factors typically explain 30-60% of individual-stock variance industry-wide), not a
  suspicious extreme.
- **Per-symbol spread**: 6.4%-95.1% removed, median 51.3% — broad/index-like names have more
  variance explained by common factors, idiosyncratic single-names have less. Expected shape.

**Known limitation confirmed live, not just theoretical**: the 96-symbol universe excludes
recent IPOs and newer ETFs (e.g. `BITX`) that lack the ~8yr history this window needs — same
gap Stage 1's cross-check already flagged, now concretely identified rather than abstract.

**Stage 3 (IC falsification) not started.** Needs `feature_vectors`/`ctf_momentum`, gated on
the concurrent corpus pipeline (`ops_corpus_pipeline_run.sh`) finishing — genuinely separate,
later step, deliberately not run in the same pass per the pre-registration discipline.

## Result — Stage 3 (IC falsification), run 2026-09-01

**DEAD. Script: `scripts/analysis/statistical_factor_residual_stage3_ic_falsification.py`.**
Design locked in the script's own docstring before running (comparison bar, three
measurement axes, warmup-asymmetry handling — see that file). Full rigor run: APR default
`n_boot=2000`, `block_size=10`, universe re-fetched fresh this session.

**Universe fetch changed before Stage 3 could even run**, and is its own finding: the
trailing 2000-day window now contains 16 corpus-wide gap dates (12 from a live-ingestion
outage discovered and filed as todo 366 this session — the consumer chain behind todo
306/363's `ib-gateway` fix was never restarted, most of the universe has had zero new bars
since 2026-08-12; 4 older isolated gaps 2026-06-23/24, 2026-07-29/30), which under the
original zero-tolerance-for-any-gap `_fetch_universe` silently zeroed the "complete
history" universe to 0/231 symbols. Fixed by excluding those specific gap DATES (not
interpolating any value) before the per-symbol completeness check — net effect grew the
usable universe from Stage 2's original 96 symbols to **148**, not a narrowing. K
re-measured per this doc's own "never carry K across a scope change" rule (MP and PA
agree exactly again): **K=11** for N=148, T=1984 (was K=9 for the old 96-symbol universe).
Stage 2 re-run clean on the corrected universe: 83 refit segments, causality PASS
(`0.00e+00`), 55.9% mean variance removed (vs. the original run's 51.1% — consistent,
not a red flag). User direction: live-ingestion freshness itself is explicitly not
urgent (decades of history already available, no proven edge yet to protect) — todo 366
stays filed but does not block this or any other research thread.

**Falsification result, all three measurement axes, raw vs. residual ctf_momentum
(Wilder RSI, tf=1d, `return_mid`/lookahead=5, on identical (symbol, date) pairs):**

| Axis | raw IC | raw CI | residual IC | residual CI |
|---|---|---|---|---|
| Pooled (n=231,472) | -0.0170 | [-0.0223, -0.0121] excludes zero | -0.0007 | [-0.0060, 0.0047] crosses zero |
| Cross-sectional (same-day rank, n=231,472) | -0.0018 | [-0.0067, 0.0032] crosses zero | -0.0006 | [-0.0051, 0.0037] crosses zero |
| Per-symbol (148 symbols, BH-FDR) | median -0.0294, 8/148 pass | — | median -0.0039, 8/148 pass | — |

Residualizing did not help — if anything it pulled the momentum signal's IC *toward*
zero on every axis (pooled |IC| dropped from 0.0170 to 0.0007; per-symbol median from
-0.0294 to -0.0039), the opposite of the thesis's prediction. The 8/148 per-symbol
BH-FDR passes are identical in count for both raw and residual — consistent with the
~5% FDR-alpha base rate expected under the null for both, not evidence of a residual
edge. Per the pre-registered verdict rule: **`statistical_factor_residual` is dead.**

This closes the discovery-track thread `statistical_factor_residual` opened as. Per
`project_discovery_track_pilot_results_2026_08_07` memory's framing, this makes 5/5
discovery-track candidates run to a definitive verdict DEAD (`jump_diffusion_decomposition`,
`cointegrated_pairs_residual`, `retail_immediacy_provision`'s levered-sleeve sharpening,
`dealer_hedging_flow`'s expiry-calendar screen, now `statistical_factor_residual`) — surface
this before starting a 6th, per that memory's own standing instruction.

## References

- `docs/research/data-edge-source-thesis.md` — hub doc, thesis summary
- `docs/research/measurement-cointegrated-pairs-residual.md`,
  `docs/research/measurement-jump-diffusion-decomposition.md` — sibling candidates, same
  discovery-track session pattern, both DEAD 2026-08-07
- `scripts/analysis/effective_breadth_diagnostic.py` — reused query/window pattern, effective
  breadth ~4.5-8.4 context
- `src/intelligence/statistics/ic_math.py` — reused statistical primitives (Stage 3)
