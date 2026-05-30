# Naming Conventions

**Version:** 2.9
**Status:** current
**Last Updated:** 2026-05-30
**Principle:** A service's *concept name* (`snake_case`, no suffix) determines all its derived names across every layer. Given `feature_pipeline`, every layer's name is mechanically derivable — no lookup needed.

---

## The Philosophy

Renaissance hired mathematicians and physicists, not software engineers. They named things by what they *are mathematically*, not by how they are implemented. A position sizing model isn't a `KellyComputerAgent` — it's a `PositionSizer`. The fact that it runs as a Python process is irrelevant to the name.

Two tests determine whether a name is right:

**1. The whiteboard test.** Could you write this name on a whiteboard in a mathematics seminar and have a quant immediately understand what the object IS — its role in the mathematical model? `SignalScorer` passes. `ComputeAgent` fails (it describes mechanism, not role).

**2. The survival test.** If you replaced the implementation tomorrow (swap the LLM for a neural net, swap asyncio for threads), would the name still be correct? If yes, it names the role. If no, it names the mechanism.

Names that fail these tests accumulate as technical debt. Every name that describes mechanism instead of role makes the codebase harder to reason about — because the code's vocabulary diverges from the mathematical model it implements.

### Name the role, not the mechanism

| Names mechanism (wrong) | Names role (right) | Why |
|---|---|---|
| `SkepticComputeAgent` | `SkepticScorer` | It *scores* signal quality skeptically. Whether it "computes" is obvious. |
| `IndicAgentModel` | `LLMAdapter` | It *adapts* our LLM infrastructure to the Pydantic AI Model protocol. |
| `AgentDeps` | `AgentContext` | It IS the execution context for an agent run. "Deps" is an abbreviation of a mechanism. |
| `AuditedModel` | `LLMAdapter` | Describes a trait (audited), not the role (adapter). |

### No abbreviations

Abbreviations are precision killers. `AgentDeps` vs `AgentContext` — one requires decoding, one is immediately clear. No abbreviations anywhere: class names, variables, function arguments, field names.

The only exceptions are universally understood domain codes: `ts` (timestamp), `tf` (timeframe), `tf` (timeframe), tier codes `I1`–`I8`.

---

## Code Organisation Rings

Every class, file, and module belongs to one of three rings. The ring determines how generic or domain-specific the name should be.

```
Ring 0 — Infrastructure   src/core/          Generic. No project prefix. No domain vocabulary.
Ring 1 — Domain           src/intelligence/  IndicAgent-specific vocabulary is correct here.
Ring 2 — Implementation   services/          Always specific. Role suffix required.
```

**Ring 0 rule:** Could this be extracted into a shared library tomorrow? If not, the name is wrong. `LLMAdapter`, `AgentContext` — no project prefix, no domain vocabulary. They name what the object IS, generically.

**Ring 1 rule:** Domain vocabulary earns its place here. `BaseAIAgent`, `AIContext`, `BaseScorer` — IndicAgent-specific abstractions with domain-appropriate names.

**Ring 2 rule:** Fully specific. Names include the role suffix that tells you exactly where in the DAG this service lives.

> **Note:** These rings are code organisation. They are separate from the intelligence pipeline tiers I1–I8, which describe data transformation layers.

---

## Cross-Layer Transformation Rules

The concept name (`snake_case`, no suffix) mechanically derives every layer name. No guessing, no lookup needed.

| Layer | Pattern | Example (`alpha_signal`) |
|-------|---------|------------------------------|
| Python file (Service) | `<concept>_service.py` | `alpha_signal_service.py` |
| Python file (Agent) | `<concept>_agent.py` | `alpha_signal_agent.py` |
| Python file (Plugin) | `src/intelligence/trading/<concept>.py` | `alpha_signal.py` |
| Python class (Service) | `PascalCase` + `Service` | `AlphaSignalService` |
| Python class (Agent) | `PascalCase` + agent role suffix | `AlphaSignalComputeAgent` |
| Python class (Plugin) | `PascalCase` + `Plugin` | `AlphaSignalPlugin` |
| Systemd unit | `indicagent-<concept-kebab>.service` | `indicagent-alpha-signal.service` |
| Kafka topic fn | `topic_<concept>()` in `stream_keys.py` | `topic_alpha_signal()` |
| Kafka topic string | `<env>.<domain>[.<sublayer>]` (dots only) | `dev.alpha_signal` |
| DB table | `snake_case` plural noun | `alpha_signals` |
| DB columns | `snake_case` | `ts`, `symbol`, `tf`, `i7` |

---

## Agent Role Suffixes

The suffix names the agent's **role in the DAG** — what it does, not how. Every agent class name ends with exactly one of these.

| Suffix | Role | DB access | Example |
|--------|------|-----------|---------|
| `ProviderAgent` | External source → Kafka, ingestion only | None | `IBKRProviderAgent` |
| `ComputeAgent` | Math/stats transform, pipeline computation | None | `IntelligencePipelineAgent` |
| `Scorer` | Signal quality evaluation → confidence multiplier ∈ [0,2] | None | `SkepticScorer` |
| `Synthesizer` | Qualitative synthesis → narrative/annotation | None | `NarrativeSynthesizer` |
| `GeneratorAgent` | Signal or trade event emission | Read-only | `SignalGeneratorAgent` |
| `WriterAgent` | DB persistence, single responsibility | Write | `FeatureWriterAgent` |
| `TrackerAgent` | Business object lifecycle management | Read/Write | `SignalTrackerComputeAgent` |
| `AuditorAgent` | Data integrity validation + self-healing | Read | `SignalAuditorAgent` |

**Why `Scorer` and `Synthesizer` are distinct from `ComputeAgent`:**

`ComputeAgent` covers general mathematical computation — indicators, regime detection, confluence scoring. `Scorer` is specific to the AI signal quality evaluation layer (I8): agents that evaluate a trading signal from a particular perspective and produce a confidence multiplier. This distinction matters because Scorers share a common contract (`result_type`, `_run_typed`, multiplier ∈ [0,2]) that general ComputeAgents do not.

`Synthesizer` covers agents whose output is qualitative synthesis rather than a numerical score — narrative generation, fundamental summary. Different contract: no multiplier, free-form structured output.

---

## AI Layer Hierarchy

The AI evaluation layer (I8) has its own class hierarchy. Names reflect mathematical role.

```
BaseAgent  (Ring 0 infrastructure — Kafka, systemd, metrics)
└── BaseAIAgent  (Ring 1 domain base — LLM generation, audit, typed output)
    ├── BaseScorer  (Ring 1 — produces confidence multiplier ∈ [0,2])
    │   ├── SkepticScorer          skeptic_scorer.py
    │   ├── CorrelationScorer      correlation_scorer.py
    │   ├── CounterfactualScorer   counterfactual_scorer.py
    │   ├── RegimeCoherenceScorer  regime_coherence_scorer.py
    │   └── MLScorer               ml_scorer.py
    └── NarrativeSynthesizer       narrative_synthesizer.py
        └── [SentimentSynthesizer, FundamentalSynthesizer ...]
```

**Why `BaseScorer` not `BaseMultiplierAgent`?**

`BaseMultiplierAgent` names the output format (it produces a multiplier). `BaseScorer` names the mathematical role (it scores signal quality). The output being a multiplier is an implementation detail of the scoring contract — a named constant in the codebase, not the identity of the class.

**`result_type` and `_run_typed` live on `BaseAIAgent`**, not `BaseScorer`. Every agent type — scorers, synthesizers, future fundamental analysts — may need typed Pydantic AI output. The capability belongs at the universal base, not the multiplier-specific subclass.

### Phase 095 Infrastructure (Ring 0)

These are generic infrastructure classes. No project prefix. No domain vocabulary.

| Class | File | What it is |
|-------|------|------------|
| `AgentContext` | `src/core/ai/agent_context.py` | Frozen execution context passed to every agent run: signal_context, llm_chain, db_pool, memory_client. Follows the `*Context` pattern established by `AIContext`, `TierContext`. |
| `LLMAdapter` | `src/core/ai/llm_adapter.py` | Implements the Pydantic AI `Model` protocol. Bridges our `LiteLLMBackend` + `LLMProviderChain` into Pydantic AI's agent execution engine. |
| `AgentProtocol` | `src/core/ai/base_agent.py` | Python `Protocol` defining the agent interface. Replaces `IAIAgent` (I+AI+Agent = redundant). |

---

## Per-Layer Rules

**Python**
- Plugins: `snake_case.py` file (short name) / `PascalCasePlugin` class — `adx.py` → `ADXPlugin`
- Aggregators/results: `PascalCase` no suffix — `CISScorer`, `AggregatedResult`
- Functions/methods: `snake_case`. Constants: `UPPER_SNAKE_CASE`. Private attrs: `_snake_case`.
- Abstract base classes: `Base*` prefix — `BaseAIAgent`, `BaseScorer`.
- Protocol classes: `*Protocol` suffix — `AgentProtocol`.
- No version numbers in class names. Version belongs in `agent_id` / `prompt_version` fields.

**Kafka topics** (always via `src/core/stream_keys.py`, never hardcoded)
- Functions: `topic_<output_domain>()` — singular noun describing what flows in the topic
- Strings: `<env>.<domain>` or `<env>.<domain>.<sublayer>` — **dots only, never colons**
- Consumer groups: `<concept>_consumer` (idempotent on restart)

**Database**
- Tables: `snake_case` plural nouns. Columns: `snake_case` — timestamp is `ts` (not `feature_ts`); always `symbol`, `tf`
- Views: `<source_table>_<timeframe>` — `ohlcv_15m`, `market_data_5m`. Migrations: `NNN_description.sql`.

**Systemd / Infrastructure**
- Units: installed in `/etc/systemd/system/`; source files in `services/`. `production/systemd/` is a reference dir — do not treat as authoritative.
- Logs: `logs/<python_service_filename>.log` — read directly for structured output (journald shows only `print()`)

**Tests / TypeScript / Docs**
- Tests: `tests/unit/test_<module>.py`; functions `test_<what>_<condition>`
- TypeScript: components `PascalCase.tsx`, hooks `use-kebab-case.ts`, utils `kebab-case.ts`
- Docs: `kebab-case.md`; plan docs `YYYY-MM-DD-<topic>.md`; uppercase `README.md`/`CLAUDE.md`/`CHANGELOG.md`

---

## Anti-Patterns

Each of these has appeared in this codebase. The reasoning is recorded so the mistake isn't repeated.

| Pattern | Why it fails | Correct |
|---------|-------------|---------|
| `SkepticComputeAgent` | Names mechanism ("compute"), not role ("scores signal quality") | `SkepticScorer` |
| `BaseMultiplierAgent` | Names output format ("multiplier"), not role ("scores signals") | `BaseScorer` |
| `NarrativeComputeAgent` | Narrative agents synthesize, they don't "compute" in the pipeline sense | `NarrativeSynthesizer` |
| `MLScorerMultiplierAgent` | "Multiplier" is redundant — all Scorers produce multipliers | `MLScorer` |
| `IndicAgentModel` | Project prefix on Ring 0 infrastructure; "Agent" in a Model is confusing | `LLMAdapter` |
| `AuditedModel` | Names a trait ("audited"), not the role ("adapts LLM to Pydantic AI protocol") | `LLMAdapter` |
| `AgentDeps` | Abbreviation; "Deps" requires decoding | `AgentContext` |
| `IAIAgent` | I + AI + Agent = three ways to say the same thing | `AgentProtocol` |
| `SkepticV2` as a class name | Version numbers in class names become permanent debt | `SkepticScorerV2` (shadow variant only) or update the class |
| Hardcoded version strings | Drift risk — single source of truth is `SIGNAL_SCHEMA_VERSION` constant | Import from `signal_schema.py` |

---

## Intelligence Tier Naming System

Tiers have both a code (`I1`–`I8`) and a functional name. Both are valid in documentation and code; use whichever aids clarity.

### Tier Mapping

| Code | Functional Name | `snake_case` | Usage |
|------|----------------|--------------|-------|
| I1 | Technical Indicators | `technical_indicators` | Plugin tier key, log tags |
| I2 | Composite Events | `composite_events` | |
| I3 | Market Structure | `market_structure` | |
| I4 | Market Context | `market_context` | Regime detection, volatility, session |
| I5 | Pattern Intelligence | `pattern_intelligence` | |
| I6 | Confluence Synthesis | `confluence_synthesis` | Also: `smc` shorthand in event keys |
| I7 | Trading Signals | `trading_signals` | |
| I8 | AI Narrative | `ai_narrative` | |

### Usage Guidelines

- **In code:** Use tier codes (`I1`–`I8`) for constants and tier keys; functional names as dict keys and topic suffixes
- **In docs:** Tier codes for brevity; functional names when clarity matters
- **In logs:** Tier codes preferred for width constraints
- **In metrics:** Dual label `I1:technical_indicators` via `format_tier_label()`
- **In DB columns:** Functional names only (Phase 104 schema)
- **In APIs:** Functional names for external consumers

### Conversion API

`src/intelligence/tier_aliases.py` provides programmatic conversion:

```python
from src.intelligence.tier_aliases import (
    tier_to_functional,   # "I1" → "technical_indicators"
    functional_to_tier,   # "trading_signals" → "I7"
    format_tier_label,    # "I1" → "I1:technical_indicators" (for metrics)
)
```

See `src/intelligence/register_plugins.py` `TIER_I1`..`TIER_I7` for the canonical tier lists.
