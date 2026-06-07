# Intelligence Documentation Refactor

**Version:** 1.0.0
**Date:** 2026-05-28
**Status:** Spec Approved
**Author:** Lead Architect (Claude)
**Milestone:** v2.8 — Documentation Foundation

---

## Purpose

Refactor `docs/intelligence/` from 5 redundant docs (1842 lines, ~40% overlap) to 4 Renaissance-layered docs with clear orthogonal purposes. Eliminate redundancy, improve navigability, and align documentation with Renaissance principles.

---

## Current State Analysis

**Existing files:**
- `ai-intelligence-architecture.md` (408 lines) — Mix of principles, I1-I8 descriptions, service reference
- `ai-tech-stack.md` (619 lines) — Tech choices + current state + gaps + decision log
- `swarm-architecture.md` (287 lines) — Agent contract + graduation + philosophy
- `ai-intelligence-resources.md` (258 lines) — Usage examples + stream keys + schema reference
- `market-intelligence-strategy.md` (270 lines) — I1-I8 descriptions + DAG + quality framework

**Problems identified:**
1. AI provider chain explained in 4 different files
2. I1-I7 layer descriptions duplicated across 3 files
3. Service list appears in multiple docs
4. No clear entry point for "how do I add a plugin/agent?"
5. Deprecated patterns mentioned without clean separation
6. `ai-tech-stack.md` content belongs in `docs/ideas/`, not operational docs

---

## Target Structure

```
docs/intelligence/
├── intelligence-foundation.md   — WHY+WHAT
├── intelligence-plugins.md      — HOW (I1-I7)
├── intelligence-ai.md          — HOW (I8, swarm)
└── intelligence-operations.md  — OPS
```

**Four docs, each with orthogonal purpose:**

| Doc | Audience | Purpose | Key Sections |
|-----|----------|---------|--------------|
| `intelligence-foundation.md` | Architects + developers (onboarding) | Principles, I1-I8 definitions, data flow philosophy, schemas/topics | Renaissance principles, I1-I8 layer definitions, data flow diagram, IntelligenceEvent schema, stream keys, topic naming |
| `intelligence-plugins.md` | Developers (adding features) | Plugin protocol, how to add a plugin, examples | Plugin contract, registration, I1-I7 tier lists, wave system, DAG execution, examples |
| `intelligence-ai.md` | Developers (adding AI) | AI agent protocol, swarm, shadow governance | BaseAIAgent contract, LLM provider chain, swarm agents (skeptic, correlation, etc.), graduation, lineage, how to add an agent |
| `intelligence-operations.md` | Operators (running system) | Services, health, monitoring, debugging | Service DAG, metrics (Prometheus/OTel), latency breakdown, common issues, performance tuning |

---

## Content Migration Map

### intelligence-foundation.md (NEW)

**From `ai-intelligence-architecture.md`:**
- Renaissance principles section (determinism, DB-ignorance, regime-awareness, shadow-first)
- I1-I8 layer definitions and responsibilities
- Data flow diagram
- CIS & signal confidence pipeline overview

**From `market-intelligence-strategy.md`:**
- I1-I8 detailed descriptions (Pattern Analysis, SMC, Regime Classification, CTF, Signal Generation)
- Intelligence Processing Hierarchy table

**From `ai-intelligence-resources.md`:**
- Stream key conventions
- Topic naming rules

**New content:**
- `IntelligenceEvent` schema reference (core data contract)
- Topic list with descriptions
- Brief service DAG overview (deep details in operations.md)

### intelligence-plugins.md (NEW)

**From `ai-intelligence-architecture.md`:**
- Plugin system section
- Tier lists (I1-I7 counts verified from register_plugins.py)
- Plugin protocol summary

**From `market-intelligence-strategy.md`:**
- DAG Execution Model section
- Wave system explanation
- Sub-wave dependency resolution

**From `ai-intelligence-resources.md`:**
- Usage examples (stream keys, settings)

**New content:**
- Full plugin contract (inputs, outputs, registration)
- How to add a plugin (step-by-step)
- Example plugin skeleton
- Tier-specific guidance (I1 indicators vs I7 signals)

### intelligence-ai.md (NEW)

**From `swarm-architecture.md`:**
- Agent contract (mandatory attributes)
- Active agents table
- Separation of concerns (compute vs persistence)
- Graduation governance
- Swarm philosophy

**From `ai-intelligence-architecture.md`:**
- I8 AI Narrative Layer section
- Intelligence Swarm (async, out-of-band)
- Redpanda topics (narratives, llm.calls, signal_lineage)

**From `ai-intelligence-resources.md`:**
- LLM provider chain usage
- I8 functionality section
- LLM audit trail tables

**From `ai-tech-stack.md`:**
- LLM Provider Chain section (Ollama local)
- Agent Framework section (BaseAIAgent, BaseGroupCoordinator)
- Swarm Agents table

**New content:**
- How to add an AI agent (step-by-step)
- Example agent skeleton (referencing TEMPLATE_agent.py)
- `prompt_version` handling
- Lineage recording
- Shadow-first lifecycle

### intelligence-operations.md (NEW)

**From `ai-intelligence-architecture.md`:**
- Services Reference table
- Database Schema section

**From `swarm-architecture.md`:**
- Cost and capacity section
- Performance considerations

**From `ai-intelligence-resources.md`:**
- Performance considerations section
- Current latency breakdown

**From `ai-tech-stack.md`:**
- Observability section (OTel, Prometheus, Grafana)
- Data Flow — AI/ML Path

**New content:**
- Service DAG with health endpoints
- Key metrics to monitor
- Common debugging scenarios
- Performance bottlenecks (I2-I6 sequential)

### Deleted/Moved

**Deleted:**
- `ai-intelligence-resources.md` — Content absorbed into plugins.md and ai.md
- `market-intelligence-strategy.md` — Content absorbed into foundation.md and plugins.md

**Moved:**
- `ai-tech-stack.md` → `docs/ideas/tech-stack.md` — Consolidate with existing tech stack doc (tech choices belong in ideas, not operational reference)

**Renamed:**
- `ai-intelligence-architecture.md` → Content migrated, then deleted
- `swarm-architecture.md` → Content migrated, then deleted

---

## File Operations

```bash
# Create new files (empty)
docs/intelligence/intelligence-foundation.md
docs/intelligence/intelligence-plugins.md
docs/intelligence/intelligence-ai.md
docs/intelligence/intelligence-operations.md

# Move ai-tech-stack.md to ideas/
mv docs/intelligence/ai-tech-stack.md docs/ideas/

# After migration, delete old files
rm docs/intelligence/ai-intelligence-architecture.md
rm docs/intelligence/ai-intelligence-resources.md
rm docs/intelligence/market-intelligence-strategy.md
rm docs/intelligence/swarm-architecture.md
```

---

## Section Templates

Each doc follows this structure:

```markdown
# <Doc Name>

**Version:** 1.0.0
**Last Updated:** <date>
**Status:** current
**Milestone:** v2.8

---

## Purpose
<One sentence: what this doc covers, who it's for>

---

## Quick Reference
<Table or list of key concepts with line anchors>

---

## <Section 1>
...

---

## See Also
- Links to other intelligence docs
- Links to src/ code reference
- Links to relevant ideas/ docs
```

---

## Validation Criteria

Spec is complete when:

1. **No redundancy:** Each concept explained in ONE place only
2. **Clear entry points:** Reader knows which doc to open for their question
3. **Cross-references work:** All links resolve after migration
4. **No deprecated patterns:** Old component names removed or clearly marked historical
5. **Code references accurate:** All file paths, class names, functions verified against src/

---

## Implementation Notes

- Preserve all code examples and usage patterns
- Keep all version numbers and dates current
- Verify all `src/` file references exist
- Check all Prometheus metric names against `src/observability/metrics.py`
- Verify plugin counts against `src/intelligence/register_plugins.py`

---

## Success Metrics

- **Before:** 5 files, 1842 lines, ~40% redundancy
- **After:** 4 files, ~1400 lines (estimated), <5% redundancy
- **Navigability:** "How do I add X?" has ONE clear answer
- **Maintainability:** Provider change requires editing ONE file

---

## Related Documentation

- `docs/intelligence/CLAUDE.md` — Plugin protocol details (src/intelligence/)
- `src/intelligence/ai/AUTHORING.md` — Agent authoring protocol
- `docs/ideas/renaissance-alpha-pipeline.md` — Shadow-first statistical gates
- `docs/ideas/ai-02-ml-agent-architecture.md` — Multi-agent learning machine design
