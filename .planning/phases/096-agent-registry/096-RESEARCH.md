# Phase 096: Agent Registry - Research

**Researched:** 2026-06-01
**Domain:** YAML-driven agent registry, dependency injection, class self-registration
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01: Class Discovery — `__init_subclass__` + Explicit Import List**
Mechanism: `BaseAIWorker.__init_subclass__` hook populates a module-level `_REGISTRY: dict[str, type[BaseAIWorker]]` keyed by `agent_id` class attribute. No decorator needed — every class that inherits `BaseAIWorker` self-registers automatically.

Determinism: An explicit `AGENT_MODULES` list in `src/intelligence/ai/register_agents.py` enumerates exactly which modules are imported at startup. No filesystem scanning. Adding a new agent class = add it to `AGENT_MODULES`.

Fail-fast: `AgentRegistry.get(agent_id)` raises `RegistryError` with the full list of known IDs if the agent_id is not in `_REGISTRY`. Service never enters `_run()` with an unknown agent.

**D-02: YAML Schema — Per-Group Sections, Class Defaults as Fallback**
Location: `config/agents.yaml` at project root.

Structure: Top-level keys mirror DAG groups (`alpha:`, `narrative:`, `risk:`). Each group contains a list of agent entries. `group` field is NOT in individual entries — inferred from section key.

Required fields: `agent_id` only.

Optional fields (fall back to class attribute when absent): `shadow_only`, `latency_budget_ms`, `prompt_version`, `model_override`.

YAML `shadow_only: false` is rejected — cannot force production promotion.

**D-03: Dependency Injection — `SwarmDeps` Dataclass**
`SwarmDeps` dataclass — typed dependency container replacing loose constructor kwargs:
```python
@dataclass
class SwarmDeps:
    llm_chain: LLMChain | None
    pool: asyncpg.Pool | None
    settings: Settings
```
`BaseAIWorker.__init__` signature change: `(self, *, deps: SwarmDeps)` — replacing current `(self, llm_chain=None, pool=None, **kwargs)` pattern.

**D-04: Registry Integration into `BaseSwarmCoordinator` — Template Method Pattern**
`BaseSwarmCoordinator._setup()` calls `self._agents = AgentRegistry.build(self.group, self._swarm_deps)` automatically after infrastructure setup. Subclasses do not call this explicitly.

The base class holds `self._swarm_deps: SwarmDeps` built from `self._llm_chain` and `self._pool` after they are initialized.

**D-05: Shadow Registry — DB is Authority, YAML is Intent**
`agents.yaml` expresses intent. `shadow_registry` holds live state. DB `is_shadow` value is authoritative gate. YAML `shadow_only: false` is rejected by `AgentSpec` validation.

**D-06: Validation Gate — Fail Before First Bar**
`AgentRegistry.validate(group, spec_list)` runs synchronously before `_run()` begins. Checks: all `agent_id` values exist in `_REGISTRY`, all required Pydantic fields present and typed correctly, at least one agent defined for the group.

### Claude's Discretion
- Whether `SwarmDeps` lives in `src/core/ai/` or `src/intelligence/ai/` (recommend `src/core/ai/` — Ring 0 infrastructure)
- Whether `AGENT_MODULES` is a Python list in `register_agents.py` or a YAML section in `agents.yaml` (recommend Python list)
- Exact Pydantic model structure for `AgentSpec` (field validators, alias handling)
- How `config/agents.yaml` is read — `PyYAML` or `ruamel.yaml` (both available; `PyYAML` is simpler)

### Deferred Ideas (OUT OF SCOPE)
- Hot-reload without restart
- Risk group agents (scaffold `risk:` section only)
- YAML validation CLI tool
</user_constraints>

---

## Summary

Phase 096 replaces hardcoded agent construction in `AlphaSwarm._setup()` (line 165) and `NarrativeSwarm._setup()` (line 70) with a YAML-driven `AgentRegistry`. The change touches six files directly and introduces three new modules: `config/agents.yaml`, `src/intelligence/ai/register_agents.py`, and `src/core/ai/swarm_deps.py`.

The biggest implementation risk is the `BaseAIWorker.__init__` signature change. Currently all five alpha agents and `NarrativeSynthesizer` accept either `llm_chain: LLMProviderChain` or `pool: Any` as positional-by-keyword arguments. `SwarmDeps` replaces these with a single `deps: SwarmDeps` kwarg. Every agent constructor and every test that instantiates agents must be updated.

The `__init_subclass__` hook already exists in `base_agent.py` but currently validates `result_type` only. The Phase 096 hook must be extended to also register `agent_id -> class` without breaking the existing `result_type` validation.

**Primary recommendation:** Build in this order: (1) `SwarmDeps` dataclass, (2) extend `__init_subclass__` for registry, (3) `AgentSpec` Pydantic model + `AgentRegistry`, (4) `register_agents.py` import list, (5) migrate all agent constructors, (6) wire `BaseSwarmCoordinator._setup()`, (7) write `config/agents.yaml`, (8) remove hardcoded construction from `AlphaSwarm._setup()` and `NarrativeSwarm._setup()`.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pydantic` | already in requirements | `AgentSpec` validation, fail-fast on bad YAML fields | Already used for `Settings`, `IntelligenceEvent`, agent outputs |
| `PyYAML` | already in requirements (`yaml`) | Load `config/agents.yaml` | Simpler than `ruamel.yaml`; no round-trip write needed |
| Python `dataclasses` | stdlib | `SwarmDeps` typed dependency container | No external dep, clean typing, Phase 097 extensible |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pydantic_settings` | already in use | N/A — `Settings` already loaded | `SwarmDeps` carries the existing `Settings` instance |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `PyYAML` | `ruamel.yaml` | `ruamel.yaml` preserves comments but adds complexity; `PyYAML` is sufficient since we only read |
| `@dataclass` for `SwarmDeps` | `pydantic.BaseModel` | `BaseModel` adds validation cost and JSON overhead that is unnecessary for a pure container; dataclass is idiomatic for DI containers |

**Installation:** No new packages required. `PyYAML` and `pydantic` are already in `requirements.txt`.

---

## Architecture Patterns

### Recommended Project Structure

New files:
```
config/
└── agents.yaml               # operator manifest (created in Phase 096)

src/core/ai/
├── base_agent.py             # extend __init_subclass__ to register agents
├── swarm_deps.py             # NEW: SwarmDeps dataclass
└── registry.py               # NEW: AgentRegistry class + _REGISTRY dict

src/intelligence/ai/
└── register_agents.py        # NEW: AGENT_MODULES explicit import list
```

Modified files:
```
src/intelligence/ai/base_group_service.py    # wire AgentRegistry.build() in _setup()
src/intelligence/ai/alpha/skeptic_agent.py   # __init__ -> deps: SwarmDeps
src/intelligence/ai/alpha/correlation_agent.py
src/intelligence/ai/alpha/regime_coherence_agent.py
src/intelligence/ai/alpha/counterfactual_agent.py
src/intelligence/ai/alpha/ml_scorer_agent.py  # reads pool from deps.pool
src/intelligence/ai/narrative/narrative_agent.py
services/alpha_swarm.py                       # remove hardcoded self._agents list
services/narrative_swarm.py                   # remove hardcoded self._narrative_agent
```

### Pattern 1: `__init_subclass__` Self-Registration

The existing `__init_subclass__` in `base_agent.py` validates `result_type`. Extend it to also register agent classes:

```python
# Source: src/core/ai/base_agent.py (existing hook, to be extended)
_REGISTRY: dict[str, type["BaseAIWorker"]] = {}

class BaseAIWorker(BaseDaemon, ABC):
    agent_id: str = ""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Existing result_type validation — preserve exactly
        if cls.result_type is not None and not (
            isinstance(cls.result_type, type) and issubclass(cls.result_type, BaseModel)
        ):
            raise TypeError(...)
        # New: self-register when agent_id is non-empty (skip base/abstract classes)
        if cls.agent_id:
            if cls.agent_id in _REGISTRY and _REGISTRY[cls.agent_id] is not cls:
                raise RegistryError(
                    f"Duplicate agent_id '{cls.agent_id}': "
                    f"{_REGISTRY[cls.agent_id].__name__} vs {cls.__name__}"
                )
            _REGISTRY[cls.agent_id] = cls
```

**Critical detail:** `agent_id = ""` on `BaseAIWorker` means the guard `if cls.agent_id:` skips base/mixin classes. `Evaluator` also has `agent_id = ""` (inherited) so it self-skips correctly. Only concrete agents with non-empty `agent_id` register.

### Pattern 2: `AgentSpec` Pydantic Model

```python
# Source: src/core/ai/registry.py (new file)
from pydantic import BaseModel, ConfigDict, field_validator

class AgentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    shadow_only: bool | None = None        # None = use class attribute
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

`extra="forbid"` means an unknown YAML key (e.g. a typo like `shadow_onlyy:`) raises `ValidationError` at startup rather than being silently ignored.

### Pattern 3: `SwarmDeps` Dataclass

```python
# Source: src/core/ai/swarm_deps.py (new file — Ring 0)
from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.config.settings import Settings
    from src.core.llm.chain import LLMProviderChain

@dataclass
class SwarmDeps:
    llm_chain: "LLMProviderChain | None"
    pool: Any | None                          # asyncpg.Pool; Any avoids import at Ring 0
    settings: "Settings"
    # Phase 097 extension point: memory_client: ZepMemoryClient | None = None
```

`SwarmDeps` belongs in `src/core/ai/` (Ring 0) because it is pure infrastructure with no domain vocabulary. Ring 0 must not import Ring 1 at runtime; the `TYPE_CHECKING` guard keeps `LLMProviderChain` and `Settings` import-time clean.

### Pattern 4: `AgentRegistry.build()` — Construction Path

```python
# Source: src/core/ai/registry.py (new file)
class AgentRegistry:
    @staticmethod
    def build(group: str, deps: SwarmDeps) -> list[BaseAIWorker]:
        """Read agents.yaml, filter by group, construct instances via SwarmDeps."""
        specs = _load_specs(group)           # reads config/agents.yaml, returns list[AgentSpec]
        AgentRegistry.validate(group, specs) # fail-fast before any construction
        agents = []
        for spec in specs:
            cls = _REGISTRY[spec.agent_id]   # guaranteed present after validate()
            agent = cls(deps=deps)            # new universal signature
            # Apply YAML overrides onto the constructed instance
            if spec.shadow_only is not None:
                agent.shadow_only = spec.shadow_only
            if spec.latency_budget_ms is not None:
                agent.latency_budget_ms = spec.latency_budget_ms
                agent._timeout_s = spec.latency_budget_ms / 1000.0
            if spec.prompt_version is not None:
                agent.prompt_version = spec.prompt_version
            agents.append(agent)
        return agents
```

### Pattern 5: `AGENT_MODULES` Explicit Import List

```python
# Source: src/intelligence/ai/register_agents.py (new file — analogous to register_plugins.py)
"""Explicit agent module imports — analogous to TIER_I7 in register_plugins.py.

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
    import importlib
    for module_path in AGENT_MODULES:
        importlib.import_module(module_path)
```

`_import_all()` is called once at `BaseSwarmCoordinator._setup()` before `AgentRegistry.build()` runs, ensuring `_REGISTRY` is populated.

### Pattern 6: `BaseSwarmCoordinator._setup()` Integration

```python
# Modified section in base_group_service.py _setup()
# ... (existing Kafka/pool/llm wiring unchanged) ...

# After self._llm_chain and self._pool are set:
from src.intelligence.ai.register_agents import _import_all
from src.core.ai.registry import AgentRegistry
from src.core.ai.swarm_deps import SwarmDeps

_import_all()  # ensure _REGISTRY is populated
self._swarm_deps = SwarmDeps(
    llm_chain=self._llm_chain,
    pool=self._pool,
    settings=self.settings,
)
self._agents = AgentRegistry.build(self.group_id, self._swarm_deps)

# Existing shadow enrollment — unchanged
if self._pool is not None:
    await self._shadow_registry_ensure_agents(self._agents)
```

### Pattern 7: Agent Constructor Migration

Current (example — SkepticEvaluator):
```python
def __init__(self, llm_chain: LLMProviderChain, **kwargs: Any) -> None:
    super().__init__(name="SkepticEvaluator", **kwargs)
    self._llm = llm_chain
```

After migration:
```python
def __init__(self, *, deps: SwarmDeps, **kwargs: Any) -> None:
    super().__init__(name="SkepticEvaluator", **kwargs)
    self._llm = deps.llm_chain
```

MLEvaluator (pool-only):
```python
def __init__(self, *, deps: SwarmDeps, **kwargs: Any) -> None:
    super().__init__(**kwargs)
    self._pool = deps.pool
    self._registry = ModelRegistry(deps.pool)
```

**MLEvaluator post-setup hook:** `MLEvaluator._setup_models()` is called by `AlphaSwarm._setup()` today (`await self._agents[-1]._setup_models()`). After the registry wires agents uniformly, `AgentRegistry.build()` cannot call async methods. The solution: `AlphaSwarm._setup()` still calls `_setup_models()` after `self._agents` is populated — it finds the `MLEvaluator` by type and calls it explicitly. This preserves correctness without adding async hooks to the registry itself.

### Pattern 8: `agents.yaml` Structure

```yaml
# config/agents.yaml
# Operator manifest — edit this file and restart the service to add/reconfigure agents.
# shadow_only: true is the only allowed value; production promotion goes through shadow_registry.

alpha:
  - agent_id: skeptic
    latency_budget_ms: 120000
  - agent_id: correlation_v1
  - agent_id: regime_coherence_v1
  - agent_id: counterfactual_v1
  - agent_id: ml_scorer_v1
    shadow_only: true

narrative:
  - agent_id: narrative_v1

risk: []  # scaffolded; no agents in Phase 096
```

**Critical:** `agent_id` values in YAML must match the `agent_id` class attribute exactly. The current agent IDs are:
- `skeptic` (SkepticEvaluator — note: NO version suffix in the class attribute)
- `correlation_v1` (CorrelationAnalyzer — inferred from AUTHORING.md pattern; verify in source)
- `regime_coherence_v1` (RegimeCoherenceAnalyzer)
- `counterfactual_v1` (CounterfactualEvaluator)
- `ml_scorer_v1` (MLEvaluator)
- `narrative_v1` (NarrativeSynthesizer)

**Agent ID verification is mandatory before writing `agents.yaml`.** The class attribute `agent_id` is the ground truth; YAML must match exactly or `AgentRegistry.get()` raises `RegistryError`.

### Anti-Patterns to Avoid

- **Import `register_agents.py` at module level in `base_group_service.py`**: leads to circular imports (Ring 1 module importing Ring 1 agent modules at module load). Use lazy import inside `_setup()` instead.
- **Calling `AgentRegistry.build()` before `_import_all()`**: `_REGISTRY` will be empty and every agent_id lookup fails. Always call `_import_all()` first.
- **Putting `SwarmDeps` in `src/intelligence/`**: it is Ring 0 infrastructure used by `src/core/ai/base_agent.py`; placing it in Ring 1 creates an upward dependency violation.
- **Making `AgentRegistry.build()` async**: the construction path is synchronous by design (no I/O); async would complicate the fail-fast guarantee. `MLEvaluator._setup_models()` remains a separate async call after build.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| YAML validation with clear errors | Custom dict walking | `AgentSpec(BaseModel)` with `extra="forbid"` | Pydantic gives field-level errors with path; `ValidationError` has line-number context |
| Duplicate agent_id detection | Manual set tracking | `__init_subclass__` with early raise | Fires at import time, not at runtime; impossible to miss |
| Type-safe dependency passing | `**kwargs` dict | `SwarmDeps` dataclass | `mypy` catches wrong field access at type-check time, not silently at runtime |

---

## Common Pitfalls

### Pitfall 1: `SkepticEvaluator.agent_id = "skeptic"` — No Version Suffix
**What goes wrong:** YAML entry uses `agent_id: skeptic_v1` but the class has `agent_id = "skeptic"`. Registry lookup fails with `RegistryError: unknown agent_id 'skeptic_v1'`.
**Why it happens:** AUTHORING.md says use `<concept>_v<N>` pattern but `SkepticEvaluator` predates that rule.
**How to avoid:** Read `agent_id` class attribute directly from source before writing `agents.yaml`. Grep: `grep -rn "agent_id = " src/intelligence/ai/`.
**Warning signs:** `RegistryError` on startup listing known IDs that don't include `skeptic_v1`.

### Pitfall 2: `__init_subclass__` Fires for Intermediate Base Classes
**What goes wrong:** `Evaluator` inherits `BaseAIWorker` and has `agent_id = ""` (inherited). If the guard `if cls.agent_id:` is missing, `Evaluator` registers with key `""` and overwrites silently.
**Why it happens:** `__init_subclass__` fires for every class in the MRO that inherits the base.
**How to avoid:** Guard: `if cls.agent_id:` — only register when `agent_id` is non-empty. `BaseAIWorker.agent_id = ""` and `Evaluator` inherits it, so both are safely skipped.

### Pitfall 3: `MLEvaluator._setup_models()` Lost After Registry Migration
**What goes wrong:** `AlphaSwarm._setup()` today calls `await self._agents[-1]._setup_models()` by index, which is fragile but works when the list is hardcoded in order. After registry migration, `ml_scorer_v1` may not be last.
**Why it happens:** The registry builds agents in YAML order; no guarantee `ml_scorer_v1` is last.
**How to avoid:** In `AlphaSwarm._setup()`, find `MLEvaluator` by type after registry build: `ml = next((a for a in self._agents if isinstance(a, MLEvaluator)), None)`. Call `await ml._setup_models()` if found.

### Pitfall 4: Shadow Config Propagation Broken After Registry Migration
**What goes wrong:** `AlphaSwarm._setup()` currently propagates `ai.agent.*` config keys from `self._config_cache` to each agent's `_config_cache` and calls `_apply_shadow_mode_config()` after constructing agents. After registry migration, this loop must still run — but the agents are now built inside `AgentRegistry.build()`, not in `AlphaSwarm._setup()`.
**Why it happens:** `BaseSwarmCoordinator._setup()` builds agents before `AlphaSwarm._setup()` can propagate config keys (super() runs first).
**How to avoid:** Keep the config propagation loop in `AlphaSwarm._setup()` after `super()._setup()` returns. The loop iterates `self._agents` (already populated by super). Order: super()._setup() → config propagation → _apply_shadow_mode_config() → _setup_models() — same as today, just without the manual construction step.

### Pitfall 5: `_REGISTRY` Populated Before `AGENT_MODULES` Imported
**What goes wrong:** If a service imports `src.core.ai.registry` but never imports `register_agents`, `_REGISTRY` is empty at `AgentRegistry.build()` time. All agent lookups raise `RegistryError`.
**Why it happens:** `__init_subclass__` only fires when the class definition is executed. That happens on module import. If the module is never imported, the class is never registered.
**How to avoid:** `_import_all()` called unconditionally inside `BaseSwarmCoordinator._setup()` before `AgentRegistry.build()`. Tests that test the registry must also call `_import_all()` or import agent modules directly.

### Pitfall 6: YAML `risk: []` Breaks `AgentRegistry.validate()`
**What goes wrong:** `AgentRegistry.validate("risk", [])` raises `RegistryConfigError: at least one agent required for group 'risk'` if the validation check requires non-empty spec lists for all groups.
**Why it happens:** D-06 states validation checks "at least one agent is defined for the group" but `risk:` is scaffolded empty in Phase 096.
**How to avoid:** Change validation to: "at least one agent required only if the group has a service instantiated." The `risk` group has no `BaseSwarmCoordinator` subclass in Phase 096, so `AgentRegistry.build("risk", deps)` is never called. The empty `risk: []` section is inert. Alternatively, emit a `logger.warning` for empty groups rather than raising.

---

## Code Examples

### Agent ID Audit (run before writing agents.yaml)

```bash
grep -rn "agent_id = " /home/bg/dev/indicagent/src/intelligence/ai/
```

Current confirmed values (from source inspection):
- `skeptic_agent.py`: `agent_id = "skeptic"`
- `ml_scorer_agent.py`: `agent_id = "ml_scorer_v1"`
- `narrative_agent.py`: `agent_id = "narrative_v1"`
- `correlation_agent.py`: verify (pattern suggests `"correlation_v1"`)
- `regime_coherence_agent.py`: verify (pattern suggests `"regime_coherence_v1"`)
- `counterfactual_agent.py`: verify (pattern suggests `"counterfactual_v1"`)

### `shadow_registry_ensure` Pattern (reuse unchanged)

```python
# Source: src/intelligence/register_plugins.py:645
async def shadow_registry_ensure(conn, component_name: str, component_type: str) -> None:
    await conn.execute(
        "INSERT INTO shadow_registry (component_name, component_type) "
        "VALUES ($1, $2) ON CONFLICT (component_name) DO NOTHING",
        component_name, component_type,
    )
```

`_shadow_registry_ensure_agents()` in `base_group_service.py` already wraps this for the `swarm_agent` type. Keep it unchanged; it iterates `self._agents` which is populated by the registry.

### YAML Loading Pattern

```python
# Source: PyYAML — standard library usage
import yaml
from pathlib import Path

def _load_specs(group: str) -> list[AgentSpec]:
    yaml_path = Path("config/agents.yaml")
    if not yaml_path.exists():
        raise RegistryConfigError(f"agents.yaml not found at {yaml_path.absolute()}")
    with yaml_path.open() as f:
        raw = yaml.safe_load(f)
    group_entries = raw.get(group, [])
    specs = []
    for entry in group_entries:
        try:
            specs.append(AgentSpec.model_validate(entry))
        except ValidationError as exc:
            raise RegistryConfigError(
                f"Invalid agent spec in group '{group}': {exc}"
            ) from exc
    return specs
```

**Use `yaml.safe_load()` not `yaml.load()`** — safe_load prevents arbitrary Python object deserialization.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hardcoded `self._agents = [...]` in each swarm `_setup()` | YAML-driven `AgentRegistry.build()` | Phase 096 | Operators add agents without Python changes |
| Loose `llm_chain=`, `pool=` kwargs | Typed `SwarmDeps` dataclass | Phase 096 | `mypy` catches wrong dep at type-check time; Phase 097 adds `memory_client` without touching agents |
| No class discovery mechanism | `__init_subclass__` self-registration | Phase 096 | Duplicate `agent_id` caught at import time; unknown IDs caught at startup |

---

## Open Questions

1. **`correlation_agent.py`, `regime_coherence_agent.py`, `counterfactual_agent.py` exact `agent_id` values**
   - What we know: AUTHORING.md specifies `<concept>_v<N>` pattern; `skeptic_agent.py` is the exception with `agent_id = "skeptic"` (pre-dates the rule)
   - What's unclear: Whether `correlation_agent.py` uses `"correlation_v1"` or just `"correlation"` (like skeptic)
   - Recommendation: Run `grep -rn 'agent_id = ' src/intelligence/ai/alpha/` before writing `agents.yaml`. This is a 30-second check; do not assume.

2. **`NarrativeSynthesizer.shadow_only = False` — conflict with D-05**
   - What we know: `NarrativeSynthesizer` has `shadow_only = False` at line 44 of `narrative_agent.py`. D-05 says YAML `shadow_only: false` is rejected. D-05 also says YAML `shadow_only: true` is the only valid value and cannot force promotion.
   - What's unclear: If `narrative_v1` has `shadow_only = False` in its class definition, does the DB authority principle mean the registry sets it to True on construction and relies solely on DB? Or does the class attribute `False` take precedence until YAML explicitly sets `True`?
   - Recommendation: Treat `NarrativeSynthesizer.shadow_only = False` as a class default that the registry leaves alone (no YAML override = class attribute wins). The DB `is_shadow` column is the gate for actual signal emission; `shadow_only = False` on the class means narratives are not gated by the same graduation path as alpha agents. This is intentional and consistent with the existing code — narrative text has no `pnl_r` correlation axis. The `AgentSpec._reject_force_production` validator only applies when YAML explicitly sets `shadow_only: false`, not when the class attribute is already `False`.

3. **`config/agents.yaml` load path — relative vs absolute**
   - What we know: Services run from the project root via systemd `WorkingDirectory=/home/bg/dev/indicagent`
   - What's unclear: If `AgentRegistry` is unit-tested, `Path("config/agents.yaml")` will fail unless tests set CWD or pass a path override
   - Recommendation: Accept an optional `yaml_path` parameter in `_load_specs()` that defaults to `Path("config/agents.yaml")`. Tests pass an explicit path. Production uses the default.

---

## Sources

### Primary (HIGH confidence)
- `src/core/ai/base_agent.py` — `BaseAIWorker.__init_subclass__`, `__init__` signature, all class attributes
- `src/intelligence/ai/base_group_service.py` — `BaseSwarmCoordinator._setup()` full lifecycle, `_shadow_registry_ensure_agents()`
- `services/alpha_swarm.py:154–198` — hardcoded construction pattern being replaced; config propagation loop; MLEvaluator async setup call
- `services/narrative_swarm.py:67–78` — `NarrativeSynthesizer` construction pattern
- `src/core/ai/evaluator.py` — `Evaluator` base; confirms no `__init__` override (inherits `BaseAIWorker.__init__`)
- `src/intelligence/ai/alpha/skeptic_agent.py` — canonical agent pattern; confirmed `agent_id = "skeptic"`, `_apply_shadow_mode_config()`
- `src/intelligence/ai/alpha/ml_scorer_agent.py` — confirmed `pool`-only constructor pattern
- `src/intelligence/ai/narrative/narrative_agent.py` — confirmed `shadow_only = False`, `llm_chain` constructor
- `src/intelligence/register_plugins.py:630–673` — `TIER_I7` explicit list pattern; `shadow_registry_ensure()` signature

### Secondary (MEDIUM confidence)
- `src/intelligence/ai/AUTHORING.md` — agent authoring protocol; `agent_id` naming convention; shadow enrollment flow
- `src/intelligence/ai/TEMPLATE.py` — canonical agent skeleton; constructor pattern
- `.planning/phases/096-agent-registry/096-CONTEXT.md` — all locked decisions (D-01 through D-06)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages required; PyYAML and pydantic verified present
- Architecture: HIGH — all six files read directly; patterns extracted from running code
- Pitfalls: HIGH — all six pitfalls are grounded in specific code lines observed in source
- Agent ID values: MEDIUM — `skeptic`, `ml_scorer_v1`, `narrative_v1` confirmed; alpha group agents 2-4 need grep verification

**Research date:** 2026-06-01
**Valid until:** 2026-07-01 (stable domain; no external dependencies to drift)
