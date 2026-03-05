# Phase 16: LLM Intelligence Layer - Context

**Gathered:** 2026-03-05
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-03-05-llm-intelligence-layer-design.md)

<domain>
## Phase Boundary

This phase delivers a complete instrumentation layer for every LLM call in the `ai_narrative_service`. All calls (per-signal, group synthesis, counterfactual) flow through the existing hot/warm/cold tiered architecture into a new `llm_calls` TimescaleDB hypertable. When signals close in `signal_lifecycle_service`, outcomes are back-filled onto the matching call rows. A new `llm_writer_service` handles all persistence and score recomputation. Adaptive model routing in `ai_narrative_service` reads the resulting model scores from Redis and promotes statistically significant winners per call_type + regime combination.

**Out of scope this phase:** Dashboard panels for model comparison, automated fine-tuning pipeline, cross-model ensemble voting.

</domain>

<decisions>
## Implementation Decisions

### Architecture: Event-Driven, Tiered (Locked)
Every LLM call emits to `{env}:llm_calls:stream` (DragonflyDB). `llm_writer_service` is the only writer to TimescaleDB — identical to `feature_writer_service`. The real-time pipeline never writes to the database directly. No special paths.

### Stream Keys (Locked)
- `{env}:llm_calls:stream` — emitted by `ai_narrative_service` after every call
- `{env}:llm_outcomes:stream` — emitted by `signal_lifecycle_service` on signal exit
- Redis score cache: `{env}:llm_scores:{call_type}:{regime}` as HSET: `{model}` → JSON score blob

### Migration: 016_llm_intelligence_layer.sql (Locked)
Creates:
- `llm_calls` — TimescaleDB hypertable, `called_at` partition key
- `llm_model_scores` — aggregate table, PK `(model, regime, setup_type, call_type)`

`llm_calls` schema (all fields locked per design doc):
- `call_id UUID PRIMARY KEY`, `called_at TIMESTAMPTZ NOT NULL`, `call_type TEXT NOT NULL` ('per_signal' | 'group_synthesis' | 'counterfactual')
- `signal_id UUID REFERENCES signal_ledger(signal_id)` (nullable for group/counterfactual)
- `group_name TEXT`, `symbol TEXT NOT NULL`, `timeframe TEXT NOT NULL`
- LLM call: `model TEXT`, `provider TEXT`, `prompt TEXT`, `response TEXT`, `latency_ms INTEGER`, `tokens_est INTEGER`, `succeeded BOOLEAN DEFAULT TRUE`
- Market context at call time: `regime TEXT`, `session TEXT`, `entry_price`, `stop_loss`, `target_price`, `confidence`, `cis_score`, `entry_zone_low`, `entry_zone_high`, `setup_type TEXT`
- Outcome (back-filled): `outcome TEXT`, `pnl_r DOUBLE PRECISION`, `mae`, `mfe`, `bars_in_trade INTEGER`, `win BOOLEAN`, `outcome_at TIMESTAMPTZ`

Indexes: `(signal_id)`, `(model, regime)`, `(called_at DESC)`

### ai_narrative_service Instrumentation (Locked)
- After every LLM call (success OR failure): `xadd llm_calls:stream` with full payload
- Counterfactuals: signals below confidence threshold produce a call log entry with `call_type='counterfactual'`, prompt built, `response=NULL`, `succeeded=False`
- At startup + every 5 min: read Redis `llm_scores`, re-sort provider chain if `is_significant=True` winner exists for current call_type + regime

### signal_lifecycle_service Emission (Locked)
- On signal exit (any outcome): `xadd llm_outcomes:stream` with `signal_id`, `outcome`, `pnl_r`, `mae`, `mfe`, `bars_in_trade`

### llm_writer_service (New Service — Locked)
- Consumer groups on both `llm_calls:stream` and `llm_outcomes:stream`
- Batch INSERT to `llm_calls` (mirror feature_writer batch pattern)
- UPDATE `llm_calls SET outcome fields WHERE signal_id = $1` on outcomes
- Every 15 min: recompute `llm_model_scores` from `llm_calls WHERE outcome IS NOT NULL`
- Update Redis score cache after recompute
- Systemd unit: `indicagent-llm-writer`, Prometheus metrics on next available port
- Consumer group: `llm_writer` (use `ensure_consumer_group_with_reset`)

### Adaptive Routing Logic (Locked)
```python
scores = get_scores_from_redis(call_type, current_regime)
significant = [s for s in scores if s.is_significant]  # p < 0.05 AND n_outcomes >= 30
if significant:
    best = max(significant, key=lambda s: s.avg_pnl_r)
    move best.model to position 0 in provider chain
```
Promotion gate: `p < 0.05 AND n_outcomes >= 30` — binomial test vs baseline win rate.

### llm_model_scores Schema (Locked)
Fields: `model`, `regime`, `setup_type`, `call_type`, `n_calls`, `n_outcomes`, `win_rate`, `avg_pnl_r`, `avg_latency_ms`, `p_value`, `is_significant BOOLEAN`, `score_updated_at`

### Claude's Discretion
- Exact port number for `llm_writer_service` metrics (use next available after 9116)
- Whether score recompute uses raw SQL or SQLAlchemy ORM (match existing service pattern)
- Batch size and flush interval for `llm_calls:stream` consumer (mirror `feature_writer_service` defaults)
- p-value computation library (scipy.stats.binomtest preferred — already available in .venv)
- `__all__` regime/setup_type rows in `llm_model_scores` for aggregate view (aggregate across all regimes)

</decisions>

<specifics>
## Specific Ideas

### Fine-Tuning Export Queries (from design doc — these are value adds, not new requirements)
```sql
-- Winning per-signal examples for supervised fine-tuning
SELECT prompt, response, outcome, pnl_r, regime, setup_type
FROM llm_calls
WHERE call_type = 'per_signal' AND win = TRUE AND pnl_r >= 1.5 AND response IS NOT NULL
ORDER BY pnl_r DESC;

-- RLHF pairs: same signal, different models, different outcomes
SELECT a.prompt, a.response as chosen, b.response as rejected
FROM llm_calls a
JOIN llm_calls b ON a.signal_id = b.signal_id AND a.model != b.model
WHERE a.win = TRUE AND b.win = FALSE;
```
The schema makes these queries possible. The queries themselves don't need to be built in this phase — just documented here as a validation that the schema supports the Renaissance fine-tuning use case.

### Counterfactual Rationale
Signals below confidence threshold (conf <= 0.7 per current `ai_narrative_service`) don't get a full LLM call but still produce a `call_type='counterfactual'` entry with the prompt that *would* have been sent. This gives us: (a) a training corpus of "what did we almost say", (b) outcome data on non-narrative signals, (c) latency benchmarks across all models without extra inference cost.

### Renaissance Validation Gates
Before promoting any model to position 1:
- Minimum 30 outcomes with known result (n_outcomes >= 30)
- p < 0.05 vs baseline win rate (binomial test)
- Performance must hold across at least 2 different regimes (not a regime artifact)
- Latency within acceptable range (high-latency model should not be promoted even with better win rate)

The `llm_model_scores` table captures all of this. The regime check (must hold across 2+ regimes) is a post-promotion validation — not enforced in the auto-routing logic this phase (that's v2). This phase enforces p < 0.05 AND n >= 30 only.

</specifics>

<deferred>
## Deferred Ideas

- Dashboard panels for model comparison (explicitly out of scope per design doc)
- Automated fine-tuning pipeline (separate phase — needs training infrastructure)
- Cross-model ensemble voting (backlog)
- Multi-regime promotion gate (must hold across 2+ regimes) — v2 enhancement; this phase uses single-regime p-value only
- Latency-adjusted promotion (demoting high-latency models even with good win rates) — backlog

</deferred>

---

*Phase: 16-llm-intelligence-layer*
*Context gathered: 2026-03-05 via PRD Express Path*
