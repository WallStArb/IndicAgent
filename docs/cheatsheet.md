# IndicAgent Command Cheatsheet

## Development Setup
```bash
source .venv/bin/activate
pip install -r requirements.txt

# PostgreSQL/TimescaleDB — native: sudo systemctl start postgresql
# Ollama — native: ollama serve
# DragonflyDB — Docker only:
cd production && docker compose up -d dragonfly

# Database schema
psql -U postgres -d indicagent -f production/schemas/create_schema.sql
for f in production/migrations/0*.sql; do psql -U postgres -d indicagent -f "$f"; done
```

## System Operations
```bash
# All 8 services are systemd-managed (Restart=always, start on boot)
sudo systemctl status 'indicagent-*'
sudo systemctl restart indicagent-tws
sudo systemctl restart indicagent-indicator
sudo systemctl restart indicagent-market-analysis
sudo systemctl restart indicagent-signal-generator
sudo systemctl restart indicagent-signal-tracker
sudo systemctl restart indicagent-ai-narrative
sudo systemctl restart indicagent-feature-writer
sudo systemctl restart indicagent-api

journalctl -u indicagent-tws -f              # live logs for any service

# Start all services (e.g. after reboot)
sudo systemctl start indicagent-tws indicagent-indicator indicagent-market-analysis \
  indicagent-signal-generator indicagent-signal-tracker indicagent-ai-narrative \
  indicagent-feature-writer indicagent-api

# Health / metrics
curl http://localhost:9109/metrics   # Indicator Service
curl http://localhost:9112/metrics   # Signal Generator
curl http://localhost:9113/metrics   # AI Narrative
curl http://localhost:9114/metrics   # Market Analysis
curl http://localhost:9115/metrics   # Signal Tracker
curl http://localhost:9116/metrics   # Feature Writer

# Grafana & Prometheus (optional — dashboards and alerts)
cd production && docker compose up -d prometheus grafana
# Grafana: http://localhost:3001  (admin / admin). Prometheus data source is preconfigured.
# Prometheus UI: http://localhost:9090  (query and targets)
# Note: 3001 avoids conflict with IndicAgent dashboard (Next.js on 3000)

# Direct invocation (debugging only)
.venv/bin/python production/daemons/high_frequency_tws_daemon.py --client-id 35
.venv/bin/python services/indicator_service.py
.venv/bin/python services/market_analysis_service.py
.venv/bin/python services/signal_generator_service.py
.venv/bin/python services/feature_writer_service.py
.venv/bin/python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

## Historical Data Backfill
```bash
# Full backfill — fetches multi-TF from IBKR then replays intelligence pipeline
.venv/bin/python production/scripts/historical_backfill.py

# Stage 1 only: IBKR → market_data_ohlcv (requires TWS running at 10.0.0.33:7497)
# Fetches: 1m(35d named), 5m(1yr continuous-adj), 15m(1yr), 1h(2yr), 1d(5yr)
.venv/bin/python production/scripts/historical_backfill.py --fetch-only

# Stage 2 only: DB → I1→I7 pipeline → signal_ledger + intelligence_features
.venv/bin/python production/scripts/historical_backfill.py --replay-only

# Override 1m depth or limit symbols
.venv/bin/python production/scripts/historical_backfill.py --days 60 --symbols ESH6,NQH6
```

## Development & Testing
```bash
.venv/bin/pytest tests/unit/ -v        # Unit tests
.venv/bin/pytest tests/integration/ -v # Integration (requires live Redis + PostgreSQL)
.venv/bin/ruff check . --fix           # Linting
.venv/bin/black .                      # Formatting
.venv/bin/mypy src/ --ignore-missing-imports
cd dashboard && npm run dev            # Frontend dev server
```

## Environment Variables
```bash
INDICAGENT_ENV="development"
DATABASE_URL="postgresql://postgres:postgres@localhost:5432/indicagent"
REDIS_URL="redis://localhost:6379/0"
IBKR_HOST="10.0.0.33"
IBKR_PORT=7497
OLLAMA_BASE_URL="http://localhost:11434"
OLLAMA_DEFAULT_MODEL="qwen3:8b"
```
