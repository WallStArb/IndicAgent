# IndicAgent Command Cheatsheet

**Version:** 3.0
**Status:** current
**Last Updated:** 2026-09-04

## Development Setup
```bash
source .venv/bin/activate
pip install -r requirements.txt

# PostgreSQL/TimescaleDB -- native: sudo systemctl start postgresql
# Ollama -- native: ollama serve
# Redpanda -- Docker only:
cd production && docker compose up -d redpanda

# Database schema (plain `psql -U postgres` fails -- password required, see docs/reference/configuration.md)
for f in production/migrations/*.sql; do PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f "$f"; done
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
sudo systemctl restart indicagent-feature-vector-writer   # v3.0 writer; indicagent-feature-writer.service does not exist
sudo systemctl restart indicagent-llm-writer
sudo systemctl restart indicagent-narrative-compute        # not indicagent-ai-narrative -- no such unit
sudo systemctl restart indicagent-alpha-swarm
sudo systemctl restart indicagent-cross-asset
sudo systemctl restart indicagent-api

journalctl -u indicagent-intelligence-pipeline -f    # live logs (print() only; structured logs in logs/<service>.log)

# Health / metrics -- all agents emit via the OTel SDK (src/observability/metrics.py) to a
# single OTel Collector, which exposes one Prometheus exporter for every service (per-service
# metrics ports like the old 9113-9133 range no longer exist for most services):
curl http://localhost:8889/metrics   # OTel Collector Prometheus exporter -- every service's metrics

# A handful of services still expose their own dedicated METRICS_PORT (production/systemd/*.service):
curl http://localhost:9005/metrics   # Config Service
curl http://localhost:9006/metrics   # Outbox Dispatcher
curl http://localhost:9007/metrics   # Self-Healing Agent
curl http://localhost:9131/metrics   # Service Auditor
curl http://localhost:9132/metrics   # Alerting Agent

# Grafana & Prometheus (optional -- dashboards and alerts)
cd production && docker compose up -d prometheus grafana
# Grafana: http://localhost:3001  (admin / admin). Prometheus data source is preconfigured.
# Prometheus UI: http://localhost:9090  (query and targets)
# Note: 3001 avoids conflict with IndicAgent dashboard (Next.js on 3000)

# Direct invocation (debugging only) -- the `_agent` file suffix is retired (naming-conventions.md);
# indicagent-intelligence-pipeline.service's ExecStart itself points at a deleted v2.x file (see CLAUDE.md)
.venv/bin/python services/ibkr_provider.py
.venv/bin/python services/signal_writer.py
.venv/bin/python services/feature_vector_pipeline.py
.venv/bin/python services/feature_vector_writer.py
.venv/bin/python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

## Pipeline Reset (full housekeeping + fetch + replay)
# pipeline_reset.py is the single entry point -- handles everything in order:
#   1. Truncates signal_ledger, intelligence_features (+ market_data_ohlcv unless --keep-ohlcv)
#   2. Clears Redpanda topics (indicators, intelligence, signals, narratives)
#   3. Fetches OHLCV from IBKR per-TF: 1m=14d named, 5m=90d, 15m=180d, 1h=365d, 1d=2555d (7yr) continuous
#   4. Replays I1→I7 pipeline through all stored bars → signal_ledger + intelligence_features
#   5. Verifies row counts and signal distribution
# Script pauses at stop/start boundaries and prints the sudo commands for you to run.
```bash
# Step 1 -- preview (no changes made)
.venv/bin/python scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py --dry-run

# Step 2 -- full reset (requires IBKR Gateway reachable at localhost:7497; expect 30–60 min)
.venv/bin/python scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py
# → when prompted to STOP, run:
sudo systemctl stop indicagent-intelligence-pipeline indicagent-signal-writer indicagent-signal-tracker-compute \
  indicagent-feature-vector-writer indicagent-narrative-compute
# → press Enter, let fetch + replay complete
# → when prompted to START, run:
sudo systemctl start indicagent-intelligence-pipeline indicagent-feature-vector-writer \
  indicagent-signal-writer indicagent-signal-tracker-compute indicagent-narrative-compute

# Fast reset -- skip IBKR fetch, re-replay from existing market_data_ohlcv
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
.venv/bin/vulture                      # Dead code (config + whitelist in pyproject.toml/tools/vulture_whitelist.py)
.venv/bin/mypy src/ --ignore-missing-imports | .venv/bin/mypy-baseline filter  # Gated in CI (todo 311); blocks only NEW errors, .mypy-baseline.txt grandfathers the rest
.venv/bin/mypy src/ --ignore-missing-imports 2>&1 | .venv/bin/mypy-baseline sync --sort-baseline  # Regenerate the baseline after cleaning up pre-existing errors
cd dashboard && npm run dev            # Frontend dev server
```

## Environment Variables
```bash
INDICAGENT_ENV="development"
DATABASE_URL="postgresql://postgres:postgres@localhost:5432/indicagent"
KAFKA_BOOTSTRAP_SERVERS="localhost:19092"
IBKR_HOST="localhost"          # settings.py code default is 172.18.176.1 (Docker network gateway); .env sets localhost
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

## Cross-Sectional Spread Tracker (Phase 167, manual/on-demand only, no timer)

`services/cross_sectional_spread_tracker.py` -- cross_sectional_relative_value's dollar-neutral decile long-short
construction. See `docs/operations/operations-infrastructure.md`'s "Manual/On-Demand Batch
Services" section for why this has no systemd unit/timer.

```bash
# One-time full-corpus backfill (first run only, or after a construction_spreads truncate)
.venv/bin/python services/cross_sectional_spread_tracker.py --backfill

# Incremental compute-and-persist (the normal, repeatable invocation)
.venv/bin/python services/cross_sectional_spread_tracker.py

# Validation Gate 1 (shadow spread Sharpe), read-only
.venv/bin/python services/cross_sectional_spread_tracker.py --evaluate-gate

# Validation Gate 2 (attribution honesty), read-only
.venv/bin/python services/cross_sectional_spread_tracker.py --evaluate-attribution

# View last run logs / verdict artifacts
tail -50 logs/cross_sectional_spread_tracker.log
ls logs/construction_verdicts/
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

# Consumer groups -- check lag, reset offsets
docker exec redpanda rpk group list
docker exec redpanda rpk group describe <group-name> --topic <topic>
docker exec redpanda rpk group reset-offset <group> --topic <topic> --to-earliest

# Feature pipeline lag
docker exec redpanda rpk group describe feature_vector_pipeline_group -t
```
