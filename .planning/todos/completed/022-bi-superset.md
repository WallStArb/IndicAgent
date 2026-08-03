---
**Created:** 2026-06-28
**Area:** operations
**Type:** new_feature
**Priority:** P3
**Effort:** 1-2 days
**Benefit:** Self-service BI analytics; ad-hoc queries without SQL
**Risk:** low (new service)
**Gate:** None
---

---
created: 2026-04-23T15:53:50.381Z
title: BI Analytics Layer — Apache Superset
area: tooling
priority: low
v3_phase: Phase B+ — natural trigger is when IC scores + feature_ic_scores table are populated and need exploration; Superset connects directly to TimescaleDB
files:
  - docs/research/bi-analytics-layer-design.md
---

## Problem

IndicAgent has no analytical visualization layer. Grafana covers ops, Next.js covers real-time signals, but there's no way to explore signal outcomes, validate edge, check calibration, or audit data quality without writing raw SQL. Months of labeled outcomes sit in TimescaleDB unused for research.

## Solution

Full design spec at `docs/research/bi-analytics-layer-design.md`. MVP scope:

- **Apache Superset** in Docker (:8088), connected to TimescaleDB via read-only user
- **2 dashboards:** Edge Audit (quant desk) + Pipeline Health (risk desk), ~8 charts total
- **4 continuous aggregates:** `analytics_signal_calibration`, `analytics_data_quality`, `analytics_setup_performance`, `analytics_outcome_distribution`
- **Statistical rigor:** Every chart includes N, CI, minimum sample thresholds (N < 30 flagged)
- **Renaissance principles:** One-way data flow, zero ETL, every chart answers a decision
- ~2GB RAM, no contention on server (16GB available)

Pre-requisites: Current phases (67-68) should complete first. Also consider stopping unused MLflow container (1.9GB reclaimable).

## REJECTED, not pursued -- 2026-08-03

Cut during a backlog-quality pass applying this project's Renaissance-quality bar. Standing up
a whole new Docker service + continuous aggregates + read-only DB role is real infra footprint
for pure convenience -- this is a single-operator system (endgame: personal live trading
capital, not a commercial product) where the operator already queries TimescaleDB directly via
psql and writes ad-hoc analysis scripts constantly (every todo in this backlog demonstrates
that fluency). No proof-of-alpha value, doesn't instrument anything that isn't already
instrumented via Grafana/OTel. Fails Musk step 1 (question the requirement) -- the underlying
"explore signal outcomes without writing SQL" problem doesn't actually exist for this user.
Also badly stale: the named continuous aggregates (`analytics_signal_calibration` etc.)
describe v2.x-era tables that predate the v3.0 rebuild. If a genuine self-service BI need
surfaces later, re-scope from scratch against the current schema rather than reviving this.
Todo 024 (dependent) cut alongside for the same reason.
