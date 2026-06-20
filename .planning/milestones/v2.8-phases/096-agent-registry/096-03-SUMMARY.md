# Phase 096-03 Summary: End-to-end Registry Wiring

**Status:** COMPLETE 2026-06-03

## Objectives
Wire the registry end to end: create the AGENT_MODULES explicit import list, write config/agents.yaml with verified agent_ids, build agents inside BaseGroupCoordinator._setup() via AgentRegistry.build(), apply authoritative shadow_registry DB state to each built agent, hard-fail on empty active groups, and remove hardcoded agent construction from AlphaSwarm and NarrativeSwarm.

## Changes Made

### Task 1: Create register_agents.py and config/agents.yaml (COMPLETED)

**Created `src/intelligence/ai/register_agents.py`:**
- `AGENT_MODULES` list with 6 agent module paths (5 alpha + 1 narrative)
- `_import_all()` function for lazy import inside _setup()
- Module docstring explaining the add-agent workflow

**Created `config/agents.yaml`:**
- `alpha:` section with 5 agents: skeptic, correlation_v1, regime_coherence_v1, counterfactual_v1, ml_scorer_v1 (with shadow_only: true)
- `narrative:` section with 1 agent: narrative_v1
- `risk: []` (scaffolded, empty)

Verification: All agent_ids resolve in _REGISTRY after _import_all()

### Task 2: Wire AgentRegistry.build into BaseGroupCoordinator._setup (COMPLETED)

**Modified `src/intelligence/ai/group_coordinator.py`:**

__init__ changes (lines 83-84):
- Added `self._agents: list[BaseAIWorker] = []`
- Added `self._agent_dependencies: Any | None = None`

_setup changes (lines 149-188):
- Added lazy imports: `_import_all`, `AgentRegistry`, `RegistryConfigError`, `AgentDependencies`
- Call `_import_all()` to trigger agent class registration
- Build `AgentDependencies(llm_chain=..., pool=..., settings=...)`
- Call `AgentRegistry.build(self.group_id, self._agent_dependencies)` to populate self._agents
- Empty-active-group guard: raise RegistryConfigError if self._agents is empty (only 'risk' group may be empty)
- Call `await self._shadow_registry_ensure_agents(self._agents)` to enroll in DB
- Call `await self._apply_shadow_registry_state(self._agents)` to apply authoritative DB state
- Lineage loop now iterates `self._agents` (built list) instead of `self.agents` (abstract property)

### Task 3: Remove Hardcoded Agent Construction from Swarm Services (COMPLETED)

**Modified `services/alpha_swarm.py`:**
- Removed imports: SkepticEvaluator, CorrelationAnalyzer, RegimeCoherenceAnalyzer, CounterfactualEvaluator
- Kept MLEvaluator import (needed for isinstance lookup)
- Replaced hardcoded `self._agents = [...]` with type-based lookup:
  ```python
  ml = next((a for a in self._agents if isinstance(a, MLEvaluator)), None)
  if ml is not None:
      await ml._setup_models()
  ```
- Kept semaphore setup, config propagation loop, SIGUSR1 handler
- Removed duplicate `await self._shadow_registry_ensure_agents(self._agents)` (base class owns enrollment)

**Modified `services/narrative_swarm.py`:**
- Replaced `self._narrative_agent = NarrativeSynthesizer(llm_chain=...)` with:
  ```python
  self._narrative_agent = next(
      (a for a in self._agents if isinstance(a, NarrativeSynthesizer)), None
  )
  ```
- Changed `agents` property to return `self._agents` instead of `[self._narrative_agent] if ...`
- Kept NarrativeSynthesizer import for isinstance lookup AND class-level `_NARRATIVE_TFS` gate
- Removed duplicate shadow_registry enrollment

**Modified `tests/unit/services/test_alpha_swarm.py`:**
- Updated `test_swarm_agents_are_four_typed_agents` to verify registry-driven path instead of hardcoded imports

### Task 4: Apply Authoritative shadow_registry DB State (COMPLETED)

**Added `_apply_shadow_registry_state()` method to BaseGroupCoordinator:**
- Runs `SELECT component_name, is_shadow FROM shadow_registry WHERE component_type = 'swarm_agent'`
- Builds state dict and applies to each agent: `agent.shadow_only = state[agent.agent_id]`
- **Fails closed**: raises RuntimeError if agent has no shadow_registry row after enrollment
- **Fails closed**: re-raises on any DB read error (never swallows and continues at class default)
- Logs `shadow_state_applied` with resolved {agent_id: shadow_only} mapping for audit

Called from _setup AFTER enrollment, before lineage loop and super()._setup().

## Verification

- 1150 unit tests pass (9.49s)
- `AgentRegistry.build('alpha', deps)` returns exactly 5 agents
- `AgentRegistry.build('narrative', deps)` returns exactly 1 agent
- `AgentRegistry.build('risk', deps)` returns 0 agents (empty group allowed)
- No hardcoded agent construction in swarm services
- _apply_shadow_registry_state verified with SELECT query and fail-closed guards

## Success Criteria Met

- **AGENT-REG-01**: Reconfiguring an existing agent is YAML-only (edit agents.yaml + restart). Adding a new agent requires one AGENT_MODULES line + one YAML entry — no swarm-service or coordinator code changes.
- **AGENT-REG-02**: AgentRegistry.build is the sole swarm-startup construction path. No swarm service constructs an agent class directly. The narrative API route is a documented request-scoped exception (per documented_exceptions).
- **AGENT-REG-03**: unknown agent_id / missing-field spec / empty active group fails fast with descriptive error before any bar (RegistryConfigError raised in _setup).
- **AGENT-REG-04**: shadow_registry enrollment runs over the built list; the DB is_shadow value is read back and APPLIED to each agent instance (fail-closed); YAML cannot force shadow_only:false (agents.yaml contains no shadow_only:false entries).

## Next Steps

Phase 096 complete. Agent registry is now the single source of truth for agent instantiation. Operators can add/reconfigure agents via YAML without Python changes.
