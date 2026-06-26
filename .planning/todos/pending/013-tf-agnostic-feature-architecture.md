---
title: TF-agnostic feature store architecture (context_features gate)
area: architecture
priority: PROMOTED — now Phase 140.5 P5. Elevated from "design only when needed" to pre-Phase 141 prerequisite: daily-cadence features currently duplicated at bar cadence inflate Spearman IC via artificial autocorrelation. See ROADMAP.md Phase 140.5 P5 for full design.
gate: build before Phase 141 CORPUS-01 feature distribution audit
---

## The Problem

`feature_vectors` is one row per (symbol, tf, bar_ts). Features without a natural bar
cadence cannot live here without duplication or staleness:

- VIX level / VIX term structure (daily, updated once per session)
- Yield curve shape / Fed funds rate (daily or event-driven)
- Cross-asset correlations (rolling, meaningful at daily or weekly horizon)
- Macro regime indicators (monthly)
- Cross-sectional features requiring ALL symbols at the same instant

Injecting daily values into every 5m bar row for the same calendar day produces
artificial precision and masks the actual information frequency.

## The Renaissance Answer

Medallion explicitly separates "fast" signals (intraday, TF-native) from "slow" signals
(multi-day, cadence-agnostic). Different feature stores, joined at inference time by date.
A feature's native cadence should match its intended lookahead horizon.

## Proposed Design

A separate `context_features` table:

```sql
context_features (
  feature_date  DATE,               -- calendar date this snapshot covers
  feature_name  TEXT,               -- same vocabulary as feature_ic_scores
  symbol        TEXT NULL,          -- NULL for market-wide (VIX, yield curve)
  value         DOUBLE PRECISION,
  source        TEXT,               -- 'ibkr', 'fred', 'derived'
  computed_at   TIMESTAMPTZ
)
```

IC Engine joins `feature_vectors` with `context_features` at computation time via
`DATE(bar_ts) = feature_date`. TF-native features pull from `feature_vectors`;
cadence-agnostic features pull from `context_features`.

## Gate

Do NOT design or implement until at least one concrete TF-agnostic feature is proven
needed and defined. Don't build the pipe before the water exists.

This todo is the prerequisite for 008 (context features cluster). Design the table here;
the providers implement against it in 008.
