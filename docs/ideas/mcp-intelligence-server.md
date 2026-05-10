# MCP Intelligence Server & Agent Tool Use

**Status:** Design direction (discussed 2026-05-09)
**Branch:** feat/phase80-swarm-observability-ux
**Related:** `docs/ideas/2026-05-06-evolvable-ai-agents.md`, `docs/concepts/evolvable-ai.md`

## Concept

Move from pure "push" (preload AIContext, hope we guessed right) to **push/pull hybrid**: AIContext provides current bar context, agents pull additional data via MCP tools as needed.

**MCP is the protocol, not the framework.** By exposing our intelligence via MCP tools, any agent — ours, Claude, future eAI-evolved variants — can discover and query what it needs. The framework is interchangeable; the intelligence data is not.

## Why

- LLM calls are 1-3s. A DB query via asyncpg is 5-20ms. Tool call overhead is noise-level.
- Agents currently reason blind to historical performance (setup win rates, signal outcomes, model calibration).
- The agent should decide what it needs, not us. Every tool call is audited in llm_calls.

## MCP as eAI Substrate

MCP is the tooling layer that makes evolvable AI possible. From `docs/concepts/evolvable-ai.md`, one of the 6 genome chromosomes is **tool sets** — which data sources and analysis tools the agent can use. MCP makes this chromosome implementable:

| eAI Requirement | How MCP Enables It |
|----------------|-------------------|
| **Tool set chromosome** | An evolved agent inherits different MCP tool permissions — same agent, different data access |
| **Gene bank** | Catalog which MCP tools each fit genome used; offspring inherit tool preferences |
| **Fitness audit** | Every MCP tool call flows through our Kafka → TimescaleDB pipeline — full traceability |
| **Shadow evaluation** | Shadow agents see the same MCP tools as live agents, just with outputs suppressed |
| **Novelty measurement** | Track which tool call patterns produce unique vs. redundant signals |
| **LLM-directed mutation** | LLM can propose new tool combinations by reasoning about which tools fit agents used |

Without MCP, evolving tool sets means rewriting code. With MCP, it means changing a config — which tools this genome is allowed to call.

## Stack Additions Needed

1. **`mcp` Python package** — MCP SDK for server + client
2. **Tool calling in `_OpenAICompatProvider`** — extend JSON payload with `tools`/`tool_choice`, parse `tool_calls` from response. All 4 providers (OpenRouter, DeepSeek, Ollama Cloud, Ollama Local) are OpenAI-compatible and support tools natively.
3. **Tool execution loop in `BaseAIAgent`** — LLM returns tool calls → agent executes → feeds results back → LLM continues
4. **`src/mcp/` module** — MCP server exposing intelligence tools

## MCP Server Tools (expose our intelligence stack)

| Tool | Source | Purpose |
|------|--------|---------|
| `query_setup_performance` | setup_performance table | Historical win rate, sharpe, avg_pnl_r by setup/symbol/regime |
| `query_signal_history` | signal_ledger table | Recent signals with outcomes, filterable by setup/symbol/outcome/date |
| `query_features` | intelligence_features table | Raw feature vectors for any past bar |
| `query_ohlcv` | market_data_ohlcv + aggregate views | Price data for any symbol/timeframe |
| `query_llm_scores` | llm_model_scores table | Per-model win rate, calibration, significance |
| `get_service_status` | Prometheus metrics | Pipeline health, consumer lag |

## Dual Use

- **Internal**: Alpha agents call tools mid-evaluation (e.g., Skeptic queries setup win rate before judging)
- **External**: Claude Code / any MCP client uses same server for research ("show me all failed ADX signals with confidence > 70%")
- **eAI**: Evolved agent variants inherit tool sets via MCP permissions — tool discovery is part of the genome

## Evaluated: LangChain + Langfuse vs Extend Ours

Considered pattern: LangChain MultiServerMCPClient for tool aggregation, Langfuse for observability, Pydantic for validation.

**Decision: extend our stack, don't add LangChain/Langfuse.**

| Component | LangChain approach | Our approach |
|-----------|-------------------|--------------|
| MCP server | FastMCP (needed either way) | FastMCP — same |
| Tool calling | LangChain agent executor | ~50-line extension to `_OpenAICompatProvider` — add `tools` to JSON payload, parse `tool_calls` response |
| Tool loop | LangChain manages | Add tool loop to `BaseAIAgent._compute()` |
| Observability | Langfuse (new dep, new SaaS) | Already have: Kafka audit to `llm_calls`, Prometheus metrics, auto-audit in chain |
| Validation | Pydantic | Already using Pydantic everywhere |

**Why not LangChain:**
- Our provider chain has circuit breakers, semantic cache, token budgets, guardrails — LangChain would bypass or duplicate all of it
- LangChain adds an abstraction layer on top of an abstraction layer we already built
- All 4 providers are OpenAI-compatible — tool calling is just `tools` param + `tool_calls` response parsing
- We'd lose tight integration with our Kafka audit pipeline

**Why not Langfuse:**
- We already have full LLM observability: Kafka `llm_calls` topic → `llm_writer_service` → `llm_calls` + `llm_model_scores` tables
- Adding Langfuse means another SaaS dependency for data we already capture locally

**Only new dependency: `mcp` package (FastMCP) for the server.**

## Build Order

1. MCP server first (immediate research value — query our stack from Claude/external tools)
2. Wire tool calling into provider chain (extend _OpenAICompatProvider)
3. Add agent tool loop to BaseAIAgent
4. Wire alpha agents to use tools for historical lookup
5. (Future eAI Phase 1) Tool set as genome chromosome — agents evolve which tools they use

## Already Done (2026-05-09)

- **Null filtering** in render_full_context(): 96% null → 0% null, ~5000 chars → ~160 chars
- **QuantSignalContext** (was I7Context): expanded from 7 to 19 fields (entry_type, stop_type, zones, co_fire, confluence, etc.)
- **Semantic tier labels**: "Quantitative Indicators (i1)", "Context & Regime (i4)", "Smart Money Concepts (smc)" etc.
- **Agent class renames**: removed double-Agent (SkepticComputeAgent, CorrelationComputeAgent, etc.)
- **Narrative prompt enrichment**: now shows entry type, stop type, zone bounds, confluence, co-fire info
