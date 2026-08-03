---
status: closed
priority: P1
filed: 2026-07-26
closed: 2026-07-26
source: live diagnostic while running scripts/analysis/nonlinear_interaction_combiner_lightgbm_check.py
  (Edge Source Thesis nonlinear_interaction_combiner falsification test)
---

# nonlinear_interaction_combiner's LightGBM combiner shows a suspiciously large OOS IC uplift — needs a canary-leakage check before it counts as evidence

**CLOSED 2026-07-26 — check ran, this specific failure mode is ruled out (not a full pass).**
Built `scripts/analysis/t5_canary_leakage_check.py` (deleted 2026-07-28, git-history only), reusing
`nonlinear_interaction_combiner_lightgbm_check.py`'s `_train_and_predict_oos`/`_per_symbol_ic_ci`
verbatim. Result: all 4 negative-control canaries (`canary_constant`, `canary_near_constant`,
`canary_noise_gaussian`, `canary_noise_uniform`) show 0/10 symbols clearing `ci_lower>0` and
near-zero/undefined mean IC — clean. `canary_acausal_placebo` (the deliberate look-ahead-leak
positive control) shows a small standalone IC (0.016, 5/10 pass) and moderate gain-importance
rank (13.4/152) — expected, correct behavior for a working positive control, not a red flag.
**Decisive check: aggregate tree IC is essentially unchanged with vs. without this maximally-
leaky feature available (0.2992 → 0.2999, Δ=+0.0007)** — if look-ahead leakage were driving
the 0.30 result, adding a stronger version of that exact leak class should have moved the
needle; it didn't. Full write-up: `docs/research/data-edge-source-thesis.md`'s nonlinear_interaction_combiner section.

**Real methodology finding along the way, worth remembering:** the script's first two
verdict-logic attempts used gain-importance thresholds (an absolute `<1.0` cutoff, then a
relative `<5% of median real feature importance` cutoff) — both produced misleading
"investigate, possible overfitting" verdicts, because in this shallow (depth 4), heavily
regularized (`min_child_samples=200`), 152-feature forest, the median REAL feature's own gain
importance (2.0) sits barely above what a pure-noise column gets by chance. Gain importance
simply isn't a discriminating statistic in this regime. Fixed by basing the verdict on
standalone per-symbol IC instead — the calibrated, unambiguous statistic this whole project
already trusts (same units as every other IC measurement in the corpus). A third bug
(`abs(nan) < 0.02` silently evaluates `False` in Python, since NaN comparisons are never true)
initially made `canary_constant`'s correctly-undefined IC — a zero-variance column has no
defined correlation — read as "not clean." Fixed by explicitly treating NaN as the expected,
vacuously-clean outcome for a literally-constant canary.

**What this does NOT prove:** nonlinear_interaction_combiner's 0.30 result is still ~3x anything else measured in this
corpus and needs independent replication (a different tf, a different OOS window) before any
production consideration — this check ruled out one specific, well-targeted failure mode
(look-ahead-style leakage), not general overfitting risk.

## What happened

`scripts/analysis/nonlinear_interaction_combiner_lightgbm_check.py` (Edge Source Thesis nonlinear_interaction_combiner: does a
non-linear combiner over the identical 147 `feature_vectors` columns find interaction
structure the linear ensemble can't) already caught and fixed one real leak during
development: naive pooled training showed mean OOS `point_ic`≈0.30 with 80/80 symbols
passing, traced to the tree implicitly learning each ETF's own persistent long-run drift (a
fixed-membership factor-exposure leak, not bar-level signal). Fixed by subtracting each
symbol's own causal (shift(1), expanding) mean `return_fast` before training/measuring.

**After that fix, the number didn't come down** — equity/1h, walk-forward OOS, day-clustered
bootstrap CI: tree combiner mean `point_ic`=0.2992 (80/80 symbols pass, `ci_lower`>0), vs.
`ctf_momentum` alone at 0.0887 (79/80 pass). A within-bar_ts cross-sectional-neutral
decomposition (subtract each bar_ts's cross-sectional mean from both prediction and actual)
confirms it isn't purely a common-market-factor artifact either: tree `point_ic`=0.258,
`ci_lower`=0.254; feature `point_ic`=0.080, `ci_lower`=0.076.

## Why this isn't a pass yet

0.30 mean OOS IC is far outside anything else measured in this corpus — the strongest single
standalone feature anywhere else has topped out around 0.10-0.13 (`ctf_momentum` itself, the
baseline used here). Having already found and fixed one leak in this exact script today, the
correct prior on a second unexplained 3x-outlier result is skepticism, not celebration —
matches this project's general disposition toward "genuinely surprising positive result" (see
`docs/foundation/principles.md`, resist overfitting).

## The check that settled it

`feature_vectors` already has purpose-built leakage canaries, currently excluded from the
script's feature set entirely (`_EXCLUDE_COLS`): `canary_acausal_placebo`,
`canary_constant`, `canary_near_constant`, `canary_noise_gaussian`, `canary_noise_uniform`.
Reran the identical walk-forward/OOS/bootstrap pipeline with these *included* as features —
see the CLOSED note above for the result.

## References

- `scripts/analysis/nonlinear_interaction_combiner_lightgbm_check.py` — the script itself, full result
  in its stdout and now `docs/research/data-edge-source-thesis.md`'s nonlinear_interaction_combiner section
- `scripts/analysis/t5_canary_leakage_check.py` — deleted 2026-07-28, git-history only -- the canary check this todo asked for, built
  and run 2026-07-26
- `docs/ideas/measurement-nonlinear-interaction-combiner.md` — nonlinear_interaction_combiner's design and overfitting
  controls
- `docs/research/data-edge-source-thesis.md` — nonlinear_interaction_combiner section, full result including the
  canary-leakage check
