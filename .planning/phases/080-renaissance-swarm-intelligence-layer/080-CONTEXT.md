# Phase 80: Renaissance Swarm Intelligence Layer - Context

**Gathered:** 2026-05-05
**Status:** Ready for planning
**Source:** Design spec `docs/plans/2026-05-05-swarm-intelligence-design.md`

<domain>
## Phase Boundary

Expand the alpha swarm from a single Skeptic agent into a multi-agent intelligence overlay. Deliver: BaseMultiplierAgent base class, four orthogonal agents (Skeptic refactor + Correlation + RegimeCoherence + Counterfactual), automated TF gate (≥5m only), outcome-learned per-(agent,TF) weight store, signal_ledger schema additions (adjusted_confidence, swarm_multiplier, swarm_agent_count), DB migration, and Prometheus observability metrics. All agents start shadow_only=True.

Does NOT include: macro/news context agents (need ctx substrate), MoA/adversarial patterns, regime-conditional routing, >1.0 confidence boosting, direct swarm writes to llm_calls, LLM calibration correction.

Target governance direction: runtime inference and statistical governance should separate. Phase 80 may keep the existing in-service graduation loop as a shortcut, but the clean DAG target is `AlphaSwarmComputeAgent` for lineage emission, `LineageWriterAgent` for persistence, `SwarmEvaluationComputeAgent` for periodic evidence computation, and writer-owned registry/weight updates.

</domain>

<decisions>
## Implementation Decisions

### D-01: BaseMultiplierAgent (P80-BASE)
- New file: `src/core/ai/multiplier_agent.py`
- Extends `BaseAIAgent` (not `BaseAgent` directly)
- Provides `_parse_multiplier_response(raw, validator_fn)` — try direct JSON parse → `_JSON_BLOCK_RE` regex fallback → `None`
- Provides `_build_multiplier_output(multiplier, confidence, payload, prompt_version)` — constructs canonical `AgentOutput`, multiplier clamped to `[0.0, 2.0]`
- Abstract `output_schema: ClassVar[dict]` — documents expected LLM JSON keys; used in parse-failure log
- All concrete agents extend this, never `BaseAIAgent` directly

### D-02: prompt_utils.py additions (P80-BASE)
- Add `JSON_BLOCK_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)` — move from `skeptic_agent.py`
- Add `parse_llm_json(raw: str, validator_fn) -> dict | None` — try/fallback pattern
- Add `clamp(val: Any, lo: float, hi: float) -> float` — `max(lo, min(hi, float(val)))`
- Existing `DIRECTION_LABELS`, `REGIME_LABELS`, `fmt()` untouched

### D-03: Skeptic refactor (P80-SKEPTIC)
- `SkepticAgentComputeAgent` extends `BaseMultiplierAgent` (not `BaseAIAgent`)
- Remove `_JSON_BLOCK_RE`, `_parse_skeptic_response()`, `_validate_skeptic_fields()` from agent file
- Import `JSON_BLOCK_RE`, `parse_llm_json`, `clamp` from `prompt_utils`
- `_build_multiplier_output()` replaces manual `AgentOutput` construction
- All existing tests must continue to pass
- `output_schema = {"failure_probability": float, "confidence": float, "risk_factors": list, "reasoning": str}`
- Multiplier formula: `(1.0 - failure_probability) × confidence`
- Phase 80 policy is discount-only: formulas may reduce confidence but must not boost above 1.0 until outcome data supports it.

### D-04: CorrelationAgentComputeAgent (P80-CORRELATION)
- New files: `src/intelligence/ai/alpha/correlation_agent.py` + `correlation_prompts.py`
- Extends `BaseMultiplierAgent`
- `agent_id = "correlation_v1"`, `group = "alpha"`, `shadow_only = True`
- `tiers_needed = frozenset({Tier.I1, Tier.I4, Tier.I6, Tier.I7})`
- `latency_budget_ms = 5000.0`
- LLM JSON schema: `{"coherence_score": float, "confidence": float, "contradicting_assets": [str], "reasoning": str}`
- Multiplier: `coherence_score × confidence`
- `ACTIVE_VERSION = "correlation_v1"`, prompt focuses on cross-asset coherence (ZN/VIX/ES/CL context)

### D-05: RegimeCoherenceAgentComputeAgent (P80-REGIME)
- New files: `src/intelligence/ai/alpha/regime_coherence_agent.py` + `regime_coherence_prompts.py`
- Extends `BaseMultiplierAgent`
- `agent_id = "regime_coherence_v1"`, `group = "alpha"`, `shadow_only = True`
- `tiers_needed = frozenset({Tier.I4, Tier.I7, Tier.SMC})`
- `latency_budget_ms = 5000.0`
- LLM JSON schema: `{"regime_fit": float, "confidence": float, "mismatches": [str], "reasoning": str}`
- Multiplier: `regime_fit × confidence`
- Prompt focuses on: is the setup TYPE (momentum/mean-reversion/breakout/SMC) appropriate for the current HMM regime + trend_regime?

### D-06: CounterfactualAgentComputeAgent (P80-COUNTERFACTUAL)
- New files: `src/intelligence/ai/alpha/counterfactual_agent.py` + `counterfactual_prompts.py`
- Extends `BaseMultiplierAgent`
- `agent_id = "counterfactual_v1"`, `group = "alpha"`, `shadow_only = True`
- `tiers_needed = frozenset({Tier.I1, Tier.I4, Tier.I7})`
- `latency_budget_ms = 5000.0`
- LLM JSON schema: `{"plausibility": float, "confidence": float, "validation_conditions": [str], "invalidation_conditions": [str], "reasoning": str}`
- Multiplier: `plausibility × confidence`
- Prompt: "What needs to be true for this to work? Is each condition plausible given current context?"

### D-07: Dispatch layer refactor (P80-DISPATCH)
- `services/alpha_swarm_agent.py`: replace bespoke `_agents` dict with `list[BaseMultiplierAgent]`
- Gate 1: skip if `timeframe_minutes < settings.SWARM_MIN_TF_MINUTES` (default 5)
- Gate 2: skip if `signal_schema_version != "v1"`
- `asyncio.gather()` across all `self._agents` in parallel
- Aggregation: `final_multiplier = Σ(wᵢ × mᵢ) / Σ(wᵢ)` — normalized weighted average
- Neutral/error outputs are excluded from aggregation unless every agent fails; if every agent fails, skip the aggregate adjustment event.
- Weights loaded from `swarm_agent_weights` table (cached in memory, refreshed each graduation cycle)
- Default weight = `1/N` (equal) until `sample_size >= SWARM_WEIGHT_MIN_SAMPLES`
- Write per-agent evidence to `signal_lineage` (canonical audit trail)
- `AlphaSwarmComputeAgent` must not update `signal_ledger` directly. It records per-agent lineage and emits any aggregate adjustment as an event.
- A WriterAgent materializes aggregate results to `signal_ledger` (adjusted_confidence, swarm_multiplier, swarm_agent_count) with bounded retry/backoff because signal_writer may not have inserted the row yet.
- Writer ownership options: extend `LineageWriterAgent` for same-event projection, or add `SwarmLedgerWriterAgent` if projection logic grows. Do not put DB write code in `AlphaSwarmComputeAgent`.
- Do not write swarm rows directly to `llm_calls` in Phase 80; `llm_calls` remains the prompt/response audit table unless a separate migration and writer update adds explicit swarm columns.
- Shadow enrollment: loop over `self._agents`, call `shadow_registry_ensure()` for each
- Runtime shadow state: refresh each agent's `shadow_only` from `shadow_registry` or a cached registry snapshot; registry is the source of truth
- Graduation evaluation: loop over `self._agents`, call per-agent evaluation based on `signal_lineage JOIN signal_ledger`
- No per-agent conditional logic in dispatch — list drives everything
- Add `asyncio.Semaphore` capacity guard using `SWARM_MAX_CONCURRENT_CALLS`; skip enrichment with metric if capacity is unavailable within `SWARM_QUEUE_TIMEOUT_MS`
- Future-compatible hooks to include now: `prompt_version`, validated payload, parse status, `segment_key`, agent_id/signal_id identifiers, and skip/error/capacity status in lineage metadata/metrics.

### D-08: Weight learning (P80-WEIGHTS)
- New table `swarm_agent_weights(agent_id TEXT, timeframe TEXT, weight FLOAT DEFAULT 1.0, sample_size INT DEFAULT 0, spearman_rho FLOAT, calibration_error FLOAT, updated_at TIMESTAMPTZ, PRIMARY KEY (agent_id, timeframe))`
- Update rule runs each graduation cycle (~15 min):
  1. Query `signal_lineage JOIN signal_ledger ON signal_id WHERE event_type='agent_prediction' AND multiplier IS NOT NULL AND outcome IS NOT NULL AND signal_lineage.ts > NOW() - INTERVAL '30 days'`
  2. Compute `scipy.stats.spearmanr(multipliers, pnl_r)` per `(agent_id, timeframe)`
  3. `weight = max(WEIGHT_FLOOR, 0.5 + spearman_rho)`
  4. Renormalize weights across active agents so sum is preserved
  5. Upsert into `swarm_agent_weights`
- `calibration_error = |mean(stated_confidence) - empirical_win_rate|`, where stated confidence comes from `signal_lineage.metadata->payload->confidence`; logged, not acted on
- Demotion: graduation loop updates `shadow_registry` when `EV[R] < -0.05` for 3 consecutive cycles; dispatch refreshes runtime `shadow_only` from registry
- Graduation should evolve from a single Spearman gate into a gate suite: minimum N, positive rank correlation, bucket lift, bootstrap CI lower bound, stability across rolling subwindows, coverage, parse quality, calibration sanity, and cost gate.
- Eligibility should be segment-local: Phase 80 `(agent_id, timeframe)`, future `(agent_id, timeframe, regime)`, later `(agent_id, timeframe, regime, setup_family)`.
- Add hysteresis: promote after two consecutive passing windows; demote after three consecutive failing windows; freeze state changes when N or data quality is insufficient.
- Keep `is_shadow`, `weight`, `health`, `coverage`, and `cost` as distinct concepts. Do not collapse them into one flag.
- Every promotion/demotion must write an audit record with segment, previous/new state, reason, N, rho/p-value, bucket lift, CI, coverage, parse failure, cost metrics, and previous/new weight.

### D-09: DB schema + migration (P80-SCHEMA)
- Migration file: `migrations/NNN_swarm_weights_and_adjusted_confidence.sql` (next available N)
- `ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS adjusted_confidence FLOAT;`
- `ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS swarm_multiplier FLOAT;`
- `ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS swarm_agent_count INT;`
- `CREATE TABLE swarm_agent_weights (...)` as specified in D-08
- Original `confidence` column in `signal_ledger` never modified

### D-10: Settings (P80-DISPATCH)
- `src/config/settings.py` additions:
  - `SWARM_MIN_TF_MINUTES: int = 5`
  - `SWARM_WEIGHT_MIN_SAMPLES: int = 30`
  - `SWARM_WEIGHT_FLOOR: float = 0.05`
  - `SWARM_MAX_CONCURRENT_CALLS: int = 8`
  - `SWARM_QUEUE_TIMEOUT_MS: int = 250`

### D-11: Prometheus metrics (P80-OBSERVABILITY)
- All registered via `src/observability/metrics.py` (prevent duplicate registration)
- `swarm_invocations_total` — Counter, labels: `agent_id, timeframe, status`
- `swarm_multiplier_distribution` — Histogram, labels: `agent_id`
- `swarm_aggregated_multiplier` — Histogram, labels: `timeframe`
- `swarm_agent_weight` — Gauge, labels: `agent_id, timeframe` (key health signal in Grafana)
- `swarm_signal_ledger_update_total` — Counter, labels: `status` (success, retry, miss)

### D-12: TEMPLATE_agent.py update
- Update `src/intelligence/ai/TEMPLATE_agent.py` to show `BaseMultiplierAgent` as the base class
- Show canonical `output_schema`, `_build_multiplier_output()`, and `parse_llm_json()` usage

### Claude's Discretion
- Exact migration number (next available in migrations/ directory)
- Whether to split into multiple plan waves or one plan per agent
- Test patterns — follow existing `tests/unit/service_tests/` patterns using `__new__` bypass
- Whether to create a follow-up plan for swarm-specific `llm_calls` expansion; do not implement direct swarm `llm_calls` writes in Phase 80
- Whether `swarm_agent_weights` needs a TimescaleDB hypertable or plain table (plain is fine — low cardinality, not time-series)
- Exact implementation of bounded retry/backoff for signal_ledger materialization

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design Contract
- `docs/plans/2026-05-05-swarm-intelligence-design.md` — full architecture, all decisions, agent contracts, DB schema, file map

### Existing AI Infrastructure (read before touching)
- `src/core/ai/base_agent.py` — BaseAIAgent: timing, timeout, error safety, metrics
- `src/core/ai/prompt_utils.py` — existing DIRECTION_LABELS, REGIME_LABELS, fmt() — extend, don't replace
- `src/core/ai/context.py` — AIContext, AIContextCache, Tier enum
- `src/core/ai/output.py` — AgentOutput schema
- `src/intelligence/ai/alpha/skeptic_agent.py` — canonical existing agent (refactor target + reference)
- `src/intelligence/ai/alpha/skeptic_prompts.py` — PROMPT_REGISTRY + ACTIVE_VERSION pattern
- `src/intelligence/ai/AUTHORING.md` — agent authoring protocol (5 steps)
- `src/intelligence/ai/TEMPLATE_agent.py` — current template (update target)

### Dispatch + Graduation (read before touching)
- `services/alpha_swarm_agent.py` — current dispatch, shadow enrollment, graduation loop

### Infrastructure Patterns
- `src/observability/metrics.py` — metric registration (prevent duplicate labels)
- `src/config/settings.py` — Settings class (add SWARM_* fields)
- `migrations/` — check latest migration number before naming new one

### Test Patterns
- `tests/unit/service_tests/test_alpha_swarm_agent.py` — existing swarm tests (must keep passing)

</canonical_refs>

<specifics>
## Specific Implementation Details

### Agent file naming (from CLAUDE.md)
- `src/intelligence/ai/alpha/correlation_agent.py` → class `CorrelationAgentComputeAgent`
- `src/intelligence/ai/alpha/regime_coherence_agent.py` → class `RegimeCoherenceAgentComputeAgent`
- `src/intelligence/ai/alpha/counterfactual_agent.py` → class `CounterfactualAgentComputeAgent`

### Shadow enrollment pattern (from existing skeptic)
Each new agent needs `shadow_registry_ensure()` called at dispatch startup — same pattern as `_shadow_registry_ensure_swarm()` in `alpha_swarm_agent.py`.

### Swarm does NOT subscribe to intelligence.journal
Full I1-I7 context arrives via `AIContextCache.build()` from the service cache, seeded by `intelligence` events and optionally DB rows — no new Kafka subscriptions.

### signal_ledger projection timing
Swarm materializes `adjusted_confidence`, `swarm_multiplier`, `swarm_agent_count` AFTER signal is already published — async enrichment, never blocks publication. This projection is WriterAgent-owned, not `AlphaSwarmComputeAgent`-owned. Because this can race the signal writer insert, implementation must use bounded retry/backoff. If the row is still missing, keep canonical evidence in `signal_lineage` and emit `swarm_signal_ledger_update_total{status="miss"}`.

### signal_lineage stated confidence
Each agent's `payload.confidence` (LLM's self-reported confidence) must be written to `signal_lineage.metadata.payload.confidence` for calibration tracking. Do not require `llm_calls.stated_confidence` in Phase 80; current `llm_calls` schema does not have the required swarm fields.

### counterfactual preservation
All agents keep writing lineage whether shadow or live. Shadow/live controls whether output affects production confidence, not whether the prediction is recorded. Lineage rows must include write-time shadow state so future audits can compare live behavior against counterfactual shadow inclusion/exclusion.

### I7 context preservation
Before adding new agents, fix `AIContextCache.build()` so I7 fields survive when dispatch passes a signal dict. Current dispatch uses `signal.model_dump()`, while `AIContextCache.build()` currently reads I7 fields via object attributes. Either pass the ranked signal object or make `build()` support dict and object access.

</specifics>

<deferred>
## Deferred (explicitly out of scope for Phase 80)

- MacroContextAgent, NewsContextAgent, VolatilitySurfaceAgent — need ctx substrate (P-CTX-01)
- MoA (Mixture-of-Agents) proposer/aggregator pattern
- Adversarial red team (bull/bear debate)
- Dynamic leadership / regime-conditional agent routing
- Regime/setup-segmented swarm weights beyond `(agent_id, timeframe)`
- Direct swarm-specific `llm_calls` schema/writer expansion
- Confidence boosting above 1.0
- LLM confidence calibration correction (data captured, action deferred)
- OTel Phase 77 dependency — swarm observability uses existing Prometheus pattern, not OTel

</deferred>

---

*Phase: 080-renaissance-swarm-intelligence-layer*
*Context gathered: 2026-05-05 via design spec*
