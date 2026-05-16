# Phase 80: Renaissance Swarm Intelligence Layer - Pattern Map

**Mapped:** 2026-05-05
**Files analyzed:** 12 new/modified files
**Analogs found:** 12 / 12

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/core/ai/multiplier_agent.py` | base class | request-response | `src/core/ai/base_agent.py` | exact |
| `src/core/ai/prompt_utils.py` | utility | transform | `src/core/ai/prompt_utils.py` (extend) | exact |
| `src/intelligence/ai/alpha/correlation_agent.py` | compute agent | request-response | `src/intelligence/ai/alpha/skeptic_agent.py` | exact |
| `src/intelligence/ai/alpha/correlation_prompts.py` | config/prompts | transform | `src/intelligence/ai/alpha/skeptic_prompts.py` | exact |
| `src/intelligence/ai/alpha/regime_coherence_agent.py` | compute agent | request-response | `src/intelligence/ai/alpha/skeptic_agent.py` | exact |
| `src/intelligence/ai/alpha/regime_coherence_prompts.py` | config/prompts | transform | `src/intelligence/ai/alpha/skeptic_prompts.py` | exact |
| `src/intelligence/ai/alpha/counterfactual_agent.py` | compute agent | request-response | `src/intelligence/ai/alpha/skeptic_agent.py` | exact |
| `src/intelligence/ai/alpha/counterfactual_prompts.py` | config/prompts | transform | `src/intelligence/ai/alpha/skeptic_prompts.py` | exact |
| `src/intelligence/ai/alpha/skeptic_agent.py` | compute agent (refactor) | request-response | `src/core/ai/base_agent.py` + self | exact |
| `services/alpha_swarm_agent.py` | dispatch service (refactor) | event-driven | `services/alpha_swarm_agent.py` (self) | exact |
| `src/config/settings.py` | config (extend) | N/A | `src/config/settings.py` (self) | exact |
| `src/observability/metrics.py` | observability (extend) | N/A | `src/observability/metrics.py` (self) | exact |
| `src/intelligence/ai/TEMPLATE_agent.py` | docs/template (update) | N/A | `src/intelligence/ai/TEMPLATE_agent.py` (self) | exact |
| `production/migrations/082_swarm_weights_and_adjusted_confidence.sql` | migration | CRUD | `.worktrees/codebase-cleanup/production/migrations/081_signal_quality_zones.sql` | role-match |

---

## Pattern Assignments

### `src/core/ai/multiplier_agent.py` (base class, request-response)

**Analog:** `src/core/ai/base_agent.py`

**Imports pattern** (lines 1-17 of base_agent.py):
```python
from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, ClassVar

import structlog

from src.core.agent.base import BaseAgent
from src.core.ai.context import AIContext, Tier
from src.core.ai.output import AgentOutput
from src.observability.metrics import AI_AGENT_DURATION_MS, AI_AGENT_INVOCATIONS_TOTAL
from src.core.ai.prompt_utils import JSON_BLOCK_RE, clamp, parse_llm_json

logger = structlog.get_logger(__name__)
```

**Class declaration pattern** (lines 38-63 of base_agent.py):
```python
class BaseMultiplierAgent(BaseAIAgent, ABC):
    """Abstract base for all multiplier-output swarm agents.

    Provides:
    - _parse_multiplier_response(raw, validator_fn) — try direct JSON → regex fallback → None
    - _build_multiplier_output(multiplier, confidence, payload, prompt_version) — canonical AgentOutput
    - Abstract output_schema: ClassVar[dict] — expected LLM JSON keys; used in parse-failure log

    All concrete agents extend this, never BaseAIAgent directly.
    Phase 80 policy: discount-only (formulas produce multiplier <= 1.0 until calibration data exists).
    Clamp range [0.0, 2.0] preserved in base for future boosting.
    """

    output_schema: ClassVar[dict]  # subclasses document expected LLM JSON keys

    def _parse_multiplier_response(
        self, raw: str, validator_fn
    ) -> dict | None:
        """Parse LLM JSON response: direct parse → regex fallback → None."""
        ...

    def _build_multiplier_output(
        self,
        multiplier: float,
        confidence: float,
        payload: dict,
        prompt_version: str,
    ) -> AgentOutput:
        """Construct canonical AgentOutput with multiplier clamped to [0.0, 2.0]."""
        ...
```

**Core parse pattern** (lines 108-129 of skeptic_agent.py — direct/fallback structure to replicate):
```python
def _parse_multiplier_response(self, raw: str, validator_fn) -> dict | None:
    try:
        data = json.loads(raw.strip())
        return validator_fn(data)
    except json.JSONDecodeError:
        pass

    match = JSON_BLOCK_RE.search(raw)
    if match:
        try:
            data = json.loads(match.group())
            return validator_fn(data)
        except json.JSONDecodeError:
            pass

    return None
```

**Build output pattern** (lines 88-105 of skeptic_agent.py — canonical AgentOutput construction):
```python
def _build_multiplier_output(
    self, multiplier: float, confidence: float, payload: dict, prompt_version: str
) -> AgentOutput:
    return AgentOutput(
        agent_id=self.agent_id,
        group=self.group,
        signal_id=context.signal_id,   # context passed via _compute
        symbol=context.symbol,
        timeframe=context.timeframe,
        ts=context.ts,
        output_type="multiplier",
        payload={
            "multiplier": clamp(multiplier, 0.0, 2.0),
            "confidence": confidence,
            "prompt_version": prompt_version,
            **payload,
        },
        shadow_only=self.shadow_only,
    )
```

**Note:** `_build_multiplier_output` needs `context` in scope. The concrete signature will pass `context: AIContext` alongside the other args, or the method will require the caller to pass `signal_id`, `symbol`, `timeframe`, `ts` fields. Copy the skeptic pattern of building AgentOutput inline in `_compute()` — the base class helper is just a convenience wrapper that calls `AgentOutput(...)` with canonical field order.

---

### `src/core/ai/prompt_utils.py` (utility, transform — ADD three symbols)

**Analog:** `src/core/ai/prompt_utils.py` (self — extend, do not replace)

**Existing content to preserve** (lines 1-19 of prompt_utils.py):
```python
"""Shared utilities for AI agent prompt builders."""
from __future__ import annotations
from typing import Any

DIRECTION_LABELS: dict[int, str] = {1: "LONG", -1: "SHORT", 0: "FLAT"}
REGIME_LABELS: dict[int, str] = {0: "Ranging", 1: "Trending Up", 2: "Trending Down"}

def fmt(val: Any, spec: str) -> str:
    """Format a numeric value with the given format spec, or return N/A."""
    if isinstance(val, (int, float)):
        return format(val, spec)
    return "N/A"
```

**Additions to append** (D-02):
```python
import json
import re
from typing import Any

JSON_BLOCK_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


def parse_llm_json(raw: str, validator_fn) -> dict | None:
    """Try direct JSON parse → regex extract fallback → None on failure.

    Single source of truth for all multiplier agents (moved from skeptic_agent.py).
    """
    try:
        data = json.loads(raw.strip())
        return validator_fn(data)
    except json.JSONDecodeError:
        pass

    match = JSON_BLOCK_RE.search(raw)
    if match:
        try:
            data = json.loads(match.group())
            return validator_fn(data)
        except json.JSONDecodeError:
            pass

    return None


def clamp(val: Any, lo: float, hi: float) -> float:
    """Clamp val to [lo, hi]. max(lo, min(hi, float(val)))."""
    return max(lo, min(hi, float(val)))
```

---

### `src/intelligence/ai/alpha/correlation_agent.py` (compute agent, request-response)

**Analog:** `src/intelligence/ai/alpha/skeptic_agent.py` (exact role and data flow)

**Imports pattern** (from skeptic_agent.py lines 1-24 — adapt for correlation):
```python
from __future__ import annotations

from typing import Any

import structlog

from src.core.ai.base_agent import BaseAIAgent          # replace with BaseMultiplierAgent
from src.core.ai.context import AIContext, Tier
from src.core.ai.output import AgentOutput
from src.core.ai.prompt_utils import clamp, parse_llm_json
from src.core.llm.chain import LLMProviderChain
from src.intelligence.ai.alpha.correlation_prompts import (
    ACTIVE_VERSION,
    build_correlation_prompt,
)

logger = structlog.get_logger(__name__)
```

**Class attributes pattern** (from skeptic_agent.py lines 36-47 — adapt values per D-04):
```python
class CorrelationAgentComputeAgent(BaseMultiplierAgent):
    """Cross-asset coherence agent — does ZN/VIX/ES/CL behavior support this signal?"""

    output_schema: ClassVar[dict] = {
        "coherence_score": float,
        "confidence": float,
        "contradicting_assets": list,
        "reasoning": str,
    }

    agent_id = "correlation_v1"
    group = "alpha"
    tiers_needed = frozenset({Tier.I1, Tier.I4, Tier.I6, Tier.I7})
    latency_budget_ms = 5000.0
    shadow_only = True
```

**Constructor pattern** (from skeptic_agent.py lines 48-50):
```python
    def __init__(self, llm_chain: LLMProviderChain, **kwargs: Any) -> None:
        super().__init__(name=self.__class__.__name__, **kwargs)
        self._llm = llm_chain
```

**Core _compute pattern** (from skeptic_agent.py lines 52-105 — adapt fields):
```python
    async def _compute(self, context: AIContext) -> AgentOutput:
        prompt = build_correlation_prompt(context)

        response = await self._llm.generate(
            prompt=prompt,
            system=_SYSTEM_MESSAGE,
            max_tokens=500,
            timeout=self.latency_budget_ms / 1000.0,
        )

        if not response:
            return self._neutral(error="LLM returned empty response", latency_ms=0.0)

        parsed = self._parse_multiplier_response(response, _validate_correlation_fields)
        if parsed is None:
            logger.warning(
                "correlation_agent.json_parse_failed",
                agent_id=self.agent_id,
                raw_response=response[:200],
                expected_schema=self.output_schema,
            )
            return self._neutral(error="JSON parse failed", latency_ms=0.0)

        coherence_score = parsed["coherence_score"]
        llm_confidence = parsed["confidence"]
        multiplier = coherence_score * llm_confidence  # D-04 formula

        return self._build_multiplier_output(
            context=context,
            multiplier=multiplier,
            confidence=llm_confidence,
            payload={
                "coherence_score": coherence_score,
                "contradicting_assets": parsed["contradicting_assets"],
                "reasoning": parsed["reasoning"],
            },
            prompt_version=ACTIVE_VERSION,
        )
```

**Validator pattern** (from skeptic_agent.py lines 132-161 — adapt field names):
```python
def _validate_correlation_fields(data: dict) -> dict | None:
    if not isinstance(data, dict):
        return None
    score = data.get("coherence_score")
    conf = data.get("confidence")
    if not isinstance(score, (int, float)) or not isinstance(conf, (int, float)):
        return None
    score = clamp(score, 0.0, 1.0)
    conf = clamp(conf, 0.0, 1.0)
    assets = data.get("contradicting_assets", [])
    if not isinstance(assets, list):
        assets = [str(assets)]
    else:
        assets = [str(a) for a in assets]
    reasoning = str(data.get("reasoning", ""))
    return {
        "coherence_score": score,
        "confidence": conf,
        "contradicting_assets": assets,
        "reasoning": reasoning,
    }
```

**Apply same pattern for:** `regime_coherence_agent.py` (fields: `regime_fit`, `confidence`, `mismatches`, `reasoning`; multiplier: `regime_fit × confidence`) and `counterfactual_agent.py` (fields: `plausibility`, `confidence`, `validation_conditions`, `invalidation_conditions`, `reasoning`; multiplier: `plausibility × confidence`).

---

### `src/intelligence/ai/alpha/correlation_prompts.py` (prompts file)

**Analog:** `src/intelligence/ai/alpha/skeptic_prompts.py` (exact structure)

**File structure to copy** (skeptic_prompts.py lines 1-16):
```python
"""correlation_prompts.py -- versioned prompt registry for CorrelationAgent."""
from __future__ import annotations

from typing import Any

from src.core.ai.context import render_full_context
from src.core.ai.prompt_utils import DIRECTION_LABELS, fmt

ACTIVE_VERSION = "correlation_v1"

PROMPT_REGISTRY: dict[str, str] = {
    "correlation_v1": """...""",
}


def build_correlation_prompt(ctx: Any) -> str:
    ...
```

**Version string rule** (from skeptic_prompts.py line 15): `ACTIVE_VERSION` must match `agent_id` — `"correlation_v1"`. This value is written to `signal_lineage.metadata.payload.prompt_version` for attribution.

**Build function pattern** (from skeptic_prompts.py lines 101-151): The `build_*_prompt` function takes an `AIContext`, extracts `i7` for winner plugin/direction/confidence, calls `render_full_context(ctx)` for the full pipeline tier block, and formats the template string. Apply same pattern for `regime_coherence_prompts.py` (`ACTIVE_VERSION = "regime_coherence_v1"`) and `counterfactual_prompts.py` (`ACTIVE_VERSION = "counterfactual_v1"`).

**Example v2 prompt builder** (from skeptic_prompts.py lines 101-124):
```python
def build_correlation_prompt(ctx: Any) -> str:
    from src.core.ai.context import AIContext
    template = PROMPT_REGISTRY[ACTIVE_VERSION]
    if not isinstance(ctx, AIContext):
        raise TypeError(f"correlation_v1 requires AIContext, got {type(ctx).__name__}")
    i7 = ctx.i7
    return template.format(
        symbol=ctx.symbol,
        timeframe=ctx.timeframe,
        winner_plugin=(i7.winner_plugin if i7 else None) or "unknown",
        winner_direction_label=DIRECTION_LABELS.get(
            (i7.winner_direction if i7 else 0) or 0, "UNKNOWN"
        ),
        winner_confidence=fmt(i7.winner_confidence if i7 else None, ".0%"),
        full_context_block=render_full_context(ctx),
    )
```

---

### `src/intelligence/ai/alpha/skeptic_agent.py` (refactor — extend BaseMultiplierAgent)

**Analog:** Self, plus `src/core/ai/base_agent.py` for the new base class contract.

**Changes required** (D-03):
1. Change `from src.core.ai.base_agent import BaseAIAgent` to `from src.core.ai.multiplier_agent import BaseMultiplierAgent`
2. Add `from src.core.ai.prompt_utils import JSON_BLOCK_RE, clamp, parse_llm_json`
3. Change class declaration: `class SkepticAgentComputeAgent(BaseMultiplierAgent):`
4. Add `output_schema: ClassVar[dict] = {"failure_probability": float, "confidence": float, "risk_factors": list, "reasoning": str}`
5. Remove module-level `_JSON_BLOCK_RE` (line 33 in current file)
6. Replace `_parse_skeptic_response()` call in `_compute()` with `self._parse_multiplier_response(response, _validate_skeptic_fields)`
7. Replace manual `AgentOutput(...)` construction in `_compute()` with `self._build_multiplier_output(...)`
8. Replace `max(0.0, min(2.0, multiplier))` inline clamp with `clamp(multiplier, 0.0, 2.0)` from prompt_utils
9. Remove module-level `_parse_skeptic_response()` function (logic moved to base class via `parse_llm_json`)
10. `_validate_skeptic_fields()` and `_context_to_dict()` remain in file — they are agent-specific

**Lines to remove from current file:**
- Line 33: `_JSON_BLOCK_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)`
- Lines 108-129: `def _parse_skeptic_response(...)` function (replaced by base class method)

**Lines to keep unchanged:**
- Lines 132-161: `_validate_skeptic_fields()` — agent-specific field validation
- Lines 164-202: `_context_to_dict()` — v1 rollback adapter, kept per plan

---

### `services/alpha_swarm_agent.py` (dispatch service refactor)

**Analog:** Self (current file as base for refactor)

**Current agent registration** (lines 127-129 — replace with typed list):
```python
# BEFORE (current):
self._agents: list[BaseAIAgent] = [
    SkepticAgentComputeAgent(llm_chain=self._llm_chain),
]

# AFTER (D-07):
from src.core.ai.multiplier_agent import BaseMultiplierAgent
from src.intelligence.ai.alpha.correlation_agent import CorrelationAgentComputeAgent
from src.intelligence.ai.alpha.regime_coherence_agent import RegimeCoherenceAgentComputeAgent
from src.intelligence.ai.alpha.counterfactual_agent import CounterfactualAgentComputeAgent

self._agents: list[BaseMultiplierAgent] = [
    SkepticAgentComputeAgent(llm_chain=self._llm_chain),
    CorrelationAgentComputeAgent(llm_chain=self._llm_chain),
    RegimeCoherenceAgentComputeAgent(llm_chain=self._llm_chain),
    CounterfactualAgentComputeAgent(llm_chain=self._llm_chain),
]
```

**TF gate pattern** (lines 358-361 — extend existing gate; current uses set lookup):
```python
# BEFORE (current _ELIGIBLE_TFS frozenset approach):
if tf not in _ELIGIBLE_TFS:
    return

# AFTER (D-07, D-10 settings-driven):
tf_minutes = _TF_MINUTES.get(tf, 0)  # or parse from tf string
if tf_minutes < self.settings.SWARM_MIN_TF_MINUTES:
    return

# Also add signal_schema_version gate:
if raw_signal.get("signal_schema_version") != "v1":
    return
```

**Semaphore pattern for concurrency cap** (D-07 — add after _setup):
```python
# In __init__:
self._semaphore: asyncio.Semaphore | None = None

# In _setup() after super():
self._semaphore = asyncio.Semaphore(self.settings.SWARM_MAX_CONCURRENT_CALLS)

# In _process_one_signal():
timeout_s = self.settings.SWARM_QUEUE_TIMEOUT_MS / 1000.0
try:
    await asyncio.wait_for(self._semaphore.acquire(), timeout=timeout_s)
except asyncio.TimeoutError:
    SWARM_INVOCATIONS_TOTAL.labels(
        agent_id="all", timeframe=tf, status="capacity_skip"
    ).inc()
    return
try:
    results = await asyncio.gather(*tasks, return_exceptions=True)
finally:
    self._semaphore.release()
```

**Weighted aggregation pattern** (D-07 — add after existing gather loop):
```python
def _compute_final_multiplier(
    self, results: list, agent_weights: dict[str, float]
) -> float | None:
    """Normalized weighted average: Σ(wᵢ × mᵢ) / Σ(wᵢ).
    Excludes neutral/error outputs. Returns None if all agents fail.
    """
    weighted_sum = 0.0
    weight_sum = 0.0
    for result in results:
        if isinstance(result, AgentOutput) and not result.error:
            m = result.payload.get("multiplier")
            if m is not None:
                w = agent_weights.get(result.agent_id, 1.0 / len(self._agents))
                weighted_sum += w * m
                weight_sum += w
    if weight_sum == 0.0:
        return None
    return weighted_sum / weight_sum
```

**Shadow enrollment pattern** (lines 146-162 — extend for all agents):
```python
# BEFORE: hardcoded skeptic_v1
async def _shadow_registry_ensure_swarm(self) -> None:
    await conn.execute(
        "INSERT INTO shadow_registry (component_name, component_type, is_shadow) "
        "VALUES ('skeptic_v1', 'swarm_agent', TRUE) ON CONFLICT (component_name) DO NOTHING"
    )

# AFTER: loop over self._agents
async def _shadow_registry_ensure_swarm(self) -> None:
    assert self._pool is not None
    async with self._pool.acquire() as conn:
        for agent in self._agents:
            await conn.execute(
                """
                INSERT INTO shadow_registry (component_name, component_type, is_shadow)
                VALUES ($1, 'swarm_agent', TRUE)
                ON CONFLICT (component_name) DO NOTHING
                """,
                agent.agent_id,
            )
    self.logger.info("alpha_swarm.shadow_enrolled", agents=[a.agent_id for a in self._agents])
```

**Graduation loop pattern** (lines 164-330 — extend to iterate all agents):
```python
# BEFORE: hardcoded 'skeptic_v1' WHERE clause
# AFTER: loop over self._agents, one Spearman query per agent_id
async def _run_graduation_cycle(self) -> None:
    for agent in self._agents:
        await self._evaluate_agent(agent.agent_id)

async def _evaluate_agent(self, agent_id: str) -> None:
    # Same query/Spearman logic as current _run_graduation_cycle,
    # but parametrized by agent_id instead of hardcoded 'skeptic_v1'
    ...
```

---

### `src/config/settings.py` (extend — add SWARM_* fields)

**Analog:** Self (existing field pattern to follow)

**Pattern to copy** (lines 119-128 of settings.py — Field with validation_alias):
```python
# Pattern from existing settings fields:
roll_monitor_window_size: int = Field(default=100, validation_alias="ROLL_MONITOR_WINDOW_SIZE")
roll_monitor_threshold_default: float = Field(
    default=1.2, validation_alias="ROLL_MONITOR_THRESHOLD_DEFAULT"
)

# New SWARM_* fields (D-10):
SWARM_MIN_TF_MINUTES: int = Field(
    default=5, validation_alias="SWARM_MIN_TF_MINUTES",
    description="Minimum timeframe in minutes for swarm enrichment (gate: skip 1m bars)"
)
SWARM_WEIGHT_MIN_SAMPLES: int = Field(
    default=30, validation_alias="SWARM_WEIGHT_MIN_SAMPLES",
    description="Minimum resolved predictions before weight learning activates"
)
SWARM_WEIGHT_FLOOR: float = Field(
    default=0.05, validation_alias="SWARM_WEIGHT_FLOOR",
    description="Minimum agent weight before formal demotion"
)
SWARM_MAX_CONCURRENT_CALLS: int = Field(
    default=8, validation_alias="SWARM_MAX_CONCURRENT_CALLS",
    description="Max concurrent LLM calls (asyncio.Semaphore capacity)"
)
SWARM_QUEUE_TIMEOUT_MS: int = Field(
    default=250, validation_alias="SWARM_QUEUE_TIMEOUT_MS",
    description="Timeout in ms to acquire semaphore before skipping enrichment"
)
```

**Placement:** Add after the `macro_window_bars` field (line 134 area) and before the regime gate safety floors block (line 136). All field names follow `UPPER_SNAKE_CASE` with matching `validation_alias`.

---

### `src/observability/metrics.py` (extend — add swarm metrics)

**Analog:** Self (existing metric registration patterns)

**Counter pattern** (lines 39-60 — labeled Counter with prometheus_client):
```python
PLUGIN_EXECUTION_TOTAL = Counter(
    "plugin_executions_total",
    "Total plugin executions",
    ["plugin_name", "symbol", "timeframe", "status"],
)
```

**Histogram pattern** (lines 47-55):
```python
PLUGIN_DURATION_MS = Histogram(
    "intelligence_pipeline_plugin_duration_ms",
    "Per-plugin execution latency",
    ["plugin_name", "tier"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 50, 100],
)
```

**Gauge pattern** (lines 204-211):
```python
SHADOW_WIN_RATE = Gauge("shadow_win_rate", "Shadow plugin win rate", ["plugin"])
```

**New swarm metrics to add** (D-11 — add in a new section after the AI agent section):
```python
# ---------------------------------------------------------------------------
# Swarm intelligence metrics (Phase 80)
# ---------------------------------------------------------------------------

SWARM_INVOCATIONS_TOTAL = Counter(
    "swarm_invocations_total",
    "Per-agent swarm call rate, error rate, and capacity skips",
    ["agent_id", "timeframe", "status"],
)
SWARM_MULTIPLIER_DISTRIBUTION = Histogram(
    "swarm_multiplier_distribution",
    "Per-agent multiplier output distribution over time",
    ["agent_id"],
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2, 1.5, 2.0],
)
SWARM_AGGREGATED_MULTIPLIER = Histogram(
    "swarm_aggregated_multiplier",
    "Final combined multiplier distribution per timeframe",
    ["timeframe"],
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2, 1.5, 2.0],
)
SWARM_AGENT_WEIGHT = Gauge(
    "swarm_agent_weight",
    "Per-agent learned weight by timeframe — key Renaissance health signal",
    ["agent_id", "timeframe"],
)
SWARM_SIGNAL_LEDGER_UPDATE_TOTAL = Counter(
    "swarm_signal_ledger_update_total",
    "Writer-owned signal_ledger materialization outcomes",
    ["status"],  # success, retry, miss
)
```

**Important:** The new swarm metrics use standard `prometheus_client` Counter/Histogram/Gauge (not OTelCounter/OTelHistogram) to match the pattern of labeled metrics in the upper section (lines 39-311). OTel wrappers (lines 475-530) are used only for the LLM/AI agent metrics that need OTel-compatible label support. Check which pattern matches the consumer (Prometheus scrape vs OTel push) before choosing.

---

### `src/intelligence/ai/TEMPLATE_agent.py` (update — show BaseMultiplierAgent)

**Analog:** Self (current template, update in place)

**Current class declaration** (line 31):
```python
class TemplateComputeAgent(BaseAIAgent):
```

**Updated class declaration** (D-12):
```python
from src.core.ai.multiplier_agent import BaseMultiplierAgent
from src.core.ai.prompt_utils import clamp, parse_llm_json
from typing import ClassVar

class TemplateComputeAgent(BaseMultiplierAgent):
    """One-line description of what this agent decides and why."""

    # Required class attributes — every multiplier agent MUST set these six.
    output_schema: ClassVar[dict] = {
        "score": float,      # agent-specific key (rename per agent)
        "confidence": float, # always required
        "reasoning": str,    # always required
    }
    agent_id = "template_v1"
    group = "alpha"
    tiers_needed = frozenset({Tier.I1, Tier.I4, Tier.I6})
    latency_budget_ms = 5000.0
    shadow_only = True
```

**Updated _compute body** (D-12 — show _parse_multiplier_response and _build_multiplier_output):
```python
    async def _compute(self, context: AIContext) -> AgentOutput:
        prompt = build_template_prompt(context)
        response = await self._llm.generate(
            prompt=prompt,
            system=_SYSTEM_MESSAGE,
            max_tokens=500,
            timeout=self.latency_budget_ms / 1000.0,
        )
        if not response:
            return self._neutral(error="LLM returned empty response", latency_ms=0.0)

        parsed = self._parse_multiplier_response(response, _validate_template_fields)
        if parsed is None:
            logger.warning(
                "template_agent.json_parse_failed",
                agent_id=self.agent_id,
                raw_response=response[:200],
                expected_schema=self.output_schema,
            )
            return self._neutral(error="JSON parse failed", latency_ms=0.0)

        score = parsed["score"]
        confidence = parsed["confidence"]
        multiplier = score * confidence  # Phase 80: discount-only formula

        return self._build_multiplier_output(
            context=context,
            multiplier=multiplier,
            confidence=confidence,
            payload={"score": score, "reasoning": parsed["reasoning"]},
            prompt_version=ACTIVE_VERSION,
        )
```

---

### `production/migrations/082_swarm_weights_and_adjusted_confidence.sql` (migration)

**Analog:** `.worktrees/codebase-cleanup/production/migrations/081_signal_quality_zones.sql`

**Migration file pattern** (from 081 analog — simple ALTER TABLE + CREATE TABLE, no transactions):
```sql
-- Phase 80: Swarm Intelligence Layer — new columns + weight table
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS adjusted_confidence FLOAT;
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS swarm_multiplier FLOAT;
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS swarm_agent_count INT;

CREATE TABLE IF NOT EXISTS swarm_agent_weights (
    agent_id          TEXT        NOT NULL,
    timeframe         TEXT        NOT NULL,
    weight            FLOAT       NOT NULL DEFAULT 1.0,
    sample_size       INT         NOT NULL DEFAULT 0,
    spearman_rho      FLOAT,
    calibration_error FLOAT,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (agent_id, timeframe)
);
```

**Notes:**
- Migration number is `082` — confirmed from `.worktrees/codebase-cleanup/production/migrations/` (081 is the latest).
- `swarm_agent_weights` is a plain table (not hypertable) — low cardinality, not time-series (per Claude's Discretion).
- Indexes: add `CREATE INDEX IF NOT EXISTS idx_ledger_adjusted_confidence ON signal_ledger (adjusted_confidence) WHERE adjusted_confidence IS NOT NULL;` for Grafana dashboard queries.
- Column `adjusted_confidence = original_confidence × swarm_multiplier` — computed by WriterAgent, never overwriting the original `confidence` column.

---

## Shared Patterns

### Base Class Inheritance Chain
**Source:** `src/core/ai/base_agent.py` (lines 38-183)
**Apply to:** `multiplier_agent.py`, all four concrete agents
```python
# Chain: BaseAgent → BaseAIAgent → BaseMultiplierAgent → ConcreteAgent
# BaseAIAgent provides: timing, timeout (asyncio.wait_for), neutral fallback, metrics
# BaseMultiplierAgent adds: _parse_multiplier_response(), _build_multiplier_output(), output_schema
# ConcreteAgent implements: _compute(), _SYSTEM_MESSAGE, output_schema value, validator fn
```

### LLM Call Pattern
**Source:** `src/intelligence/ai/alpha/skeptic_agent.py` (lines 65-73)
**Apply to:** All four concrete agent `_compute()` methods
```python
response = await self._llm.generate(
    prompt=prompt,
    system=_SYSTEM_MESSAGE,
    max_tokens=500,
    timeout=self.latency_budget_ms / 1000.0,
)
if not response:
    return self._neutral(error="LLM returned empty response", latency_ms=0.0)
```

### Neutral Output on Failure
**Source:** `src/core/ai/base_agent.py` (lines 145-155)
**Apply to:** All four concrete agent `_compute()` methods
```python
return self._neutral(error="JSON parse failed", latency_ms=0.0)
# BaseAIAgent._neutral() constructs AgentOutput(output_type="neutral", payload={}, error=error)
# Neutral outputs are excluded from weighted aggregation in dispatch (D-07)
```

### structlog Event Kwarg Rule
**Source:** CLAUDE.md
**Apply to:** All new agent files and dispatch changes
```python
# CORRECT — use named field, not event=
logger.warning("correlation_agent.json_parse_failed", agent_id=self.agent_id, ...)
# WRONG — 'event' is structlog's reserved positional arg:
logger.warning("msg", event=something)  # raises "multiple values for argument 'event'"
```

### Shadow Registry Enrollment
**Source:** `services/alpha_swarm_agent.py` (lines 146-162)
**Apply to:** `_shadow_registry_ensure_swarm()` in dispatch refactor
```python
# Idempotent: ON CONFLICT DO NOTHING preserves manually-tuned gate params
await conn.execute(
    """
    INSERT INTO shadow_registry (component_name, component_type, is_shadow)
    VALUES ($1, 'swarm_agent', TRUE)
    ON CONFLICT (component_name) DO NOTHING
    """,
    agent.agent_id,
)
```

### Lineage Record Pattern
**Source:** `services/alpha_swarm_agent.py` (lines 472-488)
**Apply to:** `_record_swarm_result()` in dispatch (ensure future-compatible fields per D-07)
```python
self._lineage.record(
    signal_id=signal_id,
    event_type="agent_prediction",
    source=result.agent_id,
    multiplier=multiplier,
    metadata={
        "segment_key": segment_key,
        "confidence": result.payload.get("confidence", 0.0),
        "group": result.group,
        "payload": result.payload,        # includes prompt_version, reasoning
        "error": result.error,
        "shadow_at_write": result.shadow_only,  # D-07 future hook
        "parse_status": "ok" if not result.error else "failed",
    },
    symbol=enriched.symbol,
    tf=enriched.timeframe,
)
```

### Settings Field Pattern
**Source:** `src/config/settings.py` (lines 119-128)
**Apply to:** All five new SWARM_* settings fields
```python
field_name: type = Field(default=<value>, validation_alias="UPPER_SNAKE_CASE")
```

### Test __new__ Bypass Pattern
**Source:** `tests/unit/service_tests/test_alpha_swarm_agent.py` (lines 39-74)
**Apply to:** All new unit tests for agents and dispatch
```python
# Bypass __init__ — avoids needing live LLM/DB/Kafka
agent = AgentClass.__new__(AgentClass)
agent.settings = MagicMock(env_name="test")
agent.logger = MagicMock()
# Manually set every instance attribute that __init__ would set
agent._llm = MagicMock()
agent._lineage = LineageRecorder(producer=fake_producer, env_name="test")
agent._agents = [mock_swarm_agent]
```

---

## No Analog Found

All files have strong analogs. No file requires falling back to RESEARCH.md patterns.

---

## Metadata

**Analog search scope:** `src/core/ai/`, `src/intelligence/ai/alpha/`, `services/`, `src/config/`, `src/observability/`, `tests/unit/service_tests/`, `.worktrees/codebase-cleanup/production/migrations/`
**Files scanned:** 11 source files read directly
**Migration number confirmed:** Latest is 081 → new file is `082_swarm_weights_and_adjusted_confidence.sql`
**Pattern extraction date:** 2026-05-05
