# Running Services

All 8 services are systemd-managed (`Restart=always`, start on boot).

---

## Production Services (systemd)

```bash
# Status of all indicagent services
sudo systemctl status 'indicagent-*'

# Individual service management
sudo systemctl restart indicagent-tws
sudo systemctl restart indicagent-indicator
sudo systemctl restart indicagent-market-analysis
sudo systemctl restart indicagent-signal-generator
sudo systemctl restart indicagent-signal-lifecycle
sudo systemctl restart indicagent-ai-narrative
sudo systemctl restart indicagent-feature-writer
sudo systemctl restart indicagent-llm-writer
sudo systemctl restart indicagent-api

# Live logs
journalctl -u indicagent-indicator -f
```

### Service Units and Ports

| Unit | Purpose | Port |
|------|---------|------|
| `indicagent-tws` | IBKR tick + bar collection | — |
| `indicagent-indicator` | I1 indicators + multi-TF aggregation | 9109 |
| `indicagent-market-analysis` | I3→I6 intelligence pipeline | 9114 |
| `indicagent-signal-generator` | I7 setups + signal aggregation | 9112 |
| `indicagent-signal-lifecycle` | Signal lifecycle (pending→active→exit) | 9115 |
| `indicagent-ai-narrative` | I8 Ollama narrative synthesis | 9113 |
| `indicagent-feature-writer` | Redpanda → intelligence_features (TimescaleDB) | 9116 |
| `indicagent-llm-writer` | LLM audit log + outcome back-fill | 9117 |
| `indicagent-api` | FastAPI REST + SSE | 8000 |

### Health / Metrics

```bash
curl http://localhost:9109/metrics   # Indicator Service
curl http://localhost:9112/metrics   # Signal Generator
curl http://localhost:9113/metrics   # AI Narrative
curl http://localhost:9114/metrics   # Market Analysis
curl http://localhost:9115/metrics   # Signal Lifecycle
curl http://localhost:9117/metrics   # LLM Writer
curl http://localhost:9116/metrics   # Feature Writer
curl http://localhost:8000/health    # API
```

---

## Development Mode (direct invocation)

```bash
.venv/bin/python production/daemons/high_frequency_tws_daemon.py --client-id 35
.venv/bin/python services/indicator_service.py
.venv/bin/python services/market_analysis_service.py
.venv/bin/python services/signal_generator_service.py
.venv/bin/python services/signal_lifecycle_service.py
.venv/bin/python services/llm_writer_service.py
.venv/bin/python services/ai_narrative_service.py
.venv/bin/python services/feature_writer_service.py
.venv/bin/python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

---

**See also:** [Cheatsheet](../../docs/cheatsheet.md) · [Service Reference](../reference/services/overview.md)
