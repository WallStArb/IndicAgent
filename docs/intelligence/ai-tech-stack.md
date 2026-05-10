# AI/ML Tech Stack — Consolidated Reference

**Purpose:** Single reference for all AI/ML technology choices. What we use, why we chose it, how it fits together.
**Last Updated:** 2026-05-10
**Status:** Living document — reflects current v2.5 state + eAI/MCP expansion plans

**Deep dives:**
- Agent system: `../ideas/ml-agent-architecture.md` — Multi-agent learning machine design
- MCP server: `../ideas/mcp-intelligence-server.md` — Tool use design for agents
- eAI evolution: `../concepts/evolvable-ai.md` — Darwinian agent evolution framework
- Validation: `../ideas/renaissance-alpha-pipeline.md` — Shadow-first statistical gates
- Platform stack: `../ideas/tech-stack.md` — Full infrastructure decisions

---

## 1. Executive Summary

**Our AI/ML philosophy:** Renaissance-grade rigor, simplest tool that works, statistical proof over intuition.

**Three AI epochs on our roadmap:**

| Epoch | Status | What |
|-------|--------|------|
| **Intelligence by design** | Live | Handcrafted I1-I7 plugins, deterministic signal pipeline |
| **Intelligence by learning** | Partially live | LLM swarm agents (I8), ML scoring (Phase 70, deferred) |
| **Intelligence by evolution** | Design phase | eAI — agents that evolve their own architecture (genome) |

**Core principles:**
- **Show Me the Data** — No model acts on capital until p < 0.05, N >= 100
- **Shadow-First Validation** — Bootstrap CI > 0 at 95% confidence before promotion
- **Tabular > Deep Learning** — Gradient boosting wins on our data type
- **Self-Hosted Everything** — No vendor lock-in, no cloud ML services
- **MCP as Protocol** — Intelligence data is portable, framework is interchangeable
- **Evolve, Don't Hardcode** — Agent genome (prompts, config, tools) is data, not code
- **Leverage OSS Frameworks** — Use open-source frameworks wherever they fit; get community updates, bug fixes, and features for free. Only hand-roll when the framework genuinely conflicts with our architecture (not just because we can)

---

## 2. Current State — What We Have (v2.5, May 2026)

### 2.1 LLM Provider Chain (Active)

**File:** `src/core/llm/providers.py`

| Provider | Type | Models | Circuit Breaker | Cost |
|----------|------|--------|----------------|------|
| **OpenRouterProvider** | Cloud (primary) | `google/gemma-4-31b-it:free`, `nvidia/nemotron-super-49b-v1:free`, `z-ai/glm-4.5-air:free`, etc. | 3 failures → 5 min | Free tier |
| **DeepSeekProvider** | Cloud (low-cost) | `deepseek-v4-flash` ($0.14/1M), `deepseek-v4-pro` ($0.435/1M) | Inherits OpenAI compat | $0.14-0.87/1M tokens |
| **OllamaCloudProvider** | Cloud (free) | `minimax-m2.7`, `nemotron-3-super`, `gemini-3-flash-preview` | Inherits OpenAI compat | Free (OLLAMA_API_KEY) |
| **OllamaProvider** | Local (fallback) | `gemma4:e4b` (AMD ROCm GPU), `phi4-mini:3.8b` | 5 failures → 1 min | Free (self-hosted) |

**Chain order:** OpenRouter → DeepSeek → Ollama Cloud → Ollama Local (always available)

All 4 providers are OpenAI-compatible (`/chat/completions` payload). This is the foundation for MCP tool calling — no new API format needed.

### 2.2 Custom LLM Middleware (Active)

**File:** `src/core/llm/chain.py` + `src/core/llm/`

| Component | Purpose | Status |
|-----------|---------|--------|
| `LLMProviderChain` | High-level facade: cache → rate limit → budget → chain → guardrails | Active |
| `SemanticCache` | LRU + TTL (5 min) cache; key = SHA-256(system + prompt[:200] + model); 500 entries max | Active |
| `RateLimiter` | Per-provider RPM/TPM rate limiting | Active |
| `TokenBudget` | Daily token budget; routes to Ollama-only when cloud budget exceeded | Active |
| `GuardrailsValidator` | Pydantic-based schema validation of LLM responses (custom, NOT `guardrails-ai` pip) | Active |
| Circuit Breakers | Per-provider with configurable thresholds and recovery | Active |

### 2.3 Agent Framework (Active)

**Files:** `src/core/ai/base_agent.py`, `src/core/ai/base_group_service.py`

| Component | Purpose | Status |
|-----------|---------|--------|
| `BaseAIAgent` | Universal base: wall-clock timing, timeout enforcement, exception handling, Prometheus metrics, OTel tracing, graceful shutdown | Active |
| `BaseGroupService` | Shared dispatcher: Kafka consumer/producer, DB pool, `AIContextCache`, `LLMProviderChain`, agent dispatch, graduation loop | Active |
| `IAIAgent` Protocol | Interface: `agent_id`, `group`, `tiers_needed`, `shadow_only`, `latency_budget_ms` | Active |
| `AIContext` / `AIContextCache` | Tiered context (I1-I7, SMC) per bar; in-memory cache with 5-min TTL; `render_full_context()` for LLM prompts | Active |
| `LineageRecorder` | Full ancestry tracking per agent call; periodic Kafka flush | Active |

**Phase 80 planned upgrades** (branch `feat/phase80-swarm-observability-ux`):
- `_llm_generate()` — calls `self._llm.generate()`, handles empty response
- `_parse_json()` — fence stripping + backward brace matching for reasoning model output
- `_make_output()` — constructs `AgentOutput` with fixed fields
- Fix `_seed_context_cache()` to include I2/I3/I5/SMC columns

### 2.4 Swarm Agents (Active)

| Agent | File | Group | Dimension | Output | Status |
|-------|------|-------|-----------|--------|--------|
| **Skeptic** | `alpha/skeptic_agent.py` | alpha | Counterfactual challenge | `failure_probability`, `confidence`, `risk_factors` → multiplier | Live |
| **Correlation** | `alpha/correlation_agent.py` | alpha | Cross-asset coherence | `coherence_score`, `confidence`, `contradicting_assets` → multiplier | Shadow |
| **Regime Coherence** | `alpha/regime_coherence_agent.py` | alpha | Regime consistency | Regime validation → multiplier | Shadow |
| **Counterfactual** | `alpha/counterfactual_agent.py` | alpha | Historical pattern matching | Similar setup outcomes → multiplier | Shadow |
| **Narrative** | `narrative/narrative_agent.py` | narrative | Market narrative | Prose + action bias (on-demand HTTP) | Live |

**Agent protocol:** All agents implement `_compute(context: AIContext) -> AgentOutput`. Alpha agents return a multiplier (0.0-1.0) applied to signal confidence. Narrative agents return prose for display.

### 2.5 Observability (Active)

| Tool | Purpose | Status |
|------|---------|--------|
| **OpenTelemetry** | Distributed tracing via `src/observability/otel.py` | Active — every `BaseAIAgent` gets a tracer |
| **Prometheus** | Metrics collection; per-service exporters on :9113-:9130 | Active — `AI_AGENT_DURATION_MS`, `AI_AGENT_INVOCATIONS_TOTAL` |
| **structlog** | Structured JSON logs → `logs/<service>.log` | Active |
| **Tempo** | Distributed trace storage | Active (Docker) |
| **OTel Collector** | Trace/metric pipeline | Active (Docker) |
| **Loki** | Log aggregation | Active (Docker) |
| **Grafana** | Dashboards :3001 | Active (Docker) |
| **Alertmanager** | Alert routing (Prometheus → Slack/email) | Active (Docker :9093) |
| **Apache Superset** | SQL analytics against TimescaleDB (:8088) | Designed, not deployed — see `docs/ideas/bi-analytics-layer-design.md` |

### 2.6 LLM Audit Trail (Active)

| Table | Purpose | Status |
|-------|---------|--------|
| `llm_calls` | Full audit per call: prompt, response, provider, latency, token usage, agent_id | Active |
| `llm_model_scores` | Per-model win rate, calibration, significance; refreshed every 15 min | Active |
| `signal_lineage` | Agent ancestry per signal | Active |
| `shadow_registry` | Shadow state for all I7 plugins + swarm agents; statistical promotion/demotion gates | Active |

### 2.7 Dashboard AI Features (Active)

| Feature | File | Purpose |
|---------|------|---------|
| Narrative display | `dashboard/src/components/signal/narrative-elevated.tsx` | Two-tier AI narratives for hero signals |
| Narrative API | `src/api/routes/narrative.py` | On-demand narrative generation, DB-first, idempotent |
| Swarm multipliers | Dashboard signal display | AI confidence adjustments shown per signal |

### 2.8 Signal Analysis Libraries (Installed, Available)

| Tool | Version | Purpose | When to Use |
|------|---------|---------|-------------|
| **stumpy** | 1.14.1 | Matrix Profile — time-series motif discovery | I5 pattern matching, anomaly detection |
| **numba** | 0.65.0 | JIT compilation for NumPy-heavy loops | Hot-path plugin optimization |
| **PyWavelets** | 1.9.0 | Wavelet transforms for signal decomposition | Multi-resolution analysis, regime detection |
| **empyrical-reloaded** | 0.5.12 | Performance metrics (Sharpe, Sortino, Calmar) | Signal performance stats, ML evaluation |
| **tsfresh** | 0.21.1 | Auto feature extraction (700+ features) | ML discovery phase |

---

## 3. Gap Analysis — What We Need for Expansion

### 3.1 MCP Intelligence Server (Tool Use)

**Design doc:** `docs/ideas/mcp-intelligence-server.md`

MCP enables agents to pull historical data on demand instead of relying solely on pre-loaded `AIContext`. It's also the substrate for eAI tool set evolution.

| Gap | What's Needed | Effort | Depends On |
|-----|--------------|--------|------------|
| MCP server | `mcp` Python package (FastMCP); new `src/mcp/` module exposing 6+ intelligence tools | ~2-3 days | Nothing |
| Tool calling in providers | Extend `_OpenAICompatProvider` JSON payload with `tools`/`tool_choice`; parse `tool_calls` response | ~1 day | All 4 providers are OpenAI-compatible |
| Agent tool loop | LLM returns tool calls → execute → feed results → continue (in `BaseAIAgent._compute()`) | ~1 day | Tool calling in providers |
| MCP tool implementations | `query_setup_performance`, `query_signal_history`, `query_features`, `query_ohlcv`, `query_llm_scores`, `get_service_status` | ~2 days | MCP server |
| Wire alpha agents | Skeptic queries setup win rate; Correlation queries signal history; etc. | ~1 day | Tool loop + MCP tools |

**Only new dependency: `mcp` package (FastMCP).** No LangChain, no new framework.

### 3.2 Evolvable AI (eAI) Substrate

**Design doc:** `docs/concepts/evolvable-ai.md`, `docs/ideas/2026-05-06-evolvable-ai-agents.md`

| Gap | What's Needed | Effort | Depends On |
|-----|--------------|--------|------------|
| Agent genome model | Data model: prompts, config params, tool sets, guardrails as heritable/mutable units | ~2 days | BaseAIAgent refactor (Phase 80) |
| Gene bank storage | `agent_genomes` table + `genome_archive` for frozen variants | ~1 day | Genome model |
| Reproductive operators | Mutation (blind perturbation), recombination (crossover), LLM-directed mutation | ~3-5 days | Gene bank |
| Composite fitness function | Accuracy, novelty, calibration, regime specificity, efficiency scoring | ~3-5 days | More outcome data (30+ day signal ledger) |
| Population management | Birth → shadow → breeding → promotion → soft death → frozen archive lifecycle | ~3 days | Fitness function |
| Novelty measurement | `pgvector` extension on PostgreSQL for embedding similarity | ~1 day | pgvector install |
| Tool set chromosome | Agents inherit different MCP tool permissions | ~2 days | MCP server |
| LLM-directed mutation | LLM analyzes parent genome + performance, proposes targeted improvements | ~2 days | Reproductive operators |

**Implementation phases:**
1. LLM-directed prompt mutation (lowest risk, leverages existing framework)
2. Composite fitness function (build and stress-test evaluation substrate)
3. Config parameter mutation + gene bank (persistent population management)
4. Code/logic evolution (highest risk, LLM-generated analysis variants)

### 3.3 LLM Expansion — General Gaps

| Gap | What's Needed | Status | Why |
|-----|--------------|--------|-----|
| **Langfuse wiring** | Add `langfuse` SDK to `LLMProviderChain`; trace every LLM call | Container deployed (:3010), SDK not installed | Full LLM observability: token usage per agent, prompt/response traces, cost tracking |
| **MLflow wiring** | Add `mlflow` to requirements.txt; wire `src/core/ml/registry.py` | Container deployed (:5000), lazy import exists | Experiment tracking for eAI genome evaluation, ML model versioning |
| **Prompt management** | Structured A/B testing beyond `prompt_version` string | Design needed | eAI needs to mutate prompts systematically; current versioning is manual |
| **Multi-model routing** | Route simpler tasks to cheaper/faster models | Not started | DeepSeek flash for routine evaluations, pro for complex reasoning; cost optimization |
| **Agent evaluation framework** | Automated evaluation beyond shadow mode win rate | Not started | eAI needs composite fitness scoring across 5 dimensions |

### 3.4 `ctx` Substrate (Qualitative Intelligence)

**Design doc:** `docs/plans/2026-05-02-unified-intelligence-design.md`

| Gap | What's Needed | Depends On |
|-----|--------------|------------|
| `ctx_events` Kafka topic | New topic for qualitative events (macro, earnings, news) | Nothing |
| `ctx_snapshots` table | Materialized context snapshots per bar | `ctx_events` |
| `intelligence_features.ctx` column | JSONB column for additive qual context | `ctx_snapshots` |
| `CtxWriterAgent` skeleton | Writer that materializes qual context into features | Table + topic |
| One deterministic qual lane | Macro calendar or earnings (not news first — too many NLP concerns) | `CtxWriterAgent` |

**Build order:** `ctx` substrate → one qual lane → additional lanes → shadow evaluation gate

---

## 4. Tech Stack Decisions — Evaluating Frameworks

### 4.1 LangChain vs Extend Our Own

**Decision: extend our stack.** LangChain would bypass or duplicate:
- Circuit breakers, semantic cache, token budgets, guardrails
- Kafka audit pipeline (`llm_calls` table)
- `BaseAIAgent` / `BaseGroupService` framework
- Shadow mode governance

All 4 providers are OpenAI-compatible — tool calling is just `tools` param + `tool_calls` response parsing. ~50 lines of code vs. a heavy abstraction layer.

### 4.2 Langfuse vs Local Audit vs Alternatives

**Decision: wire Langfuse alongside local audit.** Not either/or:
- **Local audit** (`llm_calls` table): Already capturing every call. Keep for SQL queries, ML training data, long-term retention.
- **Langfuse** (v3, MIT, 19k stars): Real-time trace visualization, cost dashboards, prompt playground, annotation workflows, evaluation suites. OTEL-native SDK v3. Deployed at :3010.
- **Why both**: Langfuse for operational visibility, local tables for statistical analysis and ML training samples.

**Evaluated alternatives:**
- **Arize Phoenix** (8k stars, Apache 2.0): Stronger embedding drift detection, but less complete for agent tracing + prompt management. Worth monitoring for drift features.
- **LangSmith**: Proprietary, self-hosting requires Enterprise license. Hard pass.
- **OpenLIT**: Niche OTEL-only layer, Langfuse does everything it does plus more.
- **Helicone**: Interesting AI Gateway (model routing) but less mature observability.
- **Braintrust**: Evaluation-focused, not full observability.

**Langfuse v3 note:** Requires ClickHouse in addition to PostgreSQL. Our v2 container is Postgres-only. Upgrading to v3 adds one more Docker container.

### 4.3 MCP Framework

**Decision: `fastmcp` v3.2.4** (includes `mcp` SDK v1.27.1). 25k stars, Apache 2.0.

Use FastMCP for both server AND client:
- **Server**: MCP endpoint for external consumers (Claude Code, research)
- **Client**: In-process tool execution for internal agents (no HTTP overhead, direct async calls)
- **Tool definitions**: Single `@mcp.tool` decorator serves both paths

The LLM↔tool bridge is ~50 lines of glue code. Everything else (schema generation, tool discovery, error handling, middleware) comes from FastMCP. This follows the "leverage OSS frameworks" principle — we get community updates and features for free.

Rejected: LangChain (bypasses our chain), pydantic-ai (owns LLM lifecycle), litellm (replaces our chain).

### 4.4 eAI Evolution Engine

**Decision: custom framework + DSPy/GEPA for prompt chromosome.**

No off-the-shelf framework fits our 6-chromosome genome model with shadow governance and statistical gates. The landscape:

| Tool | What it does | Fits our model? |
|------|-------------|----------------|
| **DSPy/GEPA** (20k stars, MIT) | Genetic-Pareto prompt optimization. Treats prompts as textual genome, evolves with mutation + crossover + Pareto selection. | **Partial** — covers prompt chromosome only. Use for 1 of 6 chromosomes. |
| **EvoAgentX** (2.9k stars) | Generates whole multi-agent workflows from NL descriptions. | No — wrong granularity. Generates workflows; we evolve individual agent parameters. |
| **TextGrad** (3.4k stars) | LLM feedback as "gradients" for text optimization. Nature paper. | No — v0.1.6, last release Dec 2024. Software-immature. Subsumed by GEPA. |
| **AdalFlow** | PyTorch-like prompt optimization. | No — no evolutionary model. |
| **OpenELM / OpenEvolve** | LLM-guided genetic programming for code synthesis. | No — code synthesis, not agent config evolution. |

**Hybrid approach (maximize OSS leverage):**
1. Use **DSPy** as the evolution framework — its `Module` abstraction, `teleprompter` optimizers, and evaluation harness handle much of the infrastructure we'd otherwise hand-roll
2. Use **GEPA** (Genetic-Pareto) optimizer for prompt evolution — state-of-the-art, maintains population, applies mutation + crossover + Pareto selection
3. Build custom chromosomes for config, tool-set, guardrails as DSPy-compatible modules where possible
4. Our shadow governance, statistical gates, and `signal_ledger` fitness data plug in as DSPy evaluation metrics
5. Only custom-code what DSPy genuinely cannot do (shadow mode lifecycle, per-signal outcome tracking, population management across market regimes)

The substrate already exists:
- Shadow mode with statistical promotion gates (Phase 75)
- Signal ledger outcome tracking (fitness data accumulating)
- Lineage recording (ancestry tracking)
- `BaseAIAgent` framework (genome mutations = parameter variations)

### 4.5 Deep Learning (PyTorch/TF)

**Decision: not now.** Our data is tabular time-series features — tree ensembles dominate. LightGBM wins 95% of tabular benchmarks with minutes of training vs. hours for neural nets.

**When we'd add PyTorch:** Unstructured data (news text embeddings, options surface images, audio from earnings calls).

---

## 5. Architecture Overview (Current + Planned)

```
┌──────────────────────────────────────────────────────────────────────┐
│                    eAI Evolution Engine (Planned)                     │
│   Gene Bank → Mutation/Recombination/LLM-directed → Population Mgmt  │
│   Fitness: Accuracy × Novelty × Calibration × Regime × Efficiency   │
│   Tool Set Chromosome via MCP permissions                             │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ evolves
┌────────────────────────────┴─────────────────────────────────────────┐
│                    MCP Intelligence Server (Planned)                  │
│   FastMCP → query_setup_performance, query_signal_history,           │
│   query_features, query_ohlcv, query_llm_scores, get_service_status  │
│   Dual use: internal agents + external Claude/research               │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ tools
┌────────────────────────────┴─────────────────────────────────────────┐
│                    Swarm Agent Layer (Active)                         │
│   Alpha: Skeptic, Correlation, RegimeCoherence, Counterfactual       │
│   Narrative: NarrativeComputeAgent (on-demand prose)                  │
│   Risk: (placeholder)                                                 │
│   Shadow governance: auto-promote/demote via bootstrap CI gates      │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ uses
┌────────────────────────────┴─────────────────────────────────────────┐
│                    LLM Provider Chain (Active)                        │
│   SemanticCache → RateLimiter → TokenBudget →                        │
│   [OpenRouter → DeepSeek → OllamaCloud → Ollama Local] →            │
│   GuardrailsValidator                                                 │
│   Circuit breakers per provider                                       │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ calls
┌────────────────────────────┴─────────────────────────────────────────┐
│                    Context Layer (Active)                             │
│   AIContext (I1-I7, SMC, BarContext, QuantSignalContext)              │
│   AIContextCache (in-memory, 5-min TTL, per-bar refresh)             │
│   render_full_context() → LLM-friendly text (null-filtered)         │
│   Future: ctx substrate for qualitative intelligence                 │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ feeds
┌────────────────────────────┴─────────────────────────────────────────┐
│                    Observability (Active)                             │
│   OTel traces + Prometheus metrics + structlog logs                  │
│   Langfuse (:3010, deploying) + Grafana (:3001, live)                │
│   llm_calls table (full audit) + llm_model_scores (calibration)      │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                Visualization Stack (4 Layers)                         │
│   Grafana (:3001) — ops/time-series (Prometheus metrics, health)     │
│   Next.js (:3000) — real-time intelligence (SSE, signals, AI)        │
│   Superset (:8088) — SQL analytics (TimescaleDB read-only, planned)  │
│   Python (matplotlib/plotly) — research/analytical output            │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 6. Dependency Status

### Active (Installed + Wired)

| Package | Version | Purpose |
|---------|---------|---------|
| `langgraph` | >=1.0.0 | Agent orchestration (installed, limited use) |
| `pydantic` | >=2.12.0 | Schema validation everywhere |
| `scipy` | 1.17.1 | Statistics, promotion gates |
| `statsmodels` | — | ADF stationarity, CUSUM |
| `scikit-learn` | — | Calibration, preprocessing |
| `numpy` | >=2.4.0 | Real-time inference arrays |
| `pandas` | >=3.0.0 | Data manipulation |
| `tsfresh` | 0.21.1 | Auto feature extraction |
| `structlog` | 25.5.0 | Structured logging |
| `prometheus-client` | 0.25.0 | Metrics |
| `opentelemetry-api/sdk` | 1.41.0 | Distributed tracing |
| `asyncpg` | — | Async DB (all new DB code) |
| `aiokafka` | — | Kafka consumer/producer |

### Available (Installed, Not Wired)

| Package | Purpose | Wiring Gate |
|---------|---------|-------------|
| `stumpy` 1.14.1 | Matrix profile motif discovery | I5/I7 plugin research |
| `numba` 0.65.0 | JIT compilation for hot paths | Plugin optimization |
| `PyWavelets` 1.9.0 | Wavelet decomposition | Regime transition detection |
| `empyrical-reloaded` 0.5.12 | Performance metrics (Sharpe, etc.) | ML evaluation pipeline |

### Deployed (Docker Container, SDK Not Wired)

| Service | Port | Purpose | Wiring Gate |
|---------|------|---------|-------------|
| Langfuse | :3010 | LLM observability, prompt traces | Add `langfuse` SDK to `LLMProviderChain` |
| MLflow | :5000 | Experiment tracking, model registry | Add `mlflow` to requirements.txt, wire registry.py |
| Apache Superset | :8088 | SQL analytics against TimescaleDB (read-only) | Design complete, not deployed — see `docs/ideas/bi-analytics-layer-design.md` |

### Planned (Not Installed)

| Package | Purpose | Install Gate |
|---------|---------|--------------|
| `fastmcp` >=3.2.0 | MCP intelligence server (includes `mcp` SDK v1.27.1) | MCP Phase 1 — immediate research value |
| `dspy` >=3.0.0 | Prompt chromosome optimization (GEPA optimizer) | eAI Phase 1 — prompt evolution only |
| `lightgbm` >=4.6.0 | ML scoring model | Phase 70 / data gate |
| `xgboost` >=3.2.0 | Shadow challenger | Phase 70 |
| `optuna` >=4.3.0 | Bayesian hyperparameter search | Phase 64 |
| `shap` >=0.51.0 | Feature attribution | Phase 64 |
| `polars` | Batch feature matrix building | Phase 64 |
| `pgvector` | Vector similarity for eAI novelty | eAI Phase 2 |

### Explicitly Rejected

| Technology | Why Not | When We'd Reconsider |
|------------|---------|---------------------|
| **LangChain** | Our provider chain has circuit breakers, cache, budgets, guardrails — LangChain duplicates or bypasses all | Never — our stack is purpose-built |
| **pydantic-ai** | Owns the LLM call lifecycle — conflicts with `BaseAIAgent._compute()` and our `LLMProviderChain` | Never — hand-roll the ~40-line tool loop instead |
| **litellm** | Replaces our provider chain — loses circuit breakers + rate limiting | Never — our chain is better for our needs |
| **instructor** | Output validation only, not a tool loop framework; our `GuardrailsValidator` already does schema validation | If we need retry-based structured extraction |
| **guardrails-ai** | Custom Pydantic validator in `src/core/llm/guardrails.py` suffices | If we need Rail specs or multi-step validation |
| **PyTorch/TF** | Overkill for tabular; gradient boosting wins | Unstructured data added (news, options) |
| **Ray/Dask** | Overkill for current scale (<1M rows) | Data volume >10M rows |
| **Feast** | TimescaleDB IS our feature store | Multi-service feature sharing |
| **Weights & Biases** | Cloud, paid; MLflow is open-source | Never — self-hosted principle |
| **Temporal** | LangGraph sufficient for near-term | Institutional multi-day workflows |
| **TextGrad** | Academic (Nature paper) but software-immature (v0.1.6, last release Dec 2024). Subsumed by DSPy GEPA | Never — use DSPy/GEPA instead |
| **EvoAgentX** | Generates whole multi-agent workflows — wrong granularity for our genome model | Never — custom evolution engine |

---

## 7. Data Flow — AI/ML Path

### 7.1 Current (Live)

```
IBKR TWS → 1m bars → Redpanda → intelligence_pipeline_agent (I1-I7)
                                                ↓
                                    IntelligenceEvent (typed bus)
                                                ↓
                              ┌───── feature_writer → TimescaleDB
                              └───── signal_ledger → TimescaleDB
                              └───── alpha_swarm_service (I8 LLM layer)
                                          ↓
                              AIContextCache.build() → AIContext
                                          ↓
                              Skeptic/Correlation/RegimeCoherence/Counterfactual
                              (BaseGroupService dispatches in parallel)
                                          ↓
                              LLMProviderChain → multiplier per agent
                                          ↓
                              Aggregated multiplier → signal confidence
                                          ↓
                              Narrative (on-demand HTTP, DB-cached)
```

### 7.2 With MCP (Planned)

```
Same as above, but agents can also:
  ┌──→ MCP tool call: query_setup_performance(symbol, setup, regime)
  │   └──→ Returns historical win_rate, sharpe, avg_pnl_r
  ├──→ MCP tool call: query_signal_history(symbol, setup, outcome, limit=20)
  │   └──→ Returns recent signals with outcomes
  └──→ MCP tool call: query_features(symbol, ts, tf)
      └──→ Returns raw feature vector for any past bar

External access: Claude Code / any MCP client → same MCP server
```

### 7.3 With eAI (Planned)

```
Gene Bank (agent_genomes table)
  ↓ reproduction operators (mutation / recombination / LLM-directed)
  ↓
New genome variant → instantiate as shadow BaseAIAgent
  ↓ shadow evaluation (n >= 100 resolved signals)
  ↓
Composite fitness scoring:
  accuracy × novelty (pgvector) × calibration × regime_specificity × efficiency
  ↓
Statistical gate: bootstrap CI lower > 0 at 95% confidence
  ↓
Promotion: genome becomes live agent variant
  ↓
Continuous monitoring: decay triggers soft death → frozen archive
```

---

## 8. Build Order — Recommended Sequence

Based on the strategy in memory (`project_ai_foundation_strategy.md`):

### Now (no blockers)
1. **BaseAIAgent refactor** (Phase 80) — extract shared LLM plumbing before more agents
2. **MCP server** — immediate research value; query our stack from Claude/external tools
3. **Wire Langfuse SDK** — container is running, just needs `pip install langfuse` + wiring

### After Phase 80 + MCP
4. **Tool calling in providers** — extend `_OpenAICompatProvider` with `tools` param
5. **Agent tool loop** — `BaseAIAgent._compute()` handles tool calls
6. **Wire alpha agents** — Skeptic queries setup win rate, etc.

### After data gate (~May 10 = now, 30-day signal data available)
7. **`ctx` substrate** — `ctx_events`, `ctx_snapshots`, `CtxWriterAgent`
8. **LightGBM signal scoring** (Phase 70) — ML-scored signals
9. **One deterministic qual lane** — macro calendar or earnings

### After substrate + ML scoring proven
10. **eAI Phase 1** — LLM-directed prompt mutation (lowest risk)
11. **eAI Phase 2** — Composite fitness function + gene bank
12. **Additional qual lanes** — earnings, macro, news
13. **Wire MLflow** — experiment tracking for eAI genome evaluation

### Later (needs outcome data to evaluate)
14. **eAI Phase 3** — Config parameter mutation + population management
15. **MoA + adversarial patterns** — prove they improve over single-model baseline first
16. **eAI Phase 4** — Code/logic evolution (highest risk)

---

## 9. Shadow-First Lifecycle (Universal)

Every AI output follows this path — no exceptions:

```
1. SHADOW MODE — Observe live data, produce analysis, zero production impact
2. FITNESS EVALUATION — Measure out-of-sample across multiple market regimes
3. STATISTICAL GATE — Bootstrap CI lower > 0 at 95%, N >= 100 resolved
4. PROMOTION — Multiplier feeds into signal scoring
5. PRODUCTION — Continuous monitoring continues
6. DEGRADATION — Auto-disable if EV[R] < -0.05 for 3 consecutive 30-min cycles
```

Applies to: I7 plugins, swarm agents, ML models, LLM-derived heuristics, eAI-evolved variants.

---

## 10. Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-05-10 | Added MCP + eAI sections, updated provider chain | Reflect v2.5 state with DeepSeek, Ollama Cloud, Phase 80 work |
| 2026-05-10 | DeepSeek as second provider | $0.14/1M tokens, 1M context, OpenAI-compatible, tool call support |
| 2026-05-10 | Ollama Cloud as third provider | Free cloud models with OLLAMA_API_KEY, another fallback |
| 2026-05-10 | MCP with FastMCP only | No LangChain; all providers are OpenAI-compatible; ~50 lines for tool calling |
| 2026-05-10 | Custom eAI engine (no framework) | Our genome model + shadow governance + statistical gates have no off-the-shelf match |
| 2026-05-10 | Langfuse alongside local audit | Not either/or — Langfuse for ops visibility, local tables for ML training |
| 2026-04-21 | LightGBM over PyTorch/TF | Dominates tabular benchmarks |
| 2026-04-21 | Custom guardrails over `guardrails-ai` | Pydantic validator suffices, no heavy dep chain |
| 2026-03-24 | MLflow for experiment tracking | Self-hosted, open source |
| 2026-03-15 | optuna for hyperparameter search | Bayesian optimization with LightGBMTuner |
| 2026-03-15 | tsfresh for feature discovery | 700+ auto features, feeds IC analysis |
| 2026-03-10 | LangFuse over LangSmith | Self-hosted, open source, no vendor lock-in |

---

## 11. Related Documentation

**Core architecture:**
- `ai-intelligence-architecture.md` — Full I1-I8 pipeline architecture
- `ai-intelligence-resources.md` — LLM provider chain usage patterns
- `../architecture/current-state.md` — Active services, data flow, performance

**Design docs (MCP + eAI):**
- `../ideas/mcp-intelligence-server.md` — MCP server + tool use design
- `../concepts/evolvable-ai.md` — eAI concept overview
- `../ideas/2026-05-06-evolvable-ai-agents.md` — Full eAI design document
- `../ideas/agent-orchestration-patterns.md` — MoA, adversarial, dynamic leadership (future)

**Deep dives:**
- `../ideas/ml-agent-architecture.md` — Multi-agent learning machine design
- `../ideas/renaissance-alpha-pipeline.md` — Shadow-first statistical gates
- `../ideas/tech-stack.md` — Full platform stack (Redpanda, TimescaleDB, etc.)
- `../ideas/ai-integration-paths.md` — Tier 1/2/3 dependency chain

**Code reference:**
- `src/core/ai/AUTHORING.md` — Agent authoring protocol
- `src/core/ai/TEMPLATE_agent.py` — Skeleton for new agents
- `src/intelligence/ai/alpha/skeptic_agent.py` — Canonical agent reference

---

**Version:** 3.0.0
**Last Updated:** 2026-05-10
**Milestone:** v2.5 Data Quality / Phase 80 Swarm Observability
