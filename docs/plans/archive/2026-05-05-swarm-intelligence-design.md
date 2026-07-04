# Plan: Renaissance Swarm Intelligence Layer

**Version:** 1.0
**Last Updated:** 2026-05-05
**Date:** 2026-05-05
**Status:** Approved — pending implementation plan
**Supersedes:** `docs/ideas/ai-09-agent-orchestration-patterns.md` (March 2026 draft — framed as post-MLAgent; this design is the current canonical target)
**Related:** `docs/ideas/ai-01-integration-paths.md`, `docs/plans/2026-05-02-unified-intelligence-design.md`

---

## Executive Summary

Expand the alpha swarm from a single devil's advocate agent (Skeptic) into a multi-agent intelligence overlay that produces an outcome-learned confidence adjustment on every qualifying signal. Each agent is independently measurable, shadow-gated, and contributes orthogonal information the quant pipeline cannot produce mechanically. Weights are earned through proof — Spearman correlation against realized `pnl_r` — never set by intuition.

The swarm is an async enrichment layer. It never blocks signal publication.

---

## Renaissance Alignment

| Principle | How This Design Satisfies It |
|---|---|
| Instrument everything | Per-agent multiplier, stated confidence, prompt version, and payload logged via `signal_lineage` from day one |
| Earn the right through proof | Shadow-only by default; graduation requires sufficient resolved outcomes and positive out-of-sample relationship to realized `pnl_r` |
| Segment relentlessly | Weights learned per `(agent_id, timeframe)` first; regime/setup segmentation is deferred until sample sizes justify it |
| Degrade gracefully, adapt automatically | Graduation loop demotes underperforming agents; weight floor prevents full zeroing |
| Let the system run | Single TF gate, no manual routing, no per-signal decisions |
| Data quality over model complexity | Weighted average with learned weights beats complex routing built on intuition |
| Never drop data that could contain signal | LLM confidence and full payload logged per agent; calibration error computed once outcomes exist |

---

## Architecture

### Role in the Pipeline

```
intelligence.i7.signals
        │
        ▼
  AlphaSwarmAgent (dispatch)
        │
   [Gate 1: timeframe_minutes >= SWARM_MIN_TF_MINUTES (default 5)]
   [Gate 2: signal_schema_version == "v1"]
        │
   asyncio.gather() — all agents in parallel
   ┌──────────┬────────────┬──────────────────┬─────────────────┐
   │          │            │                  │                 │
Skeptic  Correlation  RegimeCoherence  Counterfactual   (future agents)
   │          │            │                  │                 │
   └──────────┴────────────┴──────────────────┴─────────────────┘
                     weight aggregator
               Σ(wᵢ × mᵢ) / Σ(wᵢ)  [normalized]
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
   signal_lineage                  signal_ledger projection
   (one row per agent)             adjusted_confidence
   multiplier + metadata           swarm_multiplier
                                  swarm_agent_count
```

### What the Swarm Is Not

- Not on the hot path — signal is published before swarm starts
- Not a veto layer — it never suppresses signal publication
- Not a routing layer — no per-agent conditional logic in dispatch
- Not a replacement for I1-I7 — it synthesizes tier outputs that quant cannot reason over holistically

### Relation to `intelligence.journal`

`intelligence.journal` is the canonical per-bar fan-out bus feeding `feature_writer`, `feature_snapshot_writer`, and the SSE dashboard. The swarm does not subscribe to it. Full I1-I7 context reaches agents via `AIContextCache.build()` from the service cache, seeded by `intelligence` events and optionally DB rows. No additional topic subscription is needed.

**Implementation correction:** before adding new agents, `AIContextCache.build()` must preserve I7 fields when the dispatch layer passes a signal dict. Current code passes `signal.model_dump()` from `alpha_swarm_agent`; `AIContextCache.build()` must either receive the ranked signal object or support dict access for `plugin`, `direction`, and `calibrated_confidence`. New agents depend on this.

---

## Inheritance Chain

```
BaseAgent (lifecycle, logging, OTel)
    └── BaseAIAgent (timing, timeout, error safety, metrics)
            └── BaseMultiplierAgent  ← NEW: src/core/ai/multiplier_agent.py
                    ├── SkepticAgentComputeAgent       (refactored)
                    ├── CorrelationAgentComputeAgent    (new)
                    ├── RegimeCoherenceAgentComputeAgent (new)
                    └── CounterfactualAgentComputeAgent (new)
```

`BaseMultiplierAgent` provides:
- `_parse_multiplier_response(raw, validator_fn)` — try direct JSON parse → regex fallback → `None`
- `_build_multiplier_output(multiplier, confidence, payload, prompt_version)` — canonical `AgentOutput` construction with multiplier clamped to `[0.0, 2.0]`
- Abstract `output_schema: ClassVar[dict]` — expected LLM JSON keys, used in parse failure logging

All agents start `shadow_only = True`. The graduation loop flips this individually per agent.

---

## Shared Utilities

### `src/core/ai/prompt_utils.py` additions

| Addition | Purpose |
|---|---|
| `JSON_BLOCK_RE` | Compiled `\{[^{}]*\}` regex — moved from `skeptic_agent.py`, single source of truth |
| `parse_llm_json(raw, validator_fn)` | Try direct parse → regex extract fallback → `None` on failure |
| `clamp(val, lo, hi)` | `max(lo, min(hi, float(val)))` — used in every agent validator |

Existing `DIRECTION_LABELS`, `REGIME_LABELS`, `fmt()` unchanged.

---

## Agent Contracts

All four agents output one thing: a multiplier in `[0.0, 2.0]`. Raw LLM scores are clamped to `[0.0, 1.0]` before formula.

**Phase 80 multiplier policy:** discount-only. The first live version may reduce confidence but may not boost it. This is intentional risk control while the system collects outcomes. Boosting above `1.0` remains available to the base class but is deferred until calibration data proves the agents add positive edge.

### Skeptic (refactored from existing)

**Orthogonal value:** Holistic failure probability across all tiers — synthesizes what quant measures individually into a unified "will this fail?" judgment.

```json
{"failure_probability": float, "confidence": float, "risk_factors": [str], "reasoning": str}
```

`multiplier = (1.0 - failure_probability) × confidence`
`tiers_needed = {I1, I4, I6, I7, SMC}`

---

### Correlation

**Orthogonal value:** Cross-asset coherence — does ZN/VIX/ES behavior support or contradict this signal? I6 has `corr_z` scores but cannot reason about the *meaning* of correlation breakdowns.

```json
{"coherence_score": float, "confidence": float, "contradicting_assets": [str], "reasoning": str}
```

`multiplier = coherence_score × confidence`
`tiers_needed = {I1, I4, I6, I7}`

---

### RegimeCoherence

**Orthogonal value:** Setup type vs regime fit — is a mean-reversion signal firing in a strong trend? I4 classifies regime; LLM judges whether the *setup type* is appropriate for that regime.

```json
{"regime_fit": float, "confidence": float, "mismatches": [str], "reasoning": str}
```

`multiplier = regime_fit × confidence`
`tiers_needed = {I4, I7, SMC}`

---

### Counterfactual

**Orthogonal value:** Validation path reasoning — "what needs to be true for this to work, and is each condition plausible?" No quant equivalent exists for this.

```json
{
  "plausibility": float,
  "confidence": float,
  "validation_conditions": [str],
  "invalidation_conditions": [str],
  "reasoning": str
}
```

`multiplier = plausibility × confidence`
`tiers_needed = {I1, I4, I7}`

---

## Dispatch Layer

### `services/alpha_swarm_agent.py` changes

Agent registration is a typed list — adding an agent is one line, no other dispatch code changes:

```python
self._agents: list[BaseMultiplierAgent] = [
    SkepticAgentComputeAgent(llm_chain=self._llm_chain),
    CorrelationAgentComputeAgent(llm_chain=self._llm_chain),
    RegimeCoherenceAgentComputeAgent(llm_chain=self._llm_chain),
    CounterfactualAgentComputeAgent(llm_chain=self._llm_chain),
]
```

Dispatch loop, weight aggregation, shadow enrollment, and graduation calls are all driven by `self._agents` — no per-agent conditional logic in dispatch.

Before dispatching, the service refreshes each agent's `shadow_only` field from `shadow_registry` or a cached registry snapshot. `shadow_registry` remains the source of truth; in-memory agent attributes are runtime projections.

### Aggregation

```
final_multiplier = Σ(wᵢ × mᵢ) / Σ(wᵢ)   [normalized weighted average]
```

Default weight `1/N` (equal) until `sample_size >= SWARM_WEIGHT_MIN_SAMPLES`. Weights loaded from `swarm_agent_weights` at dispatch time (cached, refreshed each graduation cycle).

Neutral/error outputs are excluded from aggregation unless every agent fails. If every agent fails, no aggregate adjustment event is emitted and the event is counted as `swarm_skipped`.

### Concurrency Budget

The swarm is async but not free. It must cap LLM pressure so enrichment cannot starve narrative generation or other local inference.

Add:

```python
SWARM_MAX_CONCURRENT_CALLS: int = 8
SWARM_QUEUE_TIMEOUT_MS: int = 250
```

Dispatch uses an `asyncio.Semaphore`. If a signal cannot acquire capacity within `SWARM_QUEUE_TIMEOUT_MS`, the swarm skips enrichment for that signal and records `swarm_invocations_total{status="capacity_skip"}`. Signal publication remains unaffected.

---

## Weight Learning

### `swarm_agent_weights` table

```sql
CREATE TABLE swarm_agent_weights (
    agent_id          TEXT        NOT NULL,
    timeframe         TEXT        NOT NULL,
    weight            FLOAT       NOT NULL DEFAULT 1.0,
    sample_size       INT         NOT NULL DEFAULT 0,
    spearman_rho      FLOAT,
    calibration_error FLOAT,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (agent_id, timeframe)
);
```

`calibration_error = |mean(stated_confidence) - empirical_win_rate|` — computed once sufficient outcomes exist, not acted on in Phase 80.

### Update rule (runs each graduation cycle, ~15 min)

```
1. Query signal_lineage JOIN signal_ledger ON signal_id
   WHERE event_type = 'agent_prediction'
     AND multiplier IS NOT NULL
     AND signal_ledger.outcome IS NOT NULL
     AND signal_lineage.ts > NOW() - INTERVAL '30 days'
2. Compute Spearman(multiplier, pnl_r) per (agent_id, timeframe)
3. weight = max(WEIGHT_FLOOR, 0.5 + spearman_rho)
     rho = 0   → weight 0.5 (neutral)
     rho = 1   → weight 1.5 (boosted)
     rho = -1  → weight floor (0.05)
4. Renormalize weights across active agents (sum preserved)
5. Compute calibration_error from `signal_lineage.metadata->payload->confidence`
6. Update sample_size, spearman_rho, calibration_error, updated_at
```

### Demotion

Graduation updates `shadow_registry` per agent. Runtime dispatch refreshes from that registry so `AgentOutput.shadow_only` matches the source of truth. Demotion occurs when `EV[R] < -0.05` for 3 consecutive cycles. Weight floor (0.05) prevents an agent from being fully silenced before formal demotion.

---

## Graduation Governance

Runtime inference and statistical governance are different responsibilities. Phase 80 can keep the first implementation small, but the target design should separate them cleanly:

```
AlphaSwarmComputeAgent
  └─ emits agent_prediction lineage, no DB writes

LineageWriterAgent
  └─ persists signal_lineage

SwarmEvaluationComputeAgent  (timer or periodic compute agent)
  └─ reads resolved signal_lineage JOIN signal_ledger
  └─ computes per-agent/per-segment evidence
  └─ emits promotion/demotion/weight recommendations

Writer-owned registry update
  └─ updates shadow_registry, swarm_agent_weights, transition audit

AlphaSwarmComputeAgent
  └─ refreshes registry and weights
  └─ applies only live eligible agents to production confidence
```

The current in-service graduation loop is acceptable only as a short-term implementation shortcut. The clean DAG target is evaluator compute plus writer-owned registry updates.

### Graduation Gates

Do not graduate an agent on one metric. Spearman correlation is useful, but insufficient alone. Promotion should require a small gate suite:

| Gate | Purpose |
|---|---|
| Minimum N | Avoid noise. Start with `n >= 100` resolved predictions per segment. |
| Rank correlation | `spearman_rho(multiplier, pnl_r) > 0` with significance threshold. |
| Bucket lift | High-multiplier bucket must outperform low-multiplier bucket. |
| Bootstrap CI | Lower bound of expected value or bucket lift must be above zero. |
| Stability | Pass in at least 2 of 3 rolling subwindows. |
| Coverage | Valid outputs on at least 95% of eligible calls, excluding capacity skips. |
| Parse quality | JSON parse failure rate below threshold. |
| Calibration sanity | Stated confidence not severely miscalibrated versus realized win rate. |
| Cost gate | Value added must justify latency/token/GPU cost. |

Failure of any hard gate keeps the agent shadow-only for that segment. Soft gates can reduce weight without forcing demotion.

### Segment-Local Eligibility

Avoid global promotion. An agent should graduate only where it has earned the right:

1. Phase 80: `(agent_id, timeframe)`
2. Future, once N supports it: `(agent_id, timeframe, regime)`
3. Later: `(agent_id, timeframe, regime, setup_family)`

This preserves the "segment relentlessly" principle without overfitting sparse cells.

### Hysteresis

State changes must be automated but stable:

- Promote only after two consecutive passing evaluation windows.
- Demote after three consecutive failing windows.
- Freeze state changes when data quality is degraded or sample size is below threshold.
- Keep weight updates smoother than state changes, using floors and caps.

This prevents flip-flopping when the sample is near the boundary.

### State Model

Separate the concepts that are easy to conflate:

| Concept | Meaning |
|---|---|
| `is_shadow` | Whether the agent can affect production confidence. |
| `weight` | How much a live/eligible agent contributes. |
| `health` | Whether the agent is currently callable and producing valid outputs. |
| `coverage` | How often the agent returns usable outputs for eligible signals. |
| `cost` | Latency/token/GPU budget consumed per useful call. |

An agent can be live but low-weight, healthy but shadow-only, or high-quality but temporarily capacity-skipped. Do not collapse these into one flag.

### Transition Audit

Every automated state transition must leave an audit record:

- agent_id
- segment key
- previous state and new state
- decision reason
- evaluation window
- N
- Spearman rho / p-value
- bucket lift
- bootstrap CI
- coverage
- parse failure rate
- cost metrics
- previous weight and new weight

This makes rollback and post-mortem review data-driven rather than anecdotal.

### Cost-Aware Graduation

LLM agents must earn their compute. Track and gate on:

- average latency
- timeout rate
- token estimate
- valid JSON rate
- capacity skip rate
- value added per call
- value added per estimated GPU-second or token budget

An agent that adds tiny edge but consumes disproportionate inference budget should stay shadow-only or receive a lower weight.

### Counterfactual Preservation

All agents keep writing lineage whether shadow or live. Shadow/live controls whether output affects production confidence, not whether the prediction is recorded.

This preserves counterfactual datasets:

- What did each agent predict?
- Was it shadow or live at write time?
- What happened to the signal?
- What would have happened if shadow agents were included?
- What would have happened if live agents were ignored?

This is essential for future evaluation and model discovery.

---

## Database Changes

### `signal_ledger` additions

```sql
ALTER TABLE signal_ledger ADD COLUMN adjusted_confidence  FLOAT;
ALTER TABLE signal_ledger ADD COLUMN swarm_multiplier     FLOAT;
ALTER TABLE signal_ledger ADD COLUMN swarm_agent_count    INT;
```

`adjusted_confidence = original_confidence × swarm_multiplier`. Original confidence column untouched — quant pipeline output is never overwritten.

`AlphaSwarmComputeAgent` must not update `signal_ledger` directly. It records per-agent lineage and emits any aggregate adjustment as an event. A WriterAgent owns the DB projection into `signal_ledger`.

The projection update is async and may race the signal writer. Implement bounded retry/backoff in the WriterAgent by `signal_id`; if the row still does not exist, keep the per-agent evidence in `signal_lineage` and emit a metric. `signal_lineage` is the canonical audit trail; `signal_ledger` columns are materialized convenience fields.

Writer ownership options:

| Option | Boundary |
|---|---|
| Extend `LineageWriterAgent` | Acceptable if treated as a same-event projection: persist `signal_lineage`, then materialize aggregate fields from lineage metadata |
| Add `SwarmLedgerWriterAgent` | Strictest SoC if projection logic grows: consume aggregate adjustment events, write only `signal_ledger` swarm columns |

Do not put DB write code in `AlphaSwarmComputeAgent`.

### `signal_lineage` metadata

Each agent writes one `signal_lineage` row:

```json
{
  "segment_key": "hmm_regime.timeframe",
  "confidence": 0.72,
  "prompt_version": "correlation_v1",
  "group": "alpha",
  "payload": {
    "multiplier": 0.68,
    "confidence": 0.72,
    "reasoning": "..."
  }
}
```

Do not require Phase 80 to write agent rows directly to `llm_calls`. `llm_calls` remains the prompt/response audit table for existing LLM writer flows unless a separate migration and writer update adds explicit swarm columns.

### Migration file

`migrations/NNN_swarm_weights_and_adjusted_confidence.sql`

---

## Future-State Boundary

The original design points at a valid future state, but Phase 80 should not implement all of it at once.

| Future capability | Why it is deferred |
|---|---|
| Direct swarm rows in `llm_calls` | Requires schema and `LLMWriterService` changes for `agent_id`, `multiplier`, `stated_confidence`, and prompt/response capture |
| Regime/setup-segmented weights | Needs enough resolved outcomes per segment; premature segmentation will overfit sparse data |
| Confidence boosting above `1.0` | Requires calibration proof that swarm agents add positive edge, not just identify weak signals |
| LLM confidence calibration correction | Data is captured now; correction should wait for sufficient outcomes |
| Dynamic routing or agent leadership | Weighted average is simpler and measurable; routing can be justified later if weights prove regime dependence |

Phase 80's job is to make every agent measurable, bounded, and shadow-safe. Future phases can promote richer behavior from observed outcomes instead of design intuition.

### Future-Compatible Hooks To Build Now

These are low-cost hooks that keep Phase 80 aligned with the future state without taking on the full complexity:

| Hook | Phase 80 implementation |
|---|---|
| Prompt/response traceability | Store `prompt_version`, raw validated payload, and parse status in `signal_lineage.metadata` |
| Future `llm_calls` backfill | Include enough IDs in lineage metadata (`agent_id`, `signal_id`, `prompt_version`) that a later migration can backfill or cross-link if needed |
| Future regime segmentation | Store `segment_key` in lineage metadata, but keep learned weights keyed only by `(agent_id, timeframe)` until N is sufficient |
| Future confidence boosting | Keep `BaseMultiplierAgent` clamp at `[0.0, 2.0]`, but enforce Phase 80 agent formulas as discount-only |
| Future routing | Record per-agent skip/error/capacity status so later routing decisions have historical evidence |

This gives the future design data to grow from while keeping the first implementation small enough to validate.

---

## Settings

All configurable via `src/config/settings.py`:

```python
SWARM_MIN_TF_MINUTES: int = 5        # gate: don't run on 1m
SWARM_WEIGHT_MIN_SAMPLES: int = 30   # samples before weight learning activates
SWARM_WEIGHT_FLOOR: float = 0.05     # minimum weight before formal demotion
SWARM_MAX_CONCURRENT_CALLS: int = 8   # local LLM capacity guard
SWARM_QUEUE_TIMEOUT_MS: int = 250     # skip enrichment if capacity unavailable
```

---

## Observability

New Prometheus metrics registered via `src/observability/metrics.py`:

| Metric | Type | Labels | Purpose |
|---|---|---|---|
| `swarm_invocations_total` | Counter | `agent_id, timeframe, status` | Per-agent call rate + error rate |
| `swarm_multiplier_distribution` | Histogram | `agent_id` | Per-agent output distribution over time |
| `swarm_aggregated_multiplier` | Histogram | `timeframe` | Final combined multiplier distribution |
| `swarm_agent_weight` | Gauge | `agent_id, timeframe` | Weight drift — key Renaissance health signal |
| `swarm_signal_ledger_update_total` | Counter | `status` | Writer-owned materialization success, retry, or miss |

`swarm_agent_weight` gauge is the primary diagnostic: Grafana shows exactly when the system learns an agent adds or destroys value, segmented by TF.

---

## File Map

### New files
```
src/core/ai/multiplier_agent.py
src/intelligence/ai/alpha/correlation_agent.py
src/intelligence/ai/alpha/correlation_prompts.py
src/intelligence/ai/alpha/regime_coherence_agent.py
src/intelligence/ai/alpha/regime_coherence_prompts.py
src/intelligence/ai/alpha/counterfactual_agent.py
src/intelligence/ai/alpha/counterfactual_prompts.py
migrations/NNN_swarm_weights_and_adjusted_confidence.sql
```

### Modified files
```
src/core/ai/prompt_utils.py               ← add JSON_BLOCK_RE, parse_llm_json, clamp
src/intelligence/ai/alpha/skeptic_agent.py ← extend BaseMultiplierAgent, import shared utils
src/intelligence/ai/TEMPLATE_agent.py      ← update to show BaseMultiplierAgent pattern
services/alpha_swarm_agent.py              ← TF gate, typed agent list, weight aggregation
src/core/ai/context.py                     ← preserve I7 fields for dict signals
services/service_auditor_agent.py          ← _DAG_ORDER if needed
src/config/settings.py                    ← SWARM_* settings
src/observability/metrics.py              ← new swarm metrics
```

---

## Future Agents (not in this phase)

The following agents are natural extensions once the substrate is in place:

| Agent | Dependency | Orthogonal value |
|---|---|---|
| MacroContextAgent | `ctx` substrate (P-CTX-01) | Catalyst/risk event awareness in next N hours |
| NewsContextAgent | `ctx` substrate + news lane | Sentiment shift risk |
| VolatilitySurfaceAgent | DerivAgent / options data | GEX/VANNA regime context |

All will extend `BaseMultiplierAgent` and register in `self._agents` with zero dispatch changes.

---

## What This Design Explicitly Defers

- **MoA (Mixture-of-Agents) proposer/aggregator pattern** — valid future evolution, premature before outcome data proves N-agent weighted average is a bottleneck
- **Adversarial red team** — Skeptic is already the "bear case"; full bull/bear debate requires sufficient agent diversity first
- **Dynamic leadership / regime-conditional agent routing** — let the learned weights handle this; manual routing adds maintenance burden the data can eliminate
- **LLM confidence calibration correction** — data is captured from day one; act when N is sufficient
