# Running Services

All services are systemd-managed (`Restart=always`, start on boot).

---

## Production Services (systemd)

```bash
# Status of all indicagent services
sudo systemctl status 'indicagent-*'

# Individual service management
sudo systemctl restart indicagent-ibkr-provider
sudo systemctl restart indicagent-provider-merger
sudo systemctl restart indicagent-bar-aggregator
sudo systemctl restart indicagent-bar-writer
sudo systemctl restart indicagent-bar-auditor
sudo systemctl restart indicagent-roll-compute
sudo systemctl restart indicagent-contract-metadata-writer
sudo systemctl restart indicagent-intelligence-pipeline
sudo systemctl restart indicagent-signal-writer
sudo systemctl restart indicagent-signal-tracker-compute
sudo systemctl restart indicagent-signal-metrics-compute
sudo systemctl restart indicagent-signal-metrics-writer
sudo systemctl restart indicagent-signal-auditor
sudo systemctl restart indicagent-feature-writer
sudo systemctl restart indicagent-feature-snapshot-writer
sudo systemctl restart indicagent-parity-auditor
sudo systemctl restart indicagent-llm-writer
sudo systemctl restart indicagent-ai-narrative
sudo systemctl restart indicagent-cross-asset
sudo systemctl restart indicagent-service-auditor
sudo systemctl restart indicagent-api
sudo systemctl restart indicagent-dashboard

# Live logs (journald shows print() only — structured logs in logs/<service>.log)
journalctl -u indicagent-intelligence-pipeline -f
```

### Service Units and Ports

| Unit | Purpose | Port |
|------|---------|------|
| `indicagent-ibkr-provider` | IBKR dual streams (5s RTB + 1m aggregation) | 9129 |
| `indicagent-provider-merger` | Routes `market.bars.raw.*` → `market.bars` | 9130 |
| `indicagent-bar-aggregator` | 1m → HTF (5m-1d) aggregation | 9120 |
| `indicagent-bar-writer` | Writes `market_data_ohlcv` (batch) | 9121 |
| `indicagent-bar-auditor` | Gap detection → `market.events.gap_requests` | 9123 |
| `indicagent-roll-compute` | Calendar + volume z-score roll detection | 9122 |
| `indicagent-contract-metadata-writer` | Roll events → front-month promotion in `contract_metadata` | 9124 |
| `indicagent-intelligence-pipeline` | I1-I7 unified in-process pipeline | 9125 |
| `indicagent-signal-writer` | Writes `signal_ledger` (batch) | 9119 |
| `indicagent-signal-tracker-compute` | Signal lifecycle (activation, MAE/MFE, outcome) | 9115 |
| `indicagent-signal-metrics-compute` | Timer-triggered signal performance metrics | 9126 |
| `indicagent-signal-metrics-writer` | Persists signal metrics to DB | 9127 |
| `indicagent-signal-auditor` | Coverage validation + lag monitoring | 9128 |
| `indicagent-feature-writer` | Writes `intelligence_features` (batch) | 9116 |
| `indicagent-feature-snapshot-writer` | Shadow dual-write → `feature_snapshots_shadow` | 9132 |
| `indicagent-parity-auditor` | 5-min parity comparison; certifies after 60 clean cycles | 9133 |
| `indicagent-llm-writer` | Writes `llm_calls` + outcome back-fill | 9117 |
| `indicagent-ai-narrative` | I8 Ollama narrative synthesis | 9113 |
| `indicagent-cross-asset` | Cross-asset spread dynamics | 9118 |
| `indicagent-service-auditor` | Pipeline health monitor and self-healer | 9131 |
| `indicagent-api` | FastAPI REST + SSE | 8000 |
| `indicagent-dashboard` | Next.js dev server | 3000 |
| `indicagent-weight-updater` | Daily (02:00) CIS weight refresh | — (oneshot) |

### Health / Metrics

```bash
curl http://localhost:9113/metrics   # AI Narrative
curl http://localhost:9115/metrics   # Signal Tracker
curl http://localhost:9116/metrics   # Feature Writer
curl http://localhost:9117/metrics   # LLM Writer
curl http://localhost:9118/metrics   # Cross Asset
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
curl http://localhost:8000/health    # API
```

---

## Development Mode (direct invocation)

```bash
.venv/bin/python services/ibkr_provider_agent.py
.venv/bin/python services/intelligence_pipeline_agent.py
.venv/bin/python services/feature_writer_agent.py
.venv/bin/python services/signal_writer_agent.py
.venv/bin/python services/llm_writer_service.py
.venv/bin/python services/ai_narrative_service.py
.venv/bin/python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

---

**See also:** [Cheatsheet](../../docs/cheatsheet.md) · [Current State](../architecture/current-state.md)
