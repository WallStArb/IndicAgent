---
created: 2026-04-23T15:53:50.381Z
title: BI Analytics Layer — Apache Superset
area: tooling
priority: low
v3_phase: Phase B+ — natural trigger is when IC scores + feature_ic_scores table are populated and need exploration; Superset connects directly to TimescaleDB
files:
  - docs/ideas/bi-analytics-layer-design.md
---

## Problem

IndicAgent has no analytical visualization layer. Grafana covers ops, Next.js covers real-time signals, but there's no way to explore signal outcomes, validate edge, check calibration, or audit data quality without writing raw SQL. Months of labeled outcomes sit in TimescaleDB unused for research.

## Solution

Full design spec at `docs/ideas/bi-analytics-layer-design.md`. MVP scope:

- **Apache Superset** in Docker (:8088), connected to TimescaleDB via read-only user
- **2 dashboards:** Edge Audit (quant desk) + Pipeline Health (risk desk), ~8 charts total
- **4 continuous aggregates:** `analytics_signal_calibration`, `analytics_data_quality`, `analytics_setup_performance`, `analytics_outcome_distribution`
- **Statistical rigor:** Every chart includes N, CI, minimum sample thresholds (N < 30 flagged)
- **Renaissance principles:** One-way data flow, zero ETL, every chart answers a decision
- ~2GB RAM, no contention on server (16GB available)

Pre-requisites: Current phases (67-68) should complete first. Also consider stopping unused MLflow container (1.9GB reclaimable).
