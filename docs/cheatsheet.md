# IndicAgent Command Cheatsheet

## Development Setup
```bash
source .venv/bin/activate
pip install -r requirements.txt

# PostgreSQL/TimescaleDB — native: sudo systemctl start postgresql
# Ollama — native: ollama serve
# Redpanda — Docker only:
cd production && docker compose up -d redpanda

# Database schema
psql -U postgres -d indicagent -f production/schemas/create_schema.sql
for f in production/migrations/0*.sql; do psql -U postgres -d indicagent -f "$f"; done
```

## System Operations
```bash
# All services are systemd-managed (Restart=always, start on boot)
# Authoritative unit files: production/systemd/
sudo systemctl status 'indicagent-*'
sudo systemctl restart indicagent-data-provider
sudo systemctl restart indicagent-feature-pipeline
sudo systemctl restart indicagent-signal-generator
sudo systemctl restart indicagent-signal-lifecycle
sudo systemctl restart indicagent-ai-narrative
sudo systemctl restart indicagent-feature-writer
sudo systemctl restart indicagent-llm-writer
sudo systemctl restart indicagent-cross-asset
sudo systemctl restart indicagent-api

journalctl -u indicagent-data-provider -f    # live logs for any service (print() only; structured logs in logs/<service>.log)

# Start all services (e.g. after reboot — start docker first: docker start timescaledb redpanda)
sudo systemctl start indicagent-data-provider indicagent-feature-pipeline \
  indicagent-signal-generator indicagent-signal-lifecycle indicagent-ai-narrative \
  indicagent-feature-writer indicagent-llm-writer indicagent-cross-asset indicagent-api

# Health / metrics
curl http://localhost:9112/metrics   # Signal Generator
curl http://localhost:9113/metrics   # AI Narrative
curl http://localhost:9115/metrics   # Signal Lifecycle
curl http://localhost:9116/metrics   # Feature Writer
curl http://localhost:9117/metrics   # LLM Writer
curl http://localhost:9118/metrics   # Cross-Asset
curl http://localhost:9125/metrics   # Feature Pipeline

# Grafana & Prometheus (optional — dashboards and alerts)
cd production && docker compose up -d prometheus grafana
# Grafana: http://localhost:3001  (admin / admin). Prometheus data source is preconfigured.
# Prometheus UI: http://localhost:9090  (query and targets)
# Note: 3001 avoids conflict with IndicAgent dashboard (Next.js on 3000)

# Direct invocation (debugging only)
.venv/bin/python services/data_provider_agent.py
.venv/bin/python services/feature_pipeline_service.py
.venv/bin/python services/signal_generator_service.py
.venv/bin/python services/feature_writer_service.py
.venv/bin/python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

## Pipeline Reset (full housekeeping + fetch + replay)
# pipeline_reset.py is the single entry point — handles everything in order:
#   1. Truncates signal_ledger, intelligence_features (+ market_data_ohlcv unless --keep-ohlcv)
#   2. Clears Redpanda topics (indicators, intelligence, signals, narratives)
#   3. Fetches OHLCV from IBKR per-TF: 1m=14d named, 5m=90d, 15m=180d, 1h=365d, 1d=2555d (7yr) continuous
#   4. Replays I1→I7 pipeline through all stored bars → signal_ledger + intelligence_features
#   5. Verifies row counts and signal distribution
# Script pauses at stop/start boundaries and prints the sudo commands for you to run.
```bash
# Step 1 — preview (no changes made)
.venv/bin/python production/scripts/pipeline_reset.py --dry-run

# Step 2 — full reset (requires TWS connected at 10.0.0.33:7497; expect 30–60 min)
.venv/bin/python production/scripts/pipeline_reset.py
# → when prompted to STOP, run:
sudo systemctl stop indicagent-feature-pipeline indicagent-signal-generator indicagent-signal-lifecycle \
  indicagent-feature-writer indicagent-ai-narrative
# → press Enter, let fetch + replay complete
# → when prompted to START, run:
sudo systemctl start indicagent-feature-pipeline indicagent-feature-writer \
  indicagent-signal-generator indicagent-signal-lifecycle indicagent-ai-narrative

# Fast reset — skip IBKR fetch, re-replay from existing market_data_ohlcv
# (use after plugin/signal logic changes, no IBKR connection needed)
.venv/bin/python production/scripts/pipeline_reset.py --keep-ohlcv

# Limit to specific symbols
.venv/bin/python production/scripts/pipeline_reset.py --keep-ohlcv --symbols ESH6,NQH6

# Also wipe LLM audit log (llm_calls, llm_model_scores)
.venv/bin/python production/scripts/pipeline_reset.py --clear-llm
```

## Development & Testing
```bash
.venv/bin/pytest tests/unit/ -v        # Unit tests
.venv/bin/pytest tests/integration/ -v # Integration (requires live Redpanda + PostgreSQL)
.venv/bin/ruff check . --fix           # Linting
.venv/bin/black .                      # Formatting
.venv/bin/mypy src/ --ignore-missing-imports
cd dashboard && npm run dev            # Frontend dev server
```

## Environment Variables
```bash
INDICAGENT_ENV="development"
DATABASE_URL="postgresql://postgres:postgres@localhost:5432/indicagent"
KAFKA_BOOTSTRAP_SERVERS="localhost:19092"
IBKR_HOST="10.0.0.33"
IBKR_PORT=7497
OLLAMA_BASE_URL="http://localhost:11434"
OLLAMA_DEFAULT_MODEL="qwen3.5:9b"
```
