# IndicAgent Intelligence Platform Documentation

**Version:** 2.8
**Status:** current
**Last Updated:** 2026-05-02

---

## Working on the platform?

**→ [CLAUDE.md](../CLAUDE.md)** — Primary reference: architecture, commands, conventions, gotchas
**→ [Guides](guides/)** — How to add plugins, run services, debug
**→ [Roadmap](../.planning/ROADMAP.md)** — What's next
**→ [Ideas](ideas/)** — Research and strategy docs (living workspace)
**→ [AI Ideas Index](ideas/ai-index.md)** — Standardized AI / ML / agentic idea cluster

---

## Understanding the architecture?

**→ [High-Level Concepts](architecture/concepts.md)** — Core architectural patterns (DAG, clustering, microservices, ML/AI)
**→ [Intelligence Tiers](concepts/intelligence-tiers.md)** — I1-I8 framework
**→ [Plugin Architecture](concepts/plugin-architecture.md)** — How plugins work
**→ [DAG Execution](concepts/dag-execution.md)** — Dependency ordering
**→ [Data Pipeline](concepts/data-pipeline.md)** — Hot/warm/cold flow, Redpanda, TimescaleDB
**→ [Agent Contract Checklist](architecture/agent-contract-checklist.md)** — Required contract for new agents
**→ [Canonical Truth Registry](architecture/canonical-truth-registry.md)** — Canonical stream/table ownership

---

## Directory Structure

```
docs/
├── architecture/          ← System architecture deep dives
├── concepts/              ← Architectural patterns (I1–I8, plugins, DAG)
├── guides/                ← Task-oriented how-tos
├── ideas/                 ← Living research workspace (per-idea files)
├── intelligence/          ← AI/LLM intelligence layer docs
├── plans/                 ← Design docs and implementation plans
└── reference/             ← Technical specs and standards
```

---

## External Links

- [TimescaleDB Docs](https://docs.timescale.com/)
- [Redpanda Docs](https://docs.redpanda.com/)
- [IBKR TWS API Docs](https://interactivebrokers.github.io/tws-api/)
