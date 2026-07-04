# IndicAgent Concepts Library — Design Spec

**Version:** 1.0
**Date:** 2026-05-29
**Status:** Spec Approved
**Author:** Lead Architect (Claude)

---

## Purpose

Elevate `docs/concepts/` from a mixed-level documentation folder into a Renaissance-grade knowledge library — reusable intellectual artifacts that capture the *why* behind every architectural decision. Each doc is a research note that could seed a new system design from scratch.

**Distinction from domain docs:**

| `docs/concepts/` | `docs/intelligence/`, `docs/agents/`, etc. |
|-----------------|-------------------------------------------|
| What is this concept, why it exists, mathematical/systems rationale | How to implement, operate, extend, debug |
| System-agnostic recipe — works for any future system | IndicAgent-specific reference |
| Written for a brilliant new hire or outside quant | Written for a developer working in the codebase |
| Stable — concepts don't change when code changes | Updated when implementation changes |

---

## Intellectual Hierarchy

The library is structured in four layers. Foundational concepts must be understood before derived ones. A new engineer reads top-down; someone designing a new system uses the recipes at any layer.

```
Layer 1 — System Architecture       (foundations everything else rests on)
Layer 2 — Intelligence Design        (how you build a smart system on that foundation)
Layer 3 — Trust and Quality          (how you know it's right)
Layer 4 — Operational Excellence     (how you run it reliably at scale)
```

---

## Canonical Concept List

### Layer 1 — System Architecture

| Doc | Core idea |
|-----|-----------|
| `hot-path-isolation.md` | Real-time compute never touches storage — decouples latency from I/O |
| `event-driven-fabric.md` | Agents decouple through topics, never direct calls — enables independent scaling and restart |
| `incremental-computation.md` | O(1) per-bar updates via stateful plugins — not recomputed from scratch each tick |
| `temporal-data-architecture.md` | Time-series native storage; every event timestamped, nothing dropped, TimescaleDB compression |

### Layer 2 — Intelligence Design

| Doc | Core idea |
|-----|-----------|
| `progressive-intelligence-extraction.md` | Raw market data → actionable intelligence through 8 increasingly sophisticated tiers (I1-I8) |
| `plugin-composability.md` | Intelligence as independently-testable units with declared I/O dependencies — the shell is empty |
| `dag-execution.md` | Topological ordering (Kahn's algorithm) derives parallelism from the dependency graph automatically |
| `regime-awareness.md` | Signals conditioned on regime, not absolute thresholds — a rule that works globally is weaker than one that works in a regime |

### Layer 3 — Trust and Quality

| Doc | Core idea |
|-----|-----------|
| `evidence-graded-signals.md` | Multi-dimensional confirmation before any signal fires; CIS requires 3 of 6 independent buckets |
| `adaptive-intelligence.md` | Statistical gates for promotion; the system earns the right to act through proof, not configuration |
| `swarm-intelligence.md` | Mixture of expert agents for AI-level synthesis; no single LLM call makes a decision |

### Layer 4 — Operational Excellence

| Doc | Core idea |
|-----|-----------|
| `observability-and-traceability.md` | Every decision auditable end-to-end; OTel as infrastructure not afterthought |
| `autonomous-resilience.md` | The system detects and corrects its own failures without human intervention |

---

## Document Structure (Recipe Card Format)

Every concept doc follows this exact structure. Sections scaled to complexity — brief where the concept is simple, deeper where nuance matters.

```markdown
# Concept Name
> One sentence: the irreducible definition of this concept

## The Problem It Solves
What goes wrong without this concept. Concrete failure mode.

## The Principle
Abstract definition. Mathematical or systems rationale where applicable.
System-agnostic — no IndicAgent-specific code.

## How IndicAgent Applies It
Specific design choices. Links to domain docs for implementation detail.
What's shipped vs. what's roadmap.

## Invariants
The laws derived from this concept. If violated, the concept breaks.
Written as hard rules: "X must never Y."

## Recipe
Decision checklist for someone building a new system.
Not IndicAgent instructions — transferable design questions.

## See Also
Links to domain docs (implementation), ideas/ (research depth), related concepts.
```

---

## Part A — Rescue Pass (Prerequisite)

Before any concepts/ file is rewritten or deleted, implementation detail not yet captured in domain docs must be migrated. Nothing is lost.

| Source file | Content to rescue | Destination |
|-------------|------------------|-------------|
| `cis-scoring.md` | Two-system adaptive weights composition (CIS bucket weights vs. setup performance weights), exact `perf_multiplier` formula (`0.5 + ((n-1-rank)/n)`), full six-layer calibration chain detail | `intelligence-foundation.md` — CIS section |
| `plugin-architecture.md` | Reliability & error handling patterns, performance characteristics table | `intelligence-plugins.md` + `intelligence-operations.md` |
| `evolvable-ai.md` | Existing infrastructure inventory: `shadow_registry`, `LineageRecorder`, `llm_calls` audit trail, skeptic adversarial pattern, `BaseAIAgent` genome substrate | `intelligence-ai.md` — eAI substrate section |
| `tier-naming-system.md` | Full file — naming convention reference, not a concept | `docs/foundation/naming-conventions.md` (append or merge) |

---

## Part B — Concepts Library Rebuild

### Rewrites (8 files)

Files renamed to concept-level names. Old filenames deleted after rewrite committed.

| Old filename | New filename | Key change |
|-------------|-------------|------------|
| `intelligence-tiers.md` | `progressive-intelligence-extraction.md` | Strip implementation detail (stream keys, code org, plugin counts) → rescue to intelligence-foundation.md; rewrite at concept level |
| `plugin-architecture.md` | `plugin-composability.md` | Strip 132-plugin registry, DAG engine implementation → already in intelligence-plugins.md; rewrite around composability principle |
| `cis-scoring.md` | `evidence-graded-signals.md` | Strip calibration formulas → rescue to intelligence-foundation.md; rewrite around statistical confirmation principle |
| `evolvable-ai.md` | `adaptive-intelligence.md` | Expand scope: shadow governance + signal graduation + weight learning + eAI as unified "earn the right" pattern; absorbs `shadow-first-validation` concept |
| `dag-execution.md` | keep name | Strip implementation details of Kahn's algorithm code → rescue to intelligence-plugins.md; keep graph theory rationale and recipe |
| `incremental-computation.md` | keep name | Largely at right level already; minor strip of state lifecycle implementation detail |
| `regime-classification.md` | `regime-awareness.md` | Rename reflects concept not implementation; strip per-plugin implementation detail |
| `swarm-intelligence.md` | keep name | Strip BaseAIAgent/BaseGroupCoordinator API detail → already in intelligence-ai.md; keep MoA rationale and recipe |

### New Docs (5 files, written from scratch)

| File | Primary sources to draw from |
|------|------------------------------|
| `hot-path-isolation.md` | `docs/architecture/overview.md`, CLAUDE.md hot/warm/cold data flow, `intelligence-foundation.md` data flow |
| `event-driven-fabric.md` | `docs/data/data-streaming.md`, `docs/agents/agents-foundation.md`, CLAUDE.md Kafka rules |
| `temporal-data-architecture.md` | `docs/operations/timescaledb-gotchas.md`, CLAUDE.md table definitions, `docs/data/data-foundation.md` |
| `observability-and-traceability.md` | `docs/platform/platform-observability.md`, OTel contract in CLAUDE.md (D-04, D-06, D-27), `llm_calls` audit trail |
| `autonomous-resilience.md` | `docs/architecture/self-healing.md`, `docs/agents/agents-operations.md`, Phase 108 SOP (HEAL-01/03/04), circuit breaker patterns |

Total after rebuild: **13 concept docs + updated README**.

### `docs/concepts/README.md`

Rewritten as a library index: four-layer structure visible at a glance, one-line description per doc, explicit reading order for a new engineer vs. a system designer.

---

## Validation Criteria

The rebuild is complete when:

1. **No implementation detail in concepts/** — every code path, formula, or class name lives in a domain doc, not here
2. **No redundancy** — each concept explained in one place only; concepts/ links out, doesn't duplicate
3. **Invariants present in every doc** — each file has at least 2 hard rules
4. **Recipe is transferable** — the Recipe section reads as system-agnostic; no IndicAgent-specific instructions
5. **Rescue complete** — all four Part A migrations committed before any concepts/ file is deleted
6. **Layer hierarchy navigable** — README makes the four-layer structure immediately clear

---

## Success Metrics

- **Before:** 9 concept docs at mixed abstraction levels, significant overlap with domain docs, no intellectual hierarchy
- **After:** 13 concept docs in four explicit layers, zero implementation detail, usable as recipe cards for new system design
- **New hire test:** A senior quant with no IndicAgent context reads Layer 1 docs and can reconstruct the core architectural decisions
- **Recipe test:** Someone building a different algorithmic trading system can take any concept doc and apply it

---

## Related

- `docs/architecture/` cleanup (Part 1 — separate phase): `overview.md`, `layered-architecture.md`, `current-state.md`, `principles.md`, `canonical-truth-registry.md` remain; 6 files migrate to domain folders
- `docs/concepts/README.md` — will be rewritten as part of this work
- `docs/foundation/naming-conventions.md` — receives `tier-naming-system.md` content
