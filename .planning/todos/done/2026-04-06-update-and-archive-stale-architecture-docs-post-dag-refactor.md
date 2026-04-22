---
created: 2026-04-06T19:07:04.842Z
title: Update and archive stale architecture docs post-DAG-refactor
area: docs
files:
  - docs/concepts/data-pipeline.md
  - docs/concepts/intelligence-tiers.md
  - docs/architecture/layered-architecture.md
  - docs/architecture/event-driven-indicator-system.md
  - docs/architecture/comprehensive-intelligence-architecture.md
  - docs/architecture/service-separation.md
---

## Problem

Six docs still reference pre-DAG-refactor service names (indicagent-data-provider,
indicagent-feature-compute, indicagent-signal-generator, etc.) and wrong metrics ports.
Discovered during audit that aligned CLAUDE.md, current-state.md, dag-topology.md,
observability.md, cheatsheet.md, running-services.md, and README.md (all now correct).

## Solution

**Update** (conceptually valid, just need service name/port fixes):
- `docs/concepts/data-pipeline.md` — pipeline flow still correct, old service names
- `docs/concepts/intelligence-tiers.md` — I1–I7 tier model unchanged, old service names
- `docs/architecture/layered-architecture.md` — layer model still valid, wrong ports (:9112, :9114)

**Archive** (superseded by current-state.md + dag-topology.md):
- `docs/architecture/event-driven-indicator-system.md` — describes pre-DAG monolith
- `docs/architecture/comprehensive-intelligence-architecture.md` — pre-v2.1 design spec
- `docs/architecture/service-separation.md` — describes refactor goal that already shipped

Authoritative references for correct current state: CLAUDE.md § Active Services,
docs/architecture/current-state.md, docs/architecture/dag-topology.md.
