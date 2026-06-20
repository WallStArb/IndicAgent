# Phase 096: Agent Registry - Pattern Map

**Mapped:** 2026-06-01
**Files analyzed:** 12 (3 new + 9 modified)
**Analogs found:** 12 / 12

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/core/ai/swarm_deps.py` (NEW) | utility/DI container | transform | `src/core/ai/output.py` (dataclass pattern) | role-match |
| `src/core/ai/registry.py` (NEW) | registry/factory | request-response | `src/intelligence/register_plugins.py` (TIER_I7 + shadow_registry_ensure) | role-match |
| `src/intelligence/ai/register_agents.py` (NEW) | config/bootstrap | transform | `src/intelligence/register_plugins.py` lines 1-30 (explicit import list) | exact |
| `config/agents.yaml` (NEW) | config | transform | N/A — no YAML config analog exists | none |
| `src/core/ai/base_agent.py` (MODIFY) | base-class/infrastructure | request-response | self — extend existing `__init_subclass__` | exact |
| `src/intelligence/ai/base_group_service.py` (MODIFY) | service/coordinator | request-response | self — add `_swarm_deps` + `AgentRegistry.build()` call in `_setup()` | exact |
| `src/intelligence/ai/alpha/skeptic_agent.py` (MODIFY) | agent/compute | request-response | self — constructor signature migration | exact |
| `src/intelligence/ai/alpha/correlation_agent.py` (MODIFY) | agent/compute | request-response | `skeptic_agent.py` (same constructor pattern) | exact |
| `src/intelligence/ai/alpha/regime_coherence_agent.py` (MODIFY) | agent/compute | request-response | `skeptic_agent.py` | exact |
| `src/intelligence/ai/alpha/counterfactual_agent.py` (MODIFY) | agent/compute | request-response | `skeptic_agent.py` | exact |
| `src/intelligence/ai/alpha/ml_scorer_agent.py` (MODIFY) | agent/compute | request-response | self — `pool`-only constructor, different from LLM agents | exact |
| `src/intelligence/ai/narrative/narrative_agent.py` (MODIFY) | agent/compute | request-response | self — `llm_chain`-only, non-Evaluator constructor | exact |
| `services/alpha_swarm.py` (MODIFY) | service/coordinator | event-driven | self — remove hardcoded construction, keep post-setup hooks | exact |
| `services/narrative_swarm.py` (MODIFY) | service/coordinator | event-driven | self — remove hardcoded construction | exact |

---

## Pattern Assignments

### `src/core/ai/swarm_deps.py` (NEW — utility, Ring 0)

**Analog:** `src/core/ai/output.py` (dataclass/BaseModel in Ring 0); `src/core/ai/worker_context.py` (another container)

**Imports pattern — use `TYPE_CHECKING` guard for Ring 1 deps:**
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.config.settings import Settings
    from src.core.llm.chain import LLMProviderChain
```

**Core pattern — typed DI container, no validation overhead:**
```python
@dataclass
class SwarmDeps:
    llm_chain: "LLMProviderChain | None"
    pool: Any | None          # asyncpg.Pool; Any avoids Ring 0 -> Ring 1 import
    settings: "Settings"
    # Phase 097 extension: memory_client: ZepMemoryClient | None = None
```

**Key rule:** `SwarmDeps` belongs in `src/core/ai/` (Ring 0) — it is pure infrastructure with no domain vocabulary. The `TYPE_CHECKING` guard is mandatory to prevent Ring 0 importing Ring 1 at runtime. `pool: Any` avoids importing `asyncpg` at Ring 0 (same pattern used in `base_group_service.py` line 80: `self._pool: Any | None = None`).

---

### `src/core/ai/registry.py` (NEW — registry/factory, Ring 0)

**Analog:** `src/intelligence/register_plugins.py` — `shadow_registry_ensure()` (lines 645-659), `enroll_all_plugins()` (lines 662-673); `TIER_I7` explicit list pattern

**Imports pattern:**
```python
from __future__ import annotations

import yaml
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, field_validator, ValidationError

if TYPE_CHECKING:
    from src.core.ai.base_agent import BaseAIWorker
    from src.core.ai.swarm_deps import SwarmDeps
```

**`AgentSpec` Pydantic model — `extra="forbid"` is mandatory:**
```python
class AgentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    shadow_only: bool | None = None         # None = use class attribute
    latency_budget_ms: float | None = None  # None = use class attribute
    prompt_version: str | None = None       # None = use class ACTIVE_VERSION
    model_override: str | None = None       # None = use OLLAMA_MODEL env var

    @field_validator("shadow_only")
    @classmethod
    def _reject_force_production(cls, v: bool | None) -> bool | None:
        if v is False:
            raise ValueError(
                "shadow_only: false is rejected in agents.yaml — "
                "production promotion requires the statistical gate in shadow_registry"
            )
        return v
```

**Module-level registry dict — populated by `__init_subclass__`, frozen after import:**
```python
# Module-level — populated by BaseAIWorker.__init_subclass__, read-only after imports
_REGISTRY: dict[str, type["BaseAIWorker"]] = {}
```

**YAML loading pattern — `yaml.safe_load()` always (never `yaml.load()`):**
```python
def _load_specs(group: str, yaml_path: Path | None = None) -> list[AgentSpec]:
    """Accept optional yaml_path for test isolation (default: config/agents.yaml)."""
    path = yaml_path or Path("config/agents.yaml")
    if not path.exists():
        raise RegistryConfigError(f"agents.yaml not found at {path.absolute()}")
    with path.open() as f:
        raw = yaml.safe_load(f)
    group_entries = raw.get(group, [])
    specs = []
    for entry in (group_entries or []):
        try:
            specs.append(AgentSpec.model_validate(entry))
        except ValidationError as exc:
            raise RegistryConfigError(
                f"Invalid agent spec in group '{group}': {exc}"
            ) from exc
    return specs
```

**`AgentRegistry.build()` — synchronous construction path:**
```python
class AgentRegistry:
    @staticmethod
    def build(group: str, deps: "SwarmDeps") -> list["BaseAIWorker"]:
        specs = _load_specs(group)
        AgentRegistry.validate(group, specs)
        agents = []
        for spec in specs:
            cls = _REGISTRY[spec.agent_id]
            agent = cls(deps=deps)
            if spec.shadow_only is not None:
                agent.shadow_only = spec.shadow_only
            if spec.latency_budget_ms is not None:
                agent.latency_budget_ms = spec.latency_budget_ms
                agent._timeout_s = spec.latency_budget_ms / 1000.0
            if spec.prompt_version is not None:
                agent.prompt_version = spec.prompt_version
            agents.append(agent)
        return agents

    @staticmethod
    def validate(group: str, specs: list[AgentSpec]) -> None:
        """Fail before first bar: all agent_ids known, at least one agent."""
        if not specs:
            # Emit warning for empty groups (risk: [] is scaffolded empty in Phase 096)
            # but do not raise — only groups with a running service are validated
            return
        unknown = [s.agent_id for s in specs if s.agent_id not in _REGISTRY]
        if unknown:
            raise RegistryConfigError(
                f"Unknown agent_id(s) in group '{group}': {unknown}. "
                f"Known: {sorted(_REGISTRY)}"
            )
```

**Error class (define at module top):**
```python
class RegistryError(Exception):
    """Raised when agent_id is not in _REGISTRY."""

class RegistryConfigError(Exception):
    """Raised when agents.yaml is missing, malformed, or fails validation."""
```

---

### `src/intelligence/ai/register_agents.py` (NEW — config/bootstrap, Ring 1)

**Analog:** `src/intelligence/register_plugins.py` lines 1-30 — explicit module-level import list

**Core pattern — explicit import list, no filesystem scanning:**
```python
"""Explicit agent module imports — trigger __init_subclass__ self-registration.

Analogous to the TIER_I* lists in register_plugins.py.

To add a new agent:
  1. Create the agent class in src/intelligence/ai/<group>/<name>_agent.py
  2. Add the module path to AGENT_MODULES below
  3. Add the entry to config/agents.yaml
  4. Restart the swarm service

No filesystem scanning. Every import here is deliberate and auditable.
"""

AGENT_MODULES = [
    "src.intelligence.ai.alpha.skeptic_agent",
    "src.intelligence.ai.alpha.correlation_agent",
    "src.intelligence.ai.alpha.regime_coherence_agent",
    "src.intelligence.ai.alpha.counterfactual_agent",
    "src.intelligence.ai.alpha.ml_scorer_agent",
    "src.intelligence.ai.narrative.narrative_agent",
]


def _import_all() -> None:
    """Import all agent modules to trigger __init_subclass__ registration.

    Called once inside BaseSwarmCoordinator._setup() before AgentRegistry.build().
    Lazy import inside _setup() avoids circular imports at module load time.
    """
    import importlib
    for module_path in AGENT_MODULES:
        importlib.import_module(module_path)
```

**Critical rule:** Do NOT import `register_agents` at the module level of `base_group_service.py`. Import it lazily inside `_setup()` to prevent circular imports (Ring 1 importing Ring 1 agent modules at module load).

---

### `config/agents.yaml` (NEW — operator manifest)

**No analog.** There is no existing YAML config file in the project. PyYAML is already in requirements.

**Confirmed `agent_id` values (from source grep):**
- `skeptic_agent.py`: `agent_id = "skeptic"` — no version suffix (predates naming rule)
- `correlation_agent.py`: `agent_id = "correlation_v1"`
- `regime_coherence_agent.py`: `agent_id = "regime_coherence_v1"`
- `counterfactual_agent.py`: `agent_id = "counterfactual_v1"`
- `ml_scorer_agent.py`: `agent_id = "ml_scorer_v1"`
- `narrative_agent.py`: `agent_id = "narrative_v1"`

**Structure pattern:**
```yaml
# config/agents.yaml
# Operator manifest — edit and restart the service to add/reconfigure agents.
# shadow_only: true is the only valid value; false is rejected at validation.
# Production promotion goes through shadow_registry statistical gate only.

alpha:
  - agent_id: skeptic
  - agent_id: correlation_v1
  - agent_id: regime_coherence_v1
  - agent_id: counterfactual_v1
  - agent_id: ml_scorer_v1
    shadow_only: true

narrative:
  - agent_id: narrative_v1

risk: []  # scaffolded; no agents in Phase 096
```

---

### `src/core/ai/base_agent.py` (MODIFY — extend `__init_subclass__`)

**Analog:** self — existing `__init_subclass__` at lines 105-118

**Current `__init_subclass__` (lines 105-118) — preserve `result_type` validation, add registry hook:**
```python
def __init_subclass__(cls, **kwargs: Any) -> None:
    """Validate result_type at class-definition time (REVIEWS LOW item 10).
    ...
    """
    super().__init_subclass__(**kwargs)
    if cls.result_type is not None and not (
        isinstance(cls.result_type, type) and issubclass(cls.result_type, BaseModel)
    ):
        raise TypeError(
            f"{cls.__name__}.result_type must be a pydantic BaseModel subclass or None,"
            f" got {cls.result_type!r}"
        )
    # NEW: self-register when agent_id is non-empty (skips base/abstract classes)
    # BaseAIWorker.agent_id = "" and Evaluator inherits "" — both safely skipped.
    if cls.agent_id:
        from src.core.ai.registry import _REGISTRY, RegistryError  # lazy to avoid circular
        if cls.agent_id in _REGISTRY and _REGISTRY[cls.agent_id] is not cls:
            raise RegistryError(
                f"Duplicate agent_id '{cls.agent_id}': "
                f"{_REGISTRY[cls.agent_id].__name__} vs {cls.__name__}"
            )
        _REGISTRY[cls.agent_id] = cls
```

**Current `__init__` signature (lines 95-103) — this is what gets replaced by `deps: SwarmDeps`:**
```python
def __init__(self, name: str | None = None, *args: Any, **kwargs: Any) -> None:
    if name is None:
        name = self.__class__.__name__
    super().__init__(*args, name=name, **kwargs)
    self._timeout_s = self.latency_budget_ms / 1000.0
    self._lineage: LineageRecorder | None = None
    self._llm: LLMProviderChain | None = None
    self._agent_labels: dict[str, str] = {"agent_id": self.agent_id, "group": self.group}
```

**New `__init__` signature after migration:**
```python
def __init__(self, *, deps: "SwarmDeps | None" = None, name: str | None = None, **kwargs: Any) -> None:
    if name is None:
        name = self.__class__.__name__
    super().__init__(name=name, **kwargs)
    self._timeout_s = self.latency_budget_ms / 1000.0
    self._lineage: LineageRecorder | None = None
    self._llm: LLMProviderChain | None = None
    self._agent_labels: dict[str, str] = {"agent_id": self.agent_id, "group": self.group}
    # Subclasses extract from deps in their own __init__
```

---

### `src/intelligence/ai/base_group_service.py` (MODIFY — wire registry in `_setup()`)

**Analog:** self — existing `_setup()` lines 84-151; `_shadow_registry_ensure_agents()` lines 153-170

**Injection point is after `self._llm_chain` and `self._pool` are set (line ~135 in current file):**
```python
async def _setup(self) -> None:
    # ... existing Kafka/pool/llm wiring unchanged (lines 89-146) ...

    # After self._llm_chain and self._pool are set — build SwarmDeps and populate agents
    # Lazy import: avoids circular import (Ring 1 module importing Ring 1 agents at load time)
    from src.intelligence.ai.register_agents import _import_all  # noqa: PLC0415
    from src.core.ai.registry import AgentRegistry              # noqa: PLC0415
    from src.core.ai.swarm_deps import SwarmDeps                # noqa: PLC0415

    _import_all()  # ensure _REGISTRY is populated before AgentRegistry.build()
    self._swarm_deps = SwarmDeps(
        llm_chain=self._llm_chain,
        pool=self._pool,
        settings=self.settings,
    )
    self._agents = AgentRegistry.build(self.group_id, self._swarm_deps)

    # Existing shadow enrollment — unchanged; now iterates registry-built agents
    if self._pool is not None:
        await self._shadow_registry_ensure_agents(self._agents)

    # ... rest of existing _setup() (lineage, super()._setup()) ...
```

**`_shadow_registry_ensure_agents()` (lines 153-170) — keep exactly as-is:**
```python
async def _shadow_registry_ensure_agents(self, agents: list[BaseAIWorker]) -> None:
    assert self._pool is not None
    async with self._pool.acquire() as conn:
        for agent in agents:
            await conn.execute(
                "INSERT INTO shadow_registry (component_name, component_type, is_shadow) "
                "VALUES ($1, 'swarm_agent', TRUE) ON CONFLICT (component_name) DO NOTHING",
                agent.agent_id,
            )
    self.logger.info(
        "base_group_service.shadow_enrolled",
        group_id=self.group_id,
        agents=[a.agent_id for a in agents],
    )
```

**Add `_agents` and `_swarm_deps` initialization in `__init__` (line ~73):**
```python
def __init__(self, settings: Settings, *args: Any, **kwargs: Any) -> None:
    super().__init__(max_idle_seconds=0, settings=settings)
    self.settings = settings
    self._context_cache = SignalContextCache()
    self._bar_consumer: KafkaConsumerClient | None = None
    self._trigger_consumer: KafkaConsumerClient | None = None
    self._producer: KafkaProducerClient | None = None
    self._pool: Any | None = None
    self._llm_chain: LLMProviderChain | None = None
    self._lineage: LineageRecorder | None = None
    # Phase 096: registry-driven agent list and typed dep container
    self._agents: list[BaseAIWorker] = []
    self._swarm_deps: Any | None = None  # SwarmDeps; Any avoids import at module level
```

---

### Alpha agent constructor migration (MODIFY × 4 LLM agents)

**Analog:** `src/intelligence/ai/alpha/skeptic_agent.py` lines 85-87 — current constructor

**Current constructor (skeptic_agent.py:85-87):**
```python
def __init__(self, llm_chain: LLMProviderChain, **kwargs: Any) -> None:
    super().__init__(name="SkepticEvaluator", **kwargs)
    self._llm = llm_chain
```

**After migration — same for SkepticEvaluator, CorrelationAnalyzer, RegimeCoherenceAnalyzer, CounterfactualEvaluator:**
```python
def __init__(self, *, deps: "SwarmDeps", **kwargs: Any) -> None:
    super().__init__(name="SkepticEvaluator", **kwargs)
    self._llm = deps.llm_chain
```

**TYPE_CHECKING import to add (already present on skeptic_agent.py — check others):**
```python
if TYPE_CHECKING:
    from src.core.ai.swarm_deps import SwarmDeps
```

---

### `src/intelligence/ai/alpha/ml_scorer_agent.py` (MODIFY — pool-only constructor)

**Analog:** self — lines 114-124

**Current constructor (lines 114-124):**
```python
def __init__(self, pool: Any, **kwargs: Any) -> None:
    super().__init__(**kwargs)
    self._pool = pool
    self._registry = ModelRegistry(pool)
    self._models: dict[str, Any] = {}
    self._feature_cols: list[str] = []
```

**After migration:**
```python
def __init__(self, *, deps: "SwarmDeps", **kwargs: Any) -> None:
    super().__init__(**kwargs)
    self._pool = deps.pool
    self._registry = ModelRegistry(deps.pool)
    self._models: dict[str, Any] = {}
    self._feature_cols: list[str] = []
```

**`_setup_models()` async hook (lines 126-178) — must still be called explicitly by `AlphaSwarm._setup()` after `AgentRegistry.build()`. Find by type, not by index:**
```python
# In AlphaSwarm._setup() AFTER super()._setup() returns (which now runs AgentRegistry.build()):
ml = next((a for a in self._agents if isinstance(a, MLEvaluator)), None)
if ml is not None:
    await ml._setup_models()
```

---

### `src/intelligence/ai/narrative/narrative_agent.py` (MODIFY — llm_chain constructor)

**Analog:** self — lines 49-51

**Current constructor (lines 49-51):**
```python
def __init__(self, llm_chain: LLMProviderChain, **kwargs: Any) -> None:
    super().__init__(**kwargs)
    self._llm = llm_chain
```

**After migration:**
```python
def __init__(self, *, deps: "SwarmDeps", **kwargs: Any) -> None:
    super().__init__(**kwargs)
    self._llm = deps.llm_chain
```

**`shadow_only = False` (line 44) — leave this class attribute as-is.** The `AgentSpec._reject_force_production` validator only fires when YAML explicitly sets `shadow_only: false`. When the class attribute is already `False` and YAML has no override (i.e., `shadow_only: null`), the class default wins unchanged. This is intentional — narrative text has no `pnl_r` correlation axis.

---

### `services/alpha_swarm.py` (MODIFY — remove hardcoded construction)

**Analog:** self — lines 154-203

**Current hardcoded construction (lines 165-174) — DELETE this block:**
```python
self._agents = [
    SkepticEvaluator(llm_chain=self._llm_chain),
    CorrelationAnalyzer(llm_chain=self._llm_chain),
    RegimeCoherenceAnalyzer(llm_chain=self._llm_chain),
    CounterfactualEvaluator(llm_chain=self._llm_chain),
]
self._agents.append(MLEvaluator(pool=self._pool))
await self._agents[-1]._setup_models()
```

**Replace with — post-super() hooks only (agents already built by base class):**
```python
async def _setup(self) -> None:
    await super()._setup()
    # self._agents is now populated by BaseSwarmCoordinator._setup() via AgentRegistry.build()

    # MLEvaluator async setup — find by type (not by fragile index)
    ml = next((a for a in self._agents if isinstance(a, MLEvaluator)), None)
    if ml is not None:
        await ml._setup_models()

    self._semaphore = asyncio.Semaphore(self.settings.SWARM_MAX_CONCURRENT_CALLS)

    # Phase 109: apply config-DB shadow_mode overrides (loop unchanged — iterates self._agents)
    for agent in self._agents:
        for k, v in self._config_cache.items():
            if k.startswith("ai.agent."):
                agent._config_cache[k] = v
        if hasattr(agent, "_apply_shadow_mode_config"):
            agent._apply_shadow_mode_config()

    # Shadow enrollment is now done by BaseSwarmCoordinator._setup() — remove duplicate call
    # (base class calls _shadow_registry_ensure_agents already)

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(_signal.SIGUSR1, self._on_sigusr1)
    self.logger.info("alpha_swarm.sigusr1_handler_registered")
    agent_ids = [a.agent_id for a in self._agents]
    self.logger.info("alpha_swarm.started", agents=agent_ids)
```

**Remove these imports (no longer needed after registry migration):**
```python
# DELETE from alpha_swarm.py:
from src.intelligence.ai.alpha.correlation_agent import CorrelationAnalyzer
from src.intelligence.ai.alpha.counterfactual_agent import CounterfactualEvaluator
from src.intelligence.ai.alpha.regime_coherence_agent import RegimeCoherenceAnalyzer
from src.intelligence.ai.alpha.skeptic_agent import SkepticEvaluator
```

**Keep this import (still needed for `isinstance` type check in `_setup_models` lookup):**
```python
from src.intelligence.ai.alpha.ml_scorer_agent import MLEvaluator
```

---

### `services/narrative_swarm.py` (MODIFY — remove hardcoded construction)

**Analog:** self — lines 67-78

**Current hardcoded construction (lines 70-73) — REPLACE:**
```python
async def _setup(self) -> None:
    await super()._setup()
    # _llm_chain is wired by super()._setup() — construct agent here.
    self._narrative_agent = NarrativeSynthesizer(llm_chain=self._llm_chain)

    if self._pool is not None:
        await self._shadow_registry_ensure_agents(self.agents)
    ...
```

**After migration — agent is built by base class; just wire the reference:**
```python
async def _setup(self) -> None:
    await super()._setup()
    # self._agents populated by BaseSwarmCoordinator._setup() via AgentRegistry.build()
    # Wire the typed reference for _handle_trigger / _process_one_signal convenience
    self._narrative_agent = next(
        (a for a in self._agents if isinstance(a, NarrativeSynthesizer)), None
    )
    # Shadow enrollment done by base class — remove duplicate call
    self.logger.info(
        "narrative_swarm.started",
        agent_id=self._narrative_agent.agent_id if self._narrative_agent else "none",
    )
```

---

## Shared Patterns

### `__init_subclass__` Self-Registration
**Source:** `src/core/ai/base_agent.py` lines 105-118
**Apply to:** `src/core/ai/base_agent.py` (extend), `src/core/ai/registry.py` (consume `_REGISTRY`)

The existing hook validates `result_type`. The Phase 096 extension appends agent_id registration **after** the existing validation block. Guard `if cls.agent_id:` ensures `BaseAIWorker` (agent_id="") and `Evaluator` (inherits "") are silently skipped.

### Shadow Registry Enrollment
**Source:** `src/intelligence/ai/base_group_service.py` lines 153-170 (`_shadow_registry_ensure_agents`); `src/intelligence/register_plugins.py` lines 645-659 (`shadow_registry_ensure`)

The `_shadow_registry_ensure_agents()` method already exists on `BaseSwarmCoordinator` and iterates `self._agents`. After Phase 096, this list is populated by `AgentRegistry.build()` before the method is called. No changes needed to the enrollment logic itself.

```python
# Pattern from base_group_service.py:153-165
async with self._pool.acquire() as conn:
    for agent in agents:
        await conn.execute(
            "INSERT INTO shadow_registry (component_name, component_type, is_shadow) "
            "VALUES ($1, 'swarm_agent', TRUE) ON CONFLICT (component_name) DO NOTHING",
            agent.agent_id,
        )
```

### Error Handling — `_neutral()` fallback
**Source:** `src/core/ai/base_agent.py` lines 205-215
**Apply to:** `src/core/ai/registry.py` (raise `RegistryConfigError` before agents start, never in `_compute()`)

Agents use `self._neutral(error=..., latency_ms=...)` for all runtime failures. Registry errors raise before `_run()` begins — they are startup-time configuration failures, not runtime errors.

### Pydantic `extra="forbid"` Validation
**Source:** `src/intelligence/schemas.py` (all `IntelligenceEvent` models use strict Pydantic); `src/config/settings.py` (Settings uses Pydantic)
**Apply to:** `AgentSpec` in `src/core/ai/registry.py`

`model_config = ConfigDict(extra="forbid")` causes `ValidationError` on any unknown YAML key — catches typos like `latency_budgett_ms` at startup rather than silently ignoring them.

### Lazy Import Inside `_setup()` (circular import avoidance)
**Source:** `src/intelligence/ai/base_group_service.py` lines 121-122 (existing lazy import of `create_db_pool`); `src/intelligence/ai/alpha/skeptic_agent.py` line 23 (`TYPE_CHECKING` guard)

```python
# Pattern: lazy import inside async method to avoid module-level circular import
from src.core.database_manager import create_pool as create_db_pool  # noqa: PLC0415
```

Apply same pattern for `_import_all`, `AgentRegistry`, `SwarmDeps` inside `_setup()`.

### `TYPE_CHECKING` Guard for Cross-Ring Imports
**Source:** `src/core/ai/base_agent.py` lines 28-34; `src/core/ai/evaluator.py` lines 16-20
**Apply to:** `src/core/ai/swarm_deps.py`, agent files importing `SwarmDeps`

```python
if TYPE_CHECKING:
    from src.core.llm.chain import LLMProviderChain
    from src.config.settings import Settings
    from src.core.ai.swarm_deps import SwarmDeps
```

---

## No Analog Found

| File | Role | Reason |
|---|---|---|
| `config/agents.yaml` | config | No YAML-driven operator manifests exist in the codebase. Use RESEARCH.md Pattern 8 as template. |

---

## Critical Agent ID Reference

Verified via `grep -rn "agent_id = " src/intelligence/ai/alpha/` — use these exact strings in `agents.yaml`:

| Class | File | `agent_id` value |
|---|---|---|
| `SkepticEvaluator` | `alpha/skeptic_agent.py` | `"skeptic"` (NO version suffix) |
| `CorrelationAnalyzer` | `alpha/correlation_agent.py` | `"correlation_v1"` |
| `RegimeCoherenceAnalyzer` | `alpha/regime_coherence_agent.py` | `"regime_coherence_v1"` |
| `CounterfactualEvaluator` | `alpha/counterfactual_agent.py` | `"counterfactual_v1"` |
| `MLEvaluator` | `alpha/ml_scorer_agent.py` | `"ml_scorer_v1"` |
| `NarrativeSynthesizer` | `narrative/narrative_agent.py` | `"narrative_v1"` |

---

## Metadata

**Analog search scope:** `src/core/ai/`, `src/intelligence/ai/`, `src/intelligence/register_plugins.py`, `services/alpha_swarm.py`, `services/narrative_swarm.py`
**Files read:** 10 source files
**Pattern extraction date:** 2026-06-01
