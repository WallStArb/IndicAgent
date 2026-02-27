# IndicAgent Services

Systemd service unit files for the IndicAgent platform. All services use `Restart=always` and start on boot.

## Service Units

| File | Unit name | Purpose | Port |
|------|-----------|---------|------|
| `indicagent-tws.service` | `indicagent-tws` | IBKR TWS daemon — tick + bar ingest | — |
| `indicagent-indicator.service` | `indicagent-indicator` | I1 indicators + multi-TF aggregation | 9109 |
| `indicagent-market-analysis.service` | `indicagent-market-analysis` | I3→I6 intelligence pipeline | 9114 |
| `indicagent-signal-generator.service` | `indicagent-signal-generator` | I7 setups + signal aggregation + ledger | 9112 |
| `indicagent-signal-tracker.service` | `indicagent-signal-tracker` | Signal lifecycle (pending→active→exit) | 9115 |
| `indicagent-ai-narrative.service` | `indicagent-ai-narrative` | I8 Ollama narrative synthesis | 9113 |
| `indicagent-feature-writer.service` | `indicagent-feature-writer` | Redis → intelligence_features batch writer | 9116 |
| `indicagent-api.service` | `indicagent-api` | FastAPI REST + SSE fan-out | 8000 |

> `indicagent-timeframes.service` — legacy, FAILED (import bug, non-blocking). Multi-TF aggregation was moved into `indicagent-indicator`.

## Stream Flow

```
indicagent-tws
  │  ticks:SYMBOL:live + market:SYMBOL:1m
  ▼
indicagent-indicator
  │  indicators:SYMBOL:TF  (I1 per-TF combined message)
  ▼
indicagent-market-analysis
  │  intelligence:SYMBOL:TF  (typed IntelligenceEvent: I3→I6)
  ├──────────────────────────────────────────────────────────────────────►
  │                                                          indicagent-feature-writer
  │                                                          → intelligence_features (TimescaleDB)
  ▼
indicagent-signal-generator
  │  signals:SYMBOL:TF:aggregated  (I7 selected signal)
  ├─────────────────────────────────────────►
  │                               indicagent-signal-tracker
  │                               (reads market:SYMBOL:1m for SL/TP checks)
  ▼
indicagent-ai-narrative
  │  narratives:SYMBOL:TF  (per-signal, qwen3:8b, conf>0.7)
  │  narratives:group:GROUP_NAME  (group synthesis, phi4-mini:3.8b)
  ▼
indicagent-api  →  SSE  →  Dashboard
```

## Management

```bash
# Status
sudo systemctl status 'indicagent-*'

# Restart a service
sudo systemctl restart indicagent-indicator

# Live logs
journalctl -u indicagent-indicator -f

# Start all (e.g. after reboot)
sudo systemctl start indicagent-tws indicagent-indicator indicagent-market-analysis \
  indicagent-signal-generator indicagent-signal-tracker indicagent-ai-narrative \
  indicagent-feature-writer indicagent-api
```

## Install / Update Service Files

```bash
sudo cp services/indicagent-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable indicagent-tws indicagent-indicator indicagent-market-analysis \
  indicagent-signal-generator indicagent-signal-tracker indicagent-ai-narrative \
  indicagent-feature-writer indicagent-api
```

**Full reference:** [docs/guides/running-services.md](../docs/guides/running-services.md) · [docs/cheatsheet.md](../docs/cheatsheet.md)
