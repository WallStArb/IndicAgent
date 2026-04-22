# BI Analytics Layer

**Status:** idea — not yet planned
**Priority:** medium
**Created:** 2026-04-22

---

## The Gap

IndicAgent has three visualization layers today:

| Layer | Tool | Purpose |
|-------|------|---------|
| Operational | Grafana | Pipeline health, latency, service metrics, Prometheus |
| Real-time intelligence | Next.js dashboard | Live signals, SSE panels, price display, AI narratives |
| Analytical | *(missing)* | Signal outcomes, setup performance, regime analysis, ML training data quality |

The analytical layer is the gap. As the signal ledger and intelligence features accumulate months of labeled outcomes, the inability to slice, filter, and visualize that data without writing raw SQL is a real bottleneck for strategy development and performance review.

---

## What We Want

A Tableau-like analytical environment that connects directly to TimescaleDB and lets us answer questions like:

- Which setups have the highest win rate in trending regimes vs ranging?
- How does MAE/MFE distribution vary by timeframe and time-of-day?
- Which CIS bucket combinations correlate most with profitable outcomes?
- Where are the feature drift hot spots over the last 30 days?
- How does signal frequency change across instruments after a volatility regime shift?
- What does the labeled training dataset look like — class balance, feature coverage, outcome distribution?

These are exploratory, iterative questions. They need drag-and-drop filtering, time-range selectors, grouping, and chart types — not a hardcoded Next.js panel.

---

## Recommended Tool: Apache Superset

**Apache Superset** is the closest open source equivalent to Tableau. Self-hosted, free, and speaks Postgres/TimescaleDB natively.

### Why Superset over alternatives

| | Superset | Metabase | Grafana | Redash |
|--|---------|----------|---------|--------|
| Tableau-like drag-and-drop | ✅ | partial | ❌ | ❌ |
| SQL Lab (ad-hoc SQL) | ✅ | ✅ | partial | ✅ |
| Chart variety | excellent | good | time-series focused | basic |
| Self-hosted | ✅ | ✅ | ✅ | ✅ |
| TimescaleDB native | ✅ | ✅ | ✅ | ✅ |
| Setup complexity | medium | low | already running | low |
| Cost | free | free (Community) | free | free |

Superset's **Explore** view (the Tableau equivalent) lets you pick a table, drag dimensions and measures, set filters, choose chart type, and save to a dashboard — all without SQL. **SQL Lab** gives engineers full ad-hoc query access with results visualized inline.

---

## Key Datasets to Expose

All are already in TimescaleDB — no ETL required, just a read-only Superset connection.

| Dataset | Key Questions |
|---------|--------------|
| `signal_ledger` | Win rate by setup / regime / TF / hour; MAE/MFE distributions; outcome class balance; signal frequency over time |
| `signal_metrics` | Sharpe evolution per setup; regime-conditioned performance; setup ranking history |
| `intelligence_features` | Feature distributions over time; entropy/Hurst trends; GARCH volatility regimes; CIS bucket scores |
| `llm_calls` + `llm_model_scores` | Model win rates; narrative-to-outcome correlation; provider fallback rates |
| `market_data_ohlcv` | Price context for signal analysis; session volume profiles |
| `contract_metadata` | Instrument roll history, front-month timeline |

---

## Architecture

```
TimescaleDB (read-only replica or same instance, read-only user)
    └─► Apache Superset (Docker, :8088)
          ├─► Explore (drag-and-drop Tableau-like charts)
          ├─► SQL Lab (ad-hoc queries)
          └─► Dashboards (saved views, shareable)
```

- **Separate read-only DB user** — Superset never writes, no risk to live pipeline
- **Docker Compose addition** — single service alongside timescaledb + redpanda
- **No ETL, no data movement** — direct TimescaleDB connection, queries run on-demand
- **TimescaleDB time-bucket functions** available in SQL Lab (e.g. `time_bucket('1h', ts)`)

---

## Dashboard Ideas

### Signal Performance Board
- Win rate heatmap: setup × regime (grid)
- MAE/MFE scatter by outcome class
- Signal count time series by symbol
- Outcome class distribution (bar chart)

### Regime Analysis Board
- HMM state distribution over time
- GARCH sigma percentile bands
- Hurst exponent distribution by instrument
- Regime duration histogram

### ML Training Data Quality Board
- Feature coverage per bar (null rate by feature)
- Class imbalance over time (outcome distribution)
- CIS bucket score distributions
- intelligence_features row count vs signal_ledger resolved count

### CIS Deep Dive Board
- Bucket weight contribution per signal (scatter)
- CIS score vs outcome correlation
- Bucket agreement rate by regime
- Signal suppression rate (regime_suppressed vs published)

---

## Implementation Notes

- Use TimescaleDB continuous aggregates where possible for pre-aggregated data — avoids full hypertable scans on large date ranges
- `signal_ledger` has 6GB+ — apply default time filters on all dashboards to avoid unbounded queries
- Superset supports row-level security if multi-user access is needed later
- Dashboard export/import via JSON — can be version controlled in `docs/superset/`

---

## Related

- [ML Agent Architecture](ml-agent-architecture.md) — training data the BI layer will visualize
- [Intelligence Swarm Manifest](intelligence-swarm-manifest.md) — swarm outputs as future datasets
- **Code:** `src/intelligence/`, `services/signal_metrics_compute_agent.py`
- **Data:** `signal_ledger`, `intelligence_features`, `signal_metrics` in TimescaleDB
