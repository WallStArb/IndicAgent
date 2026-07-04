# Phase 4: Agent Registry Implementation Plan

**Version:** 1.0
**Status:** archived
**Last Updated:** 2026-05-20
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a central `AgentRegistry` that loads `AgentSpec` from YAML files, instantiates `PydanticAIAgent` on demand, and enables user-created agents without writing any Python subclass.

**Architecture:** `AgentRegistry` scans an `agents/` directory at startup, parses YAML specs, and returns fully-configured `PydanticAIAgent` instances. User-defined agents use a `GenericMultiplierResult` (multiplier + confidence + reasoning) so no custom Python is needed. The 4 existing hard-coded alpha agents become YAML-backed built-ins. `AlphaSwarmComputeAgent` calls `registry.build_agents(model, settings)` instead of listing factory functions directly.

**Phase dependencies:** Phase 3 (Pydantic AI) must be merged first — the registry produces `PydanticAIAgent` instances and calls the factory functions from `pydantic_agents.py`.

**Spec:** `docs/plans/2026-05-20-agent-platform-redesign.md` — Layer 5 (Agent Registry)

**Note:** This is Phase 4 of 7.
- Phase 1: LiteLLM backend — `docs/plans/2026-05-20-phase1-litellm.md`
- Phase 2: Instructor structured output — `docs/plans/2026-05-20-phase2-instructor.md`
- Phase 3: Pydantic AI agents — `docs/plans/2026-05-20-phase3-pydantic-ai.md`
- Phase 5: Zep memory
- Phase 6: DSPy optimizer
- Phase 7: Guardrails AI

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `src/core/ai/agent_spec.py` | `AgentSpec` dataclass, YAML parsing, `MemorySchema` stub |
| Create | `src/core/ai/result_types.py` | `GenericMultiplierResult` — default result type for user YAML agents |
| Create | `src/core/ai/agent_registry.py` | `AgentRegistry` — scan `agents/`, build `PydanticAIAgent` list |
| Create | `agents/` | YAML agent spec files (built-ins + user-created) |
| Create | `agents/skeptic_v1.yaml` | YAML spec for the existing skeptic agent |
| Create | `agents/correlation_v1.yaml` | YAML spec for the existing correlation agent |
| Create | `agents/counterfactual_v1.yaml` | YAML spec for the existing counterfactual agent |
| Create | `agents/regime_coherence_v1.yaml` | YAML spec for the existing regime coherence agent |
| Create | `agents/example_momentum_v1.yaml` | Example user-created agent spec |
| Modify | `services/alpha_swarm_agent.py` | Replace factory list with `registry.build_agents(model, settings)` |
| Create | `tests/unit/ai_agent_tests/test_agent_registry.py` | Unit tests for `AgentRegistry` |

---

## Task 1: Create `GenericMultiplierResult` and result type registry

**Files:**
- Create: `src/core/ai/result_types.py`

This module defines `GenericMultiplierResult` — the result type for user YAML agents — and a lookup dict so the registry can resolve `result_type` strings from YAML.

- [ ] **Step 1: Create `src/core/ai/result_types.py`**

```python
"""Built-in result types for agent registry.

YAML-defined user agents use GenericMultiplierResult by default.
Built-in agents (skeptic, correlation, etc.) use their own result models
defined in their *_prompts.py files and are registered here by string name.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class GenericMultiplierResult(BaseModel):
    """Default result type for user-created YAML agents.

    multiplier: 0.0 = full suppress, 1.0 = neutral, 2.0 = full amplify.
    confidence: 0.0–1.0 how certain the agent is of its assessment.
    reasoning: brief explanation (max 200 words).
    """

    multiplier: float = Field(ge=0.0, le=2.0)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(max_length=800)
```

The built-in result types (SkepticResult, CorrelationResult, etc.) will be registered in Task 3 alongside the registry — not here — to avoid circular imports.

- [ ] **Step 2: Verify import**

```bash
.venv/bin/python -c "from src.core.ai.result_types import GenericMultiplierResult; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/core/ai/result_types.py
git commit -m "feat(ai): add GenericMultiplierResult — default result type for YAML user agents"
```

---

## Task 2: Create `AgentSpec` dataclass and YAML parser

**Files:**
- Create: `src/core/ai/agent_spec.py`

`AgentSpec` is a frozen dataclass that carries everything needed to instantiate a `PydanticAIAgent`. YAML files map 1:1 to `AgentSpec` instances.

- [ ] **Step 1: Create `src/core/ai/agent_spec.py`**

```python
"""AgentSpec — configuration record loaded from YAML agent definition files.

Each YAML file in agents/ deserializes to one AgentSpec.
The AgentRegistry reads these at startup and builds PydanticAIAgent instances.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.core.ai.context import Tier


@dataclass(frozen=True)
class AgentSpec:
    """Immutable agent configuration loaded from a YAML spec file.

    Fields map directly to YAML keys. result_type is a string name resolved
    by AgentRegistry against its result_type_registry dict.
    dspy_program and memory_schema are stubs for Phase 6 and Phase 5 respectively.
    """

    agent_id: str
    group: str
    tiers_needed: frozenset[Tier]
    latency_budget_ms: float
    shadow_only: bool
    system_prompt: str
    result_type: str                      # resolved to a class by AgentRegistry
    prompt_version: str = ""              # defaults to agent_id if empty
    dspy_program: str | None = None       # Phase 6: path to compiled artifact
    memory_schema: str | None = None      # Phase 5: Zep schema name


def load_spec(path: Path) -> AgentSpec:
    """Parse a YAML file into an AgentSpec. Raises ValueError on missing keys."""
    raw: dict[str, Any] = yaml.safe_load(path.read_text())

    required = {"agent_id", "group", "tiers_needed", "latency_budget_ms",
                "shadow_only", "system_prompt", "result_type"}
    missing = required - set(raw)
    if missing:
        raise ValueError(f"{path.name}: missing required keys: {missing}")

    tiers = frozenset(Tier(t) for t in raw["tiers_needed"])
    prompt_version = raw.get("prompt_version") or raw["agent_id"]

    return AgentSpec(
        agent_id=raw["agent_id"],
        group=raw["group"],
        tiers_needed=tiers,
        latency_budget_ms=float(raw["latency_budget_ms"]),
        shadow_only=bool(raw["shadow_only"]),
        system_prompt=raw["system_prompt"],
        result_type=raw["result_type"],
        prompt_version=prompt_version,
        dspy_program=raw.get("dspy_program"),
        memory_schema=raw.get("memory_schema"),
    )


def load_specs_from_dir(directory: Path) -> list[AgentSpec]:
    """Load all *.yaml files from directory. Returns empty list if dir missing."""
    if not directory.exists():
        return []
    specs = []
    for path in sorted(directory.glob("*.yaml")):
        specs.append(load_spec(path))
    return specs
```

- [ ] **Step 2: Add PyYAML to requirements.txt** (it's almost certainly already present — verify first)

```bash
grep "pyyaml\|PyYAML" requirements.txt
```

If missing, add: `PyYAML>=6.0`

- [ ] **Step 3: Verify import**

```bash
.venv/bin/python -c "from src.core.ai.agent_spec import load_spec; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add src/core/ai/agent_spec.py
git commit -m "feat(ai): add AgentSpec dataclass and YAML loader"
```

---

## Task 3: Write failing tests for `AgentRegistry`

**Files:**
- Create: `tests/unit/ai_agent_tests/test_agent_registry.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for AgentRegistry — YAML spec loading and PydanticAIAgent instantiation."""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.core.ai.agent_registry import AgentRegistry
from src.core.ai.agent_spec import AgentSpec, load_spec
from src.core.ai.context import Tier
from src.core.ai.pydantic_agent import PydanticAIAgent


# ── load_spec unit tests ─────────────────────────────────────────────────────

def test_load_spec_parses_valid_yaml(tmp_path: Path):
    yaml_content = textwrap.dedent("""\
        agent_id: test_v1
        group: alpha
        tiers_needed: [i1, i7]
        latency_budget_ms: 30000
        shadow_only: true
        result_type: GenericMultiplierResult
        system_prompt: "OUTPUT ONLY RAW JSON."
    """)
    f = tmp_path / "test_v1.yaml"
    f.write_text(yaml_content)

    spec = load_spec(f)

    assert spec.agent_id == "test_v1"
    assert spec.group == "alpha"
    assert Tier.I1 in spec.tiers_needed
    assert Tier.I7 in spec.tiers_needed
    assert spec.latency_budget_ms == 30000.0
    assert spec.shadow_only is True
    assert spec.result_type == "GenericMultiplierResult"
    assert spec.prompt_version == "test_v1"   # defaults to agent_id


def test_load_spec_raises_on_missing_key(tmp_path: Path):
    f = tmp_path / "bad.yaml"
    f.write_text("agent_id: only_one_field\n")

    with pytest.raises(ValueError, match="missing required keys"):
        load_spec(f)


def test_load_spec_explicit_prompt_version(tmp_path: Path):
    yaml_content = textwrap.dedent("""\
        agent_id: test_v1
        group: alpha
        tiers_needed: [i7]
        latency_budget_ms: 5000
        shadow_only: true
        result_type: GenericMultiplierResult
        system_prompt: "..."
        prompt_version: test_v2
    """)
    f = tmp_path / "test_v1.yaml"
    f.write_text(yaml_content)
    spec = load_spec(f)
    assert spec.prompt_version == "test_v2"


# ── AgentRegistry unit tests ─────────────────────────────────────────────────

def _make_registry(agents_dir: Path) -> AgentRegistry:
    return AgentRegistry(agents_dir=agents_dir)


def test_registry_returns_empty_list_when_dir_missing(tmp_path: Path):
    registry = _make_registry(tmp_path / "nonexistent")
    model = MagicMock()
    settings = MagicMock()
    agents = registry.build_agents(model, settings)
    assert isinstance(agents, list)
    assert len(agents) == 0


def test_registry_builds_generic_agent_from_yaml(tmp_path: Path):
    yaml_content = textwrap.dedent("""\
        agent_id: momentum_v1
        group: alpha
        tiers_needed: [i1, i4, i6, i7]
        latency_budget_ms: 30000
        shadow_only: true
        result_type: GenericMultiplierResult
        system_prompt: "OUTPUT ONLY RAW JSON. {multiplier: float, confidence: float, reasoning: str}"
    """)
    (tmp_path / "momentum_v1.yaml").write_text(yaml_content)

    registry = _make_registry(tmp_path)
    model = MagicMock()
    settings = MagicMock()

    agents = registry.build_agents(model, settings)

    assert len(agents) == 1
    agent = agents[0]
    assert isinstance(agent, PydanticAIAgent)
    assert agent.agent_id == "momentum_v1"
    assert agent.shadow_only is True
    assert Tier.I1 in agent.tiers_needed
    assert agent.latency_budget_ms == 30000.0


def test_registry_raises_on_unknown_result_type(tmp_path: Path):
    yaml_content = textwrap.dedent("""\
        agent_id: bad_v1
        group: alpha
        tiers_needed: [i7]
        latency_budget_ms: 5000
        shadow_only: true
        result_type: NoSuchResult
        system_prompt: "..."
    """)
    (tmp_path / "bad_v1.yaml").write_text(yaml_content)

    registry = _make_registry(tmp_path)
    with pytest.raises(ValueError, match="Unknown result_type"):
        registry.build_agents(MagicMock(), MagicMock())


def test_registry_loads_multiple_yamls(tmp_path: Path):
    base = textwrap.dedent("""\
        agent_id: {aid}
        group: alpha
        tiers_needed: [i7]
        latency_budget_ms: 5000
        shadow_only: true
        result_type: GenericMultiplierResult
        system_prompt: "OUTPUT ONLY RAW JSON."
    """)
    for name in ("agent_a", "agent_b", "agent_c"):
        (tmp_path / f"{name}.yaml").write_text(base.format(aid=name))

    registry = _make_registry(tmp_path)
    agents = registry.build_agents(MagicMock(), MagicMock())
    assert len(agents) == 3
    ids = {a.agent_id for a in agents}
    assert ids == {"agent_a", "agent_b", "agent_c"}
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/unit/ai_agent_tests/test_agent_registry.py -v 2>&1 | head -15
```

Expected: `ModuleNotFoundError: No module named 'src.core.ai.agent_registry'`

---

## Task 4: Implement `AgentRegistry`

**Files:**
- Create: `src/core/ai/agent_registry.py`

- [ ] **Step 1: Read PydanticAIAgent constructor from Phase 3**

```bash
grep -n "def __init__\|prompt_fn\|multiplier_fn\|pydantic_agent" src/core/ai/pydantic_agent.py | head -15
```

Note the exact parameter names needed.

- [ ] **Step 2: Create `src/core/ai/agent_registry.py`**

```python
"""AgentRegistry — scan agents/ directory and build PydanticAIAgent instances.

Two categories of agents are supported:

1. Built-in agents (skeptic, correlation, counterfactual, regime_coherence):
   Their YAML sets result_type to "SkepticResult" etc. The registry delegates
   to the Phase 3 factory functions (make_skeptic_agent, etc.) so their
   prompt builders and multiplier logic stay in pydantic_agents.py.

2. User-created agents (result_type: "GenericMultiplierResult"):
   Registry builds a PydanticAIAgent directly using a generic multiplier_fn
   that reads (multiplier, confidence) fields from the result.

Phase 5 will add memory enrichment via @agent.system_prompt hooks after the
pydantic_ai.Agent is constructed here.
Phase 6 will load compiled DSPy programs when spec.dspy_program is set.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel
from pydantic_ai import Agent

from src.core.ai.agent_spec import AgentSpec, load_specs_from_dir
from src.core.ai.context import AIContext, Tier
from src.core.ai.pydantic_agent import AgentDeps, PydanticAIAgent
from src.core.ai.result_types import GenericMultiplierResult

logger = structlog.get_logger(__name__)

# Map YAML result_type string → Pydantic model class.
# Built-in agent result types are registered alongside their factory functions.
_RESULT_TYPE_REGISTRY: dict[str, type[BaseModel]] = {
    "GenericMultiplierResult": GenericMultiplierResult,
}

# Map agent_id prefix → factory function for built-in agents.
# Built-ins are recognized by their agent_id; the factory handles prompt/multiplier logic.
_BUILTIN_FACTORIES: dict[str, str] = {
    "skeptic_v1": "make_skeptic_agent",
    "correlation_v1": "make_correlation_agent",
    "counterfactual_v1": "make_counterfactual_agent",
    "regime_coherence_v1": "make_regime_coherence_agent",
}


def _register_builtin_result_types() -> None:
    """Lazy-import built-in result types to avoid circular imports at module load."""
    try:
        from src.intelligence.ai.alpha.skeptic_prompts import SkepticResult
        from src.intelligence.ai.alpha.correlation_agent import CorrelationResult
        from src.intelligence.ai.alpha.counterfactual_agent import CounterfactualResult
        from src.intelligence.ai.alpha.regime_coherence_agent import RegimeCoherenceResult

        _RESULT_TYPE_REGISTRY.update({
            "SkepticResult": SkepticResult,
            "CorrelationResult": CorrelationResult,
            "CounterfactualResult": CounterfactualResult,
            "RegimeCoherenceResult": RegimeCoherenceResult,
        })
    except ImportError as exc:
        logger.warning("agent_registry.builtin_import_failed", error=str(exc))


def _build_generic_agent(spec: AgentSpec, model: Any, settings: Any) -> PydanticAIAgent:
    """Construct a PydanticAIAgent for user-created YAML agents using GenericMultiplierResult."""
    system_prompt = spec.system_prompt
    if not system_prompt.startswith("OUTPUT ONLY RAW JSON"):
        system_prompt = (
            "OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE. "
            + system_prompt
            + ' Begin your response with { and end with }.'
        )

    pydantic_agent: Agent[AgentDeps, GenericMultiplierResult] = Agent(
        model=model,
        result_type=GenericMultiplierResult,
        system_prompt=system_prompt,
        deps_type=AgentDeps,
    )

    def _prompt_fn(ctx: AIContext) -> str:
        return (
            f"Symbol: {ctx.symbol}  Timeframe: {ctx.timeframe}\n"
            f"Analyze the trading setup and return your assessment.\n"
            f'End your response with {{ "multiplier": <0-2>, "confidence": <0-1>, "reasoning": "<text>" }}'
        )

    def _multiplier_fn(r: GenericMultiplierResult) -> tuple[float, float]:
        return r.multiplier, r.confidence

    return PydanticAIAgent(
        agent_id=spec.agent_id,
        group=spec.group,
        tiers_needed=spec.tiers_needed,
        latency_budget_ms=spec.latency_budget_ms,
        shadow_only=spec.shadow_only,
        prompt_version=spec.prompt_version,
        pydantic_agent=pydantic_agent,
        prompt_fn=_prompt_fn,
        multiplier_fn=_multiplier_fn,
        settings=settings,
    )


def _build_builtin_agent(spec: AgentSpec, model: Any, settings: Any) -> PydanticAIAgent:
    """Delegate to the Phase 3 factory function for built-in agents."""
    from src.intelligence.ai.alpha import pydantic_agents as factories

    factory_name = _BUILTIN_FACTORIES[spec.agent_id]
    factory_fn = getattr(factories, factory_name)
    return factory_fn(model, settings)


class AgentRegistry:
    """Loads AgentSpec from YAML files and produces PydanticAIAgent instances.

    Usage:
        registry = AgentRegistry(agents_dir=Path("agents"))
        agents = registry.build_agents(model, settings)
        # agents is list[PydanticAIAgent] — pass directly to AlphaSwarmComputeAgent
    """

    def __init__(self, agents_dir: Path | None = None) -> None:
        self._agents_dir = agents_dir or Path("agents")
        _register_builtin_result_types()

    def build_agents(self, model: Any, settings: Any) -> list[PydanticAIAgent]:
        """Load all YAML specs from agents_dir and instantiate PydanticAIAgent for each."""
        specs = load_specs_from_dir(self._agents_dir)
        if not specs:
            logger.info("agent_registry.no_specs_found", agents_dir=str(self._agents_dir))
            return []

        agents: list[PydanticAIAgent] = []
        for spec in specs:
            agent = self._build_one(spec, model, settings)
            agents.append(agent)
            logger.info(
                "agent_registry.loaded",
                agent_id=spec.agent_id,
                group=spec.group,
                shadow_only=spec.shadow_only,
            )

        return agents

    def _build_one(self, spec: AgentSpec, model: Any, settings: Any) -> PydanticAIAgent:
        if spec.agent_id in _BUILTIN_FACTORIES:
            return _build_builtin_agent(spec, model, settings)

        result_cls = _RESULT_TYPE_REGISTRY.get(spec.result_type)
        if result_cls is None:
            raise ValueError(
                f"Unknown result_type '{spec.result_type}' in agent '{spec.agent_id}'. "
                f"Known types: {sorted(_RESULT_TYPE_REGISTRY)}"
            )

        return _build_generic_agent(spec, model, settings)
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest tests/unit/ai_agent_tests/test_agent_registry.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/core/ai/agent_registry.py tests/unit/ai_agent_tests/test_agent_registry.py
git commit -m "feat(ai): add AgentRegistry — YAML-driven agent instantiation, no subclassing required"
```

---

## Task 5: Create YAML agent spec files for the 4 built-in agents

**Files:**
- Create: `agents/skeptic_v1.yaml`
- Create: `agents/correlation_v1.yaml`
- Create: `agents/counterfactual_v1.yaml`
- Create: `agents/regime_coherence_v1.yaml`
- Create: `agents/example_momentum_v1.yaml`

- [ ] **Step 1: Verify current agent_id, latency_budget_ms, shadow_only for each built-in**

```bash
grep -n "agent_id\|latency_budget_ms\|shadow_only" \
  src/intelligence/ai/alpha/skeptic_agent.py \
  src/intelligence/ai/alpha/correlation_agent.py \
  src/intelligence/ai/alpha/counterfactual_agent.py \
  src/intelligence/ai/alpha/regime_coherence_agent.py | grep -v "self\."
```

Also confirm from Phase 3 factory functions if already implemented:

```bash
grep -n "agent_id=\|latency_budget_ms=\|shadow_only=" \
  src/intelligence/ai/alpha/pydantic_agents.py 2>/dev/null | head -20
```

Use the values you find. The files below use the values from the spec — adjust if they differ.

- [ ] **Step 2: Create `agents/skeptic_v1.yaml`**

```yaml
# Built-in agent — do not change agent_id or result_type.
# The registry delegates to make_skeptic_agent() for prompt/multiplier logic.
agent_id: skeptic_v1
group: alpha
tiers_needed: [i1, i4, i6, i7, smc]
latency_budget_ms: 120000
shadow_only: false
result_type: SkepticResult
system_prompt: |
  OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE.
  Your entire response must be a single JSON object starting with { and ending with }.
  Schema: {"failure_probability": float, "confidence": float,
  "risk_factors": [str], "reasoning": str}
  reasoning must be under 100 words.
  Begin your response with { and end with }.
prompt_version: skeptic_v1
```

- [ ] **Step 3: Create `agents/correlation_v1.yaml`**

```yaml
agent_id: correlation_v1
group: alpha
tiers_needed: [i1, i4, i6]
latency_budget_ms: 120000
shadow_only: true
result_type: CorrelationResult
system_prompt: |
  OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE.
  Schema: {"coherence_score": float, "confidence": float,
  "contradicting_assets": [str], "reasoning": str}
  Begin your response with { and end with }.
prompt_version: correlation_v1
```

- [ ] **Step 4: Create `agents/counterfactual_v1.yaml`**

```yaml
agent_id: counterfactual_v1
group: alpha
tiers_needed: [i4, i6, i7]
latency_budget_ms: 120000
shadow_only: true
result_type: CounterfactualResult
system_prompt: |
  OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE.
  Schema: {"plausibility": float, "confidence": float,
  "validation_conditions": [str], "invalidation_conditions": [str],
  "alternative_scenario": str}
  Begin your response with { and end with }.
prompt_version: counterfactual_v1
```

- [ ] **Step 5: Create `agents/regime_coherence_v1.yaml`**

```yaml
agent_id: regime_coherence_v1
group: alpha
tiers_needed: [i4, smc]
latency_budget_ms: 120000
shadow_only: true
result_type: RegimeCoherenceResult
system_prompt: |
  OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE.
  Schema: {"regime_fit": float, "confidence": float,
  "supporting_factors": [str], "warning_factors": [str]}
  Begin your response with { and end with }.
prompt_version: regime_coherence_v1
```

- [ ] **Step 6: Create `agents/example_momentum_v1.yaml`**

This is the reference example for user-created agents. It uses `GenericMultiplierResult` so no Python is required.

```yaml
# Example user-created agent — copy this file and customize.
#
# agent_id must be unique. Use group: alpha for multiplier agents.
# tiers_needed controls which I-tiers must be populated before this agent runs.
# result_type must be "GenericMultiplierResult" for user-created agents.
# shadow_only: true means this agent runs but its output is not applied to signals.
#   The graduation_loop will flip it to false once performance criteria are met.
#
# system_prompt must instruct the model to output ONLY raw JSON matching:
#   {"multiplier": float 0-2, "confidence": float 0-1, "reasoning": str}
agent_id: example_momentum_v1
group: alpha
tiers_needed: [i1, i4]
latency_budget_ms: 30000
shadow_only: true
result_type: GenericMultiplierResult
system_prompt: |
  OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE.
  You are a momentum quality agent. Given a trading setup, assess whether
  momentum indicators confirm or contradict the signal direction.
  Return: {"multiplier": float between 0.0 and 2.0 where 1.0 is neutral,
  "confidence": float between 0.0 and 1.0,
  "reasoning": "brief explanation under 100 words"}
  Begin your response with { and end with }.
prompt_version: example_momentum_v1
```

- [ ] **Step 7: Verify the built-in YAMLs parse cleanly**

```bash
.venv/bin/python - <<'EOF'
from pathlib import Path
from src.core.ai.agent_spec import load_specs_from_dir

specs = load_specs_from_dir(Path("agents"))
for s in specs:
    print(f"  {s.agent_id}: tiers={sorted(t.value for t in s.tiers_needed)}, shadow={s.shadow_only}")
EOF
```

Expected: 5 specs listed (4 built-ins + example), no errors.

- [ ] **Step 8: Commit**

```bash
git add agents/
git commit -m "feat(agents): add YAML specs for 4 built-in agents and example user agent"
```

---

## Task 6: Wire `AgentRegistry` into `AlphaSwarmComputeAgent`

**Files:**
- Modify: `services/alpha_swarm_agent.py`

- [ ] **Step 1: Read the current `_setup` method**

```bash
sed -n '155,180p' services/alpha_swarm_agent.py
```

Note the exact lines that construct `self._agents` and append `MLScorerMultiplierAgent`.

- [ ] **Step 2: Add registry import**

At the top of `services/alpha_swarm_agent.py`, add:

```python
from src.core.ai.agent_registry import AgentRegistry
```

Remove the individual factory function imports from Phase 3 if present:
```python
# Remove these (now handled by registry):
from src.core.ai.pydantic_model import build_pydantic_model
from src.intelligence.ai.alpha.pydantic_agents import (
    make_correlation_agent,
    make_counterfactual_agent,
    make_regime_coherence_agent,
    make_skeptic_agent,
)
```

Keep `build_pydantic_model` — the registry still needs the model object:

```python
from src.core.ai.pydantic_model import build_pydantic_model
from src.core.ai.agent_registry import AgentRegistry
```

- [ ] **Step 3: Update `_setup()` to use the registry**

Replace the block that builds `self._agents` with factory calls with:

```python
_model = build_pydantic_model(self.settings)
registry = AgentRegistry()
self._agents = registry.build_agents(_model, self.settings)
```

Then append `MLScorerMultiplierAgent` after (unchanged):

```python
self._agents.append(MLScorerMultiplierAgent(pool=self._pool))
await self._agents[-1]._setup_models()
```

- [ ] **Step 4: Run unit tests**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short 2>&1 | tail -15
```

Expected: same or fewer failures as before (no regressions).

- [ ] **Step 5: Commit**

```bash
git add services/alpha_swarm_agent.py
git commit -m "feat(alpha_swarm): replace factory list with AgentRegistry — agents now YAML-driven"
```

---

## Task 7: Smoke test and restart

- [ ] **Step 1: Verify registry loads all 5 agents from `agents/` dir**

```bash
.venv/bin/python - <<'EOF'
from pathlib import Path
from unittest.mock import MagicMock
from src.core.ai.agent_registry import AgentRegistry

registry = AgentRegistry(agents_dir=Path("agents"))
agents = registry.build_agents(MagicMock(), MagicMock())
for a in agents:
    print(f"  {a.agent_id}  shadow={a.shadow_only}  budget={a.latency_budget_ms}ms")
EOF
```

Expected: 5 agents listed, no import errors.

- [ ] **Step 2: Restart alpha swarm and verify startup**

```bash
sudo systemctl restart indicagent-alpha-swarm
sleep 6 && systemctl status indicagent-alpha-swarm --no-pager | grep "Active:"
```

Expected: `active (running)`.

- [ ] **Step 3: Check logs for registry load messages**

```bash
grep "agent_registry" logs/alpha_swarm_compute_agent.log | tail -10
```

Expected: 5 `agent_registry.loaded` log lines, one per agent.

- [ ] **Step 4: Check for errors**

```bash
tail -30 logs/alpha_swarm_compute_agent.log | grep -iE "error|failed|traceback"
```

Expected: no errors.

- [ ] **Step 5: Add example user agent and verify it loads without restart**

```bash
# The registry loads at startup — verify the example YAML is included
grep "example_momentum" logs/alpha_swarm_compute_agent.log | tail -3
```

Expected: `agent_registry.loaded agent_id=example_momentum_v1 shadow_only=True`

- [ ] **Step 6: Push**

```bash
git push origin main
```

---

## Verification

Phase 4 is complete when:

- [ ] `AgentSpec` dataclass exists at `src/core/ai/agent_spec.py`
- [ ] `load_spec(path)` / `load_specs_from_dir(dir)` parse YAML files correctly
- [ ] `GenericMultiplierResult` exists at `src/core/ai/result_types.py`
- [ ] `AgentRegistry.build_agents(model, settings)` returns `list[PydanticAIAgent]`
- [ ] Unknown `result_type` raises `ValueError` with the type name in the message
- [ ] `agents/` directory contains 5 YAML files (4 built-ins + 1 example)
- [ ] `AlphaSwarmComputeAgent._setup()` calls `AgentRegistry().build_agents(...)` — no factory list
- [ ] All unit tests pass
- [ ] Alpha swarm restarts cleanly and logs show 5 agents loaded
- [ ] Adding a new YAML file to `agents/` and restarting picks it up automatically

---

## What This Enables

- **User agents without Python:** copy `example_momentum_v1.yaml`, change `agent_id` + `system_prompt` + `tiers_needed`, restart the swarm — new agent is live
- **Phase 5 (Zep memory):** add `@pydantic_agent.system_prompt async def enrich(ctx)` inside `_build_generic_agent()` — applies to ALL user-created agents at once
- **Phase 6 (DSPy):** when `spec.dspy_program` is set, load the compiled artifact in `_build_one()` before constructing the agent
- **A/B testing:** create two YAML files with different `system_prompt` values, both `shadow_only: true`, compare pnl_r via shadow_registry stats

---

## Next: Phase 5 — Zep Memory

When ready, ask for:
> "Write the implementation plan for Phase 5 — Zep episodic memory enrichment."

Phase 5 adds `EpisodicMemoryStore` backed by a self-hosted Zep instance, injects past setup outcomes into agent prompts via `@agent.system_prompt` hooks, and records outcomes when `signal_ledger` writes close a signal.
