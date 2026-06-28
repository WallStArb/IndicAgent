# IndicAgent Command Cheatsheet

**Version:** 2.8
**Status:** current
**Last Updated:** 2026-05-02

## Development Setup
```bash
source .venv/bin/activate
pip install -r requirements.txt

# PostgreSQL/TimescaleDB — native: sudo systemctl start postgresql
# Ollama — native: ollama serve
# Redpanda — Docker only:
cd production && docker compose up -d redpanda

# Database schema
for f in production/migrations/0*.sql; do psql -U postgres -d indicagent -f "$f"; done
```

## System Operations
```bash
# All services are systemd-managed (Restart=always, start on boot)
# Authoritative unit files: /etc/systemd/system/ (templates in production/systemd/)
sudo systemctl status 'indicagent-*'
sudo systemctl restart indicagent-ibkr-provider
sudo systemctl restart indicagent-provider-merger
sudo systemctl restart indicagent-bar-aggregator
sudo systemctl restart indicagent-intelligence-pipeline
sudo systemctl restart indicagent-signal-writer
sudo systemctl restart indicagent-signal-tracker-compute
sudo systemctl restart indicagent-feature-writer
sudo systemctl restart indicagent-llm-writer
sudo systemctl restart indicagent-ai-narrative
sudo systemctl restart indicagent-alpha-swarm
sudo systemctl restart indicagent-cross-asset
sudo systemctl restart indicagent-api

journalctl -u indicagent-intelligence-pipeline -f    # live logs (print() only; structured logs in logs/<service>.log)

# Health / metrics (ports 9113, 9115–9133)
curl http://localhost:9113/metrics   # AI Narrative
curl http://localhost:9115/metrics   # Signal Tracker
curl http://localhost:9116/metrics   # Feature Writer
curl http://localhost:9117/metrics   # LLM Writer
curl http://localhost:9118/metrics   # Cross-Asset
curl http://localhost:9119/metrics   # Signal Writer
curl http://localhost:9120/metrics   # Bar Aggregator
curl http://localhost:9121/metrics   # Bar Writer
curl http://localhost:9122/metrics   # Roll Compute
curl http://localhost:9123/metrics   # Bar Auditor
curl http://localhost:9124/metrics   # Contract Metadata Writer
curl http://localhost:9125/metrics   # Intelligence Pipeline
curl http://localhost:9126/metrics   # Signal Metrics Compute
curl http://localhost:9127/metrics   # Signal Metrics Writer
curl http://localhost:9128/metrics   # Signal Auditor
curl http://localhost:9129/metrics   # IBKR Provider
curl http://localhost:9130/metrics   # Provider Merger
curl http://localhost:9131/metrics   # Service Auditor
curl http://localhost:9132/metrics   # Feature Snapshot Writer
curl http://localhost:9133/metrics   # Parity Auditor

# Grafana & Prometheus (optional — dashboards and alerts)
cd production && docker compose up -d prometheus grafana
# Grafana: http://localhost:3001  (admin / admin). Prometheus data source is preconfigured.
# Prometheus UI: http://localhost:9090  (query and targets)
# Note: 3001 avoids conflict with IndicAgent dashboard (Next.js on 3000)

# Direct invocation (debugging only)
.venv/bin/python services/ibkr_provider_agent.py
.venv/bin/python services/intelligence_pipeline_agent.py
.venv/bin/python services/signal_writer_agent.py
.venv/bin/python services/feature_writer_agent.py
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
.venv/bin/python scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py --dry-run

# Step 2 — full reset (requires TWS connected at 192.168.1.157:7497; expect 30–60 min)
.venv/bin/python scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py
# → when prompted to STOP, run:
sudo systemctl stop indicagent-intelligence-pipeline indicagent-signal-writer indicagent-signal-tracker-compute \
  indicagent-feature-writer indicagent-ai-narrative
# → press Enter, let fetch + replay complete
# → when prompted to START, run:
sudo systemctl start indicagent-intelligence-pipeline indicagent-feature-writer \
  indicagent-signal-writer indicagent-signal-tracker-compute indicagent-ai-narrative

# Fast reset — skip IBKR fetch, re-replay from existing market_data_ohlcv
# (use after plugin/signal logic changes, no IBKR connection needed)
.venv/bin/python scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py --keep-ohlcv

# Limit to specific symbols
.venv/bin/python scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py --keep-ohlcv --symbols ESH6,NQH6

# Also wipe LLM audit log (llm_calls, llm_model_scores)
.venv/bin/python scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py --clear-llm
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
IBKR_HOST="192.168.1.157"
IBKR_PORT=7497
```

## Shadow Mode Validation

The shadow validator runs weekly (Mon 07:00 UTC) via `indicagent-shadow-validator.timer` and evaluates all 22 tracked I7 setups against a 5-gate promotion criteria.

**5-Gate Promotion Criteria:**
- Gate 1: N >= 100 resolved outcomes (sufficient sample)
- Gate 2: win_rate >= 50% (positive outcome rate)
- Gate 3: binomtest p < 0.05 one-sided vs 50% baseline (statistically significant)
- Gate 4: avg_pnl_r > 0 (positive expectancy)
- Gate 5: calibration_corr >= 0.3 (cis_score predicts profitable outcomes)

**Grafana dashboard:** Shadow Mode Validation (http://localhost:3001) - per-setup N, win_rate, p_value, avg_pnl_r, calibration, and promoted status.

```bash
# Manual run (debugging / forced check)
.venv/bin/python services/shadow_validator.py

# Check timer status
sudo systemctl status indicagent-shadow-validator.timer
sudo systemctl list-timers indicagent-shadow-validator.timer

# View last run logs
tail -50 logs/shadow_validator.log
```

## Kafka / Redpanda
```bash
# Topics
docker exec redpanda rpk topic list
docker exec redpanda rpk topic describe <topic-name>
docker exec redpanda rpk topic consume <topic-name> --from-beginning
docker exec redpanda rpk topic create <topic-name> --partitions 1 --replicas 1
docker exec redpanda rpk topic delete <topic-name>
docker exec redpanda rpk topic stats <topic-name>

# Retention (ms: 1h=3600000, 1d=86400000, 7d=604800000)
docker exec redpanda rpk topic create <name> --config retention.ms=86400000
docker exec redpanda rpk topic alter-config <name> --set retention.ms=86400000

# Consumer groups — check lag, reset offsets
docker exec redpanda rpk group list
docker exec redpanda rpk group describe <group-name> --topic <topic>
docker exec redpanda rpk group reset-offset <group> --topic <topic> --to-earliest

# Feature pipeline lag (from CLAUDE.md)
docker exec redpanda rpk group describe feature_pipeline -t
```
