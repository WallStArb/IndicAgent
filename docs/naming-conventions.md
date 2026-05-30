# Naming Conventions

**Version:** 1.0 | **Status:** current
**Maintained by:** Engineering. Update when a new naming pattern is established.

---

## The Layering Principle

Every class, file, and module belongs to one of three layers. The layer determines how generic or domain-specific the name should be.

```
Layer 1 — Infrastructure   src/core/          Generic. Could ship as a standalone library.
Layer 2 — Domain           src/intelligence/  IndicAgent-specific vocabulary is appropriate.
Layer 3 — Implementation   services/          Always specific. Names describe the concrete role.
```

**Layer 1 rule:** No project-name prefixes (`Indic*`). No domain vocabulary. Name by what the class IS, not which project uses it. Ask: would this name be embarrassing in a library README?

**Layer 2 rule:** Domain vocabulary is correct here. `BaseAIAgent`, `AIContext`, `AlphaSwarmComputeAgent` — all fine. The `Indic*` prefix is acceptable when namespacing is needed.

**Layer 3 rule:** Always specific. Include the role suffix (`*ComputeAgent`, `*WriterAgent`, `*GroupService`).

### Examples

| Class | Layer | Why |
|-------|-------|-----|
| `LLMAdapter` | L1 | Adapts LLM infrastructure to the Pydantic AI Model protocol — no project prefix, names the role |
| `AgentRuntime` | L1 | Frozen execution substrate — semantic, no abbreviation |
| `AgentProtocol` | L1 | Python Protocol — suffix follows convention |
| `BaseAIAgent` | L2 | IndicAgent's AI agent base — domain vocabulary OK |
| `BaseMultiplierAgent` | L2 | "Multiplier" is domain-specific quant vocabulary |
| `AIContext` | L2 | Market signal context — domain-appropriate |
| `SkepticComputeAgent` | L3 | Concrete compute agent with role suffix |
| `NarrativeComputeAgent` | L3 | Concrete compute agent with role suffix |

---

## Class Naming

### General rules

- No abbreviations. `AgentRuntime` not `AgentDeps`. `AgentDependencies` only if "Runtime" doesn't fit.
- No version numbers in class names. Version belongs in `agent_id` / `prompt_version` fields.
- Protocol classes end in `Protocol` — `AgentProtocol` not `IAIAgent`.
- Abstract base classes use `Base*` prefix — `BaseAIAgent`, `BaseMultiplierAgent`.

### Role suffixes (Layer 3)

Concept name in `snake_case` derives all layer names:

| Role | Class suffix | File suffix | Example |
|------|-------------|-------------|---------|
| Compute agent | `ComputeAgent` | `_agent.py` | `SkepticComputeAgent` |
| Writer agent | `WriterAgent` | `_agent.py` | `FeatureWriterAgent` |
| Group service | `ComputeAgent` (swarm) | `_agent.py` | `AlphaSwarmComputeAgent` |
| Service | `Service` | `_service.py` | `LLMProviderChain` |
| Result model | `Result` | `_prompts.py` | `SkepticResult` |
| Protocol adapter (L1) | `Adapter` | `_adapter.py` | `LLMAdapter` |

Full derivation example: `alpha_signal` → `AlphaSignalService` (class), `indicagent-alpha-signal.service` (systemd), `topic_alpha_signal()` (Kafka key), `alpha_signals` (DB table).

---

## File Naming

```
src/core/ai/          agent_runtime.py, llm_adapter.py   (generic infrastructure)
src/core/llm/         litellm_backend.py, chain.py
src/intelligence/ai/  <group>/<name>_agent.py, <name>_prompts.py
services/             <name>_agent.py
tests/unit/           mirrors src/ structure
```

No `indicagent_` prefix on files in `src/core/` — they are already in the project.

---

## AI Agent Specific

### Mandatory class attributes (enforced at code review)

```python
agent_id: str          # kebab-case, unique across all agents
group: str             # group this agent belongs to
tiers_needed: list     # which intelligence tiers the agent reads
latency_budget_ms: float
shadow_only: bool      # all new agents default True; never auto-promote
prompt_version: str    # set from ACTIVE_VERSION in <name>_prompts.py
result_type: ClassVar[type[BaseModel] | None] = None  # opt-in typed path
```

### Inheritance hierarchy

```
BaseAgent  (infrastructure)
└── BaseAIAgent  (AI compute base — result_type + _run_typed live here)
    ├── BaseMultiplierAgent  (_build_multiplier_output, _parse_multiplier_response)
    │   └── *ComputeAgent   (quant signal multipliers)
    └── *ComputeAgent       (qualitative: narrative, sentiment, fundamental)
```

`result_type` + `_run_typed` belong on `BaseAIAgent` — not `BaseMultiplierAgent` — so every agent type (quant and qualitative) gets typed Pydantic AI output via inheritance.

### Phase 095 infrastructure (Layer 1)

| Class | File | What it is |
|-------|------|------------|
| `AgentRuntime` | `src/core/ai/agent_runtime.py` | Frozen execution substrate: signal_context, llm_chain, db_pool, memory_client |
| `LLMAdapter` | `src/core/ai/llm_adapter.py` | Pydantic AI `Model` protocol impl wrapping LiteLLMModel + audit publishing |
| `AgentProtocol` | `src/core/ai/base_agent.py` | Protocol (replaces `IAIAgent`) |

---

## Stream / Topic Keys

Always via `src/core/stream_keys.py`. Topic names use dots, not colons. Never hardcode.

---

## Database

Tables use `snake_case` plural. Primary time column: `ts` on feature tables, `timestamp` on event tables. See `docs/database.md` for full schema reference.

---

## Services

Systemd unit names: `indicagent-<concept-kebab>.service`. Must match `_DAG_ORDER` in `service_auditor_agent.py` — that is the single source of truth for the service registry.

---

## Anti-patterns

| Pattern | Why wrong | Correct |
|---------|-----------|---------|
| `IndicAgentModel` / `AuditedModel` | Project prefix / names a trait not the role | `LLMAdapter` — concept `llm_adapter` → class `LLMAdapter` |
| `AgentDeps` | Abbreviation | `AgentRuntime` |
| `IAIAgent` | I+AI+Agent redundancy | `AgentProtocol` |
| `SkepticV2` as class name | Version in class name | `SkepticComputeAgentV2` (shadow variant only) or just update the class |
| Version strings hardcoded | Drift risk | Import `SIGNAL_SCHEMA_VERSION` from `signal_schema.py` |
