<!-- generated-by: gsd-doc-writer -->
# AI/ML Tech Stack — Consolidated Reference

**Version:** 1.0
**Status:** under-review
**Priority:** high
**Milestone:** v2.8
**Last Updated:** 2026-05-27
**Tags:** ai, ml, tech-stack, lightgbm, pydantic-ai, litellm, ollama, evolvable-ai, intelligence

**Deep dives:**
- Agent system: `../ideas/ai-02-ml-agent-architecture.md` — Multi-agent learning machine design
- MCP server: `../ideas/ai-06-mcp-intelligence-server.md` — Tool use design for agents
- eAI evolution: `../concepts/evolvable-ai.md` — Darwinian agent evolution framework
- Validation: `../ideas/renaissance-alpha-pipeline.md` — Shadow-first statistical gates
- Platform stack: `../ideas/tech-stack.md` — Full infrastructure decisions

---

## 1. Executive Summary

**Our AI/ML philosophy:** Renaissance-grade rigor, simplest tool that works, statistical proof over intuition.

**Three AI epochs on our roadmap:**

| Epoch | Status | What |
|-------|--------|------|
| **Intelligence by design** | Live | Handcrafted I1-I7 plugins, deterministic signal pipeline (132 plugins) |
| **Intelligence by learning** | Partially live | LLM swarm agents (I8), ML scoring (planned v2.8) |
| **Intelligence by evolution** | Design phase | eAI — agents that evolve their own architecture (genome) |

**Core principles:**
- **Show Me the Data** — No model acts on capital until n >= 100 resolved signals with bootstrap CI lower > 0
- **Shadow-First Validation** — Bootstrap CI > 0 at 95% confidence before promotion
- **Tabular > Deep Learning** — Gradient boosting wins on our data type
- **Self-Hosted Everything** — No vendor lock-in, no cloud ML services
- **MCP as Protocol** — Intelligence data is portable, framework is interchangeable
- **Evolve, Don't Hardcode** — Agent genome (prompts, config, tools) is data, not code
- **Leverage OSS Frameworks** — Use open-source frameworks wherever they fit; only hand-roll when the framework genuinely conflicts with our architecture

---

## 2. Current State — What We Have (v2.8, May 2026)

### 2.1 LLM Provider Chain (Active)

**File:** `src/core/llm/chain.py` + `src/core/llm/providers.py`

The narrative service (`indicagent-narrative-compute`) and swarm agents use a single Ollama local provider. OpenRouter, DeepSeek, and OllamaCloud providers were removed from the narrative path.

| Provider | Type | Default Model | Status |
|----------|------|---------------|--------|
| **OllamaProvider** | Local (primary) | `gemma4:e4b` (AMD ROCm GPU, Docker `:11434`) | Active |

Override default with `OLLAMA_MODEL` in `.env`. Swarm agent latency with gemma4:e4b: p50 ~47-52s (within 120s budget).

**Settings fields:** `ollama_enabled`, `ollama_model`, `ollama_base_url`, `ollama_num_ctx`, `llm_timeout_sec`

### 2.2 Custom LLM Middleware (Active)

**File:** `src/core/llm/chain.py` + `src/core/llm/`

| Component | Purpose | Status |
|-----------|---------|--------|
| `LLMProviderChain` | High-level facade: cache → rate limit → budget → chain → guardrails | Active |
| `SemanticCache` | LRU + TTL (5 min) cache; key = SHA-256(system + prompt[:200] + model); 500 entries max | Active |
| `RateLimiter` | Per-provider RPM/TPM rate limiting | Active |
| `TokenBudget` | Daily token budget tracking | Active |
| `GuardrailsValidator` | Pydantic-based schema validation of LLM responses (custom, NOT `guardrails-ai` pip) | Active |
| Circuit Breakers | Per-provider with configurable thresholds and recovery | Active |

**Audit pipeline:** every call → `llm.calls` (Kafka) → `indicagent-llm-writer` → `llm_calls` (TimescaleDB). Agents MUST use `self._llm_generate()` — never call `self._llm.generate()` directly. `_llm_generate()` auto-injects audit context (call_id, symbol, signal_id, regime, agent_id, prompt_version).

**gemma4:e4b JSON enforcement:** outputs prose preamble without explicit system message starting with `"OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE."` Add `"Begin your response with { and end with }."` at end of user prompt.

### 2.3 Agent Framework (Active)

**Files:** `src/core/ai/base_agent.py`, `src/core/ai/base_group_service.py`

| Component | Purpose | Status |
|-----------|---------|--------|
| `BaseAIAgent` | Universal base: wall-clock timing, timeout enforcement, exception handling, OTel tracing, graceful shutdown | Active |
| `BaseGroupCoordinator` | Shared dispatcher: Kafka consumer/producer, DB pool, `AIContextCache`, `LLMProviderChain`, agent dispatch, graduation loop | Active |
| `IAIAgent` Protocol | Interface: `agent_id`, `group`, `tiers_needed`, `shadow_only`, `latency_budget_ms`, `prompt_version` | Active |
| `AIContext` / `AIContextCache` | Tiered context (I1-I7, SMC) per bar; in-memory cache with 5-min TTL; `render_full_context()` for LLM prompts | Active |
| `LineageRecorder` | Full ancestry tracking per agent call; periodic Kafka flush | Active |

**Mandatory attributes on all `BaseAIAgent` subclasses:** `agent_id`, `group`, `tiers_needed`, `latency_budget_ms`, `shadow_only`, `prompt_version`.

**`BaseGroupCoordinator` construction rule:** agents needing `self._llm_chain` must be constructed in `_setup()` after `super()._setup()` — `_llm_chain` is `None` in `__init__`.

### 2.4 Swarm Agents (Active)

| Agent | File | Group | Dimension | Latency Budget | Status |
|-------|------|-------|-----------|---------------|--------|
| **Skeptic** | `alpha/skeptic_agent.py` | alpha | Holistic failure probability | 120s | Shadow |
| **Correlation** | `alpha/correlation_agent.py` | alpha | Cross-asset coherence | 120s | Shadow |
| **Regime Coherence** | `alpha/regime_coherence_agent.py` | alpha | Regime consistency check | 120s | Shadow |
| **Counterfactual** | `alpha/counterfactual_agent.py` | alpha | Historical pattern matching | 120s | Shadow |
| **ML Scorer v1** | `alpha/ml_scorer_v1.py` | alpha | Local ML model score | 50ms | Shadow |
| **Narrative** | `narrative/narrative_agent.py` | narrative | Market narrative prose (on-demand HTTP) | — | Live |

**Agent protocol:** All agents implement `_compute(context: AIContext) -> AgentOutput`. Alpha agents return a multiplier (0.0-1.0). Current policy is discount-only — agents may reduce confidence but should not boost above 1.0 until outcome data proves positive edge.

**Shadow governance:** Components are auto-enrolled at startup via `shadow_registry_ensure()` / `enroll_all_plugins()`. Promotion requires `n >= 100` AND `bootstrap_ci_lower(pnl_r) > 0.0`. Demotion when EV[R] < -0.05 for 3 consecutive cycles.

**Swarm raw signal confidence:** `calibrated_confidence` is null in Kafka signal payloads. Gate on `raw_signal.get("confidence")` or `raw_signal.get("pre_quality_confidence")`.

### 2.5 Observability (Active)

| Tool | Purpose | Status |
|------|---------|--------|
| **OpenTelemetry** | Distributed tracing via `src/observability/otel.py` | Active — every `BaseAIAgent` gets a tracer |
| **Prometheus** | Metrics via OTel SDK (not prometheus_client) — per-service exporters on :9113-:9130 | Active — `AI_AGENT_DURATION_MS`, `AI_AGENT_INVOCATIONS_TOTAL` |
| **structlog** | Structured JSON logs → `logs/<service>.log` | Active |
| **Tempo** | Distributed trace storage | Active (Docker) |
| **OTel Collector** | Trace/metric pipeline | Active (Docker) |
| **Loki** | Log aggregation | Active (Docker) |
| **Grafana** | Dashboards :3001 | Active (Docker) |
| **Alertmanager** | Alert routing (Prometheus → Slack/email) | Active (Docker :9093) |

**Metrics pattern:** counters → `.add(1, {"label": val})`, histograms → `.record(val, {"label": val})`. Never import `prometheus_client` — use OTel SDK only via `src/observability/metrics.py`.

**Spans:** use `observed_span(name, attributes={...})` from `src/observability/spans.py` — auto-records ERROR status + exception on raise.

### 2.6 LLM Audit Trail (Active)

| Table | Purpose | Status |
|-------|---------|--------|
| `llm_calls` | Full audit per call: prompt, response, provider, latency, token usage, agent_id, prompt_version. Composite PK: `(call_id, called_at)` | Active |
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

**Design doc:** `docs/research/ai-06-mcp-intelligence-server.md`

MCP enables agents to pull historical data on demand instead of relying solely on pre-loaded `AIContext`. It's also the substrate for eAI tool set evolution.

| Gap | What's Needed | Effort | Depends On |
|-----|--------------|--------|------------|
| MCP server | `mcp` Python package (FastMCP); new `src/mcp/` module exposing 6+ intelligence tools | ~2-3 days | Nothing |
| Tool calling in providers | Extend `_OpenAICompatProvider` JSON payload with `tools`/`tool_choice`; parse `tool_calls` response | ~1 day | All providers are OpenAI-compatible |
| Agent tool loop | LLM returns tool calls → execute → feed results → continue (in `BaseAIAgent._compute()`) | ~1 day | Tool calling in providers |
| MCP tool implementations | `query_setup_performance`, `query_signal_history`, `query_features`, `query_ohlcv`, `query_llm_scores`, `get_service_status` | ~2 days | MCP server |
| Wire alpha agents | Skeptic queries setup win rate; Correlation queries signal history; etc. | ~1 day | Tool loop + MCP tools |

**Only new dependency: `mcp` package (FastMCP).** No LangChain, no new framework.

### 3.2 Evolvable AI (eAI) Substrate

**Design doc:** `docs/concepts/evolvable-ai.md`, `docs/research/ai-03-evolvable-ai-agents.md`

| Gap | What's Needed | Effort | Depends On |
|-----|--------------|--------|------------|
| Agent genome model | Data model: prompts, config params, tool sets, guardrails as heritable/mutable units | ~2 days | BaseAIAgent framework |
| Gene bank storage | `agent_genomes` table + `genome_archive` for frozen variants | ~1 day | Genome model |
| Reproductive operators | Mutation (blind perturbation), recombination (crossover), LLM-directed mutation | ~3-5 days | Gene bank |
| Composite fitness function | Accuracy, novelty, calibration, regime specificity, efficiency scoring | ~3-5 days | 100+ day signal ledger outcome data |
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
- `BaseAIAgent` / `BaseGroupCoordinator` framework
- Shadow mode governance

All providers are OpenAI-compatible — tool calling is just `tools` param + `tool_calls` response parsing. ~50 lines of code vs. a heavy abstraction layer.

### 4.2 Langfuse vs Local Audit vs Alternatives

**Decision: wire Langfuse alongside local audit.** Not either/or:
- **Local audit** (`llm_calls` table): Already capturing every call. Keep for SQL queries, ML training data, long-term retention.
- **Langfuse** (v3, MIT, 19k stars): Real-time trace visualization, cost dashboards, prompt playground, annotation workflows, evaluation suites. OTEL-native SDK v3. Deployed at :3010.
- **Why both**: Langfuse for operational visibility, local tables for statistical analysis and ML training samples.

**Langfuse v3 note:** Requires ClickHouse in addition to PostgreSQL. Our v2 container is Postgres-only. Upgrading to v3 adds one more Docker container.

### 4.3 MCP Framework

**Decision: `fastmcp` v3.2.4** (includes `mcp` SDK v1.27.1). 25k stars, Apache 2.0.

Use FastMCP for both server AND client:
- **Server**: MCP endpoint for external consumers (Claude Code, research)
- **Client**: In-process tool execution for internal agents (no HTTP overhead, direct async calls)
- **Tool definitions**: Single `@mcp.tool` decorator serves both paths

The LLM↔tool bridge is ~50 lines of glue code. Everything else (schema generation, tool discovery, error handling, middleware) comes from FastMCP.

Rejected: LangChain (bypasses our chain), pydantic-ai (owns LLM lifecycle), litellm (replaces our chain).

### 4.4 eAI Evolution Engine

**Decision: custom framework + DSPy/GEPA for prompt chromosome.**

No off-the-shelf framework fits our 6-chromosome genome model with shadow governance and statistical gates. The landscape:

| Tool | What it does | Fits our model? |
|------|-------------|----------------|
| **DSPy/GEPA** (20k stars, MIT) | Genetic-Pareto prompt optimization. Treats prompts as textual genome, evolves with mutation + crossover + Pareto selection. | **Partial** — covers prompt chromosome only. Use for 1 of 6 chromosomes. |
| **EvoAgentX** (2.9k stars) | Generates whole multi-agent workflows from NL descriptions. | No — wrong granularity. Generates workflows; we evolve individual agent parameters. |
| **TextGrad** (3.4k stars) | LLM feedback as "gradients" for text optimization. | No — software-immature (v0.1.6, last release Dec 2024). Subsumed by GEPA. |

**Hybrid approach:**
1. Use **DSPy** as the evolution framework — its `Module` abstraction, `teleprompter` optimizers, and evaluation harness handle much of the infrastructure
2. Use **GEPA** (Genetic-Pareto) optimizer for prompt evolution
3. Build custom chromosomes for config, tool-set, guardrails as DSPy-compatible modules where possible
4. Shadow governance, statistical gates, and `signal_ledger` fitness data plug in as DSPy evaluation metrics

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
│   Alpha: MLScorerV1 (50ms, local model)                               │
│   Narrative: NarrativeComputeAgent (on-demand prose)                  │
│   Shadow governance: auto-enroll at startup, bootstrap CI gates      │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ uses
┌────────────────────────────┴─────────────────────────────────────────┐
│                    LLM Provider Chain (Active)                        │
│   SemanticCache → RateLimiter → TokenBudget →                        │
│   [OllamaProvider (gemma4:e4b, OLLAMA_MODEL override)] →             │
│   GuardrailsValidator                                                 │
│   Circuit breaker per provider                                        │
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
│   OTel traces + Prometheus metrics (OTel SDK only) + structlog logs  │
│   Langfuse (:3010, container deployed, SDK not wired) + Grafana (:3001) │
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
| `pydantic` | >=2.12.0 | Schema validation everywhere |
| `scipy` | 1.17.1 | Statistics, promotion gates |
| `statsmodels` | — | ADF stationarity, CUSUM |
| `scikit-learn` | — | Calibration, preprocessing |
| `numpy` | >=2.4.0 | Real-time inference arrays |
| `pandas` | >=3.0.0 | Data manipulation |
| `tsfresh` | 0.21.1 | Auto feature extraction |
| `structlog` | 25.5.0 | Structured logging |
| `opentelemetry-api/sdk` | 1.41.0 | Distributed tracing + metrics |
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
| Apache Superset | :8088 | SQL analytics against TimescaleDB (read-only) | Design complete, not deployed — see `docs/research/bi-analytics-layer-design.md` |

### Planned (Not Installed)

| Package | Purpose | Install Gate |
|---------|---------|--------------|
| `fastmcp` >=3.2.0 | MCP intelligence server (includes `mcp` SDK v1.27.1) | MCP Phase — v2.8 AI Platform |
| `dspy` >=3.0.0 | Prompt chromosome optimization (GEPA optimizer) | eAI Phase 1 — prompt evolution only |
| `lightgbm` >=4.6.0 | ML scoring model | Phase v2.8 / data gate |
| `xgboost` >=3.2.0 | Shadow challenger | Phase v2.8 |
| `optuna` >=4.3.0 | Bayesian hyperparameter search | v2.8 |
| `shap` >=0.51.0 | Feature attribution | v2.8 |
| `polars` | Batch feature matrix building | v2.8 |
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
| **TextGrad** | Academic (Nature paper) but software-immature (v0.1.6, last release Dec 2024). Subsumed by DSPy GEPA | Never — use DSPy/GEPA instead |
| **EvoAgentX** | Generates whole multi-agent workflows — wrong granularity for our genome model | Never — custom evolution engine |
| **OpenRouter/DeepSeek/OllamaCloud** | Removed from narrative path; Ollama local is the single provider for runtime inference | Only if local inference proves insufficient |

---

## 7. Data Flow — AI/ML Path

### 7.1 Current (Live)

```
IBKR TWS → 1m bars → Redpanda → intelligence_pipeline_agent (I1-I7, 132 plugins)
                                                ↓
                                    IntelligenceEvent (typed bus)
                                                ↓
                              ┌───── feature_writer → intelligence_features (TimescaleDB)
                              └───── signal_writer → signal_ledger (TimescaleDB)
                                          ↓ (signal_ledger: entry_zone_low/high, expires_at)
                              alpha_swarm_service (async, out-of-band)
                                          ↓
                              AIContextCache.build() → AIContext
                                          ↓
                              Skeptic/Correlation/RegimeCoherence/Counterfactual
                              (BaseGroupCoordinator dispatches in parallel, 120s budget each)
                                          ↓
                              OllamaProvider (gemma4:e4b) → multiplier per agent
                                          ↓
                              Aggregated multiplier → signal confidence
                                          ↓
                              Narrative (on-demand HTTP, DB-cached, Ollama)
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

Based on v2.8 roadmap (AI Platform + Evolvable Agents):

### Now (no blockers)
1. **MCP server** — immediate research value; query our stack from Claude/external tools
2. **Wire Langfuse SDK** — container is running, just needs `pip install langfuse` + wiring
3. **LiteLLM + Instructor** (Phase 094) — structured output extraction

### After MCP
4. **Tool calling in providers** — extend `_OpenAICompatProvider` with `tools` param
5. **Agent tool loop** — `BaseAIAgent._compute()` handles tool calls
6. **Wire alpha agents** — Skeptic queries setup win rate, etc.

### After data gate (30-day signal data accumulating)
7. **`ctx` substrate** — `ctx_events`, `ctx_snapshots`, `CtxWriterAgent`
8. **LightGBM signal scoring** — ML-scored signals
9. **One deterministic qual lane** — macro calendar or earnings

### After substrate + ML scoring proven
10. **eAI Phase 1** — LLM-directed prompt mutation (lowest risk)
11. **eAI Phase 2** — Composite fitness function + gene bank
12. **Wire MLflow** — experiment tracking for eAI genome evaluation

### Later (needs outcome data to evaluate)
13. **eAI Phase 3** — Config parameter mutation + population management
14. **MoA + adversarial patterns** — prove they improve over single-model baseline first
15. **eAI Phase 4** — Code/logic evolution (highest risk)

---

## 9. Shadow-First Lifecycle (Universal)

Every AI output follows this path — no exceptions:

```
1. SHADOW MODE — Observe live data, produce analysis, zero production impact
2. FITNESS EVALUATION — Measure out-of-sample across multiple market regimes
3. STATISTICAL GATE — n >= 100 resolved signals + bootstrap CI lower > 0.0 at 95%
4. PROMOTION — Multiplier feeds into signal scoring
5. PRODUCTION — Continuous monitoring continues
6. DEGRADATION — Auto-disable if EV[R] < -0.05 for 3 consecutive 30-min cycles
```

Applies to: I7 plugins, swarm agents, ML models, LLM-derived heuristics, eAI-evolved variants.

---

## Technology Decision Principles

**Principle 1: Self-hosted everything**
> "Vendor lock-in is architectural debt we can't afford."

We run everything on our own infrastructure. No cloud ML services, no paid observability platforms. Ollama local for inference, TimescaleDB for storage, Prometheus/Grafana for metrics.

**Principle 2: Simplest tool that works**
> "Don't introduce a framework when 50 lines of code will do."

Our LLM provider chain is ~300 lines of custom code. LangChain would be 10x the complexity for the same functionality. We only add frameworks when they solve a problem we can't hand-roll efficiently.

**Principle 3: Tabular > Deep Learning**
> "Gradient boosting wins 95% of tabular benchmarks."

Our data is structured time-series features (OHLCV, indicators, regime scores). Tree ensembles (LightGBM) dominate this space. We'll add PyTorch when we have unstructured data (news text, options surface images).

**Principle 4: Shadow-first validation**
> "No AI output touches production without statistical proof."

Every agent, model, or heuristic starts in shadow mode. n >= 100 resolved outcomes + bootstrap CI lower > 0.0 at 95% confidence before promotion.

**Principle 5: Data is forever**
> "Never drop data that could contain a signal."

We keep `intelligence_features`, `signal_ledger`, `signal_lineage`, and `llm_calls` forever. Storage is cheapest; data is irreplaceable. Every outcome is training data for the next model iteration.

**Why Ollama local over cloud APIs:**
- Zero latency from network calls
- No API key management
- No per-token billing surprises
- Works offline
- Model swap is a local config change

**Why custom agent framework over LangChain:**
- Our shadow governance pattern is unique
- Our lineage requirements are unique
- Our statistical gates are unique
- Framework would fight us on all three

**Why TimescaleDB over vector DB for features:**
- Our features are structured (not embeddings)
- Time-series queries are our primary access pattern
- Hypertable partitioning optimizes for time-based queries
- Vector similarity only needed for eAI novelty (pgvector planned)

---

## Renaissance Checklist for AI/ML Technology Choices

Before adding a new AI/ML dependency:

| Question | Renaissance principle |
|----------|----------------------|
| Is it self-hosted? No vendor lock-in? | Self-hosted everything |
| Is it open-source? Can we fork if abandoned? | Control our destiny |
| Does it solve a problem we can't hand-roll in <100 lines? | Simplest tool that works |
| Does it support shadow-first validation? | Statistical proof before production |
| Does it integrate with our data pipeline (Kafka → TimescaleDB)? | Infrastructure as edge |
| What's the ongoing maintenance cost? | Simplest tool that works |
| Does it work with our data type (tabular time-series)? | Tabular > Deep Learning |

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-05-27 | Updated to v2.8 state; Ollama is now sole runtime provider | OpenRouter/DeepSeek/OllamaCloud removed from narrative path per CLAUDE.md |
| 2026-05-27 | Plugin count updated to 132 (was 123) | Verified from TIER_I1..TIER_I7 in register_plugins.py |
| 2026-05-27 | Swarm: all 4 LLM agents have 120s budget; ml_scorer_v1 has 50ms | Verified from CLAUDE.md |
| 2026-05-10 | Added MCP + eAI sections, updated provider chain | Reflect v2.5 state with DeepSeek, Ollama Cloud |
| 2026-05-10 | MCP with FastMCP only | No LangChain; all providers are OpenAI-compatible; ~50 lines for tool calling |
| 2026-05-10 | Custom eAI engine (no framework) | Our genome model + shadow governance + statistical gates have no off-the-shelf match |
| 2026-04-21 | LightGBM over PyTorch/TF | Dominates tabular benchmarks |
| 2026-04-21 | Custom guardrails over `guardrails-ai` | Pydantic validator suffices, no heavy dep chain |
| 2026-03-24 | MLflow for experiment tracking | Self-hosted, open source |
| 2026-03-10 | LangFuse over LangSmith | Self-hosted, open source, no vendor lock-in |

---

## 11. Related Documentation

**Core architecture:**
- `ai-intelligence-architecture.md` — Full I1-I8 pipeline architecture
- `ai-intelligence-resources.md` — LLM provider chain usage patterns
- `../architecture/current-state.md` — Active services, data flow, performance

**Design docs (MCP + eAI):**
- `../ideas/ai-06-mcp-intelligence-server.md` — MCP server + tool use design
- `../concepts/evolvable-ai.md` — eAI concept overview
- `../ideas/ai-03-evolvable-ai-agents.md` — Full eAI design document

**Deep dives:**
- `../ideas/ai-02-ml-agent-architecture.md` — Multi-agent learning machine design
- `../ideas/renaissance-alpha-pipeline.md` — Shadow-first statistical gates
- `../ideas/tech-stack.md` — Full platform stack (Redpanda, TimescaleDB, etc.)

**Code reference:**
- `src/intelligence/ai/AUTHORING.md` — Agent authoring protocol
- `src/core/ai/TEMPLATE_agent.py` — Skeleton for new agents
- `src/intelligence/ai/alpha/skeptic_agent.py` — Canonical agent reference
- `src/intelligence/register_plugins.py` — TIER_I1..TIER_I7 canonical plugin lists

---

**Version:** 3.1.0
**Last Updated:** 2026-05-27
**Milestone:** v2.8 — AI Platform + Evolvable Agents
