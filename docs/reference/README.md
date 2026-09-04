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

## Plugin Reference

**ARCHIVED (v2.x, no live consumer since 2026-07-02).** The I1-I7 plugin pipeline below is not the platform's live compute path — that's Feature Factory (`src/intelligence/feature_factory.py`, run by `indicagent-feature-vector-pipeline.service`). Kept for historical reference.

**[Plugin Overview](plugins/overview.md)**
Plugin protocol, registration, lifecycle, tier source-code locations — archived system, described accurately as of 2026-09-04

**[Plugin Catalog](plugins/catalog.md)**
Full tier catalog with counts and design rationale — archived system, historical reference

Per-tier plugin directories (`i1-indicators.md`, `i3-structure.md`, `i4-context.md`, `i5-patterns.md`, `i6-smart-money.md`, `i7-trading.md`) referenced by earlier versions of this index **do not exist** in `docs/reference/plugins/` (verified via `ls`, 2026-09-04) — removed rather than left broken. Tier detail lives in `plugins/overview.md` and `plugins/catalog.md` instead; deeper archived-system detail is in `src/intelligence/CLAUDE.md`.

**Total:** 133 registered plugins across I1-I7 + SMC (authoritative count: `len(TIER_I1)`…`len(TIER_I7)` in `src/intelligence/register_plugins.py`, verified 2026-09-04). This counts what's in the archived registry's source, not anything computing signals live today — see `plugins/overview.md` for why `register_plugins.py` itself has no live consumer.

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
- **Learn how:** [Guides](../guides/) for task-oriented how-tos
- **Check status:** [STATUS.md](../STATUS.md)

---

**Back to:** [Documentation Home](../README.md)
