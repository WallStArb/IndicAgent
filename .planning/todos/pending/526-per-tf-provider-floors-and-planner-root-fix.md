---
status: pending
priority: P3
filed: 2026-10-09
corrected: 2026-10-09 (premise withdrawn after a dry-run verification; see below)
source: owner directive 2026-10-09 ("depth should be measured correctly for each TF"); corrected by the same day's verification
---

# Provider-head granularity per timeframe (the surviving piece of todo 526)

## Correction 2026-10-09 (the original premise is withdrawn)

The original body claimed the queue infers depth from each series' earliest stored bar, leaving
163 head gaps invisible and requiring an expected-domain planner rework. A dry run of the ten
genuinely short names disproves the claim: the planner already computes gap from
min(depth_days, proven_days, floor) - actual, where proven_days is the deepest stored series of
the symbol (1d, which stays IBKR-deep) and floor is max(ohlcv_provider_head.head_ts,
ohlcv_empty_history.empty_through). ODFL plans 6,197 gap-days, AAP 4,521, IEF and SHY 3,946,
TLT 3,399, CSX 3,356, AMD 3,002, all SLA-banded. The "163 invisible head gaps" were almost
entirely the vendor floors differing (1d floor 2000-01-03, IBKR 5m floor 2006-07): not missing
data. The phase 2 canonical-load hold's rationale dissolves with it: an Alpaca 5m load changes
neither proven depth (1d) nor the floor, so IBKR head planning survives it.

What remains real and worth doing, small:

- `ohlcv_provider_head` has no timeframe column (PK: symbol, provider). The 1d head stands in as
  the floor for every timeframe. For IBKR this is approximately right (1d floor 2000, 5m floor
  2006-07) but the empty-history walk pays a few definitive no-data round trips per name per
  timeframe to discover what a per-TF head row would state outright. Migrate the PK to
  (symbol, provider, timeframe), seed per-TF floors from the measured vendor floors, and let the
  existing walk keep them fresh.

## Done when

The PK migration lands with per-TF floor rows seeded; the queue's floor lookup reads the
per-timeframe row; a before-and-after dry run shows identical planned work (the correctness
bar: no planned-span change, only fewer no-data discovery trips).
