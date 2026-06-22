---
created: 2026-05-03T19:00:00.000Z
title: "Quant Pipeline Modularization (P-QUANT-01)"
area: architecture
priority: 4
resolves_phase: 88
tier: refactoring
files:
  - docs/plans/2026-05-02-unified-intelligence-design.md
  - src/intelligence/
---

# Quant Pipeline Modularization (P-QUANT-01)

**Filed:** 2026-05-03
**Priority:** Medium
**Prerequisite:** None — independent of qualitative work

## Problem

From the unified intelligence design: `IntelligencePipelineComputeAgent` is a monolithic service. To support the multi-domain intelligence fabric, the indicator logic should be a versioned library that can be consumed independently of the service runtime.

## Solution

1. **Decouple intelligence logic** into a versioned library: `src/intelligence/indicators/vN/`
2. **Ensure full test coverage** of isolated indicator logic (separate from service integration tests)
3. **Keep the service as a thin orchestration layer** that calls the versioned library

### Why this matters for qualitative work

The unified intelligence design requires that "each domain must remain independently runnable." Modularizing the quant pipeline makes it a library that other domains can consume without depending on the service runtime.

## Context

Implementation plan: `docs/plans/2026-05-02-unified-intelligence-design.md` (Phase 1: P-QUANT-01)

---
**RETIRED 2026-06-22** — v3.0 Feature Factory (`src/intelligence/feature_factory.py`) is the modularization: 54 pure functions, fully decoupled from service runtime, no plugin registry. The versioned library concept is realized via `FEATURE_FACTORY_VERSION`. `docs/plans/2026-05-02-unified-intelligence-design.md` is superseded.
