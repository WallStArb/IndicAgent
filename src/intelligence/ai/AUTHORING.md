# AI Agent Authoring Protocol

This document describes how to add a new AI agent (alpha / narrative / risk
group) to IndicAgent. Every new agent follows this pattern. Deviations are
reviewed in code review and must be justified.

## Group Definitions

| Group | Purpose | Output type |
|-------|---------|-------------|
| `alpha` | Predict signal performance — feedback loop on PnL outcome | multiplier (0..2) on signal confidence |
| `narrative` | Generate human-readable narratives — on-demand only (per Phase 78) | text |
| `risk` | Future — risk-overlay agents | placeholder, see CONTEXT D-deferred |

## Five Required Class Attributes

Every BaseAIAgent subclass MUST declare:

1. `agent_id: str` — Stable name. MUST match `shadow_registry.component_name`.
   Use `<concept>_v<N>` (e.g., `skeptic_v1`, `volflow_v2`).
2. `group: str` — `"alpha" | "narrative" | "risk"`.
3. `tiers_needed: frozenset[Tier]` — Pipeline tiers this agent reads.
   Drives AIContextCache.build() — only requested tiers populate.
4. `latency_budget_ms: float` — Hard cap on `_compute`. Wraps in `asyncio.wait_for`.
5. `shadow_only: bool` — `True` for new agents (default). Graduation loop promotes.

## File Layout

- Agent class: `src/intelligence/ai/<group>/<name>_agent.py`
- Prompt registry: `src/intelligence/ai/<group>/<name>_prompts.py`
- Tests: `tests/unit/test_<name>_agent.py`, `tests/unit/test_<name>_prompts.py`

## LineageRecorder — Single Audit Path

After Phase 78, every alpha-group agent records ONE event per signal via
`LineageRecorder.record(event_type="agent_prediction", ...)`. The recorder
publishes to `topic_signal_lineage()`; `LineageWriterAgent` persists to the
`signal_lineage` hypertable. This is the ONLY swarm write path. Do not
write to `alpha_multiplier_shadow` or `signal_transform_log` (deprecated
targets, kept for historical reads only).

## Shadow Enrollment + Graduation

New agents start with `shadow_only=True`. At startup the swarm calls:

```python
await shadow_registry_ensure(
    component_name="<agent_id>",
    component_type="swarm_agent",
    tier="alpha",
    initial_state="shadow",
)
```

The `_graduation_loop` (Phase 78 Plan 03) evaluates `signal_lineage` rows
JOIN `signal_ledger.outcome` and computes Spearman rho + p-value. Promotion:
N >= 100, rho > 0, p < 0.05. Demotion: 3 consecutive 15-min cycles with rho < 0.

## Prompt File Convention

Each agent has a paired `<name>_prompts.py` that exposes:

```python
ACTIVE_VERSION: str        # e.g. "skeptic_v2"
PROMPT_REGISTRY: dict[str, str]  # all historical versions preserved for rollback
```

The `build_<name>_prompt(ctx: AIContext) -> str` function:
- v2+ pattern: accepts the typed AIContext directly (see `_render_full_context`)
- v1 pattern (legacy): accepted a flat dict from `_context_to_dict`

Set `prompt_version = ACTIVE_VERSION` as a class attribute on the agent itself
(not just in AgentOutput.payload) -- `_build_audit_context()` reads
`self.prompt_version` to attribute every `llm_calls` audit row, and raises
`RuntimeError` on the agent's first `_llm_generate()`/`_llm_generate_structured()`/
`_run_typed()` call if it was left unset. Non-LLM agents that never reach
`_build_audit_context()` (e.g. `MLEvaluator`, which does pure LightGBM inference)
are exempt -- but any agent that calls the LLM must set it.

## _compute() Contract

```python
async def _compute(self, context: AIContext) -> AgentOutput:
    # 1. Build prompt (use ACTIVE_VERSION from prompts module)
    prompt = build_<name>_prompt(context)
    # 2. Call LLM
    response = await self._llm.generate(prompt=prompt, system=SYSTEM_MSG, ...)
    # 3. Handle empty response
    if not response:
        return self._neutral(error="LLM returned empty", latency_ms=0.0)
    # 4. Parse JSON
    parsed = _parse_response(response)
    if parsed is None:
        return self._neutral(error="JSON parse failed", latency_ms=0.0)
    # 5. Return AgentOutput — never raise
    return AgentOutput(
        agent_id=self.agent_id,
        group=self.group,
        signal_id=context.signal_id,
        symbol=context.symbol,
        timeframe=context.timeframe,
        ts=context.ts,
        output_type="multiplier",
        payload={
            ...parsed fields...,
            "prompt_version": ACTIVE_VERSION,  # REQUIRED for LineageRecorder
        },
        shadow_only=self.shadow_only,
    )
```

## Adding a New Group

To add `risk` (currently a placeholder):
1. Create `src/intelligence/ai/risk/__init__.py` (already exists).
2. Add `RiskGroupComputeAgent(BaseGroupService)` analogous to `AlphaSwarmComputeAgent`.
3. Register in `services/service_auditor_agent.py::_DAG_ORDER` and `_AGENT_ID_TO_UNIT`.
4. Add a systemd unit at `production/systemd/indicagent-<group>.service`.
5. Document the group's purpose in this file's table.

## Reference Implementation

`src/intelligence/ai/alpha/skeptic_agent.py` — read this before writing
any new agent. The patterns there (prompt registry, AgentOutput shape,
neutral fallback, prompt_version attribution) are canonical.
