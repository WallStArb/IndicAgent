# Phase 096: Agent Registry - Context

**Gathered:** 2026-06-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace hardcoded agent construction in `AlphaSwarm._setup()` and `NarrativeSwarm._setup()` with a YAML-driven `AgentRegistry` that covers all `BaseGroupCoordinator` subclasses. Operators edit `config/agents.yaml` and restart the service to add or reconfigure agents — no Python file changes, no deployment, no code review required.

**In scope:**
- `config/agents.yaml` — the operator manifest (per-group sections: `alpha:`, `narrative:`, `risk:`)
- `AgentSpec(BaseModel)` — Pydantic validation of each YAML entry; fail-fast on missing/invalid fields
- `AgentRegistry` — reads `agents.yaml`, resolves classes via `__init_subclass__` self-registration, constructs instances via `AgentDependencies`
- `AgentDependencies` dataclass — typed dependency container (`llm_chain`, `pool`, `settings`) replacing loose constructor kwargs
- `AGENT_MODULES` explicit import list in `src/intelligence/ai/register_agents.py` — deterministic, enumerated, no filesystem scanning
- `BaseGroupCoordinator._setup()` — calls `self._agents = AgentRegistry.build(self.group, self._agent_dependencies)` automatically; all subclasses inherit
- Wiring for `AlphaSwarm`, `NarrativeSwarm`, and `risk` group scaffolding
- `shadow_registry` auto-enrollment remains at startup (DB is live state, YAML is intent)
- Validation gate: registry validates all `agent_id` values before `_run()` begins

**Out of scope:**
- Hot-reload without restart (systemd restart is the deployment mechanism)
- DSPy prompt optimization (Phase 098)
- Zep episodic memory injection into `AgentDependencies` (Phase 097 adds `memory_client`)
- New agent implementations — registry is the infrastructure; agents are added separately

</domain>

<decisions>
## Implementation Decisions

### D-01: Class Discovery — `__init_subclass__` + Explicit Import List
**Mechanism:** `BaseAIWorker.__init_subclass__` hook populates a module-level `_REGISTRY: dict[str, type[BaseAIWorker]]` keyed by `agent_id` class attribute. No decorator needed — every class that inherits `BaseAIWorker` self-registers automatically.

**Determinism:** An explicit `AGENT_MODULES` list in `src/intelligence/ai/register_agents.py` (analogous to `TIER_I7` in `register_plugins.py`) enumerates exactly which modules are imported at startup. No filesystem scanning. Adding a new agent class = add it to `AGENT_MODULES`.

**Fail-fast:** `AgentRegistry.get(agent_id)` raises `RegistryError` with the full list of known IDs if the agent_id is not in `_REGISTRY`. Service never enters `_run()` with an unknown agent.

### D-02: YAML Schema — Per-Group Sections, Class Defaults as Fallback
**Location:** `config/agents.yaml` at project root.

**Structure:** Top-level keys mirror DAG groups (`alpha:`, `narrative:`, `risk:`). Each group contains a list of agent entries. The `group` field is NOT in individual entries — it is inferred from the section key.

**Required fields:** `agent_id` only (identity — no inference possible).

**Optional fields (fall back to class attribute when absent):**
- `shadow_only` — default: class attr (always `True` for new agents). YAML can set `True` but **cannot force `False`** — `shadow_registry` DB has final authority.
- `latency_budget_ms` — default: class attr (operational tuning).
- `prompt_version` — default: class `ACTIVE_VERSION` (YAML override = explicit A/B test pinning).
- `model_override` — default: `OLLAMA_MODEL` env var (uncommon per-agent override).

**Example:**
```yaml
alpha:
  - agent_id: skeptic_v1
  - agent_id: correlation_v1
    latency_budget_ms: 2000
  - agent_id: ml_scorer_v1
    shadow_only: true

narrative:
  - agent_id: narrative_synthesizer_v1
```

### D-03: Dependency Injection — `AgentDependencies` Dataclass
**Problem:** `MLEvaluator.__init__` requires `pool: asyncpg.Pool`; all LLM evaluators require `llm_chain: LLMChain`. This is a constructor inconsistency that cannot be absorbed cleanly by `**kwargs` (type hole, silent failure).

**Solution:** `AgentDependencies` dataclass — a typed dependency container:
```python
@dataclass
class AgentDependencies:
    llm_chain: LLMChain | None
    pool: asyncpg.Pool | None
    settings: Settings
```

`AgentRegistry.build()` accepts `AgentDependencies`. Each agent's `__init__` takes `dependencies: AgentDependencies` and reads what it needs. `mypy` catches misuse at type-check time. When Phase 097 adds `memory_client`, it's added to `AgentDependencies` once — no constructor changes needed across agents.

**`BaseAIWorker.__init__` signature change:** `(self, *, dependencies: AgentDependencies)` — replacing current `(self, llm_chain=None, pool=None, **kwargs)` pattern.

### D-04: Registry Integration into `BaseGroupCoordinator` — Template Method Pattern
`BaseGroupCoordinator._setup()` calls `self._agents = AgentRegistry.build(self.group, self._agent_dependencies)` automatically after infrastructure setup. Subclasses do not call this explicitly — it is structurally enforced by the base class. Adding a new `BaseGroupCoordinator` subclass = agents auto-populate from YAML; no registry wiring required.

The base class holds `self._agent_dependencies: AgentDependencies` built from `self._llm_chain` and `self._pool` after they are initialized.

### D-05: Shadow Registry — DB is Authority, YAML is Intent
`agents.yaml` expresses intent. `shadow_registry` holds live state. At startup, after `AgentRegistry.build()` populates `self._agents`, the existing `_shadow_registry_ensure_agents()` call enrolls new agents (idempotent). The DB `is_shadow` value is the authoritative gate — not the YAML `shadow_only` field. YAML `shadow_only: false` is rejected by `AgentSpec` validation (or silently treated as `true`) to prevent operators from bypassing the statistical gate.

### D-06: Validation Gate — Fail Before First Bar
`AgentRegistry.validate(group, spec_list)` runs synchronously before `_run()` begins. Checks:
1. All `agent_id` values exist in `_REGISTRY`
2. All required Pydantic fields are present and typed correctly
3. At least one agent is defined for the group

If any check fails: `RegistryConfigError` with the offending field, YAML line reference, and the full list of registered agent IDs. The service does not start.

### Claude's Discretion
- Whether `AgentDependencies` lives in `src/core/ai/` or `src/intelligence/ai/` (recommend `src/core/ai/` — it is Ring 0 infrastructure)
- Whether `AGENT_MODULES` is a Python list in `register_agents.py` or a YAML section in `agents.yaml` (recommend Python list — type-checked, importable)
- Exact Pydantic model structure for `AgentSpec` (field validators, alias handling)
- How `config/agents.yaml` is read — `PyYAML` or `ruamel.yaml` (both are available; `PyYAML` is simpler)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Agent Infrastructure
- `src/core/ai/base_agent.py` — `BaseAIWorker` class attributes, `__init__` signature, `_llm_generate()` contract
- `src/core/ai/evaluator.py` — `Evaluator` abstract base (what `AlphaSwarm` agents inherit)
- `src/intelligence/ai/group_coordinator.py` — `BaseGroupCoordinator` lifecycle, `_setup()`, `_shadow_registry_ensure_agents()`
- `src/intelligence/ai/AUTHORING.md` — agent authoring protocol, required class attributes

### Current Agent Construction (to be replaced)
- `services/alpha_swarm.py:165` — hardcoded `self._agents = [SkepticEvaluator(...), ...]` in `_setup()` — this is the pattern to eliminate
- `services/narrative_swarm.py:70` — `self._narrative_agent = NarrativeSynthesizer(...)` — also to be registry-driven

### Agent Classes (to be registered)
- `src/intelligence/ai/alpha/skeptic_agent.py`
- `src/intelligence/ai/alpha/correlation_agent.py`
- `src/intelligence/ai/alpha/regime_coherence_agent.py`
- `src/intelligence/ai/alpha/counterfactual_agent.py`
- `src/intelligence/ai/alpha/ml_scorer_agent.py` — uses `pool` dep (not `llm_chain`)
- `src/intelligence/ai/narrative/narrative_agent.py`
- `src/intelligence/ai/TEMPLATE.py` — reference implementation for new agents

### Shadow Registry
- `src/intelligence/register_plugins.py:645` — `shadow_registry_ensure()` — the enrollment function; same pattern applies to agents
- `src/intelligence/pipeline/cache_manager.py:523` — how `shadow_registry` is read back at runtime

### Configuration and Settings
- `src/config/settings.py` — `Settings` class (part of `AgentDependencies`)
- `docs/foundation/naming-system.md` — Ring 0/1/2 vocabulary; `AgentDependencies` belongs in Ring 0

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `TIER_I7` list in `src/intelligence/register_plugins.py` — exact pattern to replicate for `AGENT_MODULES`; explicit enumeration, fail-fast on missing import
- `shadow_registry_ensure()` in `register_plugins.py:645` — idempotent enrollment; reuse directly for agent enrollment
- `_shadow_registry_ensure_agents()` in `group_coordinator.py` — already iterates `self._agents` and enrolls; keep this, just call it after registry-built agents list

### Established Patterns
- `BaseAIWorker` class attributes (`agent_id`, `shadow_only`, `latency_budget_ms`, `prompt_version`, `group`) — these map directly to `AgentSpec` fields
- `register_plugins.py` explicit list pattern — no magic discovery; enumerate what exists
- `_apply_shadow_mode_config()` in `MLEvaluator` — existing config-DB shadow override; must still work after registry wiring

### Integration Points
- `BaseGroupCoordinator._setup()` in `group_coordinator.py` — the injection point for `AgentRegistry.build()` call
- `AlphaSwarm._setup()` — `super()._setup()` must complete (sets `self._llm_chain`, `self._pool`) before agents are built; `AgentDependencies` is constructed from these post-super values
- `shadow_registry` DB table — `component_name = agent_id`, `component_type = "swarm_agent"`, `is_shadow` is the live gate

</code_context>

<specifics>
## Specific Ideas

- **Renaissance design philosophy applied throughout:** model (Python class) / parameters (YAML) / live state (shadow_registry DB) are three distinct layers that never bleed into each other.
- **`AgentSpec` should use `model_config = ConfigDict(extra='forbid')`** — Pydantic strict mode; unknown YAML fields are errors, not silently ignored.
- **`_REGISTRY` is frozen after import-time** — no dynamic registration after `register_agents.py` runs. The registry is built once at module load, then read-only.
- **Phase 097 extensibility hook:** `AgentDependencies` is designed to accept `memory_client: ZepMemoryClient | None = None` with no agent constructor changes when Phase 097 ships.

</specifics>

<deferred>
## Deferred Ideas

- **Hot-reload without restart** — SIGTERM+restart is the existing deployment mechanism; live YAML reload would require a file watcher and careful agent teardown. Not worth the complexity for a passion project.
- **Risk group agents** — Phase 096 scaffolds the `risk:` YAML section and `risk` registry path but does not implement any risk agents (none exist yet).
- **YAML validation CLI tool** — `python -m src.intelligence.ai.registry validate config/agents.yaml` for operators to pre-check before restart. Nice-to-have; not in Phase 096 scope.

</deferred>

---

*Phase: 096-agent-registry*
*Context gathered: 2026-06-01*
