# Phase 096-02 Summary: Constructor Migration to AgentDependencies

**Status:** COMPLETE 2026-06-03

## Objectives
Migrate all agent constructors from hardcoded dependency injection to unified `AgentDependencies` container, establishing Ring 0 purity.

## Changes Made

### Task 1: BaseAIWorker.__init__ Signature (COMPLETED)
Modified `src/core/ai/base_agent.py`:
- Changed signature to `*, dependencies: AgentDependencies | None = None`
- Self-registration via `__init_subclass__` unchanged

### Task 2: Six Agent Constructors (COMPLETED)
All six agent constructors migrated to `dependencies: AgentDependencies`:

| Agent | File | Dependency | Guard |
|-------|------|------------|-------|
| SkepticEvaluator | `src/intelligence/ai/alpha/skeptic_agent.py` | `llm_chain` | `if self._llm is None: raise ValueError(...)` |
| CorrelationAnalyzer | `src/intelligence/ai/alpha/correlation_agent.py` | `llm_chain` | `if self._llm is None: raise ValueError(...)` |
| RegimeCoherenceAnalyzer | `src/intelligence/ai/alpha/regime_coherence_agent.py` | `llm_chain` | `if self._llm is None: raise ValueError(...)` |
| CounterfactualEvaluator | `src/intelligence/ai/alpha/counterfactual_agent.py` | `llm_chain` | `if self._llm is None: raise ValueError(...)` |
| MLEvaluator | `src/intelligence/ai/alpha/ml_scorer_agent.py` | `pool` | `if dependencies.pool is None: raise ValueError(...)` |
| NarrativeSynthesizer | `src/intelligence/ai/narrative/narrative_agent.py` | `llm_chain` | `if self._llm is None: raise ValueError(...)` |

### Task 3: On-demand Narrative API Route (COMPLETED)
Modified `src/api/routes/narrative.py`:
- Added import: `from ...core.ai.agent_dependencies import AgentDependencies`
- Changed construction from `NarrativeSynthesizer(llm_chain=_get_llm_chain())` to:
  ```python
  agent_dependencies = AgentDependencies(
      llm_chain=_get_llm_chain(),
      pool=None,
      settings=_get_settings(),
  )
  agent = NarrativeSynthesizer(dependencies=agent_dependencies)
  ```

### Task 4: Agent Unit Tests (COMPLETED)
Modified `tests/unit/services/test_skeptic_agent.py`:
- Changed `_make_skeptic_evaluator()` from `__new__` bypass pattern to:
  ```python
  deps = AgentDependencies(llm_chain=MagicMock(), pool=None, settings=None)
  evaluator = SkepticEvaluator(dependencies=deps)
  ```

Other agent tests (`test_correlation.py`, `test_regime_coherence.py`, `test_counterfactual_agent.py`) only test class attributes and result parsing—no constructor changes needed.

## Verification
- All 1150 unit tests pass (9.46s)
- All six agents import and register correctly in `_REGISTRY`
- No Ring 0→Ring 1 runtime imports (TYPE_CHECKING pattern holds)

## Next Step
Proceed to Plan 096-03: End-to-end wiring (register_agents.py, agents.yaml, BaseGroupCoordinator._setup, swarm services).
