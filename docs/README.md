# IndicAgent Intelligence Platform Documentation

**Version:** 2.8
**Status:** current
**Last Updated:** 2026-05-29

---

## Documentation Taxonomy

The docs use a **domain-first, recipe-card format**: each folder owns a specific domain, and each file answers one of four questions — WHY (design rationale), WHAT (contracts and data shapes), HOW (procedures), or WHERE (quick lookup). Files within a domain folder are named `<domain>-<role>.md` (e.g., `intelligence-foundation.md`, `signals-lifecycle.md`).

The `intelligence/` folder is the gold standard — four files, each a distinct recipe card, covering foundation, plugins, AI, and operations. New domain folders (`agents/`, `signals/`, `platform/`) follow the same pattern. Older folders (`foundation/`, `data/`, `operations/`, `reference/`) are stable but predate the recipe-card convention. `architecture/` is legacy — content migrates to domain folders over time. `concepts/` is the permanent home for cross-domain conceptual WHY docs; it is not a migration staging area.

---

## Working on the platform?

**→ [CLAUDE.md](../CLAUDE.md)** — Primary reference: architecture, commands, conventions, gotchas
**→ [Roadmap](../.planning/ROADMAP.md)** — What's next
**→ [Ideas](ideas/)** — Research and strategy docs (living workspace)
**→ [AI Ideas Index](ideas/ai-index.md)** — Standardized AI / ML / agentic idea cluster

---

## Folder Index

### `foundation/` — stable — Immutable truths

WHY+WHAT: principles, naming rules, AI working rules. These change rarely.

| File | Description |
|------|-------------|
| `principles.md` | Renaissance principles applied to market intelligence |
| `glossary.md` | Controlled vocabulary — every domain term has exactly one definition |
| `product-laws.md` | Six philosophical and economic principles governing product reality |
| `naming-system.md` | Complete vocabulary system — rings, taxonomy, surfaces, evolution |
| `documentation-system.md` | Documentation taxonomy, recipe-card format, verification lifecycle |
| `design-principles.md` | Foundational architectural design principles and DAG invariants |
| `canonical-truth-registry.md` | Canonical writer registry — one source of truth per durable fact |
| `adaptive-parameter-registry.md` | APR full specification — all tunable numeric values |
| `model-selection-principle.md` | Occam's Razor applied to model selection |
| `ship-or-sink-rules.md` | AI coding tool discipline — Ship or Sink rules |

### `intelligence/` — gold standard — I1-I8 domain

The reference implementation of the recipe-card format. Four files, four angles.

| File | Description |
|------|-------------|
| `intelligence-foundation.md` | I1-I8 definitions, data flow philosophy, tier contracts (v2.x) |
| `intelligence-alphaengine.md` | IC-weighted factor model — vocabulary, methodology, and why the plugin approach was replaced (v3.0) |
| `intelligence-plugins.md` | Plugin protocol, how to add a plugin, 132-plugin inventory |
| `intelligence-ai.md` | Swarm agents, LLM chain, shadow governance |
| `intelligence-operations.md` | Services, monitoring, debugging the intelligence pipeline |

### `agents/` — new (Phase 3) — Agent infrastructure domain

| File | Description |
|------|-------------|
| `agents-foundation.md` | Agent lifecycle, OTel signals, BaseAgent contract |
| `agents-operations.md` | Role taxonomy, DAG topology, service mesh |
| `agents-writers.md` | Writer agent patterns, DLQ, persistence contracts |

### `signals/` — new (Phase 3) — Signal domain

| File | Description |
|------|-------------|
| `signals-foundation.md` | Signal schema, entry types, status strings, schema versioning (pre-SLA; partially stale) |
| `signals-schema.md` | SLA table DDL — signal_events, trade_frames, trade_executions, signal_ledger_full view |
| `signals-ecl.md` | ECL system reference — vector fields, ML training patterns, boundary verification |
| `signals-lifecycle.md` | I7 signal creation, zone activation, MAE/MFE, outcome classification |
| `signals-operations.md` | Signal monitoring, shadow governance, graduation pipeline |
| `signal-trade-separation-ADR.md` | ADR: formal decision record for the 3-table SLA split |

### `platform/` — new (Phase 4) — Infrastructure + API + Observability domain

| File | Description |
|------|-------------|
| `platform-foundation.md` | WHY systemd/Docker split, L1-L10 DAG, container inventory, cascade failures |
| `platform-observability.md` | OTel SDK design, metric contracts, D-27 SLO alerts, circuit breaker |
| `platform-api.md` | FastAPI architecture, SSE vs WebSocket rationale, health router prefix gotcha |

### `data/` — stable — Data foundation domain

| File | Description |
|------|-------------|
| `data-foundation.md` | Reference data, instrument contracts, roll architecture |
| `data-provider.md` | Provider isolation, failover, IBKR dual streams |
| `data-pipeline.md` | Hot/warm/cold flow, Redpanda topics, consumer groups, TimescaleDB |
| `data-streaming.md` | Streaming patterns, topic naming, stream_keys.py |

### `operations/` — stable — Sysadmin HOW

Production procedures: deployment, monitoring, troubleshooting.

| File | Description |
|------|-------------|
| `infrastructure.md` | Systemd, Docker, servers, deployment |
| `database.md` | TimescaleDB operations, migrations, backup |
| `observability.md` | Operational runbook: Grafana dashboards, PromQL patterns, troubleshooting |
| `security.md` | Security procedures, audit |
| `disaster-recovery.md` | DR procedures |

### `development/` — stable — Developer HOW

Local development procedures: setup, testing, profiling.

| File | Description |
|------|-------------|
| `setup.md` | New machine setup, environment, dependencies |
| `testing.md` | Unit/integration/e2e how-to |
| `profiling.md` | Performance profiling |
| `alerting.md` | Incident response runbook |

### `reference/` — stable — Quick lookup

Cheat sheets and gotchas for fast lookup.

| File | Description |
|------|-------------|
| `cheatsheet.md` | Common commands and workflows |
| `gotchas.md` | Known pitfalls and solutions |

### `concepts/` — stable — Cross-domain conceptual library

WHY docs for concepts that span multiple domain folders. One concept per file: design rationale, what was rejected, failure modes. The permanent home for ideas too cross-cutting to live in a single domain folder.

| File | Domain |
|------|--------|
| `intelligence-tiers.md` | Intelligence |
| `plugin-architecture.md` | Intelligence |
| `dag-execution.md` | Intelligence |
| `incremental-computation.md` | Intelligence |
| `cis-scoring.md` | Intelligence |
| `regime-classification.md` | Intelligence |
| `swarm-intelligence.md` | Intelligence |
| `evolvable-ai.md` | Intelligence |
| `tier-naming-system.md` | Intelligence |

### `architecture/` — legacy — Cross-cutting design docs

System design docs that predate the domain-folder taxonomy. The two files that were cleanly migrated (`observability.md` → `platform/`, `api-design.md` → `platform/`) have been deleted. Remaining files are genuinely cross-cutting and kept in place.

| File | Description |
|------|-------------|
| `dag-topology.md` | Canonical DAG topology reference |
| `current-state.md` | Active services, current architecture state |
| `canonical-truth-registry.md` | Single source of truth registry |
| `overview.md` | Architecture overview at a glance |
| `self-healing.md` | Watchdog, stall detection, DLQ quarantine |
| `pipeline-optimization.md` | Pipeline optimization strategy |
| `design-principles.md` | Architectural design principles (10 constraints) |

### `specs/` — Design contracts

Phase-specific design documents and implementation plans.

### `plans/` — Implementation plans

Phase implementation plans (living workspace).

### `ideas/` — Research workspace

Research, strategy, and architecture analysis (living workspace).

---

## External Links

- [TimescaleDB Docs](https://docs.timescale.com/)
- [Redpanda Docs](https://docs.redpanda.com/)
- [IBKR TWS API Docs](https://interactivebrokers.github.io/tws-api/)
