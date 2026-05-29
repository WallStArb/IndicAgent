# IndicAgent Intelligence Platform Documentation

**Version:** 2.8
**Status:** current
**Last Updated:** 2026-05-28

---

## Working on the platform?

**→ [CLAUDE.md](../CLAUDE.md)** — Primary reference: architecture, commands, conventions, gotchas
**→ [Roadmap](../.planning/ROADMAP.md)** — What's next
**→ [Ideas](ideas/)** — Research and strategy docs (living workspace)
**→ [AI Ideas Index](ideas/ai-index.md)** — Standardized AI / ML / agentic idea cluster

---

## Understanding the architecture?

**→ [Architecture Overview](architecture/overview.md)** — System architecture deep dives
**→ [Intelligence Tiers](concepts/intelligence-tiers.md)** — I1-I8 framework
**→ [Plugin Architecture](concepts/plugin-architecture.md)** — How plugins work
**→ [DAG Execution](concepts/dag-execution.md)** — Dependency ordering
**→ [Data Pipeline](concepts/data-pipeline.md)** — Hot/warm/cold flow, Redpanda, TimescaleDB

---

## Renaissance documentation layers

### Foundation — WHY+WHAT

Immutable truths: principles, naming rules, AI working rules.

**→ [Principles](foundation/principles.md)** — Renaissance principles applied to market intelligence
**→ [Naming Conventions](foundation/naming-conventions.md)** — Concept name derives all layer names
**→ [AI Working Rules](foundation/ai-working-rules.md)** — AI agent development rules

### Architecture — Conceptual WHY

System design and patterns (could change, but currently true).

**→ [Overview](architecture/overview.md)** — System architecture at a glance
**→ [Self-Healing](architecture/self-healing.md)** — Watchdog, stall detection, DLQ quarantine
**→ [Observability](architecture/observability.md)** — OTel patterns, metric contracts
**→ [API Design](architecture/api-design.md)** — REST + SSE architecture

### Intelligence — I1-I8 Specific

Domain-specific documentation for the intelligence pipeline.

**→ [Foundation](intelligence/intelligence-foundation.md)** — I1-I8 definitions, data flow philosophy
**→ [Plugins](intelligence/intelligence-plugins.md)** — Plugin protocol, how to add a plugin
**→ [AI](intelligence/intelligence-ai.md)** — Swarm agents, LLM chain, shadow governance
**→ [Operations](intelligence/intelligence-operations.md)** — Services, monitoring, debugging

### Operations — Sysadmin HOW

Production procedures: deployment, monitoring, troubleshooting.

**→ [Infrastructure](operations/infrastructure.md)** — Systemd, Docker, servers, deployment
**→ [Database](operations/database.md)** — TimescaleDB operations, migrations, backup
**→ [Observability](operations/observability.md)** — Metrics, traces, dashboards, Grafana
**→ [Security](operations/security.md)** — Security procedures, audit
**→ [Disaster Recovery](operations/disaster-recovery.md)** — DR procedures

### Development — Developer HOW

Local development procedures: setup, testing, profiling.

**→ [Setup](development/setup.md)** — New machine setup, environment, dependencies
**→ [Testing](development/testing.md)** — Unit/integration/e2e how-to
**→ [Profiling](development/profiling.md)** — Performance profiling
**→ [Alerting](development/alerting.md)** — Incident response runbook

### Reference — Quick Lookup

Cheat sheets and gotchas for fast lookup.

**→ [Cheatsheet](reference/cheatsheet.md)** — Common commands and workflows
**→ [Gotchas](reference/gotchas.md)** — Known pitfalls and solutions

### Specs — Design Contracts

Phase-specific design documents and implementation plans.

**→ [Specs](specs/)** — Phase specs and design contracts

---

## Directory Structure

```
docs/
├── foundation/       ← WHY+WHAT: principles, naming, AI rules
├── architecture/     ← Conceptual WHY: system design, patterns
├── concepts/         ← Architectural patterns (I1–I8, plugins, DAG)
├── intelligence/     ← I1-I8 domain-specific docs
├── operations/       ← Sysadmin HOW: deploy, monitor, fix
├── development/      ← Developer HOW: setup, test, profile
├── reference/        ← Quick lookup: cheat sheets
├── specs/            ← Design contracts
├── ideas/            ← Living research workspace
└── reference/        ← Technical specs and standards
```

---

## External Links

- [TimescaleDB Docs](https://docs.timescale.com/)
- [Redpanda Docs](https://docs.redpanda.com/)
- [IBKR TWS API Docs](https://interactivebrokers.github.io/tws-api/)
