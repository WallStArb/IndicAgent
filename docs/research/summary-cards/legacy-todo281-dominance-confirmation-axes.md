---
card_id: legacy-todo281-dominance-confirmation-axes
kind: legacy_verdict
title: Todo 281 systematic-dominance and volume-price-confirmation as HMM regime axes
idea: "Idiosyncratic-versus-systematic dominance and volume-price confirmation each define a persistent single-security regime that a K-state HMM identifies."
verdict: REJECTED_AS_AXIS
verdict_date: 2026-08-08
recipe:
  spec: null
  script: scripts/analysis/hmm_candidate_regime_axes_identifiability_sweep.py
  recipe_commit: a9252f8efa3eac1d9eadc3a5c41e0e2b971138b9
results:
  - name: systematic_signal_fraction_w60
    value: "0.401 (1d) / 0.213 (1h), positive on 32 of 32 cells, null -0.031 / -0.021"
    source: .planning/milestones/v3.1-phases/171-hmm-walk-forward-regime-labeling-parameter-lookahead-fix/171-CANDIDATE-REGIME-AXES-FINDINGS.md#61-systematic--build-as-a-feature-reject-as-a-regime
  - name: systematic_hmm_identifiability
    value: "32/32 only at K=2, W=250 (min agreement 0.9996, min kappa 0.9992) where the null arm passes 29/32; at W=60 the real arm fails XLF/1d (0.7935/0.5803) while the null arm passes 32/32; K=3 fails on 8-10 cells at every window"
    source: .planning/milestones/v3.1-phases/171-hmm-walk-forward-regime-labeling-parameter-lookahead-fix/171-CANDIDATE-REGIME-AXES-FINDINGS.md#61-systematic--build-as-a-feature-reject-as-a-regime
  - name: volume_price_signal_fraction_w250
    value: "0.375 (1d) / 0.310 (1h); rises monotonically 0.06, 0.17, 0.26, 0.375 from W=20 to W=250; positive on 15/16 (1d) and 16/17 (1h) cells"
    source: .planning/milestones/v3.1-phases/171-hmm-walk-forward-regime-labeling-parameter-lookahead-fix/171-CANDIDATE-REGIME-AXES-FINDINGS.md#64-volume_price--defer-build-as-a-feature-gate-on-ic
  - name: volume_price_hmm_identifiability
    value: "K=2: 32/34 at W=60 and W=120, 27/34 at W=250 (null arm 29/34, 27/34, 30/34); K=3 19-27/34"
    source: .planning/milestones/v3.1-phases/171-hmm-walk-forward-regime-labeling-parameter-lookahead-fix/171-CANDIDATE-REGIME-AXES-FINDINGS.md#53-where-the-statistic-is-real-the-hmm-is-where-quality-is-lost
  - name: ledger_signal_fraction_range
    value: "0.375 to 0.401 at best window for both statistics"
    source: docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
known_defects:
  - "The identifiability gate the project used does not discriminate signal from noise: an IID-permuted null arm passed it as often as the real arm (persistence axis 34/34 real and 34/34 null at signal fraction -0.006). The verdict rests on the null-arm comparison, not on the gate."
  - "The IC-separation-across-buckets test (does IC differ across the statistic's own quantile buckets) was never run on either statistic; the ledger records it as pending."
  - "The sweep covered 17 symbols across 2 timeframes (1d and 1h), so per-cell counts are out of 32 to 34, not the full universe."
  - "The sweep read 1d and 1h data through about 2026-07-28, so it read data at or after alpha.validation.oos_start."
spans_looked_at:
  - {start: 2006-09-01, end: 2026-07-28, role: full_history}
forward_span_looks: 1
tables: [market_data_ohlcv_tradeable, instrument_tags, config_state]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - .planning/milestones/v3.1-phases/171-hmm-walk-forward-regime-labeling-parameter-lookahead-fix/171-CANDIDATE-REGIME-AXES-FINDINGS.md
  - .planning/todos/completed/281-systematic-dominance-and-volume-price-confirmation-as-feature-primitives.md
  - scripts/analysis/hmm_regime_axis_decomposition_identifiability_sweep.py
  - docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
related_cards: []
---

# Todo 281 systematic-dominance and volume-price-confirmation as HMM regime axes

Author: Claude Sonnet 5.5, 2026-09-29
Informed by: `docs/research/construction-verdict-ledger.md` section 4 row Todo 281; `171-CANDIDATE-REGIME-AXES-FINDINGS.md` sections 5.3, 6.1, 6.4

## What was tried

Phase 171 follow-on: four candidate single-security regime axes were tested for standalone
identifiability with `hmm_candidate_regime_axes_identifiability_sweep.py`. Two are the todo 281
statistics: systematic dominance (rolling R-squared and beta versus a benchmark) and
volume-price confirmation (rolling correlation of absolute return with relative volume). Each
was probed for signal fraction, then fit with a 2-state and 3-state HMM at several windows, with
every configuration re-fit on an IID-permuted null series.

## What was found

Both statistics are real: signal fraction 0.401 (1d) at W=60 for systematic dominance and 0.375
at W=250 for volume-price confirmation. Neither is a good HMM regime. Identifiability and
signal fraction move in opposite directions, and the null arm beats or matches the real arm
where the statistic is best (volume-price: 27/34 real against 30/34 null at W=250). The
verdict is that they are the wrong shape for an HMM regime, not wrong as continuous features.

## Known defects

See front matter. The persistence and tail axes in the same sweep were rejected outright with
signal fractions near zero; they belong to no card in this set.

## Why closed

Frozen as REJECTED_AS_AXIS. This card does not close the features: both statistics are not dead
as features. Ledger section 1 family 10 (volume and order flow) carries them as pending members,
with the IC-separation test still to run, so a reader must not treat this card as closing them.
The axis verdict cannot be rerun as-is: the recipe script is deleted by 186-16, `feature_vectors`
and the regime columns are rebuilt, and E15 changed the gates.

## Where the numbers came from

Signal fractions, identifiability counts and null-arm counts are copied from sections 5.3, 6.1
and 6.4 of the 171 findings doc; the ledger row gives the 0.375 to 0.401 range. No query was run
and no script was rerun.

`recipe_commit` is `git log -1 --format=%H --before="2026-08-08 23:59:59" -- scripts/analysis/hmm_candidate_regime_axes_identifiability_sweep.py`.
The sweep imports helpers from `hmm_regime_axis_decomposition_identifiability_sweep.py`, listed
in `sources`. `tables` come from those scripts' SQL (`market_data_ohlcv_tradeable` OHLCV fetch,
`instrument_tags`, `config_state`).

The span start follows the 186-01 corpus start convention; the findings doc gives cell counts
only. The end (2026-07-28) is the data freshness the 2026-08-07 research docs state.
`forward_span_looks` is 1: the sweep read data at or after 2025-12-24 and no other card counts
it. The ledger's todo 281 row is the frozen verdict; the findings doc dates it 2026-08-08.
