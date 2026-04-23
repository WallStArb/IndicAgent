# BI Analytics Layer — Apache Superset

**Status:** approved design
**Created:** 2026-04-23
**Supersedes:** `docs/ideas/bi-analytics-layer.md`

---

## Problem

IndicAgent has three visualization layers. The analytical layer is missing.

| Layer | Tool | Purpose |
|-------|------|---------|
| Operational | Grafana | Pipeline health, latency, Prometheus metrics |
| Real-time intelligence | Next.js dashboard | Live signals, SSE panels, AI narratives |
| Analytical | *(missing)* | Signal outcomes, edge validation, calibration, data quality |

Months of labeled signal outcomes sit in TimescaleDB. Without a BI layer, every analytical question requires writing raw SQL. That's a bottleneck for strategy development and a risk for undetected data quality issues.

---

## Design Principles (Renaissance)

1. **Every chart answers a decision.** If a chart changes and you can't name the action you'd take, it's noise. Remove it.
2. **Earn the right through proof.** Every performance claim backed by N, confidence intervals, minimum sample thresholds. No conclusions from noise (N < 30).
3. **Let the system run.** Continuous aggregates auto-refresh on schedule. No cron, no microservice, no manual intervention.
4. **Separation of concerns.** Superset is pure presentation. All compute happens in TimescaleDB continuous aggregates. Superset never writes, never triggers computation, never touches the live pipeline.
5. **Data quality over model complexity.** The Pipeline Health dashboard exists because garbage data makes every downstream decision wrong.
6. **Instrument everything.** Superset usage is itself observable — query performance, dashboard load times, cache hit rates.

---

## Architecture

```
IndicAgent Pipeline (no changes)
  │
  ▼ writes
TimescaleDB (existing)
  │
  │ continuous aggregates (auto-refresh)
  ▼
analytics_* tables (pre-computed, read-only)
  │
  │ SELECT only (superset_readonly user)
  ▼
Apache Superset (Docker :8088)
  ├── Edge Audit dashboard (quant desk, daily refresh)
  └── Pipeline Health dashboard (risk desk, hourly refresh)
```

**Boundaries:**
- **One-way data flow.** Pipeline → TimescaleDB → caggs → Superset. Never backwards.
- **Read-only user.** `superset_readonly` has SELECT on `analytics_*` and source tables only.
- **Zero ETL.** No data movement, no intermediate service, no dbt.
- **Three tools, three purposes.** Grafana = ops, Next.js = real-time, Superset = analytics. No overlap.

---

## Continuous Aggregates

### Risk Desk (hourly refresh)

| Aggregate | Source | Metrics |
|-----------|--------|---------|
| `analytics_signal_calibration` | `signal_ledger` | win_rate, avg_pnl_r, N, 95% CI by (setup_plugin, regime, tf, hour_et), 1h buckets |
| `analytics_data_quality` | `intelligence_features` | null_rate per key feature, row_count, coverage_pct by (symbol, tf), 1h buckets |

### Quant Desk (daily refresh)

| Aggregate | Source | Metrics |
|-----------|--------|---------|
| `analytics_setup_performance` | `signal_ledger` + `setup_performance` | win_rate, sharpe, avg_pnl_r, mae, mfe, N, CI by (setup_plugin, regime, tf), 1d buckets |
| `analytics_outcome_distribution` | `signal_ledger` | outcome class counts, suppression_rate, activation_rate, 1d buckets |

**Minimum N gate:** Rows with `N < 30` include `is_significant = false`. Superset charts grey out or badge these rows. Derived from the existing FEED-02 gate in `setup_performance`.

---

## Dashboard 1: Edge Audit (Quant Desk)

**Decision question:** "Do we have edge, where is it, and is it real?"

| Chart | Type | Segmentation | Decision it drives |
|-------|------|-------------|-------------------|
| Win rate by setup | horizontal bar | setup_plugin, N≥30 gate, CI whiskers | Kill or demote setups with no statistical edge |
| Rolling 30d Sharpe by setup | multi-line | setup_plugin, 30d rolling window | Adjust perf_multiplier when edge decays |
| MAE/MFE scatter | scatter | mae vs mfe, colored by outcome class | Validate stop/target placement — are stops too tight? |
| PnL attribution waterfall | waterfall | setup_plugin, ranked by total pnl_r | Focus compute resources on top contributors |

**Freshness:** Daily. Signal outcomes need time to settle (lifecycle tracking).

---

## Dashboard 2: Pipeline Health (Risk Desk)

**Decision question:** "Is the data clean and are we calibrated?"

| Chart | Type | Segmentation | Decision it drives |
|-------|------|-------------|-------------------|
| Calibration curve | line | predicted confidence (binned) vs actual win_rate, with diagonal reference | Trigger isotonic recalibration when curve diverges |
| Feature null rate over time | multi-line | per key feature, daily | Investigate spikes — broken plugin or data gap? |
| Signal lifecycle funnel | funnel | generated → eligible → active → target_hit | Tune suppression/activation thresholds |
| Outcome class balance | stacked bar | outcome distribution, weekly buckets | Flag class imbalance for ML retraining |

**Freshness:** Hourly. Data quality issues compound — catch them fast.

---

## Infrastructure

### Docker Compose Addition

```yaml
superset:
  image: apache/superset:latest
  container_name: indicagent-superset
  ports:
    - "8088:8088"
  environment:
    SUPERSET_SECRET_KEY: ${SUPERSET_SECRET_KEY}
  volumes:
    - superset_data:/app/superset_home
  restart: unless-stopped
```

**Resource budget:** ~2GB RAM. Server has 16GB available (28GB total, ~11GB used). No contention.

### Database User

```sql
CREATE USER superset_readonly WITH PASSWORD '<generated>';
GRANT CONNECT ON DATABASE indicagent TO superset_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO superset_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT TO superset_readonly;
```

Read-only. No write, no DDL, no access to other schemas.

### Dashboard Version Control

Superset dashboards export as JSON. Store in `docs/superset/dashboards/` for git tracking. Re-import after upgrades or on fresh setup.

---

## What's NOT In Scope (Future Phases)

These are deferred — not forgotten, but not MVP:

- **Regime Analysis dashboard** — useful but secondary to proving edge exists first
- **CIS Deep Dive dashboard** — depends on having validated edge to decompose
- **LLM model comparison dashboard** — depends on Phase 66+ (Swarm agents)
- **Row-level security / multi-user** — single user for now
- **Custom Superset viz plugins** — native chart types cover MVP needs
- **Automated alerting from Superset** — Grafana handles operational alerts

---

## Cost & Maintenance

| Item | Cost |
|------|------|
| Superset Docker container | ~2GB RAM, ~1GB disk |
| Continuous aggregates | TimescaleDB maintenance overhead: negligible (same engine, incremental refresh) |
| Query load on TimescaleDB | Minimal — all queries hit pre-computed caggs, not raw hypertables |
| Ongoing maintenance | Superset upgrades (quarterly), cagg schema changes when new setup_plugins added |
| Dashboard development | ~1 day for initial setup + 2 dashboards |

**Total incremental compute cost:** Near zero. Continuous aggregates use existing TimescaleDB capacity. Superset RAM is available.

---

## Success Criteria

1. Can answer "do we have edge?" within 30 seconds of opening Edge Audit
2. Can spot a broken plugin within 1 hour via Pipeline Health null rate chart
3. Can detect calibration drift before it compounds into a week of bad signals
4. Every performance claim on dashboards has N and CI visible
5. Zero impact on live pipeline performance (read-only, different user, pre-computed data)

---

## Related

- `docs/ideas/bi-analytics-layer.md` — original idea doc (superseded by this spec)
- `src/intelligence/` — intelligence plugins feeding the data
- `src/core/ml/registry.py` — MLflow integration (unused, 1.9GB RAM reclaimable)
- `production/docker-compose.yml` — Docker stack where Superset will be added
