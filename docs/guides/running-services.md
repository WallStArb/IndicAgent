# Running Services

**Version:** 2.8
**Status:** current
**Last Updated:** 2026-05-27

All services are systemd-managed (`Restart=always`, start on boot). Authoritative unit files: `/etc/systemd/system/` (templates in `production/systemd/`).

---

## Quick Status

```bash
# All indicagent services at a glance
systemctl list-units --all | grep indicagent

# Single service
sudo systemctl status indicagent-intelligence-pipeline
sudo systemctl restart indicagent-intelligence-pipeline

# Live logs (journald shows print() only — structured logs in logs/<service>.log)
journalctl -u indicagent-intelligence-pipeline -f
tail -f logs/intelligence_pipeline_agent.log
```

---

## Service DAG (L1 → L10)

Canonical order from `_DAG_ORDER` in `services/service_auditor_agent.py`.

### Infrastructure (L0)

| Unit | Purpose |
|------|---------|
| `indicagent-redpanda-ready` | Readiness sentinel — blocks all consumers until Redpanda accepts connections |
| `indicagent-timescaledb-ready` | Readiness sentinel - blocks all app services until TimescaleDB accepts connections |
| `indicagent-infrastructure.target` | Unified gate - all app services Require this; satisfied when both DB and Kafka are ready |
| `indicagent-redpanda-watchdog` | Liveness check + auto-restart for the Redpanda container |
| `indicagent-ibkr-restart` | Oneshot timer: restarts ibkr-provider after TWS nightly restart |

### L1 — Data Ingestion

| Unit | Purpose |
|------|---------|
| `indicagent-ibkr-provider` | IBKR TWS → `market.bars` (live 1m + HTF) |
| `indicagent-bar-replay` | Historical OHLCV one-shot replay → Kafka |

### L2 — Stream Merge

| Unit | Purpose |
|------|---------|
| `indicagent-provider-merger` | Routes `market.bars.raw.*` → canonical `market.bars` |

### L3 — Bar Processing

| Unit | Purpose |
|------|---------|
| `indicagent-bar-aggregator` | 1m → HTF (5m–1d) aggregation |
| `indicagent-bar-auditor` | Gap detection; emits `BarGapRequest` for self-healing |

### L4 — Persistence

| Unit | Purpose |
|------|---------|
| `indicagent-bar-writer` | Writes `market_data_ohlcv` (batch) |

### L5 — Intelligence Pipeline (I1–I7)

| Unit | Purpose |
|------|---------|
| `indicagent-cross-asset` | ES/NQ/RTY/YM spread z-scores and correlation |
| `indicagent-macro-compute` | Yield curve and flight-to-quality factors |
| `indicagent-intelligence-pipeline` | Unified I1–I7 in-process compute; publishes `intelligence.journal` |

### L6 — Persistence Writers (parallel)

| Unit | Purpose |
|------|---------|
| `indicagent-feature-writer` | Writes `intelligence_features` (batch) |
| `indicagent-signal-writer` | Writes `signal_ledger` (batch) |
| `indicagent-signal-tracker-compute` | Signal lifecycle — activation, MAE/MFE, outcome (DB-ignorant) |
| `indicagent-lifecycle-writer` | Persists lifecycle transitions |
| `indicagent-lineage-writer` | Persists signal lineage events to `signal_lineage` |
| `indicagent-ctx-writer` | Persists qualitative context events and snapshots |

### L7 — AI/LLM Layer

| Unit | Purpose |
|------|---------|
| `indicagent-alpha-swarm` | LLM alpha multiplier agents (Skeptic, Correlation, RegimeCoherence, Counterfactual) |
| `indicagent-narrative-compute` | Per-signal market narrative via Ollama |
| `indicagent-llm-writer` | Writes `llm_calls` + outcome back-fill |
| `indicagent-swarm-ledger-writer` | Swarm aggregate adjustments → `signal_ai_enrichment` |

### L8 — Analytics (timer-triggered + daemons)

| Unit | Purpose | Schedule |
|------|---------|----------|
| `indicagent-signal-metrics-compute` | Signal performance metrics | Timer |
| `indicagent-signal-metrics-writer` | Persists metrics to DB | Timer |
| `indicagent-graduation-compute` | Transform graduation evaluation | Event-driven |
| `indicagent-graduation-writer` | Persists graduation rows | Event-driven |
| `indicagent-weight-updater` | CIS weight refresh | Nightly 02:00 |
| `indicagent-shadow-auditor` | Shadow governance: promote/demote plugins | Timer |
| `indicagent-roll-batch` | Futures roll promotion — detects calendar rolls, updates `contract_metadata` | Nightly 20:00 |
| `indicagent-feature-validation` | Daily IC/p-value feature decisions | Timer |
| `indicagent-ml-training` | LightGBM training | Nightly 03:00 |
| `indicagent-ml-signal-training-materialize` | ML training data JOIN materialization | Nightly 02:00 |
| `indicagent-ml-orchestrator` | ML pipeline orchestration | Weekly Mon |
| `indicagent-ml-data-quality` | ML data quality audit | Weekly Mon |
| `indicagent-ml-discovery` | ML feature discovery | Weekly Mon |
| `indicagent-hmm-training` | HMM Baum-Welch retraining | Monthly |

> **Note:** `inactive (dead)` between timer runs is correct for all oneshot services — do not treat as failures.

### L9 — Audit, Parity, Alerting

| Unit | Purpose |
|------|---------|
| `indicagent-signal-auditor` | Coverage validation + Kafka lag monitoring |
| `indicagent-signal-replay` | Periodic outcome recovery for unresolved signals |
| `indicagent-alerting-agent` | Centralized Kafka → Telegram/Discord alerts |
| `indicagent-dlq-drain` | Drains all DLQ topics → `dlq_events` |

### L10 — Top-Level Services

| Unit | Purpose | Port |
|------|---------|------|
| `indicagent-api` | FastAPI REST + SSE | 8000 |
| `indicagent-dashboard` | Next.js frontend | 3000 |

### L10 — Meta Monitor

| Unit | Purpose |
|------|---------|
| `indicagent-service-auditor` | Monitors + restarts all of the above; metrics on :9131 |

---

## Observability

Metrics are exported via OTel OTLP to Prometheus, visualised in Grafana.

```bash
# Start observability stack (Prometheus + Grafana + Tempo)
cd production && docker compose up -d prometheus grafana tempo

# Grafana: http://localhost:3001  (admin / admin)
# Prometheus scrape targets: http://localhost:9090/targets
# Service Auditor metrics: curl http://localhost:9131/metrics
# Alerting Agent metrics: curl http://localhost:9132/metrics
# API health: curl http://localhost:8000/health/system
```

Consumer lag check:
```bash
docker exec redpanda rpk group describe feature_pipeline -t
```

---

## Direct Invocation (debugging only)

```bash
.venv/bin/python services/ibkr_provider_agent.py
.venv/bin/python services/intelligence_pipeline_agent.py
.venv/bin/python services/signal_writer_agent.py
.venv/bin/python services/feature_writer_agent.py
.venv/bin/python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000
cd dashboard && npm run dev
```

---

**See also:** [Cheatsheet](../cheatsheet.md) · [Current Architecture](../architecture/current-state.md) · [Operations Reference](../operations/infrastructure-reference.md)
