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

## Bar data layer
# Every vendor answer lands in ohlcv_raw (last-wins, old values in ohlcv_revision); canonical
# market_data_ohlcv is a selection from raw by bar_source_policy. Sources and owners:
# docs/foundation/canonical-truth-registry.md. The v2.x pipeline reset script is gone (185-45).
```bash
systemctl list-timers | grep indicagent   # fetcher (15 min), alpaca-nightly 04:40 UTC, grid 05:45 UTC, D7 06:00 UTC

# IBKR history (one at a time under FetcherLock; dry run first)
.venv/bin/python -u scripts/infrastructure/backfill/ohlcv_history_fetcher.py --dry-run \
    --dimension backfill --timeframes 1d --symbols AAPL,MSFT --full-scan --client-id 41

# Alpaca SIP capture (dry run still asks the vendor; add --apply to write)
.venv/bin/python -m scripts.ops.bars.ops_bar_nightly --vendor alpaca --symbols AAPL MSFT --days 5

# Proof that canonical is a pure function of raw plus policy (read-only)
.venv/bin/python scripts/ops/bars/ops_selection_gate.py --compare --timeframes 5m --symbols AAPL

# Current source policy
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT timeframe, symbol, valid_from, valid_to, primary_source, fallback_source FROM bar_source_policy_current WHERE symbol IS NULL ORDER BY 1, 3"

# Re-derive canonical 1d for named symbols (idempotent)
PYTHONPATH=. .venv/bin/python services/bar_derivation.py --stage daily --symbols AAPL,MSFT --apply
```

## Development & Testing
```bash
.venv/bin/pytest tests/unit/ -n auto   # Unit tests, parallel (-n 0 for pdb)
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

## Cross-sectional spread tracker (deleted)

The cross_sectional_spread_tracker service was deleted in 186-19; the long-short construction role is the research package's R1 rule, and the decile spec is in `docs/research/summary-cards/legacy-ctf-momentum-decile-ls.md`.

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
