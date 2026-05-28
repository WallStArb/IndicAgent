<!-- generated-by: gsd-doc-writer -->
# Reference — API & Technical Specifications

**Version:** 2.8
**Status:** current
**Last Updated:** 2026-05-27

Technical reference for APIs, plugins, services, and schemas.

---

## API Documentation

**[REST Endpoints](api/rest-endpoints.md)**
FastAPI routes, request/response formats

**[SSE Protocol](api/sse-protocol.md)**
Real-time Server-Sent Events streams

---

## Plugin Reference

**[Plugin Overview](plugins/overview.md)**
Plugin protocol, registration, lifecycle

**Plugin Directories:**
- [I1: Technical Indicators](plugins/i1-indicators.md)
- [I3: Market Structure](plugins/i3-structure.md)
- [I4: Context Classification](plugins/i4-context.md)
- [I5: Pattern Detection](plugins/i5-patterns.md)
- [I6: Smart Money Concepts](plugins/i6-smart-money.md)
- [I7: Trading Setups](plugins/i7-trading.md)

**Total:** 132 plugins across I1-I7 (authoritative count: `TIER_I1`…`TIER_I7` in `src/intelligence/register_plugins.py`)

---

## Service Reference

**[Service Overview](services/overview.md)**
Service architecture, coordination, health checks. Authoritative live state: `systemctl list-units --all | grep indicagent`

---

## Data Schemas

**[Stream Schemas](schemas/stream-schemas.md)**
Redpanda (Kafka-compatible) stream data formats and contracts

---

## Configuration

**[Configuration Reference](configuration.md)**
Settings.py, environment variables, contract definitions

---

## Next Steps

- **Understand why:** [Concepts](../concepts/) for architectural context
- **Learn how:** [Guides](../guides/) for task-oriented how-tos
- **Check status:** [STATUS.md](../STATUS.md)

---

**Back to:** [Documentation Home](../README.md)
