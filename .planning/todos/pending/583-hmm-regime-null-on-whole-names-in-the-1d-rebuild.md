---
status: pending
priority: P1
filed: 2026-11-01
source: todo 564 column screen, per-name view (scripts/ops/ops_feature_column_screen.py)
---

# HMM regime outputs are NULL on whole names in the 186-26 1d rebuild

## What the screen found

The per-name screen on the todo 564 eight-name 1d pool (report
`logs/feature_column_screen_20261101T225359Z.json`) shows the seven `hmm_*` probability and state
columns (`hmm_churn`, `hmm_duration`, `hmm_entropy`, `hmm_prob_ranging`,
`hmm_prob_trending_down`, `hmm_prob_trending_up`, `hmm_regime_prob`) all NULL on three of eight
names, and `regime` NULL with them. A pooled screen does not see it because the other names are
populated.

| symbol | 1d rows | hmm rows | first hmm row |
|---|---|---|---|
| AAPL | 5,470 | 0 | none |
| HON | 5,469 | 0 | none |
| SCCO | 3,929 | 0 | none |
| MSFT | 5,468 | 1,239 | 2018-10-19 |
| KO, JPM | 5,469 | 5,217 | warmup only missing |
| SPY, XOM | 5,465 / 5,468 | all | |

Twenty-one years of AAPL and HON with no regime is not warmup. The likely path is the
walk-forward gate in `src/intelligence/features/kernels/_hmm.py` refusing every segment
(`not_converged` or degenerate state occupation, around lines 613-640 and 959-1004); NULL is the
correct output for a refused fit, so this may be a kernel-input or gate-threshold problem rather
than a persistence one. Related: todo 226 (n_iter convergence headroom).

`equity_beta_z` is NULL on SPY only (beta of the market proxy to itself, by construction) and
populated on about 2,700 of about 5,470 rows on the other names; confirm the window start is
declared, not a gap.

## Done when

1. The refusal reason per (name, segment) is measured across the full 1d universe (how many
   names have no regime at all, and why).
2. The cause is fixed, or the refusal is shown correct and the names are declared regime-unknown,
   before any spec segments by regime on 1d (principle: segment by regime).
