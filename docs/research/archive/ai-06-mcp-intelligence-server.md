# MCP Intelligence Server & Agent Tool Use

**Version:** 1.0
**Status:** under-review
**Priority:** medium
**Milestone:** future (post-v2.8)
**Last Updated:** 2026-05-10
**Tags:** mcp, tool-use, agents, ai-context, fastmcp, intelligence, push-pull, llm

## Concept

Move from pure "push" (preload AIContext, hope we guessed right) to **push/pull hybrid**: AIContext provides current bar context, agents pull additional data via tools as needed.

**MCP is the protocol, not the framework.** By exposing our intelligence via MCP tools, any agent — ours, Claude, future eAI-evolved variants — can discover and query what it needs. The framework is interchangeable; the intelligence data is not.

## Why

- LLM calls are 1-3s. A DB query via asyncpg is 5-20ms. Tool call overhead is noise-level.
- Agents currently reason blind to historical performance (setup win rates, signal outcomes, model calibration).
- The agent should decide what it needs, not us. Every tool call is audited in llm_calls.

---

## Technology Stack Decision

### MCP Server: `fastmcp` v3.2.4

| Attribute | Detail |
|-----------|--------|
| Package | `fastmcp` (includes `mcp` SDK v1.27.1 as dependency) |
| License | Apache 2.0 |
| Stars | 25,100 (github.com/PrefectHQ/fastmcp) |
| Transport | STDIO (local), Streamable HTTP (web, replaces SSE), SSE (legacy) |
| Python | >=3.10 |
| Extras | `anthropic`, `openai`, `gemini` (for client-side provider integration) |

**Why `fastmcp` over bare `mcp` SDK:** FastMCP 3.x adds Client class (for in-process tool calls), composition (mount servers), middleware, auth, and background tasks. The official `mcp` SDK bundles FastMCP 1.0 which is feature-frozen.

```python
# Server definition
from fastmcp import FastMCP

mcp = FastMCP("indicagent-intelligence", instructions="Query IndicAgent intelligence stack")

@mcp.tool
async def query_setup_performance(symbol: str, setup: str, regime: str | None = None) -> dict:
    """Historical win rate, sharpe, avg_pnl_r by setup/symbol/regime."""
    ...
```

### Agent Tool Loop: FastMCP Client + Minimal Glue

**Principle:** Leverage `fastmcp` for tool discovery, schema generation, and execution rather than hand-rolling. FastMCP Client supports in-process (no HTTP overhead) for internal agents.

Evaluated and rejected:

| Framework | Why Rejected |
|-----------|-------------|
| **LangChain** | Bypasses our circuit breakers, cache, budgets, guardrails |
| **pydantic-ai** | Owns the LLM call lifecycle — conflicts with `BaseAIAgent._compute()` |
| **litellm** | Replaces our provider chain — loses circuit breakers + rate limiting |
| **instructor** | Output validation only, not a tool loop framework |

What we use from `fastmcp`:
- **Server**: `FastMCP` class for external MCP endpoint (tool registration, schema generation, transport)
- **Client**: `FastMCP Client` for in-process tool execution by internal agents (no HTTP overhead, direct function calls)
- **Tool definitions**: Single `@mcp.tool` decorator serves both external (MCP protocol) and internal (direct async call) consumers

The tool execution glue between our `LLMProviderChain` and FastMCP is ~50 lines:

```python
# src/core/ai/tool_loop.py
from fastmcp import Client

async def tool_loop(
    chain: LLMProviderChain,
    messages: list[dict],
    mcp_client: Client,          # In-process FastMCP client (zero HTTP overhead)
    max_iterations: int = 5,
) -> str | None:
    """ReAct loop: LLM calls tools via MCP client, gets results, continues."""
    # Discover available tools from MCP server and convert to OpenAI format
    mcp_tools = await mcp_client.list_tools()
    tools = [mcp_tool_to_openai(t) for t in mcp_tools]

    for _ in range(max_iterations):
        response = await chain.generate_with_tools(messages=messages, tools=tools)
        msg = response["choices"][0]["message"]
        messages.append(msg)

        if not msg.get("tool_calls"):
            return msg.get("content")

        for tc in msg["tool_calls"]:
            args = json.loads(tc["function"]["arguments"])
            # Execute tool via FastMCP Client (in-process, direct async call)
            result = await mcp_client.call_tool(tc["function"]["name"], args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(result.data if hasattr(result, "data") else result),
            })
    return None

def mcp_tool_to_openai(mcp_tool) -> dict:
    """Convert MCP tool schema to OpenAI function-calling format."""
    return {
        "type": "function",
        "function": {
            "name": mcp_tool.name,
            "description": mcp_tool.description,
            "parameters": mcp_tool.inputSchema,
            "strict": True,
        },
    }
```

**Why FastMCP Client instead of raw dict:** Tool schema management (JSON Schema generation from type hints), tool discovery, structured error handling, and future middleware (rate limiting, logging) come free from the framework. The ~50 lines of glue are just the LLM↔tool bridge — everything else is framework-provided.

### Tool Calling: OpenAI Format (Universal)

All 4 providers support the same `tools` parameter format:

| Provider | Tool Calling Support | Quirks |
|----------|---------------------|--------|
| **OpenRouter** | Full support | Some edge cases with free models; check `supported_parameters=tools` |
| **DeepSeek** | Supported but unreliable | ~11% failure rate: emits tool calls as plain text instead of structured JSON. Wrap with fallback parser. Use `deepseek-v4-flash` (not R1). |
| **Ollama Cloud** | Full support | Standard OpenAI format via HTTP |
| **Ollama Local** | Full support | Use `/v1/chat/completions` endpoint (not `/api/chat`) for consistent format. Supported models: qwen3, gemma3, phi4, llama3.1+ |

**OpenAI `tools` format (stable spec):**

```python
tools = [{
    "type": "function",
    "function": {
        "name": "query_signal_history",
        "description": "Query recent signals with outcomes",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "limit": {"type": "integer", "description": "Max rows"}
            },
            "required": ["symbol"],
            "additionalProperties": False,
        },
        "strict": True,
    },
}]
```

---

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

---

## Architecture: Dual-Use Design

The MCP server serves three distinct consumers through a single tool implementation:

```
┌─────────────────────────────────────────────────────┐
│                 FastMCP Server                       │
│            (src/mcp/server.py)                       │
│                                                      │
│  query_setup_performance · query_signal_history      │
│  query_features · query_ohlcv · query_llm_scores     │
│  get_service_status                                  │
│                                                      │
│  Transport: HTTP (Streamable HTTP, :8090)            │
│             STDIO (for local integration)             │
└──────────┬──────────────┬──────────────┬─────────────┘
           │              │              │
    ┌──────┴───┐   ┌─────┴──────┐  ┌────┴───────────┐
    │ Internal │   │  External   │  │   eAI Engine   │
    │  Agents  │   │  Clients    │  │   (future)     │
    │          │   │             │  │                 │
    │ Skeptic  │   │ Claude Code │  │ Genome gets    │
    │ Correl.  │   │ Research    │  │ tool_perms=[]  │
    │ etc.     │   │ Dashboard   │  │ from evolution │
    └──────────┘   └────────────┘  └─────────────────┘
```

**Internal agents** don't go through MCP protocol — they use the OpenAI tool loop directly against the same `async def` tool functions. The MCP server is the external interface; internally, the tool functions are called as plain async functions.

This avoids double-serialization (agent → MCP protocol → tool → MCP protocol → agent) for internal calls while keeping the MCP server as the canonical tool catalog.

---

## Stack Additions

### New Dependency

```
# requirements.txt
fastmcp>=3.2.0
```

### Code Changes

| Change | File | Lines | Purpose |
|--------|------|-------|---------|
| `generate_with_tools()` | `src/core/llm/providers.py` | ~40 | Add `tools` + `tool_choice` to payload, return raw response dict |
| `generate_with_tools()` (Ollama) | `src/core/llm/providers.py` | ~20 | Switch to `/v1/chat/completions` for tool-calling requests |
| `tool_loop()` + `mcp_tool_to_openai()` | `src/core/ai/tool_loop.py` (NEW) | ~50 | ReAct loop using FastMCP Client for tool execution |
| MCP server + tools | `src/mcp/server.py` (NEW) | ~250 | FastMCP server: tool definitions + asyncpg query implementations |
| DeepSeek fallback parser | `src/core/llm/providers.py` | ~15 | Handle plain-text tool call emission |

### OllamaProvider Change

Current `OllamaProvider` hits `/api/chat` (native Ollama API). For tool-calling requests, switch to `/v1/chat/completions` (OpenAI-compatible endpoint) so the tool_calls response format is identical across all providers.

```python
async def generate_with_tools(self, messages, tools, tool_choice="auto", **kwargs):
    """Use /v1/chat/completions for OpenAI-compatible tool calling."""
    payload = {
        "model": self.model,
        "messages": messages,
        "tools": tools,
        "tool_choice": tool_choice,
        "format": "json",
    }
    # POST to /v1/chat/completions instead of /api/chat
    ...
```

---

## MCP Server Tools

Each tool is an async function backed by asyncpg. Same functions serve both MCP (external) and tool loop (internal).

| Tool | Source Table | Parameters | Returns |
|------|-------------|------------|---------|
| `query_setup_performance` | `setup_performance` | `symbol`, `setup`, `regime?` | `{win_rate, sharpe, avg_pnl_r, sample_size}` |
| `query_signal_history` | `signal_ledger` | `symbol`, `setup?`, `outcome?`, `limit?` | `[{signal_id, setup, direction, outcome, pnl_r, ts}]` |
| `query_features` | `intelligence_features` | `symbol`, `ts`, `tf` | `{i1, i2, i3, i4, i5, i6, smc, i7}` |
| `query_ohlcv` | `market_data_ohlcv` + views | `symbol`, `tf`, `bars?` | `[{ts, o, h, l, c, v}]` |
| `query_llm_scores` | `llm_model_scores` | `model_id?` | `[{model, win_rate, calibration, p_value}]` |
| `get_service_status` | Prometheus metrics | — | `{services: [{name, up, lag}]}` |

### Tool Implementation Pattern

```python
# src/mcp/tools/performance.py
from fastmcp import FastMCP

mcp = FastMCP("indicagent-intelligence")

@mcp.tool
async def query_setup_performance(
    symbol: str,
    setup: str,
    regime: str | None = None,
) -> dict:
    """Historical win rate, sharpe, avg_pnl_r by setup/symbol/regime.
    Only returns rows with sample_size >= 30 (FEED-02 gate)."""
    async with asyncpg.connect(settings.database_url) as conn:
        query = """
            SELECT win_rate, sharpe, avg_pnl_r, sample_size
            FROM setup_performance
            WHERE symbol = $1 AND setup_plugin = $2 AND sample_size >= 30
        """
        args = [symbol, setup]
        if regime:
            query += " AND regime = $3"
            args.append(regime)
        row = await conn.fetchrow(query, *args)
        return dict(row) if row else {"error": "no data", "sample_size": 0}
```

---

## Build Order

### Phase 1: MCP Server (immediate research value)

1. `pip install fastmcp>=3.2.0`
2. Create `src/mcp/server.py` with all 6 tools
3. Run as standalone: `fastmcp dev src/mcp/server.py` (dev) or `fastmcp run src/mcp/server.py` (production)
4. Claude Code / external clients can query immediately

### Phase 2: Provider Chain Extension

1. Add `generate_with_tools()` to `_OpenAICompatProvider` (~40 lines)
2. Add `generate_with_tools()` to `OllamaProvider` with `/v1/` endpoint (~20 lines)
3. Add DeepSeek fallback parser for plain-text tool calls (~15 lines)
4. Add `generate_with_tools()` to `LLMProviderChain` facade (delegates to providers)

### Phase 3: Agent Tool Loop

1. Create `src/core/ai/tool_loop.py` — the ReAct loop (~50 lines)
2. Create `src/core/ai/tool_registry.py` — shared tool function registry
3. Wire tool functions (same ones MCP server uses) into registry
4. Add `tool_loop()` call option to `BaseAIAgent._compute()`

### Phase 4: Wire Alpha Agents

1. Skeptic: adds `query_setup_performance` to check historical win rate before judging
2. Correlation: adds `query_signal_history` to see recent correlated signal outcomes
3. Counterfactual: adds `query_features` + `query_ohlcv` for historical pattern matching
4. Each agent declares `tools_needed: ClassVar[list[str]]` — maps to registry keys

### Phase 5: eAI Tool Set Chromosome (future)

1. Agent genome includes `tool_permissions: list[str]` — which tools this variant may call
2. Evolution operators mutate tool_permissions (add/remove tools)
3. Fitness scoring includes tool diversity metrics (novelty)
4. Gene bank catalogs which tool combinations produced fit genomes

---

## Transport Configuration

**HTTP (Streamable HTTP):** Primary for external access.
```bash
# Production
fastmcp run src/mcp/server.py --transport http --port 8090

# Dev with hot reload
fastmcp dev src/mcp/server.py
```

**STDIO:** For local CLI integration (Claude Desktop, subprocess).
```bash
fastmcp run src/mcp/server.py --transport stdio
```

### External Client Usage

```python
# Claude Code / any MCP client
from fastmcp import Client

async with Client("http://localhost:8090/mcp") as client:
    tools = await client.list_tools()
    result = await client.call_tool("query_setup_performance", {
        "symbol": "ES",
        "setup": "adx_trend"
    })
```

---

## Observability

### Tool Call Audit Trail

Every tool call (internal or external) produces an audit record:

1. **Internal (tool loop):** `tool_loop()` logs each call with agent_id, tool_name, args, result, latency_ms → captured in `llm_calls` via existing audit pipeline
2. **External (MCP):** FastMCP middleware logs tool calls → same audit pipeline

### Prometheus Metrics

| Metric | Type | Labels |
|--------|------|--------|
| `mcp_tool_calls_total` | Counter | `tool_name, status` |
| `mcp_tool_duration_ms` | Histogram | `tool_name` |
| `mcp_tool_result_rows` | Histogram | `tool_name` |

---

## DeepSeek Quirk Handling

DeepSeek v4-flash emits tool calls as plain text ~11% of the time instead of structured JSON. Mitigation:

```python
# In _OpenAICompatProvider._parse_tool_calls()
def _parse_tool_calls(self, response: dict) -> list[dict] | None:
    """Extract tool_calls from response. Handle DeepSeek plain-text emission."""
    message = response["choices"][0]["message"]

    # Standard path
    if tool_calls := message.get("tool_calls"):
        return tool_calls

    # DeepSeek fallback: parse plain-text tool invocation
    content = message.get("content", "")
    if "```json" in content and '"name"' in content:
        try:
            extracted = self._parse_json(content)
            if extracted and "name" in extracted:
                return [{
                    "id": f"fallback_{hash(content)}",
                    "type": "function",
                    "function": {
                        "name": extracted["name"],
                        "arguments": json.dumps(extracted.get("arguments", extracted.get("parameters", {}))),
                    },
                }]
        except (json.JSONDecodeError, KeyError):
            pass

    return None
```

---

## Security

- **MCP server runs read-only queries.** No INSERT/UPDATE/DELETE through MCP tools.
- **Rate limiting** via FastMCP middleware (prevent runaway tool calls from external clients).
- **Query result size limits.** All tools cap returned rows (default 50, max 200).
- **No credentials in tool parameters.** DB connection comes from settings, not from caller input.
- **SQL injection prevention.** All queries use parameterized asyncpg (`$1`, `$2`, ...). No string interpolation.

---

## Already Done (2026-05-09 through 2026-05-10)

- **Null filtering** in render_full_context(): 96% null → 0% null, ~5000 chars → ~160 chars
- **QuantSignalContext** (was I7Context): expanded from 7 to 19 fields (entry_type, stop_type, zones, co_fire, confluence, etc.)
- **Semantic tier labels**: "Quantitative Indicators (i1)", "Context & Regime (i4)", "Smart Money Concepts (smc)" etc.
- **Agent class renames**: removed double-Agent (SkepticComputeAgent, CorrelationComputeAgent, etc.)
- **Narrative prompt enrichment**: now shows entry type, stop type, zone bounds, confluence, co-fire info
- **AI tech stack doc updated**: `docs/intelligence/ai-tech-stack.md` v3.0 with full MCP + eAI gap analysis
