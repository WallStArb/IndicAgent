# AI Agent Systems — Master Open-Source Stack Map

**Version:** 1.1.0  
**Last Updated:** 2026-02-12  
**Status:** Current — I1-I5 operational (22 plugins) 

## Purpose

Authoritative, OSS-first map of components and subcomponents for modern AI agent systems (autonomous assistants, automation bots, decision agents). Includes IndicAgent baseline choices and how each maps to Intelligence Tiers (I1–I8).

## Framework Standard

- Orchestration/workflows: LangChain / LangGraph (adopted)
- Actions/tools: LangChain Toolkits (adopted)
- Model routing: LiteLLM + OpenRouter (adopted)

## Principles

- LangGraph for orchestration; LiteLLM + OpenRouter for model routing
- Deterministic control in I5/I7; LLMs for rationale/synthesis (I8)
- Redis Streams + TimescaleDB/Postgres; pgvector for retrieval (OSS-first)
- Observability by default: OpenTelemetry + Prometheus
- Docker Compose-first; simple, cost-efficient, incremental

## Baseline (Current / Planned / Deferred)

 - Orchestration: LangChain / LangGraph (Current) / Pydantic AI
- Models: LiteLLM + OpenRouter (Current)
- Messaging: Redis Streams (Current)
- Persistence: TimescaleDB/Postgres (Current); pgvector (Current)
- Observability: OpenTelemetry (Current), Prometheus (Current), Grafana/Jaeger (Planned)
- Guardrails: Pydantic schemas + timeouts/circuit breakers (Current); Guardrails AI (Planned, ready); OPA/NeMo/Llama Guard (Deferred)
- Deployment: Docker Compose (Current); K8s/Service Mesh (Deferred)
- CI/CD: GitHub Actions (Current)

Legend: Current (C), Planned (P), Deferred (D); SaaS noted where applicable

## 1. Core Runtime (Agent Brain)

- Model/Policy
  - Tools: vLLM, TGI, Ollama, LM Studio
  - Baseline: LiteLLM + OpenRouter (C, SaaS)
  - Tiers: I8
- Reasoning/Planner
  - Tools: LangChain / LangGraph, DSPy, AutoGen, CrewAI
  - Baseline: LangChain / LangGraph (C)
  - Tiers: I5/I7/I8
- Tooling/Actions
  - Tools: LangChain Toolkits, LlamaIndex tools
  - Baseline: LangChain Toolkits (C)
  - Tiers: I5/I7
- Perception (optional)
  - Tools: Transformers, OpenCV, Whisper.cpp
  - Baseline: Deferred (D)
  - Tiers: I8
- State/Memory
  - Tools: LlamaIndex, Haystack, pgvector, Weaviate, Milvus
  - Baseline: Postgres + pgvector (C)
  - Tiers: I2/I4/I8
- Belief/State Update
  - Tools: LangGraph state, custom reducers
  - Baseline: LangGraph state (C)
  - Tiers: I5/I7/I8

## 2. Orchestration & Workflow

- Task Orchestration
  - Tools: LangChain / LangGraph, Prefect, Temporal, Dagster
  - Baseline: LangChain / LangGraph (C)
  - Tiers: I5/I7/I8
- Multi-Agent
  - Tools: AutoGen, CrewAI, MetaGPT, Langroid
  - Baseline: LangGraph composition (C)
  - Tiers: I8
- Scheduling
  - Tools: Celery, APScheduler, Arq
  - Baseline: APScheduler (P)
  - Tiers: I5/I7/I8
- Pipelines/DAGs
  - Tools: Airflow, Dagster, Prefect
  - Baseline: Deferred (D)
  - Tiers: I8

## 3. Observability & Monitoring

- Instrumentation
  - Tools: OpenTelemetry, Prometheus
  - Baseline: OpenTelemetry + Prometheus (C)
  - Tiers: All
- Dashboards
  - Tools: Grafana, OpenSearch Dashboards
  - Baseline: Grafana (P)
  - Tiers: All
- Tracing
  - Tools: Jaeger, Tempo, Zipkin
  - Baseline: OTel → Jaeger (P)
  - Tiers: All
- Anomaly Detection
  - Tools: Evidently, Arize, Feast
  - Baseline: Deferred (D)
  - Tiers: I8

## 4. Guardrails & Safety

- Input Filtering
  - Tools: Pydantic, regex, Presidio
  - Baseline: Pydantic validation + sanitization (C)
  - Tiers: All
- Output Constraints
  - Tools: Guardrails AI, Pydantic AI
  - Baseline: Pydantic schemas (C); Guardrails AI (P)
  - Tiers: I7/I8
- Policy Enforcement
  - Tools: OPA
  - Baseline: Deferred (D)
  - Tiers: I7/I8
- Rate/Access Control
  - Tools: Nginx, OAuth2 Proxy
  - Baseline: Minimal/Nginx (P)
  - Tiers: API

### Simplified Guardrails Pipeline (Adopt Now)

1) Input sanitization (fast, local)
- Regex/PII scrubbing and tool ACL allowlist
- Simple policy flags in Settings (no OPA yet)

2) LangGraph node execution
- Deterministic logic for I5/I7; LLM only in explanatory subpaths

3) Output guard
- Guardrails AI: enforce Pydantic/JSON schemas and domain constraints
- Optional sampled semantic check (e.g., Llama Guard) on high-risk nodes

4) Escalation
- On guard fail: deterministic fallback or HITL queue (`env:intel_hitl`)
- Emit OTel spans and Prometheus counters

Metrics
- `ai_guardrails_validation_total{result=pass|fail,reason}`
- `ai_guardrails_violation_total{type}`
- `ai_request_duration_seconds{stage}`
- `ai_cost_usd_total{stage}`

Settings (examples)
- `AI_GUARDRAILS_ENABLED=true`
- `AI_HITL_ENABLED=true`
- `AI_SEMANTIC_GUARD_SAMPLING=0.1`

## 5. Security & Privacy

- AuthN/AuthZ
  - Tools: OAuth2 Proxy
  - Baseline: Planned (P)
- Secrets
  - Tools: Vault, SOPS
  - Baseline: Env vars now; Vault (P)
- PII Redaction
  - Tools: Presidio, scrubadub
  - Baseline: Deferred (D)
- Supply-Chain
  - Tools: Sigstore, in-toto
  - Baseline: Deferred (D)

## 6. Data & Knowledge Management

- Vector Stores
  - Tools: Postgres + pgvector
  - Baseline: Current (C)
- Retrieval/Indexing
  - Tools: LlamaIndex, Haystack, LightRAG
  - Baseline: LlamaIndex (P)
- Labeling
  - Tools: Label Studio, doccano
  - Baseline: Deferred (D)
- Versioning/Lineage
  - Tools: DVC, LakeFS, Pachyderm
  - Baseline: Deferred (D)

## 7. Testing, Evaluation & Validation

- Unit/Integration
  - Tools: pytest, tox
  - Baseline: pytest (C)
- Safety/Adversarial
  - Tools: Promptfoo, Rebuff, Garak
  - Baseline: Promptfoo (P)
- Benchmarks
  - Tools: HELM, Evals, EleutherAI
  - Baseline: Deferred (D)
- A/B Experiments
  - Tools: Flagr, GrowthBook
  - Baseline: Deferred (D)
- Human Evaluation
  - Tools: Argilla, Label Studio
  - Baseline: Deferred (D)

## 8. UX / Interaction

- Conversational UI
  - Tools: Chainlit, Gradio, Rasa
  - Baseline: Chainlit (D)
  - Tiers: I8
- Agent–UI Protocol (event stream)
  - Tools: AG-UI (SSE/WebSocket event taxonomy)
  - Baseline: Planned (P)
  - Tiers: I7/I8
- Proactive Behavior
  - Tools: n8n
  - Baseline: n8n (D)
  - Tiers: I8
- Explainability
  - Tools: Trulens
  - Baseline: Trulens (D)
  - Tiers: I8

## 9. Developer Experience

- Replay/Debugging
  - Tools: Helicone, Trulens
  - Baseline: Helicone (D)
- CI/CD
  - Tools: GitHub Actions, Jenkins
  - Baseline: GitHub Actions (C)
- Docs
  - Tools: MkDocs, Docusaurus
  - Baseline: MkDocs (D)

## 10. Deployment & Infrastructure

- Model Hosting
  - Tools: vLLM, TGI, Ollama
  - Baseline: OpenRouter (C, SaaS); self-host (D)
- Microservices
  - Tools: FastAPI, gRPC, Kong
  - Baseline: FastAPI (P)
- Caching
  - Tools: Redis, SQLite
  - Baseline: Redis (C)
- Cost Management
  - Tools: Prometheus, Kubecost
  - Baseline: Prometheus cost counters (P)

## 11. Governance, Compliance & Audit

- Policy documents: acceptable use, data handling, escalation procedures
- Audit trails: immutable decision and tool-action logs in TimescaleDB (append-only), correlation IDs
- Regulatory checks: domain-specific controls (finance/health) via policy gates (Deferred)
- Ethics reviews / risk committees: periodic reviews, red-team findings, mitigations

## 12. Metrics & KPIs (recommended)

- Health/infra: latency (p95/p99), availability, throughput, cost/request
- Behavioral: task success rate, CSAT, average steps/task, re-runs/task
- Quality: hallucination rate, factuality score, safety violations
- Model economics: tokens/session, cost/conversation, API calls/sec
- Suggested metrics: `ai_request_total{agent,node,tier,outcome}`, `ai_request_duration_seconds{agent,node}`, `ai_cost_usd_total{provider,model}`, `ai_tokens_total{type,provider}`, `ai_safety_violations_total{type}`

## 13. Dataflow & Integration

- Input → Observation pipeline (parsing, enrichment)
- Memory/RAG retrieval (pgvector/LlamaIndex planned) → model context
- Planner/policy decides next actions (LangGraph)
- Tool invocation → normalized results → belief/state update
- Response & logging → UX; telemetry to OpenTelemetry/Prometheus
- Streams via `src/core/stream_keys.py` with `env_prefix`; contracts per `docs/architecture/intelligence-tiers.md`

## 14. Common architecture patterns

- Reactive — immediate single-step response (stateless)
- Deliberative / planner-based — explicit multi-step planning before action
- Hybrid — reactive for simple tasks, planner for complex
- Hierarchical — high-level policy delegates to specialized agents
- Multi-agent — specialized agents (search, exec, critic) coordinate (LangGraph composition)

## 15. Failure modes & mitigations

- Hallucinations → RAG with verification, chained validators, HITL
- Prompt injection → strict input sanitization, tool ACLs, separate tool prompts
- Drift → continuous monitoring, automatic retraining triggers
- Resource exhaustion / DoS → quotas, circuit breakers, backpressure
- Data leaks → token scrubbing, endpoint vetting, least privilege

## 16. Tier Alignment (I1–I8)

- I1 features: deterministic; no LLM
- I2/I4 composites/context: deterministic first; optional LLM summaries
- I5 patterns: deterministic detection + optional LLM rationale
- I7 trading outputs: deterministic decisions; LLM explanations only
- I8 insights: LLM multi-agent synthesis, narratives, what-if analysis

## 17. Near-Term Priorities (low risk, high impact)

1) Observability: Prometheus counters/histograms + OTel spans for AI nodes
2) Settings/Config: `AI_ENABLED`, provider/model map, per-request budget caps
3) Vector starter: pgvector schema + LlamaIndex adapter (read-only)
4) Minimal `ai-agent-runtime` scaffold (LangGraph state, health, metrics)

## Cross-References

- Intelligence tiers: `docs/architecture/intelligence-tiers.md`
- Stream schemas: `docs/architecture/stream-schemas.md`
- Planning: `docs/planning/ai-architecture-guide.md`, `docs/planning/ai-implementation-roadmap.md`, `docs/planning/ai-intelligence-strategy.md`, `docs/planning/ai-architecture-gaps-analysis.md`, `docs/planning/ai-agents-innovative-concepts-and-ideas.md`
 - External references: `docs/reference/AI_REFERENCE_LINKS.md`


