# Quick Start

Get IndicAgent running from a fresh clone.

---

## Prerequisites

- Python 3.11+
- Docker + Docker Compose
- Node.js 18+ (dashboard only)
- IBKR TWS running and accepting API connections

---

## 1. Clone and install

```bash
git clone https://github.com/yourusername/indicagent.git
cd indicagent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Configure environment

Copy and edit the env file:

```bash
cp .env.example .env
```

Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `INDICAGENT_ENV` | `development` | `development` or `production` |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/indicagent` | TimescaleDB |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:19092` | Redpanda |
| `IBKR_HOST` | `10.0.0.33` | TWS host |
| `IBKR_PORT` | `7497` | TWS port (7497=paper, 7496=live) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama LLM endpoint |

## 3. Start infrastructure

```bash
cd production
docker compose up -d
cd ..
```

Starts TimescaleDB (:5432), Redpanda (:9092/:19092), and Ollama (:11434).

## 4. Apply database migrations

```bash
bash production/scripts/db_setup.sh
```

Applies all migrations in `production/migrations/` in order.

## 5. Seed historical data

Fetch OHLCV bars from IBKR and replay through the intelligence pipeline:

```bash
.venv/bin/python production/scripts/pipeline_reset.py
```

This stops services, fetches all TF depths (1m=14d, 5m=90d, 15m=180d, 1h=365d, 1d=7yr), replays through I1→I7, then starts services. Takes 20–60 min depending on symbol count.

For a quick test with fewer days:

```bash
.venv/bin/python production/scripts/historical_backfill.py --days 7
```

## 6. Start services

Services are systemd-managed in production. For local dev, start them directly:

```bash
# In separate terminals (or use a process manager):
.venv/bin/python services/indicator_service.py
.venv/bin/python services/market_analysis_service.py
.venv/bin/python services/signal_generator_service.py
.venv/bin/python services/signal_lifecycle_service.py
.venv/bin/python services/ai_narrative_service.py
.venv/bin/python services/feature_writer_service.py
.venv/bin/python services/llm_writer_service.py
uvicorn src.api.main:app --port 8000
```

Signal generator needs ~50 min of live 1m bars before signals fire (warmup).

## 7. Start the dashboard

```bash
cd dashboard && npm install
npm run dev -- --port 3000 --hostname 0.0.0.0
```

Open http://localhost:3000

---

## Next Steps

- **Architecture:** [architecture-overview.md](architecture-overview.md)
- **First Plugin:** [first-plugin.md](first-plugin.md)
- **Running services in production:** [../guides/running-services.md](../guides/running-services.md)
- **Gap-filling after downtime:** [../guides/database-management.md](../guides/database-management.md#gap-filling)
