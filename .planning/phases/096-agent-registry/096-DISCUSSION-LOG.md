# Phase 096: Agent Registry - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-01
**Phase:** 096-agent-registry
**Areas discussed:** Class Discovery, YAML Structure, MLEvaluator Exception, Scope

---

## Class Discovery

| Option | Description | Selected |
|--------|-------------|----------|
| Import path in YAML | `class: src.intelligence.ai.alpha.skeptic.SkepticEvaluator` in each entry. Explicit but fragile to refactoring. | |
| Registry decorator | `@register_agent('skeptic_evaluator')` on each class. Python-idiomatic. | |
| Auto-scan by agent_id | `__init_subclass__` self-registration + explicit `AGENT_MODULES` import list. | ✓ |

**User's choice:** Auto-scan by agent_id — "most Renaissance"

**Notes:** User consistently invoked Renaissance/Jim Simons standard throughout. Extended discussion on what Simons would demand: explicit import list (like `TIER_I7` in `register_plugins.py`) + `__init_subclass__` self-registration = explicit at the enumeration level, automatic at the registration level. `_REGISTRY` is immutable after startup. Fail-fast: `RegistryError` with full known-IDs list if `agent_id` not found. Pydantic for YAML schema validation.

---

## YAML Structure

| Option | Description | Selected |
|--------|-------------|----------|
| `config/agents.yaml` — flat list | Single flat list with `group:` field per entry. | |
| `config/agents.yaml` — per-group sections | Top-level `alpha:`, `narrative:`, `risk:` sections. | ✓ |
| `src/config/agents.yaml` | Co-located with `settings.py`. | |

**User's choice:** Per-group sections at `config/agents.yaml`

**Notes:** User indicated this is "foundational base agent logic/functionality" — bigger than just swarm config. Per-group sections mirror DAG topology, match operational mental model ("look under alpha: to see alpha evaluators"). Required fields: `agent_id` only. Optional fields fall back to class defaults. `shadow_only: false` in YAML is rejected — `shadow_registry` DB has final authority per ROADMAP success criteria #4.

---

## MLEvaluator Exception

| Option | Description | Selected |
|--------|-------------|----------|
| Normalize BaseAIWorker constructor | `BaseAIWorker.__init__(llm_chain=None, pool=None, **kwargs)` | |
| `SwarmDeps` dependency container | Typed dataclass with all available deps. Registry passes one object. | ✓ |
| `constructor_type` field in YAML | `constructor_type: llm_chain \| pool \| none` in AgentSpec. | |

**User's choice:** `SwarmDeps` dependency container

**Notes:** User invoked Renaissance/Simons standard. Council ruling: `**kwargs` is a type hole — silent failure on mismatched arguments. `SwarmDeps(llm_chain, pool, settings)` is typed, testable, and extensible. When Phase 097 adds `memory_client`, it's added to `SwarmDeps` once with no constructor changes across agents. `BaseAIWorker.__init__(self, *, deps: SwarmDeps)` is the new signature.

---

## Scope / Swarm Coverage

| Option | Description | Selected |
|--------|-------------|----------|
| AlphaSwarm + NarrativeSwarm | Both hardcode construction today; both should be registry-driven. | |
| AlphaSwarm only | NarrativeSwarm is simpler; leave for later phases. | |
| All BaseSwarmCoordinator subclasses + future-proof hook | Alpha + Narrative + risk scaffolding + automatic base-class integration. | ✓ |

**User's choice:** All BaseSwarmCoordinator subclasses + future-proof hook

**Notes:** "This is foundational." Council ruling: two parallel construction patterns in the same codebase = technical debt on day one. `BaseSwarmCoordinator._setup()` calls `AgentRegistry.build()` automatically (Template Method Pattern) — structural enforcement, not convention. Risk group scaffolded but no agents implemented. Extensibility hook: any new `BaseSwarmCoordinator` subclass gets agents from YAML automatically.

---

## Claude's Discretion

- `SwarmDeps` module location (`src/core/ai/` recommended — Ring 0 infrastructure)
- `AGENT_MODULES` as Python list vs. YAML section (Python list recommended — type-checked)
- Exact Pydantic model structure for `AgentSpec`
- YAML parsing library (`PyYAML` vs `ruamel.yaml`)

## Deferred Ideas

- Hot-reload without restart — file watcher complexity not worth it for passion project
- Risk group agent implementations — scaffolding only in Phase 096
- YAML validation CLI tool — nice-to-have, not in Phase 096 scope
