# IndicAgent Intelligence Platform Documentation

**Current Version:** See [STATUS.md](STATUS.md) for current state
**Last Updated:** 2026-02-20

---

## Start Here

Choose your path based on what you need:

### New to IndicAgent?
**→ [Quick Start](getting-started/quickstart.md)** — Get running in 5 minutes
**→ [Architecture Overview](getting-started/architecture-overview.md)** — Understand the system

### Working on the platform?
**→ [STATUS.md](STATUS.md)** — Current state, versions, health
**→ [Guides](guides/)** — How to add plugins, run services, debug
**→ [Roadmap](../.planning/ROADMAP.md)** — What's next

### Understanding the architecture?
**→ [Intelligence Tiers](concepts/intelligence-tiers.md)** — I1-I8 framework
**→ [Plugin Architecture](concepts/plugin-architecture.md)** — How plugins work
**→ [Stream Schemas](reference/schemas/stream-schemas.md)** — Redis data formats

### Looking up specifics?
**→ [Plugin Reference](reference/plugins/)** — All 57 plugins documented
**→ [API Reference](reference/api/)** — REST endpoints, SSE protocol
**→ [Stream Schemas](reference/schemas/stream-schemas.md)** — Redis data formats

### Contributing?
**→ [CONTRIBUTING.md](contributing/CONTRIBUTING.md)** — How to contribute
**→ [Code Standards](contributing/code-standards.md)** — Linting, naming, testing

### AI Assistant?
**→ [CLAUDE.md](../CLAUDE.md)** — Project conventions and context

---

## Directory Structure

```
docs/
├── STATUS.md              ← Current status
├── getting-started/       ← Tutorials and onboarding
├── guides/                ← Task-oriented how-tos
├── concepts/              ← Deep architectural understanding
├── reference/             ← API & technical specs
├── plans/                 ← Design docs and implementation plans (historical)
└── contributing/          ← For contributors
```

---

## Quick Links

**Development:**
- [Adding Plugins](guides/adding-plugins.md)
- [Running Services](guides/running-services.md)
- [Testing](guides/testing.md)

**Architecture:**
- [Intelligence Tiers](concepts/intelligence-tiers.md)
- [Plugin System](concepts/plugin-architecture.md)
- [Data Pipeline](concepts/data-pipeline.md)

**Reference:**
- [All Plugins](reference/plugins/overview.md)
- [API Endpoints](reference/api/rest-endpoints.md)
- [Configuration](reference/configuration.md)

---

## External Links

- [Main Repository README](../README.md)
- [IBKR TWS API Docs](https://interactivebrokers.github.io/tws-api/)
- [TimescaleDB Docs](https://docs.timescale.com/)
- [DragonflyDB Docs](https://www.dragonflydb.io/docs/)
