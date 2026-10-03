# IndicAgent Intelligence Platform Documentation

**Version:** 3.0
**Status:** current
**Last Updated:** 2026-10-03

---

## Documentation Taxonomy

The docs use a **domain-first, recipe-card format**: each folder owns a specific domain, and each file answers one of four questions — WHY (design rationale), WHAT (contracts and data shapes), HOW (procedures), or WHERE (quick lookup). Files within a domain folder are named `<domain>-<role>.md` (e.g., `intelligence-foundation.md`, `signals-lifecycle.md`).

The `intelligence/` folder is the gold standard — its four core files (foundation, plugins, AI, operations) are each a distinct recipe card. New domain folders (`agents/`, `signals/`, `platform/`) follow the same pattern. Older folders (`foundation/`, `data/`, `operations/`, `reference/`) are stable but predate the recipe-card convention. `architecture/` is legacy — content migrates to domain folders over time. `concepts/` is the permanent home for cross-domain conceptual WHY docs; it is not a migration staging area.

Docs declare a `Status` (`draft`, `design`, `current`, `archived`; see `foundation/documentation-system.md` §6). Read it before citing a doc: much of the domain content below documents the archived v2.x pipeline.

---

## Working on the platform?

**→ [CLAUDE.md](../CLAUDE.md)** — Primary reference: architecture, commands, conventions, gotchas
**→ [Unified research-to-production design](plans/2026-09-26-unified-research-to-production-design.md)**: the governing design (adopted 2026-09-26, E18)
**→ [Roadmap](../.planning/ROADMAP.md)** — What's next
**→ [Ideas](ideas/)** — Research and strategy docs (living workspace)
**→ [AI Ideas Index](research/archive/ai-index.md)** — Standardized AI / ML / agentic idea cluster

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
| `apr-calibration-backlog.md` | APR calibration backlog |
| `instrument-data-model.md` | Base entity model for symbols — `instruments`/`instrument_metadata`/`instrument_annotations`/`instrument_tags`, how ITR and CVR attach on top |
| `instrument-tag-registry.md` | ITR full specification — instrument classification/exposure tags, TagCalibrator |
| `instrument-onboarding-sop.md` | Instrument onboarding SOP: source, select, classify, manifest, backfill, verify, promote |
| `controlled-vocabulary-registry.md` | CVR full specification — symbolic taxonomies, VocabularyService, drift auditor |
| `unified-concept-registry.md` | UCR full specification: recipe lifecycle, ConceptRegistryService; redesign as the recipe book adopted 2026-09-26 (phase 187) |
| `security-classification-hierarchy.md` | SCH: asset class > sector > industry group > industry, point-in-time and append-only (Layer 1 built in Phase 182) |
| `model-selection-principle.md` | Occam's Razor applied to model selection |
| `ship-or-sink-rules.md` | AI coding tool discipline — Ship or Sink rules |
| `musk-5-step-process.md` | Musk's 5-step design process: make requirements less dumb, delete, simplify, accelerate, automate |
| `renaissance-grade-standards.md` | Renaissance-grade standards |
| `performance-investigation-sop.md` | Performance and throughput investigation SOP |
| `timescaledb-compressed-column-migration.md` | TimescaleDB compressed-column migration pattern |
| `business-requirements.md` | IndicAgent business requirements |
| `v3-north-star.md` | v3.0 North Star: the intelligence-vectors concept (canonical for the North Star philosophy) |

### `intelligence/` — gold standard — I1-I8 domain

The reference implementation of the recipe-card format: four core recipe cards plus supporting references.
**Content status:** the I1-I7 plugin system these files document is ARCHIVED — no live consumer
as of 2026-07-02 (see root `CLAUDE.md`'s Architecture section). Format is still the gold
standard; the domain content itself is historical, not currently-running behavior.

| File | Description |
|------|-------------|
| `intelligence-foundation.md` | I1-I8 definitions, data flow philosophy, tier contracts (v2.x, ARCHIVED) |
| `intelligence-alphaengine.md` | IC-weighted factor model — vocabulary, methodology, and why the plugin approach was replaced (v3.0) |
| `intelligence-alphaengine-methodology.md` | IC measurement methodology (current, living reference) |
| `intelligence-plugins.md` | Plugin protocol, how to add a plugin, 132-plugin inventory |
| `intelligence-ai.md` | Swarm agents, LLM chain, shadow governance |
| `intelligence-operations.md` | Services, monitoring, debugging the intelligence pipeline |
| `intelligence-layer-architecture.md` | Layers vs. mechanisms in the intelligence layer (current) |
| `intelligence-alpha-frames-and-feature-lifecycle.md` | Feature lifecycle: data-quality governance of feature status (current) |
| `intelligence-hmm-observation-vector.md` | HMM observation vector design (5D vector) |
| `intelligence-performance.md` | Pipeline optimization strategy (stale, v2.x) |

### `agents/` — new (Phase 3) — Agent infrastructure domain

| File | Description |
|------|-------------|
| `agents-foundation.md` | Agent lifecycle, OTel signals, BaseAgent contract |
| `agents-operations.md` | Role taxonomy, DAG topology, service mesh |
| `agents-writers.md` | Writer agent patterns, DLQ, persistence contracts |

### `signals/` — new (Phase 3) — Signal domain

**Content status:** the Signal Ledger Architecture (SLA) these files document is ARCHIVED — no
live consumer as of 2026-07-02 (see root `CLAUDE.md`'s Data Flow section).

| File | Description |
|------|-------------|
| `signals-foundation.md` | Signal schema, entry types, status strings, schema versioning (pre-SLA; partially stale) |
| `signals-schema.md` | SLA table DDL — signal_events, trade_frames, trade_executions, signal_ledger view (v2.x, ARCHIVED) |
| `signals-ecl.md` | ECL system reference — vector fields, ML training patterns, boundary verification |
| `signals-lifecycle.md` | I7 signal creation, zone activation, MAE/MFE, outcome classification |
| `signals-operations.md` | Signal monitoring, shadow governance, graduation pipeline |
| `signals-confidence-patterns.md` | Setup confidence patterns (stale, v2.x) |
| `signal-trade-separation-ADR.md` | ADR: formal decision record for the 3-table SLA split |

### `platform/` — new (Phase 4) — Infrastructure + API + Observability domain

| File | Description |
|------|-------------|
| `platform-foundation.md` | WHY systemd/Docker split, L1-L10 DAG, container inventory, cascade failures |
| `platform-observability.md` | OTel SDK design, metric contracts, D-27 SLO alerts, circuit breaker |
| `platform-self-healing.md` | Self-healing architecture: watchdog, stall detection, circuit breaker, alerting (Phase 108) |
| `platform-api.md` | FastAPI architecture, SSE vs WebSocket rationale, health router prefix gotcha |
| `platform-config.md` | APR namespace registry |

### `data/` — stable — Data foundation domain

| File | Description |
|------|-------------|
| `data-foundation.md` | Reference data, instrument contracts, roll architecture |
| `data-provider.md` | Provider isolation, failover, IBKR dual streams |
| `data-pipeline.md` | Hot/warm/cold flow, Redpanda topics, consumer groups, TimescaleDB |
| `data-streaming.md` | Streaming patterns, topic naming, stream_keys.py |

### `operations/` — stable — Sysadmin HOW

Production procedures: deployment, monitoring, troubleshooting. Files carry an `operations-` prefix; several describe the archived v2.x pipeline and carry a staleness note, so check each Status line.

| File | Description |
|------|-------------|
| `operations-infrastructure.md` | Systemd, Docker, servers, deployment |
| `operations-database.md` | TimescaleDB operations (stale, v2.x) |
| `operations-observability.md` | Operational runbook: Grafana dashboards, PromQL patterns, troubleshooting |
| `operations-security.md` | Security architecture (not implemented; planned) |
| `operations-disaster-recovery.md` | DR procedures (table-specific backup examples carry a staleness note) |
| `operations-memory-performance.md` | Memory subsystem performance |
| `operations-i7-emission-gates.md` | I7 emission gates (stale, v2.x) |
| `operations-promotion-protocol.md` | Alpha promotion protocol, swarm (Path B) to kernel (Path A) (stale, v2.x) |

### `development/` — stable — Developer HOW

Local development procedures: setup, testing, profiling.

| File | Description |
|------|-------------|
| `setup.md` | New machine setup, environment, dependencies |
| `testing.md` | Unit/integration/e2e how-to |
| `profiling.md` | Performance profiling |
| `alerting.md` | Incident response runbook |

### `reference/` — stable — Quick lookup

Cheat sheets, gotchas, configuration, naming and documentation standards for fast lookup.

| File | Description |
|------|-------------|
| `cheatsheet.md` | Common commands and workflows |
| `gotchas.md` | Known pitfalls and solutions |
| `configuration.md` | Configuration reference |
| `db-maintenance.md` | Database maintenance runbook |
| `naming-conventions.md` | Naming conventions |
| `renaissance-naming-philosophy.md` | Extended rationale for the naming system (not the canonical spec; see `foundation/naming-system.md`) |
| `documentation-standards.md` | Documentation standards |
| `external-links.md` | External links and resources |

### `concepts/` — stable — Cross-domain conceptual library

WHY docs for concepts that span multiple domain folders. One concept per file: design rationale, what was rejected, failure modes. The permanent home for ideas too cross-cutting to live in a single domain folder.

| File | Description |
|------|-------------|
| `progressive-intelligence-extraction.md` | Raw market data holds no signal; it passes through sequential layers, each a prerequisite for the next, before an edge claim |
| `adaptive-intelligence.md` | Every component that influences a decision must earn that influence through statistical proof, and lose it when evidence degrades |
| `regime-awareness.md` | Market behavior is non-stationary, so predictive power is measured per regime |
| `evidence-graded-signals.md` | A signal requires agreement from multiple independent evidence sources |
| `extrinsic-confidence-layer.md` | Extrinsic market context is a feature to learn from, not a gate to filter on (stale, v2.x) |
| `event-driven-fabric.md` | Agents communicate only through named topics; no agent calls another directly |
| `hot-path-isolation.md` | Real-time compute never blocks on a database or network call |
| `temporal-data-architecture.md` | Every market event is a timestamped, immutable record |
| `incremental-computation.md` | Per-bar compute is bounded work, not O(full history) |
| `autonomous-resilience.md` | The system detects failures, routes around them, and recovers without human intervention |
| `observability-and-traceability.md` | Every decision is measurable, attributable, and auditable |
| `dag-execution.md` | Declared dependencies plus a topological sort derive execution order (Service DAG level current; plugin DAG level historical) |
| `signal-ledger-architecture.md` | Three concerns, three tables, one unbiased training set (implementation archived, principle live) |
| `plugin-composability.md` | Intelligence composed entirely of plugins (implementation archived, pattern superseded) |
| `swarm-intelligence.md` | Specialist agents each assess one dimension and compose into a calibrated multiplier (design; dormant-pending-design) |

### `architecture/` — legacy — Cross-cutting design docs

System design docs that predate the domain-folder taxonomy. Files carry an `architecture-` prefix and most describe the dormant v2.x pipeline, so read each Status line before citing one. The canonical truth registry and design principles now live in `foundation/`.

| File | Description |
|------|-------------|
| `architecture-overview.md` | Architecture overview (draft, staleness-quarantined 2026-08-11) |
| `architecture-dag-topology.md` | DAG topology and methodology for the v2.x intelligence pipeline (historical / future-revival reference) |
| `architecture-evolution.md` | v2.8 historical architecture snapshot of the archived v2.x I1-I7 pipeline |
| `architecture-v2-event-driven-pipeline.md` | V2 event-driven real-time pipeline, architecture generation 1 (built, dormant) |
| `architecture-v3-alphaengine-pipeline.md` | V3.0 statistical IC-discovery architecture, generation 2 (status as of 2026-08-05; predates the v3.5 unified design) |

### `plans/` — Design specs, preregistrations and implementation plans

Design documents, preregistrations and phase implementation plans (living workspace). New design specs go here, named `YYYY-MM-DD-<topic>-design.md`. Docs may be filename-stable (edited in place); check for a stale dated fork of an undated doc before citing either. `archive/` holds superseded plans.

### `superpowers/` — Earlier specs and plans (legacy location)

Eleven specs and plans written July to September 2026 under the brainstorming tool's default location. They stay put because completed todos, milestone records, source comments and a migration cite them by path; new design docs use `plans/`.

### `research/` — Research notes and verdict records

Research documents, verdict records (for example `construction-verdict-ledger.md`) and design explorations. Docs may be filename-stable (edited in place). `archive/` holds superseded and historical research.

### `analysis/` — Analysis outputs

Outputs and reports from past measurements (for example BIC k selection, IC discovery report, corpus feature audit, crowding proxy report).

### `ideas/` — Research workspace

Research, strategy, and architecture analysis (living workspace). `from-ssfi/` holds ideas imported from the sibling ssfi project; many of their internal references point at that project's docs.

### `renaissance-rigor-playbook/` — Portable playbook

A portable extraction of the institutional-rigor foundation docs with project-specific content replaced by generics, plus a `CLAUDE.md.template`. Intentionally differs from `foundation/`; see its own `README.md`.

---

## External Links

- [TimescaleDB Docs](https://docs.timescale.com/)
- [Redpanda Docs](https://docs.redpanda.com/)
- [IBKR TWS API Docs](https://interactivebrokers.github.io/tws-api/)
