# Phase 66: SkepticAgent - Context

**Gathered:** 2026-04-24
**Status:** Ready for planning

<domain>
## Phase Boundary

First LLM-powered swarm agent on Phase 56 infrastructure. At signal fire time, asks the LLM "what's wrong with this signal?" — predicts failure probability via structured prompt. Runs as standalone Kafka consumer microservice processing 5m+ TF winner signals. Writes all predictions (raw and adjusted) as separate auditable columns — never overwrites existing confidence values. Production impact from day one.

Includes: SkepticAgent service, structured LLM prompt with versioning, failure probability mapping, naive baseline computation, validation/correlation scripts.

Excludes: Additional swarm agents (future phases), deterministic heuristic scorer (deferred), dashboard UI for skeptic accuracy (future phase).

</domain>

<decisions>
## Implementation Decisions

### LLM Prompt Design
- **D-01:** Full SwarmContext dump as structured JSON input — send all available features (regime, ATR, RSI, CTF alignment, volume, OHLCV, winner signal metadata). Maximum context for LLM reasoning. Higher token cost but richer signal.
- **D-02:** LLM returns structured JSON: `failure_probability` [0,1], `confidence` [0,1], `risk_factors` (list of strings), `reasoning` (free text). Parseable, auditable, every field stored.
- **D-03:** Prompt versioning in code — `prompt_registry.py` stores prompt template with version ID (e.g. `skeptic_v1`). Version tracked in every `alpha_multiplier_shadow` row via `features` JSONB. No DB dependency on hot path. A/B testable by deploying new version.

### Failure Probability Mapping
- **D-04:** Start with linear transfer function: `multiplier = (1.0 - failure_probability) * llm_confidence`. Shadow-track raw `failure_probability` and `confidence` separately. Transfer function is a separable concern — tunable without touching LLM layer. Let validation discover optimal mapping.
- **D-05:** Confidence-weighted — `llm_confidence` modulates the multiplier. Low-confidence predictions decay toward neutral (1.0). High-confidence predictions have full impact.
- **D-06:** Never overwrite existing confidence values. Each SkepticAgent adjustment is a separate, auditable column: `skeptic_failure_prob`, `skeptic_confidence`, `skeptic_adjusted_confidence`. Follows the same pattern as CIS attribution (raw → calibrated → TOD → perf → skeptic). All intermediate values persisted.

### Trigger & Orchestration
- **D-07:** Single `SwarmDispatchService` consuming from `intelligence.i7.signals`. All swarm agents run as pure compute classes inside one process — shared SwarmContextCache, ShadowRecorder, DB pool, LLMProviderChain, Kafka connections. Adding a new agent = adding a SwarmBaseAgent subclass, not deploying a new service. Independent failure domains maintained per-agent via neutral fallback on any exception.
- **D-08:** SwarmContext seeded from DB on startup via `SwarmContextCache.seed_from_db_row()`, kept warm by consuming bar topics. Already built in Phase 56.
- **D-09:** 5m+ TF filter only — process 5m, 15m, 1h, 4h, 1d. Skip 1m (too frequent, ~500+ signals/day). At 5m+ we get ~50-100 signals/day across 55 symbols. Manageable LLM cost (~$0.50-2.00/day).
- **D-10:** Production impact from day one. SkepticAgent output flows into signal confidence. On failure/timeout: fallback to neutral (no adjustment). No shadow-only period — but all predictions tracked to `alpha_multiplier_shadow` for continuous validation.
- **D-11:** `SafeSwarmWrapper` wraps the LLM call — timeout, exception isolation, neutral fallback on error. Already built in Phase 56.

### Validation Framework
- **D-12:** Naive baseline: per-segment historical failure rate from `signal_ledger`. Compute failure rate per (regime, tf, setup). E.g. "trend signals on ES 5m in ranging regime fail 62% of the time." The LLM must beat this baseline per segment.
- **D-13:** Validation via correlation + segment analysis. JOIN `alpha_multiplier_shadow` → `signal_ledger` on `signal_id`. Compute Pearson(skeptic_failure_prob, actual_outcome) per segment. Output report with per-regime/TF/setup breakdown.
- **D-14:** Graduation gate: per-segment Pearson ρ ≥ 0.3 AND p < 0.05 AND N ≥ 30. Segments that pass get promoted individually. Global threshold: overall ρ ≥ 0.2.

### Service Architecture
- **D-15:** Single SwarmDispatchService — all swarm agents deployed as compute-only SwarmBaseAgent subclasses inside one process. One bar consumer, one signal consumer, one DB pool, one ShadowRecorder, one LLMProviderChain, one SwarmContextCache. Agents are registered in an agent list and run via `asyncio.gather()`. This is the correct microservices DAG pattern — the service is the deployment unit, the agent is the compute unit.
- **D-16:** SwarmContext schema extended with optional enrichment fields: `lead_context: SwarmContext | None = None` (for CorrelationAgent) and `volume_profile: dict[str, Any] | None = None` (for VolumeAgent). No `object.__setattr__` hacks — proper Pydantic fields with validation.

### Claude's Discretion
- Exact prompt wording and system message
- Signal_ledger migration column names (subject to existing conventions)
- Systemd unit configuration details
- Naive baseline script implementation details
- Agent registration order (does not affect results since agents are independent)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Swarm Infrastructure (Phase 56)
- `src/core/agents/alpha_contributor.py` — IAlphaContributor protocol definition
- `src/intelligence/swarm/context.py` — SwarmContext + SwarmContextCache (seed_from_db_row, build)
- `src/intelligence/swarm/safety.py` — SafeSwarmWrapper (timeout, exception isolation, neutral fallback)
- `src/intelligence/swarm/aggregator.py` — SwarmAggregator (Path A/B combination)
- `src/intelligence/swarm/metrics.py` — SwarmMetrics (Prometheus counters/histograms)
- `src/core/ml/shadow.py` — ShadowRecorder (batch DB writes to alpha_multiplier_shadow)

### LLM Infrastructure
- `src/core/llm/chain.py` — LLMProviderChain (OpenRouter → Ollama, caching, guardrails)
- `src/core/llm/providers.py` — LLMChain, OpenRouterProvider, OllamaProvider

### Signal Pipeline
- `src/intelligence/schemas.py` — AgentResult, AlphaMultiplier schemas
- `src/core/stream_keys.py` — topic_swarm_* functions (5 topics)
- `src/intelligence/swarm/agents/` — archived placeholder agents (pattern reference)

### Database
- `production/migrations/058_alpha_multiplier_shadow.sql` — shadow table schema

### Project Principles
- `CLAUDE.md` — naming conventions, service patterns, test patterns, Renaissance principles
- `src/intelligence/CLAUDE.md` — plugin protocol, I7 utilities, signal lifecycle

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `IAlphaContributor` protocol: `compute(SwarmContext) → AgentResult` — the contract SkepticAgent implements
- `SwarmContextCache.seed_from_db_row()`: seeds cache from intelligence_features row — no need to build context from scratch
- `SafeSwarmWrapper`: timeout + exception isolation + neutral fallback — wrap SkepticAgent LLM call
- `ShadowRecorder`: batch async writes to alpha_multiplier_shadow — just call `record()`
- `LLMProviderChain`: full provider chain with caching, rate limiting, budget, guardrails — use for LLM calls
- `SwarmAggregator`: Path A/B combination with confidence weighting — already handles SkepticAgent's Path B output
- `SwarmMetrics`: Prometheus metrics for swarm operations — reuse existing counters/histograms

### Established Patterns
- Writer agents: BaseWriterAgent consume loop, manual offset commit, DLQ routing, bounded buffer
- Service pattern: standalone systemd unit, setup_service_logging(), graceful SIGINT/SIGTERM
- Kafka consumer: KafkaConsumerClient with consumer group, async iteration
- Test pattern: `__new__()` for service tests, `isinstance(val, (int, float))` for mock safety

### Integration Points
- Kafka topic `intelligence.i7.signals` — SkepticAgent subscribes here (published by SignalWriterAgent)
- `signal_ledger` — add new columns for skeptic predictions (migration required)
- `alpha_multiplier_shadow` — existing hypertable, 0 rows, ready for writes
- `SwarmAggregator.aggregate()` — SkepticAgent's AgentResult feeds into existing aggregation

</code_context>

<specifics>
## Specific Ideas

- The SkepticAgent is the "devil's advocate" from the swarm manifest — counterfactual reasoning
- Every LLM call produces a training sample for future distillation into a deterministic model
- Prompt versioning enables A/B testing: deploy skeptic_v2, compare correlation with skeptic_v1
- The transfer function (failure_prob → confidence adjustment) is a separable concern, tunable independently
- Renaissance standard: naive baseline first, then prove the LLM beats it per segment

</specifics>

<deferred>
## Deferred Ideas

- Deterministic heuristic scorer (Path A companion) — future phase after LLM predictions validate
- Dashboard UI for skeptic accuracy visualization — future phase
- Additional swarm agents (Regime Sentinel, Volatility Arbiter, etc.) — adding to SwarmDispatchService is near-zero cost; blocked on validation of first 3 agents
- Prompt A/B testing infrastructure (simultaneous versions) — single version first, add comparison later
- Multi-agent ensemble reasoning (agents seeing prior agent results) — architecture supports it, defer until individual agents validate independently

</deferred>

---

*Phase: 066-skeptic-agent*
*Context gathered: 2026-04-24*
