# Reference — API & Technical Specifications

Technical reference for APIs, plugins, services, and schemas.

---

## API Documentation

**[REST Endpoints](api/rest-endpoints.md)**
FastAPI routes, request/response formats

**[SSE Protocol](api/sse-protocol.md)**
Real-time Server-Sent Events streams

**[WebSocket Protocol](api/websocket-protocol.md)**
Alternative real-time API (optional)

---

## Plugin Reference

**[Plugin Overview](plugins/overview.md)**
Plugin protocol, registration, lifecycle

**Plugin Directories:**
- [I1: Technical Indicators](plugins/i1-indicators.md) — 16 plugins
- [I3: Market Structure](plugins/i3-structure.md) — 3 plugins
- [I4: Context Classification](plugins/i4-context.md) — 3 plugins
- [I5: Pattern Detection](plugins/i5-patterns.md) — 4 plugins
- [I6: Smart Money Concepts](plugins/i6-smart-money.md) — 7 plugins
- [I7: Trading Setups](plugins/i7-trading.md) — 5 plugins

**Total:** 45 plugins

See [STATUS.md](../../STATUS.md) for current counts.

---

## Service Reference

**[Service Overview](services/overview.md)**
Service architecture, coordination, health checks

**Service Docs:**
- [HF TWS Daemon](services/hf-tws-daemon.md) — IBKR data collection
- [Indicator Processor](services/indicator-processor.md) — I1 calculations
- [Timeframe Builder](services/timeframe-builder.md) — Multi-timeframe aggregation
- [Intelligence Processor](services/intelligence-processor.md) — I3-I7 processing
- [Coordination Service](services/coordination.md) — Service orchestration

---

## Data Schemas

**[Stream Schemas](schemas/stream-schemas.md)**
Redis stream data formats

**[Database Schemas](schemas/database-schemas.md)**
TimescaleDB table definitions

---

## Configuration

**[Configuration Reference](configuration.md)**
Settings.py, environment variables, contract definitions

**[CLI Commands](cli-commands.md)**
Common command reference for development

---

## Next Steps

- **Understand why:** [Concepts](../concepts/) for architectural context
- **Learn how:** [Guides](../guides/) for task-oriented how-tos
- **Check status:** [STATUS.md](../STATUS.md)

---

**Back to:** [Documentation Home](../README.md)
