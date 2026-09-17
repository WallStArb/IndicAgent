# Design decision: source filtering for instrument_tags in breadth/peer-grouping (todo 379)

Author: Claude Sonnet 5, 2026-09-17

## Problem

`services/equity_regime_model.py` (`_compute_breadth_fraction`, lines ~284-291) and
`services/cross_sectional_regime_model.py` (`_load_tags_by_symbol`, line 377, feeding
`tag_filter`/`signal_tag_filter` resolution at line ~524) both read `instrument_tags`
with no filter on `source`. Confirmed live (Fable, 2026-09-17, with symbol-level
evidence): GLD, AGG, EMB, EMLC, DBC, FXA, FXE carry `source='empirical'` `eq_*`-prefixed
tags with no corresponding `source='human'` tag, and are currently counted into
`equity_regime_model.py`'s equity breadth signal.

This is the sibling of the bug fixed same-day in `ic_engine.py`'s `_build_symbol_regime_class`
(commit `b8af2b749`) — but explicitly a different question. That fix needed exactly one
categorical answer per symbol (which regime group), so `source='human'`-only was
unambiguously correct. Here, the underlying question is sensitivity/behavioral similarity
("does this instrument currently trade like an equity"), not categorical identity — an
empirical `eq_momentum`/`equity_beta`-style tag is arguably a philosophically *more*
correct signal for that question, not less. The reason it's wrong today is that
`TagCalibrator`'s empirical tags are drowning in common-beta noise: with n=250+
observations, trivial shared-market-beta correlation clears statistical significance
easily, so filtering on `passes_fdr=true` instead of `source` resolved 0 of the
`ic_engine.py` bug's 144 collisions — the same is expected to hold here.

## Blast radius (new findings, not in the original todo)

Traced where `market_regimes` rows written by `equity_regime_model.py`
(`asset_class='equity'`) and `cross_sectional_regime_model.py` (`rates`/`commodity`/`fx`)
are actually consumed downstream, since the todo flagged this as unverified:

- **`services/ensemble_trainer.py`** (~line 950-962) — JOINs `feature_vectors` to
  `market_regimes` on `(tf, ts)` and filters `WHERE mr.regime_label = $2` to build
  regime-stratified training data. A polluted breadth label doesn't just mislabel a
  display metric — it silently corrupts which bars get bucketed into which regime
  stratum for every symbol trained under this asset class, not just the mistagged ones.
- **`services/ensemble_ic_engine.py`** (~line 645-715) — same JOIN pattern for
  regime-stratified IC measurement. Has a crash-loud startup gate if `market_regimes`
  is empty ("the 9-label regime stratification the entire measurement..." — comment at
  line 645), i.e. this consumer explicitly treats the regime label as load-bearing for
  measurement validity, not cosmetic.
- **`services/ic_engine.py`** — reads `market_regimes` for scope/labeling in addition
  to the already-fixed `_build_symbol_regime_class` routing path; the routing fix does
  NOT address this breadth-label consumption path, which is separate.
- Several `scripts/ops/alpha/*` and `scripts/analysis/*` diagnostics also read
  `market_regimes`, but spot-checked: **`portfolio_covariance_weighting_diagnostic.py`
  (todo 378's diagnostic) is NOT affected** — it deliberately computes its own
  `causal_regime_labels` from SPY close directly, bypassing `market_regimes`/HMM labels
  for an unrelated, already-documented reason (comment at line ~274).

Net: this is not a cosmetic breadth-metric bug. It reaches training-time stratification
and IC significance testing for the equity/international universe, and peer-grouping
for rates/commodity/fx regime groups. Higher stakes than the todo's framing suggested
before this trace.

## Options

**(a) Stopgap — filter both call sites to `source='human'`, matching the ic_engine.py fix.**
Safe, fast, consistent with the precedent just set. Cost: discards empirical
sensitivity/behavioral data that may have genuine value here once properly filtered —
if TagCalibrator later measures a real, non-common-beta-confounded equity-like behavior
in an untagged symbol, this filter won't surface it until a human manually tags it.

**(b) Materiality-filtered empirical signal** — admit `source='empirical'` tags only
above some economically-justified threshold (not just `passes_fdr`), designed to
reject common-beta noise the way the ic_engine.py investigation showed `passes_fdr`
alone cannot. Needs its own design pass: what threshold, measured how, against what
null (the ic_engine fix's own finding — significance alone doesn't separate signal
from common-market-beta noise at n=250+ — has to be solved here too, not just avoided
by filtering source away).

## Question for review

1. Given the actual blast radius (training stratification + IC measurement, not a
   cosmetic breadth number), does (a) or (b) look right as the *first* fix to land now,
   with the other as a tracked follow-up? Or is there a third option we're missing?
2. If (b) is worth designing now rather than deferring: what's a defensible
   materiality filter that doesn't just reintroduce the `passes_fdr`-alone failure mode
   from the ic_engine.py bug (e.g., loading magnitude threshold vs. some peer-relative
   z-score vs. requiring agreement between empirical AND a definitional proxy)?
3. Apply consistently to BOTH `equity_regime_model.py` and `cross_sectional_regime_model.py`,
   or do they warrant different answers given one is a strict breadth-fraction
   (binary above/below 200MA) and the other is peer-pool membership for
   regime-group-relative signal computation?
