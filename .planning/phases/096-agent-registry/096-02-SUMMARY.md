---
phase: 096-agent-registry
plan: 02
status: completed
completed_at: "2026-06-03T15:30:00Z"
---
# Phase 096-02 Summary: AgentDependencies Constructor Migration

**Status:** COMPLETE 2026-06-03

## Objectives

Migrate every agent constructor from loose kwargs (`llm_chain=`, `pool=`) to the unified keyword-only `dependencies: AgentDependencies` signature. Update `BaseAIWorker.__init__` to accept `dependencies`, migrate all six agent constructors, update the on-demand narrative API route, and update agent unit tests. This is the constructor-uniformity prerequisite for `AgentRegistry.build` to construct all swarm agents identically via `cls(dependencies=agent_dependencies)`.

## Changes Made

### Task 1: BaseAIWorker.__init__ updated (COMPLETED)

**Modified `src/core/ai/base_agent.py`:**
- `__init__` signature changed to keyword-only `dependencies: AgentDependencies | None = None`
- `AgentDependencies` added to `TYPE_CHECKING` import block
- Base class ignores `dependencies`; subclasses extract what they need in their own `__init__`

### Task 2: All six agent constructors migrated (COMPLETED)

**Modified `src/intelligence/ai/alpha/skeptic_agent.py`, `correlation_agent.py`, `regime_coherence_agent.py`, `counterfactual_agent.py`:**
- Constructor changed from `(self, llm_chain: LLMProviderChain, **kwargs)` to `(self, *, dependencies: "AgentDependencies", **kwargs)`
- Body changed from `self._llm = llm_chain` to `self._llm = dependencies.llm_chain`
- Required-dep guard added: raises `ValueError` when `dependencies.llm_chain is None`
- `AgentDependencies` added to `TYPE_CHECKING` block in each file

**Modified `src/intelligence/ai/alpha/ml_scorer_agent.py`:**
- Constructor changed from `(self, pool: Any, **kwargs)` to `(self, *, dependencies: "AgentDependencies", **kwargs)`
- `self._pool = dependencies.pool`; `self._registry = ModelRegistry(dependencies.pool)`
- Guard raises `ValueError` when `dependencies.pool is None`

**Modified `src/intelligence/ai/narrative/narrative_agent.py`:**
- Constructor changed to `(self, *, dependencies: "AgentDependencies", **kwargs)`
- `self._llm = dependencies.llm_chain` with required-dep guard
- `shadow_only = False` class attribute preserved (in-memory default only; DB row `is_shadow=TRUE` applied by Plan 03 is authoritative)

### Task 3: On-demand narrative API route migrated (COMPLETED)

**Modified `src/api/routes/narrative.py`:**
- Added `from ...core.ai.agent_dependencies import AgentDependencies`
- Replaced `NarrativeSynthesizer(llm_chain=_get_llm_chain())` with:
  ```python
  agent_dependencies = AgentDependencies(llm_chain=_get_llm_chain(), pool=None, settings=_get_settings())
  agent = NarrativeSynthesizer(dependencies=agent_dependencies)
  ```
- This is the documented request-scoped exception to registry-sole-construction (per-request on-demand path, not swarm startup)

### Task 4: Agent unit tests updated (COMPLETED)

**Modified `tests/unit/services/test_skeptic_agent.py`, `test_correlation.py`, `test_regime_coherence.py`, `test_counterfactual_agent.py`:**
- All construction calls changed from `Agent(llm_chain=x)` to `Agent(dependencies=AgentDependencies(llm_chain=x, pool=None, settings=None))`
- `AgentDependencies` imported in each test file
- All suites pass green

## Verification

- `BaseAIWorker.__init__` accepts keyword-only `dependencies: AgentDependencies | None = None`
- No call site of `SkepticEvaluator`, `CorrelationAnalyzer`, `RegimeCoherenceAnalyzer`, `CounterfactualEvaluator`, `MLEvaluator`, or `NarrativeSynthesizer` passes `llm_chain=` or `pool=` directly
- All six agent unit tests and the narrative route test pass
- `AgentRegistry.build` can construct all swarm agents uniformly via `cls(dependencies=agent_dependencies)`
