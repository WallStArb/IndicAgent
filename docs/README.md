# IndicAgent Intelligence Platform Documentation

**Last Updated:** 2026-03-15

---

## Working on the platform?

**→ [CLAUDE.md](../CLAUDE.md)** — Primary reference: architecture, commands, conventions, gotchas
**→ [Guides](guides/)** — How to add plugins, run services, debug
**→ [Roadmap](../.planning/ROADMAP.md)** — What's next
**→ [Ideas](ideas/)** — Research and strategy docs (living workspace)

---

## Understanding the architecture?

**→ [Intelligence Tiers](concepts/intelligence-tiers.md)** — I1-I8 framework
**→ [Plugin Architecture](concepts/plugin-architecture.md)** — How plugins work
**→ [DAG Execution](concepts/dag-execution.md)** — Dependency ordering
**→ [Data Pipeline](concepts/data-pipeline.md)** — Hot/warm/cold flow, Redpanda, TimescaleDB

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
