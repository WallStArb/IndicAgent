# New Machine Setup

**Version:** 3.0.0
**Last Updated:** 2026-04-14
**Status:** Current — covers full v2.2 stack

Use this when rebuilding the server from scratch (reformat, new machine, DR).
Everything needed to go from bare OS to fully running pipeline lives in this repo.

---

## Prerequisites

- **Ubuntu 24.04+** (tested on 26.04)
- **Docker** with Compose plugin (`docker compose` — not `docker-compose`)
- **Python 3.14+** (`python3 --version`)
- **Node.js 20+** (`node --version`) — for the Next.js dashboard
- **psql** client — `sudo apt install postgresql-client`
- **git** — to clone the repo

---

## 1. Clone the repo

```bash
git clone git@github.com:WallStArb/IndicAgent.git /home/bg/dev/indicagent
cd /home/bg/dev/indicagent
```

---

## 2. Environment

```bash
cp .env.example .env
# Edit .env — set OPENROUTER_API_KEY and any non-default values.
# Defaults that match this setup (no changes needed for local dev):
#   DATABASE_URL=postgresql://postgres:postgres@localhost:5432/indicagent
#   KAFKA_BOOTSTRAP_SERVERS=localhost:19092
#   INDICAGENT_ENV=dev
```

---

## 3. Start infrastructure (Docker Compose)

The single `production/docker-compose.yml` starts the full infrastructure stack:
TimescaleDB, Redpanda, Ollama (ROCm GPU), Prometheus, Grafana, Tempo, MLflow, Langfuse.

```bash
cd production
docker compose up -d
cd ..
```

Verify all containers are up:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```

Expected: `timescaledb`, `redpanda`, `ollama`, `indicagent-prometheus`, `indicagent-grafana`,
`indicagent-tempo`, `indicagent-mlflow`, `indicagent-langfuse` — all `Up`.

**Langfuse needs its own database** (it uses TimescaleDB as its backend):

```bash
docker exec timescaledb psql -U postgres -c "CREATE DATABASE langfuse;"
```

---

## 4. Apply database migrations

65+ migrations in `production/migrations/` applied in order by the setup script:

```bash
bash scripts/infrastructure/setup/infrastructure_db_setup.sh
```

This applies all numbered migrations in order — `production/migrations/` (legacy, 001–103) then `db/migrations/` (canonical, Phase 104+). All migrations are idempotent.

Verify:

```bash
bash scripts/debug/validate/debug_db_verify.sh
```

---

## 5. Initialize Redpanda topics

Creates all Kafka topics with correct retention tiers (hot/buffer/HTF):

```bash
python3 production/scripts/init_kafka_topics.py
```

Topics are created with env prefix from `INDICAGENT_ENV` in `.env` (default: `dev`).

---

## 6. Pull Ollama model

```bash
docker exec ollama ollama pull gemma4:e4b
```

This is the offline LLM fallback for AI narratives (I8). Takes a few minutes on first pull.
Model is stored in the `ollama-data` Docker volume (survives container restarts).

---

## 7. Python virtual environment

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Verify:

```bash
.venv/bin/pytest tests/unit/ -q --ignore=tests/unit/providers/ 2>&1 | tail -3
```

Expected: ~2835 passed.

---

## 8. Dashboard (Next.js)

```bash
cd dashboard
npm install
cd ..
```

Start dev server: `cd dashboard && npm run dev` (port 3000).

---

## 9. Install systemd services

Copy service files from the repo reference dir and enable them:

```bash
sudo cp production/systemd/*.service /etc/systemd/system/
sudo cp production/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable indicagent-*.service indicagent-*.timer
```

Then start the full pipeline in dependency order:

```bash
sudo systemctl start \
  indicagent-ibkr-provider \
  indicagent-bar-aggregator \
  indicagent-bar-writer \
  indicagent-bar-auditor \
  indicagent-provider-merger \
  indicagent-roll-compute \
  indicagent-contract-metadata-writer \
  indicagent-intelligence-pipeline \
  indicagent-signal-writer \
  indicagent-signal-tracker-compute \
  indicagent-signal-metrics-compute \
  indicagent-signal-metrics-writer \
  indicagent-signal-auditor \
  indicagent-feature-writer \
  indicagent-feature-snapshot-writer \
  indicagent-lifecycle-writer \
  indicagent-llm-writer \
  indicagent-ai-narrative \
  indicagent-cross-asset \
  indicagent-parity-auditor \
  indicagent-service-auditor \
  indicagent-swarm-orchestrator \
  indicagent-swarm-writer \
  indicagent-api \
  indicagent-dashboard
```

Verify everything is running:

```bash
systemctl list-units --all | grep indicagent | grep -v "dead\|exited\|waiting"
```

---

## 10. IBKR TWS

TWS must be running on `192.168.1.157` with API enabled on port 7497.
The `indicagent-ibkr-provider` service connects at startup. Restart on futures expiry:

```bash
sudo systemctl restart indicagent-ibkr-provider
```

---

## What's in the repo

| Item | Location |
|------|----------|
| Full infrastructure stack | `production/docker-compose.yml` |
| Prometheus config | `production/prometheus.yml` |
| Grafana provisioning | `production/grafana/` |
| DB migrations (legacy 001–103) | `production/migrations/0*.sql` |
| DB migrations (Phase 104+) | `db/migrations/0*.sql` |
| Apply migrations | `production/scripts/db_setup.sh` |
| Verify schema | `production/scripts/db_verify.sh` |
| Init Redpanda topics | `production/scripts/init_kafka_topics.py` |
| Systemd service templates | `production/systemd/` |
| Env template | `.env.example` |

---

## Service endpoints (post-setup)

| Service | URL |
|---------|-----|
| API + SSE | `http://localhost:8000` |
| Dashboard | `http://localhost:3000` |
| Grafana | `http://localhost:3001` (admin / admin) |
| MLflow | `http://localhost:5000` |
| Langfuse | `http://localhost:3010` |
| Prometheus | `http://localhost:9090` |
| Redpanda Admin | `http://localhost:9644` |
| Ollama | `http://localhost:11434` |

---

## Troubleshooting

**Service crash-loops on startup:** Check journalctl — `journalctl -u indicagent-<name> -n 30`
or read the log file directly: `tail -50 logs/<service_name>.log`

**TimescaleDB not ready:** Both TimescaleDB and Redpanda readiness are now gated by `indicagent-infrastructure.target`. All app services `Requires=indicagent-infrastructure.target`, which is satisfied only when both `indicagent-timescaledb-ready.service` and `indicagent-redpanda-ready.service` exit cleanly. Services will not start until both backends accept connections. If startup hangs, check `systemctl status indicagent-timescaledb-ready indicagent-redpanda-ready indicagent-infrastructure.target`.

**Consumer lag:** `docker exec redpanda rpk group describe feature_pipeline -t`

**Consumer group stuck:** Delete and restart — `docker exec redpanda rpk group delete <group>`
then `sudo systemctl restart indicagent-<name>`

**Ollama GPU not detected:** Check ROCm device access — `docker exec ollama ollama list`
should show `gemma4:e4b`. If blank, repull: `docker exec ollama ollama pull gemma4:e4b`

**Full reference:** `docs/operations/operations-infrastructure.md` · `docs/cheatsheet.md`
