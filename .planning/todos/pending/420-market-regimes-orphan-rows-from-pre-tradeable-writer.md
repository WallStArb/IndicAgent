---
status: pending
priority: P2
filed: 2026-09-24
source: Phase 179 V4 diagnosis (weekend 1d regime labels)
---

# market_regimes keeps orphan rows the current writer no longer produces

## What

`cross_sectional_regime_model` recomputes full history each run and upserts (`ON CONFLICT DO
UPDATE`), never deleting. Rows it wrote before 7054f6da5 (2026-07-16, switch to
`market_data_ohlcv_tradeable`) at timestamps it no longer labels survive: 1,223,265 weekend rows
for equity and rates across all four tfs (1d: 2,012 equity + 912 rates; 5m: 595,008 + 266,454;
15m: 198,336 + 88,818; 1h: 49,539 + 22,186), latest 2026-07-05 (equity) / 2026-06-28 (rates).
Commodity and fx have none.

Verified harmless for IC today: no `feature_vectors` row falls on a weekend at any tf, so none of
these join a cell. Not yet measured: weekday orphans (intraday timestamps the current writer no
longer labels) that could coincide with a real feature row and hand a cell a stale label.

## What to do

1. Dry-run the writer and diff its (group, tf, ts) set against `market_regimes`; report orphan
   counts by weekday/weekend and how many orphan timestamps join a `feature_vectors` row.
2. Make the writer replace each (regime_group, tf) history atomically (delete + insert in one
   transaction), since it always recomputes full history; delete the orphans.
3. Any orphan that joined a feature row changes IC cells: land with the next planned recompute
   (ic_engine's market_regimes watermark will invalidate the affected cells).
