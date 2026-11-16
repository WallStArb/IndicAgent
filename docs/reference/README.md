<!-- generated-by: gsd-doc-writer -->
# Reference — API & Technical Specifications

**Version:** 2.9
**Status:** current
**Last Updated:** 2026-09-04

Technical reference for APIs, plugins, services, and schemas.

---

## API Documentation

**[REST Endpoints](api/rest-endpoints.md)**
FastAPI routes, request/response formats

**[SSE Protocol](api/sse-protocol.md)**
Real-time Server-Sent Events streams

---

## Service Reference

**[Service Overview](services/overview.md)**
Live v3.0 service DAG — provider/bar/compute/persistence/ML/alpha-pipeline tiers, cross-checked against `_DAG_ORDER` in `services/service_auditor.py` and `systemctl` live state, 2026-09-04. Authoritative live state: `systemctl list-units --all | grep indicagent`

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

---

**Back to:** [Documentation Home](../README.md)
