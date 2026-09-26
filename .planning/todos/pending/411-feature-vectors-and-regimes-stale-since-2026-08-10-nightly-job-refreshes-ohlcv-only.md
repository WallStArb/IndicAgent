---
status: pending
priority: P1
filed: 2026-09-24
source: user question on holdout freshness, verified live 2026-09-24
---

# feature_vectors and market_regimes stale since 2026-08-10: the nightly job refreshes OHLCV only

## What

Measured 2026-09-24: 1d `market_data_ohlcv_tradeable` is current (max 2026-09-22/23) for ~215 of
233 symbols, but 1d `feature_vectors` stops at 2026-08-10 (or 08-07) for ~220 of them; only ~8
symbols reach 2026-09-15/17. 1d `market_regimes` stops at 2026-08-12.

Cause: `indicagent-nightly-backfill.service` runs
`scripts/infrastructure/backfill/infrastructure_nightly_backfill.py`, which fetches OHLCV only.
Features for new bars came from the streaming `FeatureVectorPipeline`, which stopped around
2026-08-10 (see todo 366 / the IBKR live-ingestion memory). No batch step computes features or
regimes for bars the nightly job adds. The corpus orchestrator
(`ops_corpus_pipeline_run.sh` step 1, `backfill_feature_factory.py --compute-only`, then the
regime writers) does, but only when run by hand.

## Why it matters

Doesn't touch any in-sample verdict: IC, training and the Phase 179 walk-forward all stop at
`alpha.validation.oos_start` (2025-12-24). It does block everything that reads the holdout or
the present: Phase 179's S5 holdout read, any forward shadow run a PASS opens, and eventual
deployment. A silent 6-week gap is also the same integrity class as todo 395.

## What to do

1. One-time catch-up: `backfill_feature_factory.py --compute-only`, then the regime writers
   (orchestrator steps 1, 2, 4), all symbols. **Not while an ic_engine run is live or
   resumable** until todo 412 lands: new `feature_vectors` rows move ic_engine's upstream
   watermark and would invalidate every completed cell.
2. Chain feature + regime compute after the nightly OHLCV backfill (the automation), after 412,
   or every nightly run triggers a full IC recompute.
3. Emit a freshness check: max(bar_ts) per (symbol, tf) of `feature_vectors` vs OHLCV, alerting
   past N sessions of lag (APR key), through the route todo 395 fixes.

## Gap-fill is not possible with the tool as it stands (checked 2026-09-24)

`backfill_feature_factory.py --compute-only` is all-or-nothing per (symbol, tf): pairs with
`backfill_status.status='complete'` are skipped (all 233 x 4 intraday+1d pairs are), so a plain
run adds zero new bars; `--refresh` recomputes from the first bar and upserts. Both paths fetch
full history (`_fetch_bars_from_db` with no `since`).

Plan:
- 1d: full `--refresh` (~5,000 bars/symbol, cheap, exact by construction). Covers what 179, H-A
  and the holdout read.
- Intraday: add an incremental mode (fetch from last feature bar minus W, insert only bars after
  it). Gate it on an equivalence test: incremental vs full history on a sample of symbols per
  tf must match on the new bars. Long-memory features (EMAs, expanding ranks, swing anchors, HMM
  forward filters, long z-scores) that don't converge within W get persisted state or stay on
  full recompute. Without this check a short warmup leaves a silent seam at the gap boundary.

## Triage 2026-09-26 (backlog review with the owner)

Status 2026-09-26: `feature_vectors` 1d current to 2026-09-24; 5m/15m/1h stop at 2026-09-18. On the feature critical path: todo 435 wires `feature_vectors` into the research layer, so fresh, complete, correct features are a book input.
