# Phase 171: Final Verdict (authoritative — read this first, not the 4 findings docs below)

**Status: investigation complete, decisive. Date: 2026-08-08.**

This document supersedes `171-MODEL-IDENTIFIABILITY-FINDINGS.md`,
`171-REGIME-DECOMPOSITION-FINDINGS.md`, `171-CANDIDATE-REGIME-AXES-FINDINGS.md`, and
`171-NULL-ARM-VALIDATION-FINDINGS.md`. Each is a real, verified step in the investigation and is
kept for the reasoning trail (each now carries a banner pointing here), but none of their
intermediate recommendations should be cited as current. This document is the only one that
should be treated as settled.

---

## 1. What Phase 171 originally set out to do — still true, unaffected by anything below

`services/regime_writer.py`'s production HMM fits its parameters (means, covariances,
transition matrix) on a symbol's **entire** price history before causally decoding bar-by-bar.
The decode step is genuinely causal; the model doing the deciding was estimated with knowledge
of the whole series — a real, confirmed lookahead-bias violation, tracked since 2026-06-28
(todo 026 P4a / todo 248). The fix — refit periodically on an expanding window, using only data
available at each point in time — was coded and TDD-tested well before this investigation
started (`_walk_forward_hmm_full`, `_seed_prior_from_label`, `_hmm_seed_stability_check`), and
per this project's standing rule, **causal-law violations get fixed regardless of measured
predictive benefit.** Nothing found in this investigation changes that. The walk-forward fitting
*procedure* was never the problem — everything below is about *what the model should be fit on*,
not *how it gets fit*.

## 2. What actually happened, in the order it happened, compressed

1. **Plan 171-05's staged pilot returned NO-GO.** Seed-stability check (does refitting with a
   different random seed reproduce the same regime labels) failed 16/16 tested cells at
   production's `n_components=5`. `171-PILOT-GATE.md`.
2. **Root-cause investigation.** Ruled out a miscalibrated covariance threshold. Found the
   instability was NOT specific to the new walk-forward candidate — production's *current*,
   already-live full-history fit shows the identical failure. `full_cov_min_obs` was a red
   herring.
3. **Model-complexity sweep.** K=5 is non-identifiable on 9/16 cells (two independently-seeded
   fits land on substantively different labels — the formal signature: near-tied competing
   optima, e.g. SPY/1h's two champions agreed on 7.8% of bars off a 0.06% log-likelihood
   difference). K=3 cleared 16/16 with wide margin. BIC still preferred K=5 — BIC measures
   fit quality, not whether the fitting process reliably finds the same answer twice; those
   turned out to be different questions with different answers. `171-MODEL-IDENTIFIABILITY-FINDINGS.md`.
4. **Decomposition test.** The 5-column observation vector (log_return, realized_vol, momentum,
   vol_of_vol, rel_volume) is really three families — trend, volatility, volume — fused into one
   ordinal chain. Tested each in isolation: trend alone identified cleanly at K=2 (best-separated
   axis tested), volatility alone at K=2-3, volume alone **never** identified at any K.
   `171-REGIME-DECOMPOSITION-FINDINGS.md`. A follow-up (composite minus volume) found dropping
   volume didn't raise the achievable K ceiling — neutral, not a drag. Widening the trend check
   to 17 symbols (adding AAPL, MSFT, GOOGL, AMZN, JPM, QQQ, DIA, XLF, XLK) found a clean K=3
   flat/ranging state for every domestic-equity symbol, with degeneracy concentrated in FXY
   (currency), GLD (commodity), TLT (rates), EEM (international) — an apparent asset-class
   pattern.
5. **Four new candidate regime axes tested**, motivated by "what else would a rigorous shop
   look at": idiosyncratic-vs-systematic co-movement, momentum-persistence-vs-mean-reversion,
   tail-risk/skew, volume-price confirmation. In the course of testing these, **a permutation
   (scrambled-data) null-arm control was built** — and it revealed that momentum-persistence
   passed the standard agreement/kappa identifiability test 34/34 times on real data *and* 34/34
   times on data with all structure destroyed. The identifiability battery used everywhere in
   this investigation up to that point could not distinguish real regime structure from a
   two-state model's tendency to reliably split any smooth series into a "low half" and "high
   half." `171-CANDIDATE-REGIME-AXES-FINDINGS.md`.
6. **The null-arm control was applied retroactively to composite K=3, trend, volatility, and
   composite-minus-volume** — the axes this investigation had been about to recommend shipping.
   `171-NULL-ARM-VALIDATION-FINDINGS.md`. This is the result that governs everything below.

## 3. The governing result (verified independently against raw data before being written here)

| axis | real vs. null margin | verdict |
|---|---|---|
| **volatility** (realized_vol, vol_of_vol) | **+0.62** (realized_vol; null stays within ±0.05) | **VALIDATED — real** |
| trend (log_return, momentum) | **−0.02** (statistically indistinguishable from its own null, at every window and timeframe) | **NOT VALIDATED — dead** |
| composite (all 5 columns, K=3) | only `realized_vol` carries real structure; `log_return` — the column production's label vocabulary is ordered by — does not | **PARTIAL — mislabeled** |
| composite-minus-volume | same as composite: only `realized_vol` is real | **PARTIAL — same defect** |
| momentum-persistence (new candidate) | **~0.00**, negative at all 4 windows on 1h | **REJECTED** |
| tail-risk/skew (new candidate) | **0.00–0.11** across a 12.5× window range — not a "needed more data" problem | **REJECTED** |
| idiosyncratic-vs-market co-movement (new candidate) | **+0.40 (1d) / +0.21 (1h)** — real, confirmed by the same null-arm check | **Real signal — build as a feature, not a regime** (identifiability only holds at one narrow config) |
| volume-price confirmation (new candidate) | **+0.375 (1d) / +0.31 (1h)** at a long window | **Real signal — defer**, build as a feature; revisit as a regime only if it earns its place via IC |
| volume alone (original decomposition) | never passed even the (now-known-weak) agreement/kappa test | **dead, doesn't need the null-arm check — already failed the weaker one** |
| trend's asset-class split (equity clean, fx/commodity/rates/intl degenerate) | does not reproduce — the null arm showed **more** degeneracy (7/34 vs 3/34), including in clean domestic-equity cells the real data never touched | **the pattern was a fit-instability artifact, not an economic one — withdrawn** |

**The single most consequential finding:** `_build_label_map` ranks states by `means[:, 0]` =
`log_return`, and production's live label vocabulary (`trending_down` / `transition_down` /
`ranging` / `transition_up` / `trending_up`) is named as if it describes direction. But across
the whole observation vector, direction carries no validated signal — only volatility does.
**Production's current regime label has been a volatility partition wearing trend names, since
before this investigation started, not a defect introduced by anything tested here.**

## 4. What this means, concretely

- **Volatility clustering is real** — consistent with decades of documented market behavior, and
  now independently confirmed for this project's own data, not assumed.
- **Trend/direction as a standalone regime dimension does not exist in this feature set.** Not
  "unstable" or "needs more restarts" — no amount of additional compute fixes a signal that was
  never there. Same failure mode as the rejected persistence candidate, just hiding inside
  something already believed to be working.
- **The asset-class-specific K story is withdrawn**, not refined. It was a genuine, carefully-
  measured pattern in the agreement/kappa numbers — and it was still a fit-stability artifact,
  not economics. This is exactly why the null-arm control matters: a real, reproducible-looking
  pattern in a non-discriminating test is not evidence.
- **Two new real signals were found** (idiosyncratic-vs-market co-movement, volume-price
  confirmation) but neither should become a discrete regime label yet — both should ship as
  continuous features, with regime-conversion deferred pending actual downstream IC evidence
  that discretizing them helps.

## 5. Recommended design (supersedes every composite/trend recommendation made earlier in this investigation)

**Ship `regime_volatility` as a standalone regime, built from `realized_vol` + `vol_of_vol`
only. Retire the composite `regime` column and its trend-flavored label vocabulary entirely.**
Not a compromise — fewer moving parts than every design proposed earlier today, and the only one
with real evidence behind it rather than reproducibility mistaken for validity.

- **Model:** GaussianHMM, 2 observation dimensions (realized_vol, vol_of_vol), `covariance_type=full`,
  K=2 or K=3 (both validated; K=3 preserves the calm/elevated/turbulent framing already familiar
  from the composite's "ranging" concept — recommend K=3 unless a later check finds K=2 meaningfully
  more robust at the wider symbol/timeframe scope).
- **Fitting procedure:** reuse the already-built, already-tested walk-forward fix
  (`_walk_forward_hmm_full` et al.) unchanged in its causal-correctness logic — it was never
  implicated by anything found here. It just needs to run against a 2-column observation slice
  instead of the current 5-column composite. This is a smaller, better-conditioned estimation
  problem than what it was built and tested against, not a step backward.
- **Label vocabulary:** new, honest naming (e.g. `calm` / `elevated` / `turbulent`) — not a
  renamed trend vocabulary. This needs a controlled-vocabulary entry before it ships (see
  CLAUDE.md's Glossary discipline).
- **Trend and volume:** no regime column. Not deferred — dead, on direct evidence.
- **New candidates (idiosyncratic co-movement, volume-price confirmation):** land as plain
  `feature_vectors` columns (todo 281, already filed), not regime labels.
- **K-selection policy going forward:** identifiability is necessary but not sufficient. **Every
  future regime candidate must clear the null-arm block-reliability check before its
  agreement/kappa numbers are trusted at all** — this is now a permanent addition to how this
  project validates any HMM-based regime, not a one-time fix for this phase.

## 6. What's still open, honestly

- **Not yet tested at the wider corpus scope.** Everything here (volatility included) was
  validated on the same 8-to-17-symbol sample used throughout this investigation. Before a
  full-corpus relabel, the same null-arm check needs to run at 15m/5m and across a larger
  symbol sample (the same gap already flagged for the trend axis before it was withdrawn —
  applies equally to volatility now that it's the thing being shipped).
- **`vol_of_vol`'s own margin is window-dependent** (thin at the 20-bar window used everywhere
  else in this investigation, solid from 60 bars up) — the production window choice needs to
  land on a value that's actually been checked, not inherited by default from the old composite
  model's `vol_window=20`.
- **Trend is dead for now, not forever.** Nothing here rules out a *real* directional signal
  existing in a differently-constructed feature (e.g. a longer-horizon trend measure, or one
  that accounts for the volatility regime it's measured within). It just isn't in `log_return`/
  `momentum` at the windows tested. A future attempt should design for this from the start, not
  reuse the composite's columns and hope.
- **Todo 280** (single-name equity symbols like AAPL/MSFT/GOOGL/AMZN/JPM match no enabled
  `alpha.regime.groups` filter, so they're silently excluded from regime-stratified IC) is
  unrelated to this whole arc but was discovered along the way — still open, filed, not blocking.

## 7. Next step

Scope this as Phase 172 ("HMM Regime — Volatility-Only Redesign," or similar), replacing
whatever version of Phase 172 was discussed earlier today around a composite/trend design.
Rough shape: (1) APR migration retiring the 5-column composite, defining the 2-column
volatility observation and new label vocabulary; (2) wire the already-built walk-forward fit
against the new 2-column slice; (3) run the null-arm check at wider scope (15m/5m, larger symbol
sample) before touching the corpus — this is the one gate this investigation's own history says
not to skip; (4) full-corpus relabel; (5) downstream re-verification (`ic_engine` regime strata,
any prior analysis that cited `regime` as a conditioning variable). Phase 171 itself closes here
— its validated deliverable is the walk-forward fitting procedure and the diagnostic tooling that
produced this verdict, not the composite label it was originally aimed at deploying.
