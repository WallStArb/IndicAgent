---
status: pending
priority: P2
filed: 2026-09-25
source: checking externally owned columns after the todo 426 native-upsert probe
---

# 1d regime_volatility is populated on at most 31% of rows for every symbol

## What

`feature_vectors.regime_volatility` (owned by `regime_writer --regime-column regime_volatility`,
walk-forward HMM, todo 248) at tf=1d: 230 of 233 symbols have it on <= 17% of rows, the other 3
on 21-31%; XOM and TLT have none. SPY has it only for 2010-07..2011 (252 rows, about one refit
segment) and nothing in any later year, so this is not a warmup effect: after the initial warmup
every later bar should carry a walk-forward label. GLD's and QQQ's start in 2014/2016 and cover
756 rows (three segments). The writer decides per segment whether to write
(`_walk_forward_hmm_full` / `_compute_symbol_tf_walk_forward`, ~line 888); a fit-quality skip or
an interrupted run are the likely causes.

Consumers: ic_engine's per-symbol volatility-regime cells (`symbol_hmm`, 1,800 rows at 1d vs
~600k cross-sectional), so per-symbol 1d volatility-regime IC is measured on a sliver of history.
Phase 179 is unaffected (pooled equity-group labels from `market_regimes`). Intraday tfs not yet
measured (a count over 72M 5m rows; run it off-peak).

## What to do

1. Count coverage by (tf, year) for a few symbols per tf; read regime_writer's segment-skip
   reasons (its log) for SPY 1d.
2. If segments are skipped by a gate, decide whether a skipped segment should carry NULL (today)
   or the prior segment's model; if the run was interrupted, rerun the family, which now needs
   todo 426's write path (the decompress-all session is refused on feature_vectors).
