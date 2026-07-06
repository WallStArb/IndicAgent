# BI Analytics Layer — Apache Superset

**Version:** 1.0
**Status:** adopted
**Priority:** medium
**Milestone:** future (post-v2.8)
**Last Updated:** 2026-05-05
**Tags:** bi, analytics, superset, timescaledb, dashboards, signal-outcomes, data-quality

**Implementation snapshot (2026-05-05):**
- Superset is planned but not present in `production/docker-compose.yml`.
- No `superset_readonly` database role exists in migrations yet.
- No `analytics_*` continuous aggregates exist in migrations yet.
- No exported Superset dashboards exist under `docs/superset/` yet.

---

## Problem

IndicAgent has two implemented visualization layers and one missing layer.

| Layer | Tool | Purpose |
|-------|------|---------|
| Operational | Grafana | Pipeline health, latency, Prometheus metrics |
| Real-time intelligence | Next.js dashboard | Live signals, SSE panels, AI narratives |
| Analytical | Apache Superset *(planned)* | Signal outcomes, edge validation, calibration, data quality |

Months of labeled signal outcomes sit in TimescaleDB. Without a BI layer, every analytical question requires writing raw SQL or building one-off dashboard UI. That's a bottleneck for strategy development and a risk for undetected data quality issues.

---

## Design Principles (Renaissance)

1. **Every chart answers a decision.** If a chart changes and you can't name the action you'd take, it's noise. Remove it.
2. **Earn the right through proof.** Every performance claim backed by N, confidence intervals, minimum sample thresholds. No conclusions from noise (N < 30).
3. **Let the system run.** Continuous aggregates auto-refresh on schedule. No cron, no microservice, no manual intervention.
4. **Separation of concerns.** Superset is pure presentation. All compute happens in TimescaleDB continuous aggregates. Superset never writes, never triggers computation, never touches the live pipeline.
5. **Data quality over model complexity.** The Calibration & Data Quality dashboard exists because garbage data makes every downstream decision wrong.
6. **Instrument everything.** Superset usage is itself observable — query performance, dashboard load times, cache hit rates.
7. **Use Superset for exploration, not operations.** Grafana remains the on-call surface. The Next.js dashboard remains the live trading surface. Superset is for historical analysis, cohort slicing, and research review.
8. **UX should reduce false certainty.** Low-N results, wide confidence intervals, missing data, stale refreshes, and uncalibrated predictions must be visible in the layout, not hidden in tooltips.

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
  ├── Calibration & Data Quality dashboard (risk desk, hourly refresh)
  └── Research Lab datasets (ad-hoc Explore + SQL Lab)
```

**Boundaries:**
- **One-way data flow.** Pipeline → TimescaleDB → caggs → Superset. Never backwards.
- **Read-only user.** `superset_readonly` has SELECT on `analytics_*` and source tables only.
- **Zero ETL.** No data movement, no intermediate service, no dbt.
- **Three tools, three purposes.** Grafana = ops, Next.js = real-time, Superset = analytics. No overlap.
- **Semantic layer in Superset.** Curated datasets expose business names, verified metrics, default filters, and certified charts so analysis does not depend on every user knowing raw table semantics.

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

### Dataset Contract

Superset should connect to curated `analytics_*` datasets first. Raw tables remain available to maintainers in SQL Lab, but default dashboards should not query hypertables directly.

| Dataset | Grain | Required UX fields |
|---------|-------|--------------------|
| `analytics_setup_performance` | setup_plugin × regime × tf × day | `n`, `is_significant`, `win_rate_ci_low`, `win_rate_ci_high`, `avg_pnl_r`, `sharpe`, `last_updated_at` |
| `analytics_signal_calibration` | confidence_bin × setup_plugin × regime × tf × hour | `predicted_confidence`, `actual_win_rate`, `ece`, `n`, `is_significant`, `last_updated_at` |
| `analytics_data_quality` | feature × symbol × tf × hour | `null_rate`, `coverage_pct`, `row_count`, `expected_row_count`, `last_updated_at` |
| `analytics_outcome_distribution` | setup_plugin × outcome × week | `outcome_count`, `suppression_rate`, `activation_rate`, `n`, `last_updated_at` |

Every dataset should include `last_updated_at` so dashboard users can distinguish "nothing changed" from "refresh broke."

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

## Dashboard 2: Calibration & Data Quality (Risk Desk)

**Decision question:** "Is the data clean and are we calibrated?"

| Chart | Type | Segmentation | Decision it drives |
|-------|------|-------------|-------------------|
| Calibration curve | line | predicted confidence (binned) vs actual win_rate, with diagonal reference | Trigger isotonic recalibration when curve diverges |
| Feature null rate over time | multi-line | per key feature, daily | Investigate spikes — broken plugin or data gap? |
| Signal lifecycle funnel | funnel | generated → eligible → active → target_hit | Tune suppression/activation thresholds |
| Outcome class balance | stacked bar | outcome distribution, weekly buckets | Flag class imbalance for ML retraining |

**Freshness:** Hourly. Data quality issues compound — catch them fast.

---

## Superset UX Model

Superset should feel like a research cockpit, not a generic BI dump. The default experience should help answer one question at a time and make uncertainty hard to ignore.

### Navigation

| Entry point | Audience | Default time range | Primary question |
|-------------|----------|--------------------|------------------|
| Edge Audit | Quant / strategy review | Last 90 days | Which setups have statistically credible edge? |
| Calibration & Data Quality | Risk / model governance | Last 14 days | Are confidence scores and source data trustworthy? |
| Research Lab | Maintainers / research | User-selected | What changed, and what should we investigate next? |

### Global Filters

Every certified dashboard should share the same top filter bar:

- Time range
- Symbol / asset class
- Timeframe
- Setup plugin
- Market regime
- Outcome class
- Significant only (`N >= 30`) defaulted on
- Live/shadow/retired setup status when available

This keeps visual comparison consistent across dashboards and prevents users from mentally reconciling different slices.

### Layout Pattern

Each dashboard should follow the same visual rhythm:

1. **KPI strip:** sample size, significant setup count, average pnl_r, calibration error, latest refresh timestamp.
2. **Decision panel:** the one or two charts that answer the dashboard's primary question.
3. **Diagnostic panel:** supporting charts that explain why the primary result moved.
4. **Detail table:** sortable rows with setup, regime, tf, N, CI, last_updated_at, and notes/deep links.

Avoid decorative cards. Use dense tables, compact charts, and fixed filter positions. This is an analytical workbench.

### Visual Semantics

- Low-N rows are muted by default and never rank above significant rows.
- Confidence intervals are shown anywhere win rate, Sharpe, or pnl_r is compared.
- Red/green encodes outcome quality, not bullish/bearish direction.
- Stale datasets show an obvious freshness badge in the KPI strip.
- Charts should prefer setup/regime/timeframe grouping over free-form color palettes so repeated review builds visual memory.
- Tables should expose exact numbers; charts should expose shape and ranking.

### Drill Paths

Superset should not replace the Next.js signal UI. It should point back to it when analysis reaches a specific signal or setup.

Useful links:
- Setup-level row → filtered Edge Audit dashboard for that setup.
- Signal cohort row → `/signals?setup_plugin=...&symbol=...&tf=...`
- Data quality anomaly → source feature, symbol, timeframe, and first affected timestamp.
- Calibration issue → confidence bin, setup plugin, regime, and retraining/recalibration note.

Deep links can be added once the Next.js routes expose stable query parameters for setup, symbol, timeframe, and date range.

### Certified Charts

Only reviewed charts should be promoted into default dashboards. Ad-hoc SQL Lab charts stay in personal workspaces until they meet these rules:

- Metric definition is documented in the dataset description.
- N and freshness are visible.
- Source table or aggregate is named.
- The chart answers a named decision question.
- The chart has an owner responsible for removing it if it becomes noise.

---

## Infrastructure

### Docker Compose Addition

```yaml
superset:
  image: apache/superset:<pinned-version>
  container_name: indicagent-superset
  ports:
    - "8088:8088"
  environment:
    SUPERSET_SECRET_KEY: ${SUPERSET_SECRET_KEY}
    SQLALCHEMY_DATABASE_URI: postgresql+psycopg2://superset_app:${SUPERSET_APP_PASSWORD}@timescaledb:5432/superset
  volumes:
    - superset_data:/app/superset_home
  depends_on:
    - timescaledb
  restart: unless-stopped
```

**Resource budget:** ~2GB RAM, ~1GB disk plus metadata DB growth. Server had enough headroom when this design was written, but re-check memory before enabling alongside Langfuse, MLflow, Grafana, Tempo, Loki, Ollama, and Redpanda.

Use a pinned image tag, not `latest`, so dashboard exports and plugin behavior are reproducible.

### Superset Metadata DB

Use a separate `superset` database in the existing TimescaleDB/PostgreSQL container for Superset metadata. Do not store Superset metadata in the `indicagent` application database.

```sql
CREATE DATABASE superset;
CREATE USER superset_app WITH PASSWORD '<generated>';
GRANT ALL PRIVILEGES ON DATABASE superset TO superset_app;
```

The `superset_app` role owns Superset metadata only. It is not the data access role used for analytics queries.

### Database User

```sql
CREATE USER superset_readonly WITH PASSWORD '<generated>';
GRANT CONNECT ON DATABASE indicagent TO superset_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO superset_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT TO superset_readonly;
```

Read-only. No write, no DDL, no access to other schemas. Prefer granting `SELECT` on `analytics_*` first, then add raw source-table access only where a dashboard or SQL Lab workflow truly needs it.

### Bootstrap Steps

1. Add `superset` metadata database and `superset_app` role migration or setup script.
2. Add `superset_readonly` role with least-privilege `SELECT`.
3. Add `analytics_*` continuous aggregate migrations.
4. Add pinned Superset service and `superset_data` volume to Docker Compose.
5. Initialize Superset, create the admin user, connect TimescaleDB with `superset_readonly`.
6. Create certified datasets before creating dashboards.
7. Export dashboard JSON to `docs/superset/dashboards/`.

### Implementation Phases

| Phase | Deliverable | Exit criteria |
|-------|-------------|---------------|
| 1. Foundation | Compose service, metadata DB, readonly role | Superset boots on `:8088` and connects to TimescaleDB read-only |
| 2. Analytics schema | `analytics_*` continuous aggregates | Queries return bounded, pre-computed data with `last_updated_at` |
| 3. Dataset certification | Superset datasets + metric descriptions | Edge and calibration metrics are reusable without raw SQL |
| 4. MVP dashboards | Edge Audit + Calibration & Data Quality | Success criteria 1-5 pass with real data |
| 5. Research workflow | Exported dashboards + docs/superset runbook | Fresh setup can restore dashboards from git-tracked exports |

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
- **Embedding Superset inside the Next.js dashboard** — defer until auth, routing, and iframe/security boundaries are explicit.

---

## Cost & Maintenance

| Item | Cost |
|------|------|
| Superset Docker container | ~2GB RAM, ~1GB disk |
| Continuous aggregates | TimescaleDB maintenance overhead: negligible (same engine, incremental refresh) |
| Query load on TimescaleDB | Minimal — all queries hit pre-computed caggs, not raw hypertables |
| Ongoing maintenance | Superset upgrades (quarterly), cagg schema changes when new setup_plugins added |
| Dashboard development | ~1 day for initial setup + 2 dashboards, plus iteration after real analyst use |

**Total incremental compute cost:** Near zero. Continuous aggregates use existing TimescaleDB capacity. Superset RAM is available.

---

## Success Criteria

1. Can answer "do we have edge?" within 30 seconds of opening Edge Audit
2. Can spot a broken plugin within 1 hour via Calibration & Data Quality null rate chart
3. Can detect calibration drift before it compounds into a week of bad signals
4. Every performance claim on dashboards has N and CI visible
5. Zero impact on live pipeline performance (read-only, different user, pre-computed data)
6. Dashboard freshness is visible without opening SQL Lab
7. A reviewed chart can be traced back to its dataset, aggregate, and metric definition

---

## Related

- `src/intelligence/` — intelligence plugins feeding the data
- `src/core/ml/registry.py` — MLflow integration (unused, 1.9GB RAM reclaimable)
- `production/docker-compose.yml` — Docker stack where Superset will be added
